"""analyze 工具：统计分析"""

import pandas as pd
import numpy as np


def _is_numeric(col: pd.Series) -> bool:
    try:
        return np.issubdtype(col.dtype, np.number)
    except TypeError:
        return False


class AnalyzeTool:
    """统计分析工具"""

    def execute(self, df: pd.DataFrame, action: str,
                columns: list[str], params: dict | None = None, **kwargs) -> dict:
        params = params or {}
        action_map = {
            "describe": self._describe,
            "correlation": self._correlation,
            "groupby": self._groupby,
            "trend": self._trend,
            "distribution": self._distribution,
            "outlier": self._outlier,
            "forecast": self._forecast,
        }
        func = action_map.get(action)
        if not func:
            return {"action": action, "error": f"不支持的分析操作: {action}"}

        try:
            result = func(df, columns, params)
            return result
        except Exception as e:
            return {"action": action, "error": str(e)}

    def _describe(self, df, columns, params):
        cols = [c for c in columns if c in df.columns and _is_numeric(df[c])]
        if not cols:
            return {"action": "describe", "error": "没有数值列可分析"}
        desc = df[cols].describe().to_dict()
        insight = self._gen_describe_insight(df, cols, desc)
        return {"action": "describe", "results": desc, "insight": insight}

    def _gen_describe_insight(self, df, cols, desc):
        parts = []
        for c in cols:
            d = desc[c]
            mean, med = d.get("mean", 0), d.get("50%", 0)
            if mean and med and mean > med * 1.5:
                parts.append(f"「{c}」分布右偏严重（均值 {mean:.0f} >> 中位数 {med:.0f}）")
            elif mean and med and med > mean * 1.5:
                parts.append(f"「{c}」分布左偏（中位数 {med:.0f} >> 均值 {mean:.0f}）")
        return "；".join(parts) if parts else "数据分布基本对称"

    def _correlation(self, df, columns, params):
        cols = [c for c in columns if c in df.columns and _is_numeric(df[c])]
        if len(cols) < 2:
            return {"action": "correlation", "error": "至少需要 2 个数值列"}
        corr = df[cols].corr().round(4)
        pairs = []
        for i, c1 in enumerate(cols):
            for c2 in cols[i + 1:]:
                v = corr.loc[c1, c2]
                strength = "强" if abs(v) > 0.7 else "中" if abs(v) > 0.4 else "弱"
                pairs.append(f"{c1} vs {c2}: r={v:.3f}（{strength}度{'正' if v > 0 else '负'}相关）")
        return {"action": "correlation", "results": corr.to_dict(), "insight": "；".join(pairs)}

    def _groupby(self, df, columns, params):
        group_col = params.get("groupby_col", columns[0] if columns else None)
        target_col = params.get("target_col", None)
        if group_col not in df.columns:
            return {"action": "groupby", "error": f"分组列 {group_col} 不存在"}
        if target_col is None:
            numeric = [c for c in df.columns if _is_numeric(df[c]) and c != group_col]
            target_col = numeric[0] if numeric else df.columns[-1]
        if target_col not in df.columns:
            return {"action": "groupby", "error": f"目标列 {target_col} 不存在"}
        agg = params.get("method", "sum")
        result = df.groupby(group_col)[target_col].agg(agg).reset_index()
        rows = [[self._safe(v) for v in row] for row in result.values]
        return {
            "action": "groupby",
            "results": {"columns": list(result.columns), "rows": rows},
            "insight": f"按 {group_col} 分组，对 {target_col} 计算 {agg}",
        }

    def _trend(self, df, columns, params):
        date_cols = [c for c in df.columns if "date" in str(df[c].dtype).lower()
                     or "time" in str(df[c].dtype).lower()]
        if not date_cols:
            date_cols = [c for c in df.columns if any(k in c for k in ("日期", "月", "年", "date"))]
        if not date_cols:
            return {"action": "trend", "error": "未找到日期列"}
        date_col = date_cols[0]
        df2 = df.copy()
        df2[date_col] = pd.to_datetime(df2[date_col], errors="coerce")
        df2["_period"] = df2[date_col].dt.to_period("M").astype(str)

        numeric = [c for c in columns if c in df.columns and _is_numeric(df[c])]
        if not numeric:
            numeric = [c for c in df.columns if _is_numeric(df[c]) and c != date_col]
        if not numeric:
            return {"action": "trend", "error": "未找到数值列"}
        target = numeric[0]
        trend = df2.groupby("_period")[target].sum().reset_index()
        rows = [[self._safe(v) for v in row] for row in trend.values]
        insight = f"按 {date_col} 统计 {target} 的月度趋势，共 {len(trend)} 个月"
        return {
            "action": "trend",
            "results": {"columns": ["period", target], "rows": rows},
            "insight": insight,
        }

    def _distribution(self, df, columns, params):
        col = columns[0] if columns else df.columns[0]
        if col not in df.columns:
            return {"action": "distribution", "error": f"列 {col} 不存在"}
        s = df[col].dropna()
        if _is_numeric(df[col]):
            ss = s.dropna()
            counts, edges = np.histogram(ss, bins=10)
            bins = [f"{edges[i]:.1f}-{edges[i+1]:.1f}" for i in range(len(counts))]
            result = {"histogram": [{"range": b, "count": int(c)} for b, c in zip(bins, counts)]}
            insight = f"「{col}」的数值分布在 {ss.min():.2f} ~ {ss.max():.2f} 之间"
        else:
            vc = s.value_counts().head(10)
            result = {"top_values": {str(k): int(v) for k, v in vc.items()}}
            insight = f"「{col}」共有 {s.nunique()} 个不同值，top10 占比 {vc.sum()/len(s)*100:.1f}%"
        return {"action": "distribution", "results": result, "insight": insight}

    def _forecast(self, df, columns, params):
        """时序预测（statsmodels 可用则 Holt-Winters，否则线性趋势）"""
        params = params or {}
        date_col = params.get("date_col") or self._find_date_col(df, columns)
        if not date_col or date_col not in df.columns:
            return {"action": "forecast", "error": "未找到日期列，请在 params.date_col 指定，或确保列名含 日期/date/month/月 等"}

        target_col = params.get("target_col")
        if not target_col or target_col not in df.columns:
            target_col = None
            for c in columns:
                if c in df.columns and c != date_col and _is_numeric(df[c]):
                    target_col = c
                    break
        if not target_col:
            nums = [c for c in df.columns if _is_numeric(df[c]) and c != date_col]
            target_col = nums[0] if nums else None

        if not target_col:
            return {"action": "forecast", "error": "未找到可预测的数值列，请在 params.target_col 指定"}

        periods = int(params.get("periods", 10))
        df2 = df[[date_col, target_col]].copy()
        df2[date_col] = pd.to_datetime(df2[date_col], errors="coerce")
        df2 = df2.dropna().sort_values(date_col)
        if df2.empty:
            return {"action": "forecast", "error": f"列 {date_col} 无法解析为日期"}

        # 客户级明细按月聚合，得到连续月度序列
        df2 = df2.groupby(df2[date_col].dt.to_period("M").dt.to_timestamp())[target_col].sum().reset_index()
        if date_col not in df2.columns:
            df2 = df2.rename(columns={df2.columns[0]: date_col})
        df2 = df2.sort_values(date_col)

        if len(df2) < 3:
            return {"action": "forecast", "error": f"聚合后时间点不足（仅{len(df2)}个月），无法预测"}

        forecast = None
        method = "linear_regression"
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            series = df2[target_col].astype(float).values
            period = min(max(int(len(series) / 3), 2), 12) if len(series) > 8 else None
            model = ExponentialSmoothing(
                series, trend="add",
                seasonal="add" if period else None,
                seasonal_periods=period,
                initialization_method="estimated",
            )
            forecast = model.fit().forecast(periods).tolist()
            method = "holt_winters"
        except Exception:
            import numpy as np
            x = np.arange(len(df2))
            y = df2[target_col].astype(float).values
            slope, intercept = np.polyfit(x, y, 1)
            forecast = [float(intercept + slope * (len(df2) + i)) for i in range(periods)]
            method = "linear_regression"

        last_date = df2[date_col].iloc[-1]
        if not isinstance(last_date, pd.Timestamp):
            last_date = pd.to_datetime(last_date)
        future_dates = [(last_date + pd.DateOffset(months=i + 1)) for i in range(periods)]

        rows = [
            [future_dates[i].strftime("%Y-%m"), round(float(forecast[i]), 2), "", ""]
            for i in range(periods)
        ]
        trend_dir = (
            "上升" if forecast[-1] > forecast[0] * 1.02
            else "下降" if forecast[-1] < forecast[0] * 0.98
            else "平稳"
        )
        method_label = "Holt-Winters指数平滑" if method == "holt_winters" else "线性趋势回归"
        insight = (
            f"时序预测（{method_label}）：基于 {date_col} → {target_col} 的月度序列，"
            f"未来{periods}个月总体呈{trend_dir}趋势，预测终值约 {round(float(forecast[-1]), 0)}"
        )
        return {
            "action": "forecast",
            "method": method,
            "date_col": date_col,
            "target_col": target_col,
            "periods": periods,
            "results": {"columns": ["日期", "预测值", "下限", "上限"], "rows": rows},
            "insight": insight,
        }

    def _linear_forecast(self, df, date_col, target_col, params):
        """线性回归降级方案"""
        import numpy as np
        df2 = df[[date_col, target_col]].copy()
        df2[date_col] = pd.to_datetime(df2[date_col], errors="coerce")
        df2 = df2.dropna()
        df2 = df2.sort_values(date_col)

        periods = int(params.get("periods", 5))
        x = np.arange(len(df2))
        y = df2[target_col].values.astype(float)
        slope, intercept = np.polyfit(x, y, 1)

        predictions = [round(float(intercept + slope * (len(df2) + i)), 2) for i in range(periods)]
        dates = [str((df2[date_col].iloc[-1] + pd.Timedelta(days=i + 1)).date()) for i in range(periods)]

        rows = [[dates[i], predictions[i], "", ""] for i in range(periods)]
        trend_dir = "上升" if slope > 0 else "下降" if slope < 0 else "平稳"

        return {
            "action": "forecast",
            "method": "linear_regression",
            "date_col": date_col,
            "target_col": target_col,
            "periods": periods,
            "results": {"columns": ["日期", "预测值", "", ""], "rows": rows},
            "insight": f"线性回归预测：未来{periods}期 '{target_col}' 呈{trend_dir}趋势（斜率={slope:.2f}/期）",
        }

    @staticmethod
    def _find_date_col(df, columns):
        """智能查找日期列（支持 billing_month / 年月 / date 等）"""
        for c in columns:
            if c in df.columns:
                if "date" in str(df[c].dtype).lower() or "time" in str(df[c].dtype).lower():
                    return c
        keywords = (
            "日期", "月", "年", "时间", "date", "time", "month", "year",
            "period", "ds", "账期",
        )
        for c in df.columns:
            name = str(c).lower()
            if any(k in name for k in keywords):
                return c
        # 尝试解析前几行是否像日期
        for c in df.columns:
            if _is_numeric(df[c]):
                continue
            sample = df[c].dropna().astype(str).head(5)
            if sample.empty:
                continue
            parsed = pd.to_datetime(sample, errors="coerce")
            if parsed.notna().mean() >= 0.8:
                return c
        return None

    def _outlier(self, df, columns, params):
        cols = [c for c in columns if c in df.columns and _is_numeric(df[c])]
        if not cols:
            return {"action": "outlier", "error": "没有数值列"}
        results = {}
        for c in cols:
            s = df[c].dropna()
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = s[(s < low) | (s > high)]
            results[c] = {
                "outlier_count": int(len(outliers)),
                "outlier_ratio": round(len(outliers) / len(s) * 100, 2),
                "bounds": {"low": round(low, 2), "high": round(high, 2)},
            }
        return {"action": "outlier", "results": results}

    @staticmethod
    def _safe(v):
        if isinstance(v, (int, float)):
            return None if pd.isna(v) else v
        if isinstance(v, str):
            return v
        return str(v) if v is not None else None
