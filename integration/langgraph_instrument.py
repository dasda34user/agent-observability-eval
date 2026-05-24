"""
LangGraph Instrumentation — 无侵入式 Agent 追踪

通过包装 supervisor.invoke() 方法，自动记录每次 Agent 调用的完整决策链。

用法:
    from integration.langgraph_instrument import instrument_agent
    traced_agent = instrument_agent(agent, tracer)
    result = traced_agent.invoke(state, config)  # 自动记录 trace
"""

import time, uuid
from typing import Dict, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from observability.tracer import AgentTracer


def instrument_agent(agent, tracer: AgentTracer, agent_name: str = "supervisor"):
    """
    对 LangGraph agent 做无侵入式追踪包装。

    原理: 包装 .invoke() 方法，在执行前后插入 trace/span 记录。
    """

    original_invoke = agent.invoke

    def traced_invoke(state, config=None, **kwargs):
        question = ""
        if state.get("messages"):
            msgs = state["messages"]
            if msgs:
                question = str(getattr(msgs[-1], "content", msgs[-1]))[:200]

        trace_name = f"{agent_name}: {question[:80]}"

        with tracer.trace(trace_name, agent=agent_name, question=question) as trace_span:
            # Span 1: Agent 执行
            with tracer.span(f"{agent_name}.invoke", "agent_execution",
                             input_length=len(question)) as exec_span:
                start = time.time()
                try:
                    result = original_invoke(state, config, **kwargs)
                    exec_span.attributes["status"] = "success"
                    exec_span.attributes["output_length"] = len(
                        str(result.get("messages", [{}])[-1].content if result.get("messages") else ""))
                except Exception as e:
                    exec_span.add_event("error", {"error": str(e)})
                    raise

            # 分析消息链
            if result.get("messages"):
                msgs = result["messages"]
                for i, msg in enumerate(msgs):
                    msg_type = msg.__class__.__name__
                    tc = getattr(msg, "tool_calls", None)

                    if tc:
                        for t in tc:
                            tracer.span(
                                f"tool_call.{t.get('name', 'unknown')}",
                                "tool_call",
                                tool=t.get("name", "?"),
                                args=str(t.get("args", {}))[:200]
                            )
                    elif msg_type == "AIMessage":
                        content = str(getattr(msg, "content", ""))
                        if "transfer" in content.lower():
                            tracer.span("router_decision", "router_decision",
                                        decision=content[:200])

            return result

    # 替换方法
    agent.invoke = traced_invoke
    agent._instrumented = True
    return agent
