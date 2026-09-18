"""The agent as its own process, hosted by AgentCore Runtime (step 6).

    python -m app.agentcore        # serves POST /invocations and GET /ping on port 8080

Same graph as before. What changes is where the tools come from: the hub tools go over HTTP
to the web process, and the MCP tools come through an AgentCore Gateway, which sits in front
of the DeepWiki server and checks that the caller is allowed in. The OpenRouter key is read
from Secrets Manager with this process's IAM role, so no key is in the environment.
"""

import logging

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import build_graph, create_llm, hub_tools_http, mcp_tools, wikipedia_tools
from app.config import get_settings
from app.sigv4 import SigV4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("agentcore")

app = BedrockAgentCoreApp()
settings = get_settings()
graphs: dict[str, object] = {}  # one compiled graph per hub URL; the checkpointer keeps chats


def read_key() -> str:
    if settings.openrouter_api_key:
        return settings.openrouter_api_key
    client = boto3.client("secretsmanager", region_name=settings.aws_region)
    return client.get_secret_value(SecretId=settings.openrouter_secret_name)["SecretString"]


async def graph_for(hub_url: str):
    if hub_url not in graphs:
        settings.openrouter_api_key = read_key()
        tools = hub_tools_http(hub_url) + wikipedia_tools()
        if settings.gateway_url:
            signer = SigV4("bedrock-agentcore", settings.aws_region)
            tools += await mcp_tools({"gateway": settings.gateway_url}, auth=signer)
        graphs[hub_url] = build_graph(create_llm(settings), tools, InMemorySaver())
        log.info("graph ready for %s with tools %s", hub_url, [t.name for t in tools])
    return graphs[hub_url]


@app.entrypoint
async def invoke(payload: dict, context):
    """payload: {"prompt": str, "hub_url": str}. Yields the same events the dashboard reads."""
    graph = await graph_for(payload["hub_url"])
    config = {"configurable": {"thread_id": context.session_id}}
    stream = graph.astream(
        {"messages": [HumanMessage(content=payload["prompt"])]}, config, stream_mode="messages"
    )
    tools_used: list[str] = []
    async for message, metadata in stream:
        if isinstance(message, ToolMessage):
            tools_used.append(message.name)
            yield {"event": "tool", "name": message.name}
        elif isinstance(message, AIMessage) and metadata.get("langgraph_node") == "agent":
            text = message.content if isinstance(message.content, str) else ""
            if text:
                yield {"event": "token", "text": text}
    yield {"event": "done", "tools_used": tools_used}


@app.ping
def ping() -> str:
    return "Healthy"


if __name__ == "__main__":
    log.info("agent runtime starting, gateway=%s", settings.gateway_url)
    app.run()
