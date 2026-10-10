import json
from typing import Any

from pydantic import ValidationError

from .llm import LLMError, QwenProvider
from .knowledge_search import SEARCH_TOOL, search_experiment_knowledge
from .models import DataProfile, ExperimentSchema, TableSample, VisualizationPlan, VisualizationSpec
from .visualization_plan import legacy_spec_to_plan, validate_visualization_plan


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _validate_columns(spec: ExperimentSchema, profile: DataProfile) -> None:
    columns = {column.name for column in profile.columns}
    referenced = (
        [m.column for m in spec.metrics]
        + [v.column for v in spec.variables]
        + [item.column for item in spec.column_meanings]
    )
    if spec.methods.column:
        referenced.append(spec.methods.column)
    referenced.extend(spec.methods.setting_columns)
    if spec.dataset_dimension.column:
        referenced.append(spec.dataset_dimension.column)
    referenced.extend(spec.dataset_dimension.setting_columns)
    if spec.repeat_column:
        referenced.append(spec.repeat_column)
    missing = sorted({name for name in referenced if name not in columns})
    if missing:
        raise LLMError(f"Experiment Schema 引用了不存在的列: {', '.join(missing)}")


def _validate_visualization_columns(spec: VisualizationSpec, profile: DataProfile) -> None:
    columns = {column.name: column for column in profile.columns}
    synthetic_series_name = spec.series_name or spec.group or "series"
    synthetic_x = bool(spec.series_columns and spec.x == synthetic_series_name)
    synthetic_y = spec.series_columns and spec.y in {"value", "__value__"}
    missing = [name for name in (spec.x,) if name and name not in columns and not synthetic_x]
    if spec.y and spec.y not in columns and not synthetic_y:
        missing.append(spec.y)
    if spec.group and not spec.series_columns and spec.group not in columns:
        missing.append(spec.group)
    for name in spec.series_columns:
        if name not in columns:
            missing.append(name)
    selection_columns = (
        ([spec.row_selection.order_by] if spec.row_selection.order_by else [])
        + ([spec.row_selection.column] if spec.row_selection.column else [])
        + spec.row_selection.group_by
    )
    for name in selection_columns:
        if name not in columns:
            missing.append(name)
    if missing:
        raise LLMError(f"Visualization Spec 引用了不存在的列: {', '.join(sorted(set(missing)))}")
    if not synthetic_y and columns[spec.y].semantic_type != "numeric":
        raise LLMError(f"Y 轴 {spec.y} 不是数值字段")
    for name in spec.series_columns:
        if columns[name].semantic_type != "numeric":
            raise LLMError(f"宽表方法列 {name} 不是数值字段")
    if spec.group and spec.group == spec.x:
        raise LLMError("x 与 group 不能引用同一字段；类别柱形图应保留 x 并将 group 设为 null")
    if spec.row_selection.mode in {"first", "last"} and not spec.row_selection.order_by:
        raise LLMError("row_selection 为 first/last 时必须设置 order_by")
    if spec.row_selection.mode == "match":
        if not spec.row_selection.column or spec.row_selection.value is None:
            raise LLMError("row_selection 为 match 时必须设置 column 和 value")
        if spec.row_selection.match_strategy == "nearest" and columns[spec.row_selection.column].semantic_type != "numeric":
            raise LLMError("row_selection 使用 nearest 时 column 必须是数值字段")


def _validate_visualization_values(spec: VisualizationSpec, schema: ExperimentSchema) -> None:
    available = set(schema.methods.values)
    if spec.series_columns:
        invalid = sorted(set(spec.series_columns) - available) if available else []
    elif spec.group_values and schema.methods.column and (
        spec.group == schema.methods.column or spec.x == schema.methods.column
    ):
        invalid = sorted(set(spec.group_values) - available) if available else []
    elif spec.group_values:
        raise LLMError("group_values 必须筛选真实方法列（x/group）或 wide-format series_columns")
    else:
        invalid = []
    if invalid:
        raise LLMError(f"Visualization Spec 引用了不存在的方法取值: {', '.join(invalid)}")


def infer_experiment_with_skill(
    provider: QwenProvider,
    description: str,
    profile: DataProfile,
    table_sample: TableSample,
    skill_prompt: str,
) -> tuple[ExperimentSchema, list[dict[str, Any]]]:
    system = f"""你是 ResearchViz 的实验理解 Agent。下面是你本次必须执行的 Skill 指令。

{skill_prompt}

执行 Skill 后只返回一个 ExperimentSchema JSON 对象，不要返回 Markdown、图表或额外说明。"""
    user = _json({
        "experiment_description": description,
        "data_schema": profile.model_dump(mode="json"),
        "table_sample": table_sample.model_dump(mode="json"),
        "output_json_schema": ExperimentSchema.model_json_schema(),
    })
    try:
        raw, tool_trace = provider.generate_json_with_tools(
            system,
            user,
            tools=[SEARCH_TOOL],
            tool_handlers={"search_experiment_knowledge": search_experiment_knowledge},
            max_tool_rounds=3,
            max_tokens=2200,
        )
        result = ExperimentSchema.model_validate(raw)
        web_facts = [fact for fact in result.external_facts if fact.source_type == "web_search"]
        if web_facts and not tool_trace:
            evidence_system = system + """

证据校验失败：上一次输出包含 external_facts，但没有任何工具调用记录。不得依赖模型记忆或自行编造来源。
本次必须先调用 search_experiment_knowledge 获取证据，再基于工具结果输出 ExperimentSchema。"""
            raw, tool_trace = provider.generate_json_with_tools(
                evidence_system,
                user,
                tools=[SEARCH_TOOL],
                tool_handlers={"search_experiment_knowledge": search_experiment_knowledge},
                max_tool_rounds=3,
                max_tokens=2200,
                force_first_tool=True,
            )
            result = ExperimentSchema.model_validate(raw)
    except ValidationError as exc:
        raise LLMError(f"Experiment Understanding Skill 输出校验失败: {exc.errors()[0]['msg']}") from exc
    evidence_urls = {
        item.get("url")
        for step in tool_trace
        for item in step.get("result", {}).get("results", [])
        if item.get("url")
    }
    unsupported = [
        fact.key
        for fact in result.external_facts
        if fact.source_type == "web_search" and (not fact.source_url or fact.source_url not in evidence_urls)
    ]
    if unsupported:
        raise LLMError(f"External facts 缺少工具证据: {', '.join(unsupported)}")
    _validate_columns(result, profile)
    return result, tool_trace


def plan_visualization_with_skill(
    provider: QwenProvider,
    request: str,
    schema: ExperimentSchema,
    profile: DataProfile,
    table_sample: TableSample,
    skill_prompt: str,
) -> VisualizationPlan:
    system = f"""你是 ResearchViz 的可视化规划 Agent。下面是你本次必须执行的 Skill 指令。

{skill_prompt}

执行 Skill 后只返回一个 VisualizationPlan JSON 对象，其中 data_query 负责数据选择转换，chart 只负责视觉编码。不要返回 Markdown、Python 或额外说明。"""
    payload = {
        "request": request,
        "experiment_schema": schema.model_dump(mode="json"),
        "data_schema": profile.model_dump(mode="json"),
        "table_sample": table_sample.model_dump(mode="json"),
        "available_method_values": schema.methods.values,
        "output_json_schema": VisualizationPlan.model_json_schema(),
    }
    last_error = ""
    previous_output: dict[str, Any] | None = None
    for attempt in range(1, 4):
        turn_payload = dict(payload)
        if previous_output is not None:
            turn_payload["previous_invalid_output"] = previous_output
            turn_payload["validation_error"] = last_error
            turn_payload["retry_instruction"] = "根据校验错误重新执行 Skill；只能引用给定真实列或契约允许的合成字段。"
        raw = provider.generate_json(system, _json(turn_payload), max_tokens=1800)
        previous_output = raw
        try:
            try:
                result = VisualizationPlan.model_validate(raw)
            except ValidationError:
                result = legacy_spec_to_plan(VisualizationSpec.model_validate(raw))
            validate_visualization_plan(result, profile, schema)
            return result
        except ValidationError as exc:
            last_error = f"Visualization Skill 输出结构错误: {exc.errors()[0]['msg']}"
        except LLMError as exc:
            last_error = str(exc)
    raise LLMError(f"Visualization Skill 连续 3 次未通过校验: {last_error}")


def repair_visualization_with_llm(
    provider: QwenProvider,
    request: str,
    schema: ExperimentSchema,
    profile: DataProfile,
    current: VisualizationPlan,
    error: str,
    attempt_count: int,
) -> VisualizationPlan:
    system = """你是 Visualization Plan 修复 Agent。根据执行错误修正计划，只返回 JSON，不返回 Python。
不得使用不存在的列，不得删除必要筛选，不得原样返回无法解决错误的计划。data_query 只负责过滤、reshape、selection 和聚合；chart 只引用查询结果字段。用户只要求部分方法时，必须在 filters 或 reshape.value_columns 中严格保留。rationale 只用一至两句话描述最终修复结果，禁止输出推理过程、能力限制讨论或放宽用户需求。代码最多执行 3 次。"""
    user = _json({
        "original_request": request,
        "experiment_schema": schema.model_dump(mode="json"),
        "data_profile": profile.model_dump(mode="json"),
        "current_spec": current.model_dump(mode="json"),
        "sanitized_execution_error": error[-1600:],
        "attempt_count": attempt_count,
        "max_attempts": 3,
        "output_json_schema": VisualizationPlan.model_json_schema(),
    })
    try:
        result = VisualizationPlan.model_validate(provider.generate_json(system, user, max_tokens=1400))
        validate_visualization_plan(result, profile, schema)
        return result
    except (ValidationError, LLMError):
        validate_visualization_plan(current, profile, schema)
        return current
