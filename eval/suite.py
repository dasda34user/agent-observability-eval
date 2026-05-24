"""
EvalSuite — Agent 行为评估框架

支持:
  - 多维度评估 (正确性、延迟、Tool选择、安全性)
  - LLM-as-Judge 语义评分
  - 批量测试运行
  - 回归测试 (golden dataset)
"""

import json, time
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EvalCase:
    """单个评估用例"""
    id: str
    question: str
    expected_route: str = ""          # 期望的 Supervisor 路由
    expected_tool: str = ""           # 期望调用的 Tool
    expected_keywords: List[str] = field(default_factory=list)  # 回答中应包含的关键词
    forbidden_keywords: List[str] = field(default_factory=list) # 回答中不应包含的关键词
    category: str = "general"         # routing / accuracy / safety / latency
    difficulty: str = "basic"         # basic / edge_case / adversarial
    metadata: Dict = field(default_factory=dict)


@dataclass
class EvalResult:
    """单个用例的评估结果"""
    case_id: str
    passed: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0


class EvalSuite:
    """Agent 评估套件"""

    def __init__(self, agent_fn: Callable, tracer=None):
        """
        agent_fn: 接受 question: str, 返回 {"answer": str, "route": str, ...} 的函数
        """
        self.agent_fn = agent_fn
        self.tracer = tracer
        self.cases: List[EvalCase] = []
        self.results: List[EvalResult] = []

    def add_case(self, case: EvalCase):
        self.cases.append(case)

    def add_routing_test(self, id: str, question: str, expected_route: str, category: str = "routing"):
        """添加路由测试"""
        self.add_case(EvalCase(id=id, question=question, expected_route=expected_route, category=category))

    def add_accuracy_test(self, id: str, question: str, expected_keywords: List[str],
                          forbidden_keywords: List[str] = None):
        """添加准确性测试"""
        self.add_case(EvalCase(
            id=id, question=question,
            expected_keywords=expected_keywords,
            forbidden_keywords=forbidden_keywords or [],
            category="accuracy"
        ))

    def add_safety_test(self, id: str, question: str, should_block: bool = True):
        """添加安全性测试"""
        self.add_case(EvalCase(
            id=id, question=question,
            expected_keywords=[] if should_block else ["*"],
            category="safety",
            metadata={"should_block": should_block}
        ))

    def add_boundary_test(self, id: str, question: str, difficulty: str = "edge_case"):
        """添加边界测试"""
        self.add_case(EvalCase(
            id=id, question=question,
            category="boundary", difficulty=difficulty
        ))

    def run(self) -> List[EvalResult]:
        """运行所有评估用例"""
        self.results = []
        print(f"Running {len(self.cases)} eval cases...")

        for case in self.cases:
            start = time.time()

            try:
                result = self.agent_fn(case.question)
                answer = result.get("answer", "")
                route = result.get("route", "")
            except Exception as e:
                result = {"answer": f"ERROR: {e}", "route": "error"}
                answer = f"ERROR: {e}"
                route = "error"

            duration = (time.time() - start) * 1000

            # 逐项检查
            checks = {}

            # 路由检查
            if case.expected_route:
                checks["route_match"] = case.expected_route.lower() in route.lower()

            # 关键词检查
            if case.expected_keywords and case.expected_keywords != ["*"]:
                checks["keywords_present"] = all(
                    kw.lower() in answer.lower() for kw in case.expected_keywords
                )

            # 禁用词检查
            if case.forbidden_keywords:
                checks["forbidden_absent"] = not any(
                    kw.lower() in answer.lower() for kw in case.forbidden_keywords
                )

            # 安全检查
            if case.metadata.get("should_block") is not None:
                blocked = "blocked" in str(result.get("verdict", "")).lower() or \
                          "blocked" in str(result.get("blocked_at", "")).lower()
                checks["safety_blocked"] = blocked == case.metadata["should_block"]

            all_checks_passed = all(checks.values()) if checks else True

            eval_result = EvalResult(
                case_id=case.id,
                passed=all_checks_passed,
                checks=checks,
                details={
                    "category": case.category,
                    "difficulty": case.difficulty,
                    "answer_preview": answer[:300],
                    "route": route,
                },
                duration_ms=round(duration, 2),
            )
            self.results.append(eval_result)

            status = "PASS" if all_checks_passed else "FAIL"
            print(f"  [{status}] {case.id} ({duration:.0f}ms)")

        return self.results

    def summary(self) -> Dict:
        """生成评估总结"""
        if not self.results:
            return {"error": "No results. Run suite.run() first."}

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)

        by_category = {}
        for r in self.results:
            cat = r.details.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"total": 0, "passed": 0}
            by_category[cat]["total"] += 1
            if r.passed:
                by_category[cat]["passed"] += 1

        for cat in by_category:
            by_category[cat]["rate"] = f"{by_category[cat]['passed'] / max(by_category[cat]['total'], 1) * 100:.0f}%"

        avg_duration = sum(r.duration_ms for r in self.results) / max(total, 1)

        return {
            "total": total, "passed": passed, "failed": total - passed,
            "pass_rate": f"{passed / max(total, 1) * 100:.1f}%",
            "avg_duration_ms": round(avg_duration, 1),
            "by_category": by_category,
            "failed_cases": [
                {"id": r.case_id, "checks": r.checks, "details": r.details}
                for r in self.results if not r.passed
            ]
        }
