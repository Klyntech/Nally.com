"""Simple LangGraph ReAct agent with hard limits."""
from __future__ import annotations

import json
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from nally.agent.llm import chat_completion
from nally.agent.prompts import SYSTEM_PROMPT
from nally.config import MAX_ITERATIONS, MAX_TOOL_CALLS, MAX_WALL_TIME
from nally.core.logging import logger
from nally.tools.registry import get_tools, get_tools_by_name


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    tool_calls: int
    started_at: float
    stop_reason: str


def _lc_tools_to_openai(tools) -> list[dict]:
    out = []
    for t in tools:
        schema = t.args_schema.model_json_schema() if hasattr(t, "args_schema") and t.args_schema else {
            "type": "object",
            "properties": {},
        }
        schema.pop("title", None)
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or t.name,
                    "parameters": schema,
                },
            }
        )
    return out


def _messages_to_openai(messages: list[BaseMessage]) -> list[dict]:
    result = []
    for m in messages:
        if isinstance(m, SystemMessage):
            result.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            result.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            item: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"],
                        },
                    }
                    for tc in m.tool_calls
                ]
            result.append(item)
        elif isinstance(m, ToolMessage):
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                }
            )
    return result


def _over_budget(state: AgentState) -> str | None:
    if state["iteration"] >= MAX_ITERATIONS:
        return f"max_iterations={MAX_ITERATIONS}"
    if state["tool_calls"] >= MAX_TOOL_CALLS:
        return f"max_tool_calls={MAX_TOOL_CALLS}"
    if time.time() - state["started_at"] >= MAX_WALL_TIME:
        return f"max_wall_time={MAX_WALL_TIME}s"
    return None


def llm_node(state: AgentState) -> dict:
    if reason := _over_budget(state):
        logger.info("Budget stop before LLM: %s", reason)
        return {
            "messages": [AIMessage(content=f"[stopped: {reason}]")],
            "stop_reason": reason,
            "iteration": state["iteration"] + 1,
        }

    tools = get_tools()
    oai_tools = _lc_tools_to_openai(tools)
    oai_msgs = _messages_to_openai(state["messages"])
    resp = chat_completion(oai_msgs, tools=oai_tools)
    msg = resp.choices[0].message

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            args = tc.function.arguments
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                parsed = {}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "args": parsed})

    ai = AIMessage(content=msg.content or "", tool_calls=tool_calls)
    return {"messages": [ai], "iteration": state["iteration"] + 1}


def tools_node(state: AgentState) -> dict:
    if reason := _over_budget(state):
        return {
            "messages": [AIMessage(content=f"[stopped: {reason}]")],
            "stop_reason": reason,
        }

    last = state["messages"][-1]
    by_name = get_tools_by_name()
    outputs: list[ToolMessage] = []
    count = state["tool_calls"]

    for tc in getattr(last, "tool_calls", []) or []:
        if count >= MAX_TOOL_CALLS:
            outputs.append(
                ToolMessage(
                    content=f"Error: max_tool_calls={MAX_TOOL_CALLS}",
                    tool_call_id=tc["id"],
                    name=tc["name"],
                )
            )
            continue
        name = tc["name"]
        tool = by_name.get(name)
        count += 1
        if not tool:
            outputs.append(ToolMessage(content=f"Error: unknown tool {name}", tool_call_id=tc["id"], name=name))
            continue
        try:
            result = tool.invoke(tc["args"])
        except Exception as e:
            result = f"Error: {e}"
        outputs.append(ToolMessage(content=str(result), tool_call_id=tc["id"], name=name))

    return {"messages": outputs, "tool_calls": count}


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    if state.get("stop_reason"):
        return END
    if _over_budget(state):
        return END
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("llm", llm_node)
    g.add_node("tools", tools_node)
    g.set_entry_point("llm")
    g.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "llm")
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_agent(user_text: str, session_id: str = "default") -> str:
    """Run one agent turn; returns final assistant text."""
    graph = get_graph()
    initial: AgentState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_text),
        ],
        "iteration": 0,
        "tool_calls": 0,
        "started_at": time.time(),
        "stop_reason": "",
    }
    final = graph.invoke(initial)
    for m in reversed(final["messages"]):
        if isinstance(m, AIMessage) and (m.content or "").strip():
            return m.content
    return "(no response)"
