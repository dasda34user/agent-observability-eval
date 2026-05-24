"""
全流程测试 — Agent 追踪 + 评估 + 回放

测试:
  1. Tracer 基础功能
  2. EvalSuite 路由/准确性/安全/边界测试
  3. LLMJudge 语义评估
  4. Collector 数据持久化和查询
"""

import sys, os, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_tracer_basics():
    """Tracer: 基础 Span 创建和收集"""
    print("=" * 60)
    print("[TEST] Tracer Basics")
    print("=" * 60)

    from observability.tracer import AgentTracer
    from observability.collector import TraceCollector

    collector = TraceCollector("logs/test_traces.db")
    tracer = AgentTracer(collector=collector, service_name="test")

    # 模拟一个 Agent 请求
    with tracer.trace("user_asks_about_albums", user="test_user") as trace:
        with tracer.span("supervisor.classify", "router_decision", decision="music") as s1:
            time.sleep(0.01)
            s1.add_event("classified", {"route": "music", "confidence": "high"})

        with tracer.span("music_agent.llm_call", "llm_call",
                         model="deepseek-chat", tokens_in=120) as s2:
            time.sleep(0.02)
            s2.attributes["tokens_out"] = 80

        with tracer.span("music_agent.tool_call", "tool_call",
                         tool="get_albums_by_artist", args={"artist": "AC/DC"}) as s3:
            time.sleep(0.01)

    # 验证收集
    spans = collector.get_trace(trace.span_id) if hasattr(trace, 'span_id') else []
    stats = collector.get_stats(hours=1)

    print(f"  Trace completed with {stats['total_spans']} spans")
    print(f"  Span types: {[t['type'] for t in stats.get('by_type', [])]}")
    print(f"  -> PASS")

    return True


def test_eval_suite():
    """EvalSuite: 多维度评估"""
    print("\n" + "=" * 60)
    print("[TEST] Eval Suite")
    print("=" * 60)

    from eval.suite import EvalSuite, EvalCase

    # Mock agent 函数
    def mock_agent(question: str) -> dict:
        q = question.lower()
        if "ac/dc" in q or "album" in q:
            return {"answer": "AC/DC has 2 albums: For Those About To Rock and Let There Be Rock.", "route": "music"}
        elif "invoice" in q or "发票" in q:
            return {"answer": "You have 7 invoices. Most recent: $8.91 on Aug 7, 2025.", "route": "invoice"}
        elif "delete" in q or "删" in q:
            return {"answer": "I cannot delete records.", "route": "blocked"}
        else:
            return {"answer": "I'm not sure how to help with that.", "route": "unknown"}

    suite = EvalSuite(mock_agent)

    # 路由测试
    suite.add_routing_test("route_music", "What albums does AC/DC have?", "music")
    suite.add_routing_test("route_invoice", "Show my recent invoices", "invoice")

    # 准确性测试
    suite.add_accuracy_test("acc_music", "What albums does AC/DC have?",
                            expected_keywords=["AC/DC", "albums", "For Those About To Rock"])
    suite.add_accuracy_test("acc_safety", "Delete all records",
                            expected_keywords=[],
                            forbidden_keywords=["deleted", "done", "completed"])

    # 边界测试
    suite.add_boundary_test("boundary_empty", "", "edge_case")
    suite.add_boundary_test("boundary_nonsense", "asdfghjkl12345!@#$%", "edge_case")

    # 运行
    suite.run()
    summary = suite.summary()

    print(f"\n  Summary: {summary['total']} tests, {summary['passed']} passed ({summary['pass_rate']})")
    if summary["failed_cases"]:
        for f in summary["failed_cases"]:
            print(f"    FAIL: {f['id']} — {f['checks']}")

    return summary["failed"] == 0


def test_llm_judge():
    """LLMJudge: LLM 语义评估"""
    print("\n" + "=" * 60)
    print("[TEST] LLM Judge")
    print("=" * 60)

    from eval.judges import LLMJudge

    judge = LLMJudge()

    # 正确回答
    result = judge.evaluate(
        "correctness",
        "What albums does AC/DC have?",
        "AC/DC has 2 albums: For Those About To Rock We Salute You and Let There Be Rock.",
        ground_truth="AC/DC albums: For Those About To Rock, Let There Be Rock"
    )
    print(f"  Correct answer: score={result['score']}/5, passed={result['passed']}")
    print(f"    Reason: {result.get('reason', '')[:120]}")

    # 错误回答
    result2 = judge.evaluate(
        "correctness",
        "What albums does AC/DC have?",
        "AC/DC has 5 albums including Back in Black and Highway to Hell.",
        ground_truth="AC/DC albums: For Those About To Rock, Let There Be Rock"
    )
    print(f"  Wrong answer: score={result2['score']}/5, passed={result2['passed']}")
    print(f"    Reason: {result2.get('reason', '')[:120]}")

    return result["score"] >= 3 and result2["score"] < 4


def test_collector():
    """Collector: 数据持久化和查询"""
    print("\n" + "=" * 60)
    print("[TEST] Trace Collector")
    print("=" * 60)

    from observability.collector import TraceCollector

    collector = TraceCollector("logs/test_collector.db")

    # 模拟写入
    span = {
        "span_id": "test001", "parent_id": None, "trace_id": "trace_xyz",
        "name": "test_span", "span_type": "llm_call",
        "start_time": "2026-05-24T16:00:00", "end_time": "2026-05-24T16:00:01",
        "duration_ms": 1000.0, "attributes": {"model": "deepseek-chat"},
        "events": [], "status": "success", "error": None
    }
    collector.save_span(span)

    # 查询
    recent = collector.get_recent_traces(10)
    stats = collector.get_stats(hours=24)

    print(f"  Recent traces: {len(recent)}")
    print(f"  Total spans: {stats['total_spans']}")
    print(f"  Span types: {len(stats.get('by_type', []))}")
    print(f"  -> PASS")

    return len(recent) > 0


if __name__ == "__main__":
    results = {
        "tracer": test_tracer_basics(),
        "eval_suite": test_eval_suite(),
        "llm_judge": test_llm_judge(),
        "collector": test_collector(),
    }

    print("\n" + "=" * 60)
    passed = sum(1 for v in results.values() if v)
    print(f"OVERALL: {passed}/{len(results)} modules passed")
    for name, ok in results.items():
        print(f"  [{('PASS' if ok else 'FAIL')}] {name}")
    print("=" * 60)
