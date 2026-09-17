"""The scheduled task: wake up, do a small piece of housekeeping, report, exit.

    uv run python -m app.ticker            # one run, then exit (how it runs on ECS, on a schedule)
    TICK_FOREVER=1 uv run python -m app.ticker   # loop every 30 s (handy on a laptop)

Its job here is to count the day's jobs and post a one-line report. Real tickers clean up
files, refresh caches, retrain models.
"""

import logging
import os
import time

import httpx

from app.config import get_settings, task_label
from app.hub import Hub

log = logging.getLogger("ticker")


def tick(hub: Hub, hub_url: str) -> str:
    jobs = httpx.get(f"{hub_url}/api/jobs", timeout=10).json()
    by_status: dict[str, int] = {}
    for job in jobs:
        by_status[job["status"]] = by_status.get(job["status"], 0) + 1
    counts = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
    report = f"jobs: {counts or 'none yet'}"
    hub.heartbeat(note=f"tick at {time.strftime('%H:%M:%S')} · {report}")
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    hub = Hub(settings.hub_url, name=task_label("ticker", settings.task_name), kind="ticker")
    while True:
        try:
            log.info(tick(hub, settings.hub_url))
        except Exception as exc:  # noqa: BLE001 - the hub may not be up yet; try again next time
            log.warning("tick failed: %s", exc)
        if not os.environ.get("TICK_FOREVER"):
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
