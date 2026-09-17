# Mission Control

A small application with four kinds of process, built to be deployed step by step:

| Process | What it does | How it runs on AWS |
|---|---|---|
| `web` | Serves the dashboard, holds the state, runs the agent | ECS service behind a load balancer |
| `worker` | Asks the web process for jobs and does them | ECS service, several copies, autoscaled |
| `ticker` | Wakes up, posts a one-line report, exits | Scheduled ECS task |
| the agent | A LangGraph loop over DeepSeek with hub tools and MCP tools | Inside `web`, later on AgentCore |

Each commit on `main` is one step of that journey. Read them in order.

![architecture](docs/architecture.svg)

The diagram in `docs/architecture.svg` is redrawn at every step.

## Run it on a laptop

```bash
cp .env.example .env            # put your OpenRouter key in it
uv sync
uv run python -m app.dev        # web on :8000, two workers, and the ticker
```

Open http://localhost:8000. Submit a job and watch a worker take it. Ask the agent who is running.
If port 8000 is busy: `PORT=8010 uv run python -m app.dev`.

Or run the processes one per terminal: `make web`, `make worker`, `make ticker`.

## Run it in containers (step 2)

```bash
docker compose up --build --scale worker=2     # or: make up
```

One image, built from the `Dockerfile`, runs all four processes; the `command` in
`docker-compose.yml` decides which one each container is. The dashboard is on http://localhost:8010.
Workers reach the web process as `http://web:8000`, by service name, instead of `localhost`.

## Layout

```
app/main.py     the web process: dashboard, API, agent endpoint
app/state.py    tasks and jobs, in memory for now
app/agent.py    the LangGraph agent and its tools
app/worker.py   the worker loop
app/ticker.py   the scheduled task
app/jobs.py     what a worker can do: count_primes, summarise_url
app/hub.py      how workers talk to the web process
static/         the dashboard
Dockerfile      one image for every process
docker-compose.yml  the four processes as containers, for a laptop
tests/          run with: make test
```
