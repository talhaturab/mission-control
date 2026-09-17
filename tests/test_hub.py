def test_heartbeat_shows_up_in_tasks(client):
    client.post("/api/heartbeat", json={"name": "worker-a", "kind": "worker", "note": "idle"})
    names = {t["name"]: t for t in client.get("/api/tasks").json()}
    assert names["worker-a"]["alive"] is True
    assert names["worker-a"]["note"] == "idle"
    assert any(t["kind"] == "web" for t in names.values())  # the web process reports itself


def test_job_goes_queued_running_done(client):
    job = client.post("/api/jobs", json={"kind": "count_primes", "input": "100"}).json()
    assert job["status"] == "queued"

    claimed = client.post("/api/jobs/claim", json={"worker": "worker-a"}).json()
    assert claimed["id"] == job["id"] and claimed["status"] == "running"
    assert client.post("/api/jobs/claim", json={"worker": "worker-b"}).json() is None

    done = client.post(
        f"/api/jobs/{job['id']}/result", json={"result": "25 primes below 100"}
    ).json()
    assert done["status"] == "done" and done["worker"] == "worker-a"
    assert client.get("/api/jobs").json()[0]["result"] == "25 primes below 100"


def test_bad_job_kind_rejected(client):
    assert client.post("/api/jobs", json={"kind": "mine_bitcoin", "input": "1"}).status_code == 422


def test_chat_without_key_is_503(client):
    assert (
        client.post("/api/chat/stream", json={"session_id": "s", "message": "hi"}).status_code
        == 503
    )


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Mission Control" in r.text


def test_summary_and_worker_status(client):
    client.post("/api/jobs", json={"kind": "count_primes", "input": "10"})
    client.post("/api/jobs", json={"kind": "count_primes", "input": "20"})
    job = client.post("/api/jobs/claim", json={"worker": "worker-a"}).json()
    client.post(
        "/api/heartbeat",
        json={"name": "worker-a", "kind": "worker", "status": "busy", "job_id": job["id"]},
    )
    assert client.get("/api/summary").json() == {"queued": 1, "running": 1, "done": 0, "failed": 0}
    worker = [t for t in client.get("/api/tasks").json() if t["name"] == "worker-a"][0]
    assert worker["status"] == "busy" and worker["job_id"] == job["id"]
