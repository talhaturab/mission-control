"""The agent: a two-node LangGraph loop over a model with tools.

START -> agent -> (tool calls?) -> tools -> agent -> ... -> END

Tools come from two places: functions in this file that read and write the hub, and MCP
servers, which are tool servers the agent connects to over HTTP.
"""

import logging

import httpx
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.config import Settings
from app.state import MemoryState

log = logging.getLogger("agent")

SYSTEM_PROMPT = """You are Mission Control's assistant. You can see which tasks are running,
submit jobs to the workers, look people and topics up on Wikipedia, and ask DeepWiki about
GitHub repositories (DeepWiki knows repositories only, never people). Be brief and concrete.
When you use a tool, say what it returned. Never invent task or job ids."""

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
HEADERS = {"User-Agent": "mission-control/0.1 (teaching demo)"}


def create_llm(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.llm_base_url,
        temperature=0.3,
        default_headers={"HTTP-Referer": "http://localhost:8000", "X-Title": "Mission Control"},
    )


def hub_tools(state: MemoryState) -> list:
    """Tools that read and write the hub's state. The agent runs inside the web process."""

    @tool
    def list_tasks() -> str:
        """List the tasks that are running right now, with what each one is doing."""
        rows = [
            f"{t.kind} {t.name}: {'alive' if t.alive else 'gone'}, {t.note}"
            for t in state.list_tasks()
        ]
        return "\n".join(rows) or "no tasks have reported yet"

    @tool
    def submit_job(kind: str, input: str) -> str:
        """Queue a job. kind: 'count_primes' (input: a number) or 'summarise_url' (input: a URL)."""
        job = state.submit(kind, input)
        return f"queued job {job.id} ({kind})"

    @tool
    def job_status(job_id: str) -> str:
        """Check a job by id: its status, which worker took it, and the result if finished."""
        job = state.jobs.get(job_id)
        if job is None:
            return f"no job {job_id}"
        return f"{job.id}: {job.status}, worker={job.worker}, result={job.result}"

    @tool
    def list_jobs() -> str:
        """List recent jobs, newest first: id, kind, status, worker, and the result if any."""
        rows = [
            f"{j.id} {j.kind} {j.status} worker={j.worker} result={(j.result or '')[:200]}"
            for j in state.list_jobs()[:20]
        ]
        return "\n".join(rows) or "no jobs yet"

    return [list_tasks, submit_job, job_status, list_jobs]


def wikipedia_tools() -> list:
    """Two tools over Wikipedia's public API. No key, no MCP: plain HTTP wrapped as tools."""

    @tool
    def search_wikipedia(query: str) -> str:
        """Search Wikipedia for a person, place or topic. Returns up to five article titles."""
        r = httpx.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 5,
            },
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        hits = r.json()["query"]["search"]
        return "\n".join(h["title"] for h in hits) or "no articles found"

    @tool
    def wikipedia_summary(title: str) -> str:
        """Get the summary paragraph of one Wikipedia article by its exact title."""
        r = httpx.get(WIKIPEDIA_SUMMARY + title.replace(" ", "_"), headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return f"no article called {title!r}; try search_wikipedia first"
        r.raise_for_status()
        data = r.json()
        return f"{data.get('title')}: {data.get('extract', '')}"

    return [search_wikipedia, wikipedia_summary]


async def mcp_tools(servers: dict[str, str]) -> list:
    """Connect to each MCP server and fetch its tool list. A server that is down is skipped."""
    if not servers:
        return []
    client = MultiServerMCPClient(
        {name: {"url": url, "transport": "streamable_http"} for name, url in servers.items()}
    )
    try:
        tools = await client.get_tools()
        log.info("MCP tools: %s", [t.name for t in tools])
        return tools
    except Exception as exc:  # noqa: BLE001 - a missing tool server must not stop the app
        log.warning("MCP servers unavailable: %s", exc)
        return []


def build_graph(llm, tools: list, checkpointer=None):
    llm_with_tools = llm.bind_tools(tools)
    system = SystemMessage(content=SYSTEM_PROMPT)

    async def agent(state: MessagesState) -> dict:
        response = await llm_with_tools.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    def route(state: MessagesState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)
