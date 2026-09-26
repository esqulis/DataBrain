"""PatternMemory: 记忆成功查询模式，相似问题复用模板"""

import uuid
import re
import hashlib
from datetime import datetime


class PatternMemory:
    """历史查询模式记忆库"""

    def __init__(self, max_patterns: int = 30):
        self.max_patterns = max_patterns
        self.patterns: list[dict] = []

    # ----------------------------------------------------------------
    # 存储
    # ----------------------------------------------------------------
    def store(self, user_query: str, sql: str, table_name: str = "",
              query_type: str = "aggregation") -> dict:
        """存储一条成功查询为 pattern"""
        pattern = {
            "id": str(uuid.uuid4())[:8],
            "user_query": user_query,
            "sql": sql,
            "sql_template": self._abstract_sql(sql),
            "query_type": query_type,
            "table_name": table_name,
            "data_schema_hash": self._schema_hash(table_name),
            "use_count": 0,
            "success_rate": 1.0,
            "created_at": datetime.now().isoformat(),
        }
        self.patterns.append(pattern)
        # LRU 淘汰
        if len(self.patterns) > self.max_patterns:
            self.patterns.sort(key=lambda p: p["use_count"])
            self.patterns.pop(0)
        return pattern

    # ----------------------------------------------------------------
    # 检索
    # ----------------------------------------------------------------
    def retrieve(self, user_query: str, table_name: str = "",
                 top_k: int = 3) -> list[dict]:
        """按查询类型 + schema 匹配 + 语义关键词检索"""
        query_lower = user_query.lower()
        scored = []

        for p in self.patterns:
            score = 0.0

            # 1) 同表优先
            if table_name and p["table_name"] == table_name:
                score += 2.0

            # 2) 关键词重叠
            q_tokens = set(self._tokenize(query_lower))
            p_tokens = set(self._tokenize(p["user_query"].lower()))
            overlap = q_tokens & p_tokens
            if len(q_tokens) > 0:
                score += len(overlap) / len(q_tokens) * 3.0

            # 3) 查询类型匹配
            if self._classify_query(user_query) == p["query_type"]:
                score += 1.5

            # 4) 使用频次奖励
            score += min(p.get("use_count", 0) * 0.1, 1.0)

            if score > 0.5:
                scored.append((score, p))

        scored.sort(key=lambda x: -x[0])
        # 使用计数 +1
        for _, p in scored[:top_k]:
            p["use_count"] = p.get("use_count", 0) + 1

        return [p for _, p in scored[:top_k]]

    # ----------------------------------------------------------------
    # SQL 模板化 / 实例化
    # ----------------------------------------------------------------
    def _abstract_sql(self, sql: str) -> str:
        """具体 SQL → 模板"""
        s = sql.strip()
        s = re.sub(r"'[^']*'", "{val}", s)           # 字符串常量
        s = re.sub(r"\b\d+\.?\d*\b", "{num}", s)     # 数字常量
        s = re.sub(r"\{val\}", "{val}", s)
        s = re.sub(r"\{num\}", "{num}", s)
        return s

    def render(self, pattern: dict, columns: list[str]) -> str | None:
        """将模板适配到目标表的列名"""
        sql = pattern["sql"]
        # 尝试直接使用（如果列名匹配）
        return sql

    # ----------------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------------
    @staticmethod
    def _classify_query(query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ("趋势", "变化", "增长", "走势", "逐月", "按月", "随时间")):
            return "trend"
        if any(kw in q for kw in ("对比", "比较", "vs", " versus", " versus")):
            return "comparison"
        if any(kw in q for kw in ("占比", "比例", "分布", "百分比", "饼图")):
            return "proportion"
        if any(kw in q for kw in ("筛选", "过滤", "大于", "小于", "等于", "条件", "where")):
            return "filter"
        if any(kw in q for kw in ("平均", "均值", "总和", "合计", "统计", "汇总", "每个", "各")):
            return "aggregation"
        return "aggregation"

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        words = re.findall(r"[\w一-鿿]+", text)
        return [w for w in words if len(w) > 1 or w.isascii()]

    @staticmethod
    def _schema_hash(table_name: str) -> str:
        return hashlib.md5(table_name.encode()).hexdigest()[:12]

    def to_dict(self) -> list[dict]:
        return list(self.patterns)

    @classmethod
    def from_dict(cls, data: list[dict]) -> "PatternMemory":
        obj = cls()
        obj.patterns = list(data) if data else []
        return obj
