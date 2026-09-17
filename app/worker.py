"""A worker: send a heartbeat, ask for a job, do it, report the result, repeat.

    uv run python -m app.worker

It exits only when killed. On ECS a service keeps N of these running.
"""

import logging
import time

from app import jobs
from app.agent import create_llm
from app.config import get_settings, task_label
from app.hub import Hub

log = logging.getLogger("worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    hub = Hub(settings.hub_url, name=task_label("worker", settings.task_name), kind="worker")
    llm = create_llm(settings) if settings.llm_configured else None
    done = 0
    note = "waiting for jobs"
    log.info("started, reporting to %s", settings.hub_url)
    while True:
        try:
            hub.heartbeat(note=note, jobs_done=done, status="idle")
            job = hub.claim()
            if job is None:
                time.sleep(3)
                continue
            note = f"running {job['kind']} {job['id']}"
            hub.heartbeat(note=note, jobs_done=done, status="busy", job_id=job["id"])
            log.info("job %s: %s(%s)", job["id"], job["kind"], job["input"][:60])
            started = time.time()
            try:
                result = jobs.run(job["kind"], job["input"], llm)
                hub.finish(job["id"], result, ok=True)
                done += 1
                note = f"finished {job['id']} in {time.time() - started:.1f}s"
            except Exception as exc:  # noqa: BLE001 - a bad job must not kill the worker
                hub.finish(job["id"], f"{type(exc).__name__}: {exc}", ok=False)
                note = f"job {job['id']} failed"
            log.info(note)
        except Exception as exc:  # noqa: BLE001 - the hub may be down; wait and retry
            log.warning("hub unreachable: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
