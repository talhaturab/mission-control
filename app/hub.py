"""How a worker or ticker talks to the web process. Four small HTTP calls."""

import httpx


class Hub:
    def __init__(self, url: str, name: str, kind: str) -> None:
        self.client = httpx.Client(base_url=url, timeout=10)
        self.name, self.kind = name, kind

    def heartbeat(
        self, note: str = "", jobs_done: int = 0, status: str = "", job_id: str | None = None
    ) -> None:
        self.client.post(
            "/api/heartbeat",
            json={
                "name": self.name,
                "kind": self.kind,
                "note": note,
                "jobs_done": jobs_done,
                "status": status,
                "job_id": job_id,
            },
        ).raise_for_status()

    def claim(self) -> dict | None:
        r = self.client.post("/api/jobs/claim", json={"worker": self.name})
        r.raise_for_status()
        return r.json() or None

    def finish(self, job_id: str, result: str, ok: bool) -> None:
        self.client.post(
            f"/api/jobs/{job_id}/result", json={"result": result, "ok": ok}
        ).raise_for_status()
