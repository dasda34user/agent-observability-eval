# Agent 可观测性与评估系统 — 学习指南

## 项目概述

Agent 的"黑匣子"——记录每一步决策、支持回放分析、自动化质量评估。

## 核心概念

### 1. AgentTracer (分布式追踪)

```
一次 Agent 请求 = 1 个 Trace = 多个嵌套 Span

Trace: "user_asks_about_albums"
  ├── Span: supervisor.classify (router_decision, 5ms)
  ├── Span: music_agent.llm_call (llm_call, 500ms, 230 tokens)
  └── Span: music_agent.tool_call (tool_call, 10ms)
```

### 2. threading.local() 线程隔离

```python
self._local = threading.local()  # 每个线程独立的 span_stack

with tracer.trace("request"):
    # span_stack = [root_id]
    with tracer.span("llm_call"):
        # span_stack = [root_id, llm_id]
```

FastAPI 多线程并发时, 两个请求的 Span 不会互相干扰。

### 3. EvalSuite 评估框架

四种测试类型:
- 路由测试: 期望路由匹配
- 准确性测试: 关键词+禁用词检查
- 安全测试: 拦截验证
- 边界测试: 空输入/乱码

### 4. LLMJudge 语义评估

5 个维度: correctness / completeness / conciseness / safety / tool_selection

```python
judge.evaluate("correctness",
    question="What albums does AC/DC have?",
    answer="AC/DC has 5 albums...",
    ground_truth="AC/DC has 2 albums: ...")
# → score=1/5 (事实错误)
```

### 5. 无侵入集成

```python
# 一行改动, Agent 自动获得追踪能力
agent = instrument_agent(agent, tracer)
```

原理: 运行时替换 `agent.invoke` 方法, 插入追踪逻辑。

## 文件结构

| 文件 | 作用 |
|------|------|
| `observability/tracer.py` | AgentTracer (Span 追踪) |
| `observability/collector.py` | TraceCollector (SQLite 持久化) |
| `eval/suite.py` | EvalSuite (评估框架) |
| `eval/judges.py` | LLMJudge (LLM 语义评分) |
| `integration/langgraph_instrument.py` | LangGraph 无侵入集成 |

## 启动

```bash
uv run python tests/test_full_pipeline.py   # 全流程测试 (4 模块)
```
