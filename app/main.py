"""The web process: serves the dashboard, holds the state, and runs the agent.

Endpoints:
  GET  /                      the dashboard
  GET  /health
  GET  /api/tasks             who is alive
  POST /api/heartbeat         workers and the ticker call this every few seconds
  GET  /api/summary           how many jobs are queued, running, done, failed
  GET  /api/jobs              the job list
  POST /api/jobs              submit a job (from the dashboard or the agent)
  POST /api/jobs/claim        a worker asks for the next queued job
  POST /api/jobs/{id}/result  a worker reports the outcome
  POST /api/chat/stream       talk to the agent; tokens stream back as server-sent events
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from app.agent import build_graph, create_llm, hub_tools, mcp_tools, wikipedia_tools
from app.config import Settings, get_settings, task_label
from app.state import MemoryState

STATIC = Path(__file__).resolve().parent.parent / "static"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("web")


class Heartbeat(BaseModel):
    name: str
    kind: str
    note: str = ""
    jobs_done: int = 0
    status: str = ""
    job_id: str | None = None


class JobIn(BaseModel):
    kind: str = Field(pattern="^(count_primes|summarise_url)$")
    input: str = Field(min_length=1, max_length=500)


class Claim(BaseModel):
    worker: str


class Result(BaseModel):
    result: str
    ok: bool = True


class Chat(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.state = MemoryState()
        app.state.started = time.time()
        app.state.graph = None
        if settings.llm_configured:
            tools = (
                hub_tools(app.state.state)
                + wikipedia_tools()
                + await mcp_tools(settings.mcp_server_map)
            )
            app.state.graph = build_graph(create_llm(settings), tools, InMemorySaver())
            app.state.tool_names = [t.name for t in tools]

        async def self_heartbeat() -> None:
            # The web process reports itself the same way the workers do.
            while True:
                st = app.state.state
                st.heartbeat(
                    task_label("web", settings.task_name),
                    "web",
                    note=f"{len(st.jobs)} jobs known",
                    status="serving",
                )
                await asyncio.sleep(5)

        beat = asyncio.create_task(self_heartbeat())
        yield
        beat.cancel()

    app = FastAPI(title="Mission Control", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health(request: Request) -> dict:
        return {
            "status": "ok",
            "llm_configured": settings.llm_configured,
            "tasks": len(request.app.state.state.tasks),
        }

    @app.get("/api/tasks")
    async def tasks(request: Request) -> list[dict]:
        st = request.app.state.state
        return [{**asdict(t), "alive": t.alive} for t in st.list_tasks()]

    @app.post("/api/heartbeat")
    async def heartbeat(body: Heartbeat, request: Request) -> dict:
        request.app.state.state.heartbeat(
            body.name, body.kind, body.note, body.jobs_done, body.status, body.job_id
        )
        return {"ok": True}

    @app.get("/api/summary")
    async def summary(request: Request) -> dict:
        return request.app.state.state.summary()

    @app.get("/api/jobs")
    async def jobs(request: Request) -> list[dict]:
        return [asdict(j) for j in request.app.state.state.list_jobs()]

    @app.post("/api/jobs")
    async def submit(body: JobIn, request: Request) -> dict:
        return asdict(request.app.state.state.submit(body.kind, body.input))

    @app.post("/api/jobs/claim")
    async def claim(body: Claim, request: Request) -> dict | None:
        job = request.app.state.state.claim(body.worker)
        return asdict(job) if job else None

    @app.post("/api/jobs/{job_id}/result")
    async def result(job_id: str, body: Result, request: Request) -> dict:
        st = request.app.state.state
        if job_id not in st.jobs:
            raise HTTPException(404, "no such job")
        return asdict(st.finish(job_id, body.result, body.ok))

    @app.post("/api/chat/stream")
    async def chat_stream(body: Chat, request: Request) -> StreamingResponse:
        graph = request.app.state.graph
        if graph is None:
            raise HTTPException(503, "OPENROUTER_API_KEY is not set")
        config = {"configurable": {"thread_id": body.session_id}}

        async def events() -> AsyncIterator[str]:
            tools_used: list[str] = []
            try:
                stream = graph.astream(
                    {"messages": [HumanMessage(content=body.message)]},
                    config,
                    stream_mode="messages",
                )
                async for message, metadata in stream:
                    if isinstance(message, ToolMessage):
                        tools_used.append(message.name)
                        yield sse("tool", {"name": message.name})
                    elif (
                        isinstance(message, AIMessage) and metadata.get("langgraph_node") == "agent"
                    ):
                        text = message.content if isinstance(message.content, str) else ""
                        if text:
                            yield sse("token", {"text": text})
            except Exception as exc:  # noqa: BLE001 - report any failure to the browser
                yield sse("error", {"detail": f"{type(exc).__name__}: {exc}"})
                return
            yield sse("done", {"tools_used": tools_used})

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


app = create_app()
