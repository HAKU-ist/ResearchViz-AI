"""Deterministic offline fallback used only when RESEARCHVIZ_FORCE_RULES=1."""

from .models import Aggregation, DataProfile, ExperimentSchema, VisualizationSpec


def _mentioned(request: str, candidates: list[str]) -> str | None:
    lower = request.lower()
    return next((name for name in candidates if name.lower() in lower), None)


def _mentioned_values(request: str, candidates: list[str]) -> list[str]:
    lower = request.lower()
    return [name for name in candidates if name.lower() in lower]


def plan_visualization(request: str, schema: ExperimentSchema, profile: DataProfile) -> VisualizationSpec:
    numeric = [c.name for c in profile.columns if c.semantic_type == "numeric"]
    if not schema.metrics:
        raise ValueError("实验中没有可绘制的数值指标")
    lower = request.lower()
    wide_methods = [m for m in schema.methods.values if m in numeric]
    selected_methods = _mentioned_values(request, schema.methods.values)
    compare_methods = any(k in lower for k in ("different methods", "compare", "comparison", "方法", "算法", "曲线", "多条", "multi"))

    if not schema.methods.column and len(wide_methods) >= 2 and compare_methods:
        x_candidates = [v.column for v in schema.variables if v.column not in wide_methods]
        preferred_order = ("budget", "n_labeled", "labeled", "label", "query", "round", "step", "epoch", "time")
        preferred_x = _mentioned(request, x_candidates)
        if not preferred_x and x_candidates:
            preferred_x = min(
                x_candidates,
                key=lambda c: next((idx for idx, key in enumerate(preferred_order) if key in c.lower()), len(preferred_order)),
            )
        if not preferred_x:
            raise ValueError("无法确定宽表实验的 X 轴，请在请求中指定 budget/round 等字段")
        chosen_methods = [method for method in wide_methods if method in selected_methods] or wide_methods
        return VisualizationSpec(
            chart_type="line",
            x=preferred_x,
            y=chosen_methods[0],
            group="method",
            group_values=chosen_methods,
            series_columns=chosen_methods,
            series_name="method",
            aggregation=Aggregation(group_by=[preferred_x, "method"], y_function="mean", error="none"),
            title=f"Accuracy vs. {preferred_x}",
            x_label=preferred_x.replace("_", " ").title(),
            y_label="Accuracy",
            rationale=f"检测到宽表方法列 {', '.join(chosen_methods)}，绘图前先转成长表并按 method 分组画多条线",
            assumptions=["多个方法结果以独立数值列存储，绘图时会自动 melt 成 method/value 长表"] + ([f"按用户请求仅保留方法: {', '.join(chosen_methods)}"] if selected_methods else []),
        )

    y = _mentioned(request, [m.column for m in schema.metrics]) or schema.metrics[0].column
    variables = [v.column for v in schema.variables if v.column != y]
    x = _mentioned(request, variables) or (variables[0] if variables else next((c for c in numeric if c != y), ""))
    if not x:
        raise ValueError("无法确定图表 X 轴，请在请求中指定字段")
    group = schema.methods.column
    if any(k in lower for k in ("散点", "scatter", "相关")):
        chart_type = "scatter"
    elif any(k in lower for k in ("箱线", "box", "分布")):
        chart_type = "box"
    elif any(k in lower for k in ("柱", "bar", "柱状")):
        chart_type = "bar"
    else:
        chart_type = "line"
    use_error = bool(schema.repeat_column and chart_type in ("line", "bar"))
    group_by = [x] + ([group] if group else [])
    assumptions = []
    if use_error:
        assumptions.append(f"将 {schema.repeat_column} 视作重复实验并显示标准差")
    if group and selected_methods:
        assumptions.append(f"按用户请求仅保留方法: {', '.join(selected_methods)}")
    return VisualizationSpec(
        chart_type=chart_type, x=x, y=y, group=group, group_values=selected_methods,
        aggregation=Aggregation(group_by=group_by, y_function="mean", error="std" if use_error else "none"),
        title=f"{y} vs. {x}", x_label=x.replace("_", " ").title(), y_label=y.replace("_", " ").title(),
        rationale=f"根据请求和字段类型选择 {chart_type}，X={x}，Y={y}" , assumptions=assumptions,
    )
