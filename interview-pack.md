# 面试材料包 — Agent 可观测性与评估系统

## Profile

- 目标岗位：Agent 工程可用性支撑（Agent 可靠性/可控性/可追溯性）
- 技术栈：Python · SQLite · OpenTelemetry 风格追踪 · LLM-as-Judge · LangGraph Instrumentation · EvalSuite
- 项目定位：Agent 的"黑匣子"——记录每一步决策、支持回放分析、自动化质量评估
- GitHub: https://github.com/dasda34user/agent-observability-eval

---

## STAR 简历项目

> **Agent 可观测性与评估系统 — OpenTelemetry 风格追踪 + LLM-as-Judge** — 个人项目
> - 实现 AgentTracer：OpenTelemetry 风格的分布式决策追踪框架，支持嵌套 Span（LLM 调用 / Tool 调用 / Router 决策），`threading.local()` 保证线程安全，SQLite 持久化存储完整调用链
> - 构建 TraceCollector：支持按 trace_id 完整回放（重建决策时间线）、按 span_type 聚合分析（各类型 Span 的耗时/频率/错误率）、时间范围筛选、24h 统计摘要
> - 实现 EvalSuite 多维度评估框架：路由测试 / 准确性测试 / 安全测试 / 边界测试四类自动化评估，批量运行 + 分类通过率统计
> - 实现 LLMJudge 语义评估器：LLM-as-Judge 在 correctness / completeness / conciseness / safety / tool_selection 五个维度评分（1-5），支持 ground truth 对比
> - 实现 LangGraph Instrumentation 无侵入集成：一行代码包装 agent.invoke() 自动记录完整决策链，对原有 Agent 零侵入
> - 全流程 4/4 模块测试通过（Tracer / EvalSuite 6/6 / LLMJudge / Collector）

---

## 面试官拷问 Q&A

### Q1: 已经有了 LangSmith / Arize Phoenix 这样的商业可观测性工具，为什么自己写？

两个原因：

1. **学习深度**：`threading.local()` 做 context propagation、SQLite 做 Span 存储、嵌套 Span 做调用链重建——这些都是 OpenTelemetry 的核心概念。手写一遍才能真正理解分布式追踪的工作原理，而不是只会 `pip install` 然后调 API。

2. **本地优先**：LangSmith 是 SaaS，Arize 需要自建服务。我的系统只用 SQLite + 纯 Python，零外部依赖，离线可用。对于 Agent 开发调试阶段，本地快速迭代比云上全家桶更实用。

### Q2: Span 的嵌套结构怎么实现？为什么用 threading.local()？

每个线程维护一个 `span_stack`（用 `threading.local()` 存储）：

```python
with tracer.trace("request") as root:        # span_stack = [root_id]
    with tracer.span("llm_call") as llm:     # span_stack = [root_id, llm_id]
        with tracer.span("tool_call") as t:  # span_stack = [root_id, llm_id, t_id]
            ...
        # 退出 → span_stack.pop() → [root_id, llm_id]
    # 退出 → span_stack.pop() → [root_id]
```

每个 Span 的 `parent_id` 指向 `span_stack[-1]`（进入时的栈顶）。

**为什么用 threading.local() 而不是全局变量？**

FastAPI 是多线程处理请求的。如果两个用户同时调用 Agent，全局变量会导致它们的 Span 互相串。`threading.local()` 保证每个线程有独立的 span_stack。

### Q3: SQLite 做 Span 存储有什么优劣？

| 优势 | 劣势 |
|------|------|
| 零配置，文件即数据库 | 高并发写入有锁竞争 |
| SQL 查询灵活（GROUP BY, JOIN） | 不适合分布式部署 |
| 嵌入式，不需要额外进程 | 单机容量有限 |

**选型逻辑**：Agent 调试阶段的 Span 量级是每秒几十条，SQLite 完全够用。如果到生产环境每秒几千条 Span，迁移到 ClickHouse 或 PostgreSQL——但架构不变，只是换 `TraceCollector` 的后端实现。

### Q4: LLMJudge 的 5 个评估维度是怎么选的？

参考了 RAGAS 评估框架的维度设计，结合 Agent 场景的特定需求：

| 维度 | 为什么重要 |
|------|-----------|
| correctness | Agent 输出必须准确——不能编造数据 |
| completeness | Agent 不能只回答一半——用户问"AC/DC 有什么专辑"，只列出 1 张是 incomplete |
| conciseness | Agent 不能啰嗦——每次 LLM 调用都要 Token 成本 |
| safety | Agent 不能输出有害内容——即使护栏漏了，评估也能发现 |
| tool_selection | Agent 选对 Tool 了吗——用 web_search 查简单数学题就是浪费 |

### Q5: EvalSuite 和 LLMJudge 有什么区别？什么时候用哪个？

| | EvalSuite | LLMJudge |
|---|---|---|
| **检测方式** | 规则匹配（路由/关键词） | LLM 语义分析 |
| **速度** | <1ms per case | 500-2000ms per case |
| **适用场景** | CI/CD 每次 commit 跑 | 发布前深度评估 |
| **发现能力** | 能发现"路由错了""关键词丢失" | 能发现"答案不通顺""部分事实错误" |

**实际使用**：EvalSuite 做快速回归（6 个用例 < 10ms），LLMJudge 做深度抽查（选 3-5 个关键 case 做 5 维评分）。

### Q6: 怎么保证评估框架本身是可靠的？

这是个好问题——评估框架的可靠性问题是 LLM 评估领域的核心挑战。

1. **确定性检查优先**：路由匹配、关键词检查、禁用词检查——这些是硬规则，100% 可靠
2. **LLMJudge 用 temperature=0**：保证同一条输入每次评分一致
3. **Ground truth 依赖**：所有 LLMJudge 评估都提供 ground truth 做对比，不是让 LLM 凭空判断
4. **定期校准**：人工抽查 LLMJudge 的评分结果，发现偏差就调整 Prompt

### Q7: LangGraph Instrumentation 的"零侵入"是怎么做到的？

Python 的对象是动态的——你可以在运行时替换一个对象的方法：

```python
original_invoke = agent.invoke   # 保存原始方法

def traced_invoke(state, config):
    with tracer.trace(...):      # 插入追踪逻辑
        return original_invoke(state, config)  # 调用原始方法

agent.invoke = traced_invoke     # 替换方法
```

Agent 代码完全不知道自己在被追踪。这跟 Python 的装饰器原理一致，只不过我们是运行时替换而非编译时装饰。

### Q8: 这个项目和护栏系统的关系是什么？

| | 护栏系统（项目 2） | 可观测性系统（项目 3） |
|---|---|---|
| **角色** | Agent 的"刹车" | Agent 的"黑匣子" |
| **做什么** | 拦截危险行为 | 记录 + 评估所有行为 |
| **联动** | 护栏拦截 → 追踪记录拦截事件 | 追踪发现高频错误 → 反馈给护栏优化规则 |
| **PDCA 闭环** | Plan（策略定义）→ Do（执行） | Check（追踪+评估）→ Act（护栏优化） |

两者合在一起构成完整的 **Agent 可靠性工程 PDCA 闭环**——这正是 JD 要求的能力体系。

---

## 核心代码讲解稿

### 架构

```
Agent 请求
   │
   ▼
LangGraph Instrumentation (无侵入包装)
   │
   ▼
AgentTracer
   ├── Span 1: supervisor.classify (router_decision, <1ms)
   ├── Span 2: music_agent.llm_call (llm_call, 500ms, 230 tokens)
   ├── Span 3: music_agent.tool_call (tool_call, 10ms, SQL query)
   └── Span 4: music_agent.final_response (llm_call, 300ms)
   │
   ▼
TraceCollector → SQLite (logs/traces.db)
   │
   ▼
评估 (可选)
   ├── EvalSuite: 快速回归测试
   └── LLMJudge: 深度语义评估
```

### 模块职责

| 模块 | 文件 | 核心类/函数 | 功能 |
|------|------|-----------|------|
| Tracer | `observability/tracer.py` | `AgentTracer`, `TraceSpan` | 分布式追踪 |
| Collector | `observability/collector.py` | `TraceCollector` | SQLite 持久化 + 查询 |
| EvalSuite | `eval/suite.py` | `EvalSuite`, `EvalCase`, `EvalResult` | 自动化评估 |
| LLMJudge | `eval/judges.py` | `LLMJudge` | LLM 语义评分 |
| Integration | `integration/langgraph_instrument.py` | `instrument_agent()` | 无侵入集成 |

### 启动命令

```bash
cd D:\FILE\CODE\py\agent-observability

# 运行全流程测试 (4 模块)
uv run python tests/test_full_pipeline.py
```

### 我的设计决策

| 决策 | 为什么 |
|------|--------|
| SQLite 而非 JSONL（对比护栏项目） | Span 之间有层级关系，SQL 的 JOIN/GROUP BY 比 JSONL 遍历高效 |
| `threading.local()` 而非全局变量 | FastAPI 多线程并发，线程隔离是基本要求 |
| `@contextmanager` 而非手动 start/stop | with 语句自动计时 + 自动处理异常，不会忘记 stop |
| 包装 `invoke()` 而非修改 LangGraph 源码 | 零侵入，Agent 升级不影响追踪 |
| temperature=0 用于 LLMJudge | 同一条输入每次评分必须一致，否则评估不可信 |

### 业务价值映射

| JD 职责 | 本项目的实现 |
|---------|------------|
| 职责 4: 行为日志与决策轨迹记录 | AgentTracer + TraceCollector：每条 Span 记录时间/类型/属性/状态，SQLite 持久化 |
| 职责 5: 失败与边界案例构造 | EvalSuite 边界测试 + 安全测试 + 路由验证 |
| 职责 6: 行为反馈与问题归因 | LLMJudge 5 维评分 + Collector 统计摘要（错误率/耗时分布/问题频率） |

---

## 投递检查表

- [ ] 是否能讲清 "为什么不用 LangSmith 而自建"（学习深度 + 本地优先）？
- [ ] 是否能解释 `threading.local()` 在并发场景下的作用？
- [ ] 是否能说清 EvalSuite（快速规则匹配）和 LLMJudge（深度语义）的使用场景差异？
- [ ] 是否能讲清 "无侵入集成" 的实现原理（运行时方法替换）？
- [ ] 是否能把三个系统串起来讲：Agent（多 Agent 项目）→ 护栏（Aegis）→ 可观测性（这个项目）？ 
- [ ] 是否能一句话概括：可观测性 = Agent 的"黑匣子"，出问题了能回溯、能评估、能改进？
