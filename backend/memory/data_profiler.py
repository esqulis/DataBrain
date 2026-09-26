"""DataProfiler: 上传数据后自动执行全面分析，提供高质量数据上下文"""

import pandas as pd
import numpy as np
from typing import Any


def _is_numeric(col: pd.Series) -> bool:
    """安全判断是否为数值列（兼容 pandas StringDtype）"""
    try:
        return np.issubdtype(col.dtype, np.number)
    except TypeError:
        return False


class DataProfiler:
    """数据自动感知引擎"""

    def analyze_dataframe(self, df: pd.DataFrame) -> dict:
        """对 DataFrame 进行全面分析，返回结构化描述"""
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [self._analyze_column(df, col) for col in df.columns],
            "dtype_summary": self._dtype_summary(df),
            "suggested_questions": self._suggest_questions(df),
            "data_quality_flags": self._check_quality(df),
        }

    # ----------------------------------------------------------------
    # 列级分析
    # ----------------------------------------------------------------
    def _analyze_column(self, df: pd.DataFrame, col: str) -> dict:
        s = df[col]
        info: dict[str, Any] = {"name": col, "dtype": str(s.dtype)}

        # 推断业务类型
        info["inferred_type"] = self._infer_type(s)
        info["null_count"] = int(s.isna().sum())
        info["null_pct"] = round(float(s.isna().mean() * 100), 1)
        info["unique_count"] = int(s.nunique())
        info["sample_values"] = self._safe_sample(s.dropna().unique(), 5)
        info["business_meaning"] = self._guess_meaning(col)

        # 数值列统计
        if info["inferred_type"] == "numeric":
            info["stats"] = self._numeric_stats(s)
            info["value_distribution"] = self._numeric_distribution(s)
        elif info["inferred_type"] == "date":
            info["stats"] = self._date_stats(s)
        elif info["inferred_type"] == "category":
            info["value_distribution"] = self._category_distribution(s)

        return info

    def _infer_type(self, s: pd.Series) -> str:
        """推断业务类型：numeric / category / date / text / id"""
        dtype = str(s.dtype)
        name = str(s.name).lower()

        # id 列
        if any(kw in name for kw in ("id", "编号", "订单", "序号")):
            return "id"

        # 时间
        if "datetime" in dtype or "date" in dtype:
            return "date"
        # 尝试解析时间
        if s.dtype == "object" and s.nunique() > 0:
            try:
                pd.to_datetime(s.dropna().head(100), infer_datetime_format=True)
                return "date"
            except Exception:
                pass

        if _is_numeric(s):
            return "numeric"

        # 少量类别 → category
        if s.nunique() <= min(50, len(s) * 0.1):
            return "category"

        return "text"

    # ----------------------------------------------------------------
    # 统计辅助
    # ----------------------------------------------------------------
    def _numeric_stats(self, s: pd.Series) -> dict:
        ss = s.dropna()
        if len(ss) == 0:
            return {}
        q = ss.quantile([0.25, 0.5, 0.75])
        return {
            "min": round(float(ss.min()), 2),
            "max": round(float(ss.max()), 2),
            "mean": round(float(ss.mean()), 2),
            "median": round(float(ss.median()), 2),
            "std": round(float(ss.std()), 2) if len(ss) > 1 else 0,
            "q1": round(float(q.iloc[0]), 2),
            "q3": round(float(q.iloc[2]), 2),
        }

    def _date_stats(self, s: pd.Series) -> dict:
        try:
            ss = pd.to_datetime(s.dropna(), errors="coerce")
            ss = ss.dropna()
            if len(ss) == 0:
                return {}
            span = (ss.max() - ss.min()).days
            return {
                "min": str(ss.min().date()),
                "max": str(ss.max().date()),
                "span_days": int(span),
                "granularity": self._detect_granularity(ss),
            }
        except Exception:
            return {}

    def _detect_granularity(self, s: pd.Series) -> str:
        if len(s) < 2:
            return "unknown"
        diffs = s.sort_values().diff().dt.total_seconds().dropna()
        if len(diffs) == 0:
            return "unknown"
        median_sec = diffs.median()
        if median_sec < 120:
            return "minute"
        if median_sec < 3600 * 36:
            return "day"
        if median_sec < 3600 * 24 * 35:
            return "week"
        return "month"

    def _numeric_distribution(self, s: pd.Series) -> list:
        ss = s.dropna()
        if len(ss) < 3:
            return []
        counts, edges = np.histogram(ss, bins=5)
        return [
            {"range": f"{round(edges[i],0)}-{round(edges[i+1],0)}", "count": int(c)}
            for i, c in enumerate(counts)
        ]

    def _category_distribution(self, s: pd.Series) -> list:
        return [
            {"value": str(k), "count": int(v)}
            for k, v in s.value_counts().head(10).items()
        ]

    # ----------------------------------------------------------------
    # 业务含义猜测
    # ----------------------------------------------------------------
    def _guess_meaning(self, col: str) -> str:
        mapping = {
            "日期": "日期", "date": "日期", "time": "时间",
            "销售额": "销售额(元)", "金额": "金额(元)", "销售": "销售相关",
            "利润": "利润(元)", "成本": "成本(元)",
            "部门": "部门名称", "dep": "部门名称",
            "区域": "区域名称", "地区": "区域名称",
            "姓名": "人员姓名", "名称": "名称", "名字": "名称",
            "数量": "数量", "qty": "数量", "count": "计数",
            "单价": "单价(元)", "价格": "单价(元)", "price": "单价(元)",
            "类别": "类别", "类型": "类别", "产品": "产品名称",
            "id": "编号", "编号": "编号", "code": "编号",
            "电话": "联系电话", "手机": "联系电话",
            "邮箱": "电子邮箱", "email": "电子邮箱",
            "地址": "地址", "地址": "地址",
            "状态": "状态", "status": "状态",
        }
        col_lower = col.lower()
        for kw, meaning in mapping.items():
            if kw in col_lower:
                return meaning
        return col

    # ----------------------------------------------------------------
    # 整体摘要 & 质量检查
    # ----------------------------------------------------------------
    def _dtype_summary(self, df: pd.DataFrame) -> dict:
        return {
            "numeric_columns": [c for c in df.columns if self._infer_type(df[c]) == "numeric"],
            "category_columns": [c for c in df.columns if self._infer_type(df[c]) == "category"],
            "date_columns": [c for c in df.columns if self._infer_type(df[c]) == "date"],
            "text_columns": [c for c in df.columns if self._infer_type(df[c]) == "text"],
        }

    def _check_quality(self, df: pd.DataFrame) -> list:
        flags = []
        for col in df.columns:
            s = df[col]
            nulls = s.isna().sum()
            if nulls > 0:
                flags.append(f"「{col}」列有 {nulls} 个空值（占 {round(nulls/len(s)*100,1)}%）")
            if _is_numeric(s):
                ss = s.dropna()
                if len(ss) > 5:
                    q1, q3 = ss.quantile(0.25), ss.quantile(0.75)
                    iqr = q3 - q1
                    upper = q3 + 3 * iqr
                    outliers = ss[ss > upper]
                    if len(outliers) > 0:
                        flags.append(f"「{col}」列发现 {len(outliers)} 个异常高值（>{round(upper,0)}）")
        return flags

    def _suggest_questions(self, df: pd.DataFrame) -> list:
        """根据数据特征自动生成 3 个示例问题"""
        cats = [c for c in df.columns if self._infer_type(df[c]) == "category"]
        nums = [c for c in df.columns if self._infer_type(df[c]) == "numeric"]
        dates = [c for c in df.columns if self._infer_type(df[c]) == "date"]

        questions = []
        if cats and nums:
            questions.append(f"各{cats[0]}的{self._guess_meaning(nums[0])}是多少？")
        if dates and nums:
            if len(nums) > 1:
                questions.append(f"按月统计{nums[0]}和{nums[1]}的趋势")
            else:
                questions.append(f"按月统计{nums[0]}的趋势")
        if cats and nums:
            if len(cats) > 1:
                questions.append(f"{cats[0]}和{cats[1]}的{nums[0]}对比")
            else:
                questions.append(f"哪个{cats[0]}{self._guess_meaning(nums[0])}最高？")

        if not questions:
            questions = ["显示所有数据", "统计各列的基本信息", "检查数据质量"]

        return questions[:3]

    # ----------------------------------------------------------------
    # 生成给 LLM 看的 schema 文本
    # ----------------------------------------------------------------
    def schema_text(self, profile: dict) -> str:
        """将 profile 转成 LLM 友好的 schema 描述"""
        lines = [f"数据总行数: {profile['row_count']}", f"总列数: {profile['column_count']}", ""]
        lines.append("列信息:")
        for c in profile["columns"]:
            parts = [f"  - {c['name']} ({c['inferred_type']})"]
            if c["business_meaning"]:
                parts.append(f"含义: {c['business_meaning']}")
            parts.append(f"非空: {c['row_count'] if 'row_count' in c else profile['row_count'] - c['null_count']}/{profile['row_count']}")
            parts.append(f"唯一值: {c['unique_count']}")
            if c["sample_values"]:
                parts.append(f"示例值: {c['sample_values'][:4]}")
            if "value_distribution" in c and c["inferred_type"] == "category":
                dist = c["value_distribution"][:5]
                parts.append(f"取值分布: { {d['value']: d['count'] for d in dist} }")
            if "stats" in c:
                st = c["stats"]
                if "mean" in st:
                    parts.append(f"范围: {st['min']} ~ {st['max']}, 均值: {st['mean']}, 中位: {st['median']}")
                if "granularity" in st:
                    parts.append(f"时间范围: {st['min']} ~ {st['max']}, 粒度: {st['granularity']}")
            lines.append(" | ".join(parts))

        if profile["data_quality_flags"]:
            lines.append("\n数据质量提示:")
            for f in profile["data_quality_flags"]:
                lines.append(f"  ⚠ {f}")

        return "\n".join(lines)

    def _safe_sample(self, arr, k):
        """安全取样，返回 Python 原生类型列表"""
        arr = list(arr)
        if len(arr) <= k:
            return [str(x) for x in arr]
        return [str(x) for x in arr[:k]]
