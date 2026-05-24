"""
AgentTracer — OpenTelemetry 风格的 Agent 决策追踪

记录 Agent 执行过程中的每一个 Span:
  - LLM 调用 (model, tokens, latency, prompt_preview)
  - Tool 调用 (tool_name, args, result, duration)
  - Router 决策 (supervisor → which sub-agent, reasoning)
  - 子 Agent 执行 (name, input, output, sub-spans)

线程安全，支持嵌套 Span，SQLite 持久化。
"""

import time, uuid, threading, json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager
from .collector import TraceCollector


@dataclass
class TraceSpan:
    """一条追踪 Span"""
    span_id: str
    parent_id: Optional[str]
    trace_id: str
    name: str
    span_type: str  # llm_call / tool_call / router_decision / agent_execution / guardrail_check
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)
    status: str = "running"  # running / success / error
    error_message: Optional[str] = None

    def finish(self, status: str = "success", error: str = None):
        self.end_time = time.time()
        self.status = status
        self.error_message = error

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def add_event(self, name: str, attributes: Dict = None):
        self.events.append({
            "timestamp": datetime.now().isoformat(),
            "name": name,
            "attributes": attributes or {}
        })

    def to_dict(self) -> Dict:
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "span_type": self.span_type,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "error": self.error_message,
        }


class AgentTracer:
    """
    Agent 追踪器 — 分布式追踪风格

    线程安全: 使用 threading.local() 存储当前 trace context。
    每个 Agent 请求 = 一个 Trace，Trace 内包含多个嵌套 Span。

    用法:
        tracer = AgentTracer()
        with tracer.trace("user_query") as span:
            with tracer.span("llm_call", model="deepseek-chat") as llm_span:
                # ... LLM 调用 ...
                llm_span.add_event("tokens_used", {"input": 150, "output": 80})
            with tracer.span("tool_call", tool="get_albums") as tool_span:
                # ... Tool 调用 ...
    """

    def __init__(self, collector: TraceCollector = None, service_name: str = "multi-agent-supervisor"):
        self._local = threading.local()
        self.collector = collector or TraceCollector()
        self.service_name = service_name

    @property
    def _current_trace_id(self) -> Optional[str]:
        return getattr(self._local, "trace_id", None)

    @property
    def _current_span_id(self) -> Optional[str]:
        return getattr(self._local, "span_stack", [None])[-1] if getattr(self._local, "span_stack", None) else None

    @contextmanager
    def trace(self, name: str, **attrs):
        """开始一个新的 Trace。整个 Agent 请求的顶层入口。"""
        trace_id = str(uuid.uuid4())[:12]
        span_id = str(uuid.uuid4())[:8]

        # 保存旧的 context
        old_trace_id = getattr(self._local, "trace_id", None)
        old_span_stack = getattr(self._local, "span_stack", [])

        self._local.trace_id = trace_id
        self._local.span_stack = [span_id]

        span = TraceSpan(
            span_id=span_id,
            parent_id=None,
            trace_id=trace_id,
            name=name,
            span_type="trace_root",
            start_time=time.time(),
            attributes={"service": self.service_name, "started_at": datetime.now().isoformat(), **attrs}
        )

        try:
            yield span
            span.finish("success")
        except Exception as e:
            span.finish("error", str(e))
            raise
        finally:
            self.collector.save_span(span.to_dict())
            # 恢复旧的 context
            self._local.trace_id = old_trace_id
            self._local.span_stack = old_span_stack

    @contextmanager
    def span(self, name: str, span_type: str = "generic", **attrs):
        """在当前 Trace 内创建一个子 Span。"""
        parent_id = self._current_span_id
        if not parent_id:
            raise RuntimeError("No active trace. Use tracer.trace() first.")

        span_id = str(uuid.uuid4())[:8]
        self._local.span_stack.append(span_id)

        span = TraceSpan(
            span_id=span_id,
            parent_id=parent_id,
            trace_id=self._current_trace_id,
            name=name,
            span_type=span_type,
            start_time=time.time(),
            attributes=attrs
        )

        try:
            yield span
            span.finish("success")
        except Exception as e:
            span.finish("error", str(e))
            span.add_event("exception", {"error": str(e)})
            raise
        finally:
            self.collector.save_span(span.to_dict())
            self._local.span_stack.pop()
