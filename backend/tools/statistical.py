"""statistical 工具：统计检验方法（T检验/方差分析/线性回归/卡方检验）"""
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats


def _fmt(val, decimals=3):
    if val is None:
        return "—"
    if isinstance(val, (int, np.integer)):
        return str(val)
    try:
        number = float(val)
        if not np.isfinite(number):
            return "—"
        return f"{number:.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _sig(p):
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


def _sig_note():
    return "*** p<0.001, ** p<0.01, * p<0.05"


def _make_section(title: str, content: str, chart_option: dict | None = None) -> dict:
    return {"title": title, "content": content, "chart_option": chart_option}


class StatisticalTool:
    """统计检验工具 —— T检验/方差分析/线性回归/卡方检验"""

    @staticmethod
    def run_ttest(df: pd.DataFrame, params: dict) -> dict:
        """独立样本 / 配对样本 T 检验"""
        group_col = params.get("group_col")
        test_col = params.get("test_col")
        test_cols = params.get("test_cols") or ([test_col] if test_col else [])
        paired = params.get("paired", False)
        popmean = params.get("popmean", None)

        if not test_cols:
            return {"success": False, "error": "请指定要检验的数值列"}

        results = []
        for col in test_cols:
            if col not in df.columns:
                continue
            data = df[col].dropna()

            if popmean is not None:
                # 单样本 T 检验
                t_stat, p_val = scipy_stats.ttest_1samp(data, popmean)
                results.append({
                    "method": f"单样本T检验（{col} vs {popmean}）",
                    "t": _fmt(t_stat), "p": _fmt(p_val), "sig": _sig(p_val),
                    "mean": _fmt(data.mean()), "n": len(data),
                })
            elif group_col and group_col in df.columns:
                # 分组 T 检验
                groups = df[group_col].dropna().unique()
                if len(groups) != 2:
                    results.append({
                        "method": f"分组T检验（{col} 按 {group_col}）",
                        "error": f"分组变量应有2个值，当前有 {len(groups)} 个"
                    })
                    continue
                g1, g2 = groups[:2]
                v1 = df.loc[df[group_col] == g1, col].dropna()
                v2 = df.loc[df[group_col] == g2, col].dropna()
                func = scipy_stats.ttest_rel if paired else scipy_stats.ttest_ind
                t_stat, p_val = func(v1, v2)
                results.append({
                    "method": f"{'配对' if paired else '独立样本'}T检验（{col}）",
                    "group1": str(g1), "group2": str(g2),
                    "mean1": _fmt(v1.mean()), "mean2": _fmt(v2.mean()),
                    "t": _fmt(t_stat), "p": _fmt(p_val), "sig": _sig(p_val),
                    "n1": len(v1), "n2": len(v2),
                })
            else:
                results.append({"method": f"T检验（{col}）", "error": "需要分组列或总体均值参数"})

        sections = [_make_section("T检验结果", _sig_note())]
        return {"success": True, "results": results, "sections": sections, "name": "T检验"}

    @staticmethod
    def run_anova(df: pd.DataFrame, params: dict) -> dict:
        """单因素方差分析"""
        group_col = params.get("group_col")
        test_cols = params.get("test_cols") or []

        if not group_col or group_col not in df.columns:
            return {"success": False, "error": "请指定分组变量"}
        if not test_cols:
            return {"success": False, "error": "请指定要分析的数值列"}

        results = []
        groups = df[group_col].dropna().unique()
        if len(groups) < 2:
            return {"success": False, "error": f"分组变量至少应有2个组，当前有 {len(groups)} 个"}

        for col in test_cols:
            if col not in df.columns:
                continue
            samples = [df.loc[df[group_col] == g, col].dropna().values for g in groups]
            f_stat, p_val = scipy_stats.f_oneway(*samples)
            means = {str(g): _fmt(df.loc[df[group_col] == g, col].mean()) for g in groups}
            results.append({
                "method": f"单因素方差分析（{col} 按 {group_col}）",
                "f": _fmt(f_stat), "p": _fmt(p_val), "sig": _sig(p_val),
                "groups": means, "k": len(groups),
            })

        sections = [_make_section("方差分析结果", _sig_note())]
        return {"success": True, "results": results, "sections": sections, "name": "方差分析"}

    @staticmethod
    def run_linear_regression(df: pd.DataFrame, params: dict) -> dict:
        """线性回归"""
        target = params.get("target")
        features = params.get("features") or []

        if not target or target not in df.columns:
            return {"success": False, "error": "请指定目标变量"}
        if not features:
            return {"success": False, "error": "请指定自变量"}

        valid_features = [c for c in features if c in df.columns]
        if not valid_features:
            return {"success": False, "error": "指定的自变量不存在"}

        try:
            import statsmodels.api as sm
            data = df[[target] + valid_features].dropna()
            X = data[valid_features]
            X = sm.add_constant(X)
            y = data[target]
            model = sm.OLS(y, X).fit()

            coefs = []
            for i, name in enumerate(["(截距)"] + valid_features):
                coefs.append({
                    "variable": name,
                    "coef": _fmt(model.params.iloc[i]),
                    "std_err": _fmt(model.bse.iloc[i]),
                    "t": _fmt(model.tvalues.iloc[i]),
                    "p": _fmt(model.pvalues.iloc[i]),
                    "sig": _sig(model.pvalues.iloc[i]),
                })
            results = {
                "r_squared": _fmt(model.rsquared),
                "adj_r_squared": _fmt(model.rsquared_adj),
                "f_stat": _fmt(model.fvalue),
                "f_p": _fmt(model.f_pvalue),
                "n": int(model.nobs),
                "coefficients": coefs,
            }
            sections = [_make_section("线性回归结果", f"R²={results['r_squared']}, 调整R²={results['adj_r_squared']}, F={results['f_stat']}, p={results['f_p']}\n{_sig_note()}")]
            return {"success": True, "results": results, "sections": sections, "name": "线性回归"}
        except Exception as e:
            return {"success": False, "error": f"回归分析失败: {e}"}

    @staticmethod
    def run_chisquare(df: pd.DataFrame, params: dict) -> dict:
        """卡方检验"""
        row_col = params.get("row_col")
        col_col = params.get("col_col")

        if not row_col or row_col not in df.columns:
            return {"success": False, "error": "请指定行变量"}
        if not col_col or col_col not in df.columns:
            return {"success": False, "error": "请指定列变量"}

        try:
            ct = pd.crosstab(df[row_col], df[col_col])
            chi2, p, dof, expected = scipy_stats.chi2_contingency(ct)
            cramer_v = np.sqrt(chi2 / (df.shape[0] * (min(ct.shape) - 1))) if min(ct.shape) > 1 else 0
            results = {
                "chi2": _fmt(chi2), "p": _fmt(p), "sig": _sig(p),
                "dof": int(dof), "n": df.shape[0],
                "cramer_v": _fmt(cramer_v),
                "rows": list(ct.index[:10]),
                "cols": list(ct.columns[:10]),
            }
            sections = [_make_section("卡方检验结果", f"χ²={results['chi2']}, p={results['p']}, Cramér\'s V={results['cramer_v']}\n{_sig_note()}")]
            return {"success": True, "results": results, "sections": sections, "name": "卡方检验"}
        except Exception as e:
            return {"success": False, "error": f"卡方检验失败: {e}"}

    def execute(self, df: pd.DataFrame, **kwargs) -> dict:
        """统一入口 —— 供 ToolRegistry 调用"""
        method = kwargs.get("method", "")
        params = kwargs.get("params", {})

        if method in ("ttest", "t_test", "独立样本t检验", "配对t检验"):
            return self.run_ttest(df, params)
        elif method in ("anova", "方差分析", "单因素方差分析"):
            return self.run_anova(df, params)
        elif method in ("linear_regression", "regression", "线性回归", "回归分析"):
            return self.run_linear_regression(df, params)
        elif method in ("chisquare", "chi_square", "卡方检验"):
            return self.run_chisquare(df, params)
        else:
            return {"success": False, "error": f"未知统计方法: {method}"}
