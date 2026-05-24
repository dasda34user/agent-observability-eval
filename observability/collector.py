"""
TraceCollector — SQLite 持久化的 Span 收集器

所有 Span 写入本地 SQLite 数据库，支持:
  - 按 trace_id 查询完整调用链
  - 按 span_type 聚合分析 (LLM 调用耗时、Tool 调用频率)
  - 时间范围筛选
  - 统计摘要生成
"""

import sqlite3, json, threading
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class TraceCollector:
    """Span 收集器 — SQLite 后端"""

    def __init__(self, db_path: str = "logs/traces.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS spans (
                    span_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    trace_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    span_type TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_ms REAL,
                    attributes TEXT,
                    events TEXT,
                    status TEXT DEFAULT 'running',
                    error TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_id ON spans(trace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_span_type ON spans(span_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_start_time ON spans(start_time)")
            conn.commit()
            conn.close()

    def save_span(self, span_dict: Dict):
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                INSERT OR REPLACE INTO spans
                (span_id, parent_id, trace_id, name, span_type, start_time, end_time,
                 duration_ms, attributes, events, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                span_dict["span_id"], span_dict["parent_id"], span_dict["trace_id"],
                span_dict["name"], span_dict["span_type"], span_dict["start_time"],
                span_dict["end_time"], span_dict["duration_ms"],
                json.dumps(span_dict["attributes"], ensure_ascii=False),
                json.dumps(span_dict["events"], ensure_ascii=False),
                span_dict["status"], span_dict.get("error")
            ))
            conn.commit()
            conn.close()

    def get_trace(self, trace_id: str) -> List[Dict]:
        """获取一个完整 Trace 的所有 Span"""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time",
            (trace_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_recent_traces(self, limit: int = 20) -> List[Dict]:
        """获取最近的 Trace 列表"""
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("""
            SELECT trace_id, name, MIN(start_time) as started, MAX(end_time) as ended,
                   COUNT(*) as span_count,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_count,
                   MAX(duration_ms) as total_ms
            FROM spans
            GROUP BY trace_id
            ORDER BY started DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        return [{
            "trace_id": r[0], "name": r[1], "started": r[2], "ended": r[3],
            "span_count": r[4], "error_count": r[5], "total_ms": r[6]
        } for r in rows]

    def get_stats(self, hours: int = 24) -> Dict:
        """获取统计摘要"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = sqlite3.connect(str(self.db_path))

        total = conn.execute("SELECT COUNT(*) FROM spans WHERE start_time > ?", (cutoff,)).fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM spans WHERE start_time > ? AND status = 'error'", (cutoff,)
        ).fetchone()[0]

        # 按 span_type 聚合
        by_type = conn.execute("""
            SELECT span_type, COUNT(*) as count, AVG(duration_ms) as avg_ms,
                   MAX(duration_ms) as max_ms, MIN(duration_ms) as min_ms
            FROM spans WHERE start_time > ?
            GROUP BY span_type
        """, (cutoff,)).fetchall()

        conn.close()

        return {
            "total_spans": total,
            "error_count": errors,
            "error_rate": f"{errors / max(total, 1) * 100:.1f}%",
            "period_hours": hours,
            "by_type": [{
                "type": r[0], "count": r[1],
                "avg_ms": round(r[2], 2) if r[2] else 0,
                "max_ms": round(r[3], 2) if r[3] else 0,
                "min_ms": round(r[4], 2) if r[4] else 0,
            } for r in by_type]
        }

    def _row_to_dict(self, row) -> Dict:
        cols = ["span_id", "parent_id", "trace_id", "name", "span_type",
                "start_time", "end_time", "duration_ms", "attributes", "events", "status", "error"]
        d = dict(zip(cols, row))
        for k in ["attributes", "events"]:
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except (json.JSONDecodeError, TypeError):
                d[k] = {}
        return d
