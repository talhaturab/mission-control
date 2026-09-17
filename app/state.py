"""The hub's memory: which tasks are alive, and the job queue.

This first version keeps everything in the web process. It is lost on restart and not shared
between copies of the web process. A later step swaps it for DynamoDB without changing the API.
"""

import time
import uuid
from dataclasses import dataclass, field

STALE_AFTER_SECONDS = 45


@dataclass
class Task:
    name: str
    kind: str  # web | worker | ticker
    started_at: float
    last_seen: float
    note: str = ""
    jobs_done: int = 0
    status: str = ""  # idle | busy | serving | (empty for the ticker)
    job_id: str | None = None  # the job a busy worker is on

    @property
    def alive(self) -> bool:
        return time.time() - self.last_seen < STALE_AFTER_SECONDS


@dataclass
class Job:
    id: str
    kind: str  # summarise_url | count_primes
    input: str
    status: str = "queued"  # queued | running | done | failed
    created_at: float = field(default_factory=time.time)
    worker: str | None = None
    result: str | None = None


class MemoryState:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.jobs: dict[str, Job] = {}

    # --- tasks -----------------------------------------------------------------------------
    def heartbeat(
        self,
        name: str,
        kind: str,
        note: str = "",
        jobs_done: int = 0,
        status: str = "",
        job_id: str | None = None,
    ) -> Task:
        now = time.time()
        task = self.tasks.get(name)
        if task is None:
            task = self.tasks[name] = Task(name=name, kind=kind, started_at=now, last_seen=now)
        task.last_seen, task.note, task.jobs_done = now, note, jobs_done
        task.status, task.job_id = status, job_id
        return task

    def summary(self) -> dict[str, int]:
        """How many jobs are in each state. The queue length is the 'queued' number."""
        counts = {"queued": 0, "running": 0, "done": 0, "failed": 0}
        for job in self.jobs.values():
            counts[job.status] += 1
        return counts

    def list_tasks(self) -> list[Task]:
        return sorted(self.tasks.values(), key=lambda t: (t.kind, t.name))

    # --- jobs ------------------------------------------------------------------------------
    def submit(self, kind: str, input: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], kind=kind, input=input)
        self.jobs[job.id] = job
        return job

    def claim(self, worker: str) -> Job | None:
        """Hand the oldest queued job to a worker. First come, first served."""
        for job in sorted(self.jobs.values(), key=lambda j: j.created_at):
            if job.status == "queued":
                job.status, job.worker = "running", worker
                return job
        return None

    def finish(self, job_id: str, result: str, ok: bool = True) -> Job:
        job = self.jobs[job_id]
        job.status, job.result = ("done" if ok else "failed"), result
        return job

    def list_jobs(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: -j.created_at)[:50]
