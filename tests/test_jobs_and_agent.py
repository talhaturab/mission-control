from langchain_core.messages import AIMessage, HumanMessage

from app import jobs
from app.agent import build_graph, hub_tools
from app.state import MemoryState
from tests.fakes import ScriptedChatModel


def test_count_primes():
    assert jobs.count_primes("100") == "25 primes below 100"


async def test_agent_calls_a_tool_then_answers():
    state = MemoryState()
    state.heartbeat("worker-a", "worker", note="idle")
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"id": "c1", "name": "list_tasks", "args": {}}]),
            AIMessage(content="One worker, worker-a, is idle."),
        ]
    )
    graph = build_graph(llm, hub_tools(state))
    result = await graph.ainvoke({"messages": [HumanMessage(content="who is running?")]})
    assert result["messages"][-1].content == "One worker, worker-a, is idle."
    assert "worker-a" in result["messages"][-2].content  # the tool's output was fed back


def test_wikipedia_tools_exist_with_docs():
    from app.agent import wikipedia_tools

    names = {t.name: t.description for t in wikipedia_tools()}
    assert set(names) == {"search_wikipedia", "wikipedia_summary"}
    assert all(names.values())  # the description is what the model reads
