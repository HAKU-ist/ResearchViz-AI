from .llm import LLMError
from .models import (
    ChartSpec,
    DataFilter,
    DataProfile,
    DataQuerySpec,
    ExperimentSchema,
    QueryAggregation,
    QueryMetric,
    QuerySelection,
    ReshapePlan,
    VisualizationPlan,
    VisualizationSpec,
)


def legacy_spec_to_plan(spec: VisualizationSpec) -> VisualizationPlan:
    filters: list[DataFilter] = []
    if spec.row_selection.mode == "match" and spec.row_selection.column:
        filters.append(DataFilter(column=spec.row_selection.column, operator="eq", value=spec.row_selection.value))
    if spec.group_values and not spec.series_columns:
        filters.append(DataFilter(column=spec.group or spec.x, operator="in", values=spec.group_values))

    series_name = spec.series_name or spec.group or "series"
    value_name = "value"
    reshape = ReshapePlan()
    if spec.series_columns:
        raw_id_columns = [
            column for column in spec.aggregation.group_by
            if column not in spec.series_columns and column != series_name
        ]
        if spec.x not in {series_name, "value", "__value__"} and spec.x not in raw_id_columns:
            raw_id_columns.insert(0, spec.x)
        reshape = ReshapePlan(
            mode="wide_to_long",
            id_columns=raw_id_columns,
            value_columns=spec.series_columns,
            variable_name=series_name,
            value_name=value_name,
        )

    source_y = value_name if spec.series_columns else spec.y
    function = spec.aggregation.y_function
    error = spec.aggregation.error
    metric = QueryMetric(
        source=source_y,
        output=source_y,
        function=function,
        error=error,
        error_output=f"{source_y}_{error}" if error != "none" else None,
    )
    group_by = [column for column in spec.aggregation.group_by if column not in spec.series_columns]
    aggregation = QueryAggregation(group_by=group_by, metrics=[metric])
    selection = QuerySelection(
        mode=spec.row_selection.mode if spec.row_selection.mode in {"first", "last"} else "all",
        order_by=spec.row_selection.order_by,
        group_by=spec.row_selection.group_by,
    )
    chart_x = series_name if spec.series_columns and spec.x == series_name else spec.x
    chart_group = series_name if spec.series_columns and chart_x != series_name else spec.group
    if chart_group == chart_x:
        chart_group = None
    return VisualizationPlan(
        data_query=DataQuerySpec(filters=filters, reshape=reshape, selection=selection, aggregation=aggregation),
        chart=ChartSpec(
            chart_type=spec.chart_type,
            x=chart_x,
            y=source_y,
            group=chart_group,
            error_y=metric.error_output,
            title=spec.title,
            x_label=spec.x_label,
            y_label=spec.y_label,
            dpi=spec.dpi,
        ),
        rationale=spec.rationale,
        assumptions=spec.assumptions,
    )


def validate_visualization_plan(plan: VisualizationPlan, profile: DataProfile, schema: ExperimentSchema) -> None:
    raw = {column.name: column for column in profile.columns}
    query = plan.data_query
    missing_raw: set[str] = set()
    for item in query.filters:
        if item.column not in raw:
            missing_raw.add(item.column)
        if item.operator in {"in", "not_in", "between"} and not item.values:
            raise LLMError(f"过滤条件 {item.column}/{item.operator} 缺少 values")
        if item.operator not in {"in", "not_in", "between"} and item.value is None:
            raise LLMError(f"过滤条件 {item.column}/{item.operator} 缺少 value")
    if query.selection.mode in {"first", "last"}:
        if not query.selection.order_by:
            raise LLMError("first/last selection 必须设置 order_by")
        if query.selection.order_by not in raw:
            missing_raw.add(query.selection.order_by)
        missing_raw.update(column for column in query.selection.group_by if column not in raw)

    reshape = query.reshape
    if reshape.mode == "wide_to_long":
        missing_raw.update(column for column in reshape.id_columns + reshape.value_columns if column not in raw)
        if not reshape.value_columns:
            raise LLMError("wide_to_long 必须提供 value_columns")
        non_numeric = [column for column in reshape.value_columns if column in raw and raw[column].semantic_type != "numeric"]
        if non_numeric:
            raise LLMError(f"wide_to_long value_columns 不是数值列: {', '.join(non_numeric)}")
        available = set(reshape.id_columns) | {reshape.variable_name, reshape.value_name}
        numeric = {reshape.value_name}
    else:
        available = set(raw)
        numeric = {name for name, column in raw.items() if column.semantic_type == "numeric"}
    if missing_raw:
        raise LLMError(f"DataQuerySpec 引用了不存在的原始列: {', '.join(sorted(missing_raw))}")

    aggregation = query.aggregation
    if aggregation:
        missing = [column for column in aggregation.group_by if column not in available]
        missing += [metric.source for metric in aggregation.metrics if metric.source not in available]
        if missing:
            raise LLMError(f"聚合引用了不存在的查询字段: {', '.join(sorted(set(missing)))}")
        output_columns = set(aggregation.group_by)
        output_numeric: set[str] = set()
        for metric in aggregation.metrics:
            output_columns.add(metric.output)
            output_numeric.add(metric.output)
            if metric.error != "none":
                if not metric.error_output:
                    raise LLMError(f"指标 {metric.output} 设置误差时必须提供 error_output")
                output_columns.add(metric.error_output)
                output_numeric.add(metric.error_output)
        available = output_columns
        numeric = output_numeric

    chart = plan.chart
    chart_fields = [chart.x, chart.y] + ([chart.group] if chart.group else []) + ([chart.error_y] if chart.error_y else [])
    missing_chart = [field for field in chart_fields if field not in available]
    if missing_chart:
        raise LLMError(f"ChartSpec 引用了不存在的查询结果字段: {', '.join(missing_chart)}")
    if chart.y not in numeric or (chart.error_y and chart.error_y not in numeric):
        raise LLMError("ChartSpec 的 y/error_y 必须是数值字段")
    if chart.group and chart.group == chart.x:
        raise LLMError("ChartSpec 的 x 与 group 不能相同")

    method_column = schema.methods.column
    if method_column:
        allowed = set(schema.methods.values)
        for item in query.filters:
            if item.column == method_column and item.operator in {"eq", "in"}:
                requested = {str(item.value)} if item.operator == "eq" else {str(value) for value in item.values}
                invalid = requested - allowed if allowed else set()
                if invalid:
                    raise LLMError(f"方法筛选包含不存在的值: {', '.join(sorted(invalid))}")
    if reshape.mode == "wide_to_long":
        allowed = set(schema.methods.values)
        invalid = set(reshape.value_columns) - allowed if allowed else set()
        if invalid:
            raise LLMError(f"wide_to_long 包含不存在的方法列: {', '.join(sorted(invalid))}")
