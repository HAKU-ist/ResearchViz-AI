from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from .llm import QwenProvider
from .models import (
    ColumnMeaning,
    DatasetDimension,
    ExperimentSchema,
    KnowledgeSourceSelection,
    MethodDimension,
    MethodVariantDefinition,
    Metric,
    Variable,
)
from .storage import Repository
from .tools.knowledge_tools import SOURCE_SELECTION_TOOL_DEFINITIONS, KnowledgeToolRuntime


SOURCE_SELECTION_PROMPT = """你是 ResearchViz 的知识库数据源规划 Agent。
用户只描述想看的图，你必须自己决定使用哪些已入库实验，不能要求用户手动选表。
先调用 list_knowledge_catalog 查看候选；必要时再调用 search_knowledge、方法/数据集详情或观测查询工具。
只选择完成需求所必需且语义匹配的实验。跨数据集、跨实验比较时可选择多个实验。
不要编造 experiment_id。最终只返回 JSON：
{"experiment_ids":["真实ID"],"rationale":"为何这些来源足够完成任务"}
如果没有任何匹配数据，返回 experiment_ids 为空数组。"""


def _offline_selection(repository: Repository, request: str) -> KnowledgeSourceSelection:
    items = [item for item in repository.list_knowledge() if item.get("indexed") and item.get("observation_count", 0)]
    if not items:
        raise ValueError("知识库中没有可用于绘图的结构化观测")
    text = request.casefold()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        labels = [item["name"], *item.get("datasets", []), *item.get("methods", [])]
        score = sum(
            3 for label in labels
            if label and re.search(rf"(?<![a-z0-9]){re.escape(str(label).casefold())}(?![a-z0-9])", text)
        )
        request_tokens = set(re.findall(r"[a-z0-9_.+-]{2,}", text))
        item_tokens = set(re.findall(r"[a-z0-9_.+-]{2,}", str(item).casefold()))
        score += len(request_tokens & item_tokens)
        scored.append((score, item))
    best = max(score for score, _ in scored)
    selected = [item for score, item in scored if score == best] if best > 0 else items
    return KnowledgeSourceSelection(
        experiment_ids=[item["id"] for item in selected[:20]],
        rationale="离线模式按用户需求中的数据集、方法和实验名称匹配知识库来源。",
    )


def select_knowledge_sources(
    repository: Repository,
    request: str,
    provider: QwenProvider | None,
) -> tuple[KnowledgeSourceSelection, list[dict[str, Any]]]:
    """Let the model inspect the catalog and choose one or more source experiments."""
    if provider is None:
        return _offline_selection(repository, request), []
    runtime = KnowledgeToolRuntime(repository)
    raw, trace = provider.generate_json_with_tools(
        SOURCE_SELECTION_PROMPT,
        f"可视化需求：{request}",
        tools=SOURCE_SELECTION_TOOL_DEFINITIONS,
        tool_handlers=runtime.handlers,
        max_tool_rounds=3,
        max_tokens=800,
        force_first_tool=True,
    )
    if not raw.get("experiment_ids"):
        raise ValueError("模型没有在知识库中找到满足需求的数据")
    selection = KnowledgeSourceSelection.model_validate(raw)
    available = {item["id"] for item in repository.list_knowledge() if item.get("indexed")}
    invalid = [item for item in selection.experiment_ids if item not in available]
    if invalid:
        raise ValueError(f"模型选择了无效或未索引的知识项: {', '.join(invalid)}")
    selection.experiment_ids = list(dict.fromkeys(selection.experiment_ids))
    return selection, trace


RESERVED_COLUMNS = {
    "experiment_id", "experiment_name", "dataset", "dataset_variant", "method",
    "method_variant", "metric", "value", "source_row", "source_column",
}


def materialize_observations(rows: list[dict[str, Any]], output_path: Path) -> pd.DataFrame:
    """Flatten normalized observations into one auditable, cross-experiment table."""
    records: list[dict[str, Any]] = []
    for row in rows:
        record = {
            "experiment_id": row["experiment_id"],
            "experiment_name": row["experiment_name"],
            "dataset": row["dataset"],
            "dataset_variant": row["dataset_variant"],
            "method": row.get("method") or "Unknown",
            "method_variant": row.get("method_variant") or row.get("method") or "Unknown",
            "metric": row["metric_name"],
            "value": row["metric_value"],
            "source_row": row["source_row"],
            "source_column": row["source_column"],
        }
        for key, value in (row.get("dimensions") or {}).items():
            column = f"dimension_{key}" if key in RESERVED_COLUMNS else str(key)
            record[column] = value
        records.append(record)
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("所选知识项没有可用于绘图的数值观测")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def build_combined_experiment_schema(frame: pd.DataFrame) -> ExperimentSchema:
    datasets = [str(value) for value in frame["dataset"].dropna().unique()]
    methods = [str(value) for value in frame["method_variant"].dropna().unique()]
    variables = [Variable(name="dataset", column="dataset", ordered=False, confidence=1.0)]
    excluded = RESERVED_COLUMNS | {"value"}
    for column in frame.columns:
        if column in excluded:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().mean() >= 0.8:
            variables.append(Variable(name=column, column=column, ordered=True, confidence=0.95))
    repeat_column = "seed" if "seed" in frame.columns else None
    return ExperimentSchema(
        experiment_type="cross_experiment_comparison",
        datasets=datasets,
        dataset_dimension=DatasetDimension(
            column="dataset", values=datasets, setting_columns=["dataset_variant"], confidence=1.0,
        ),
        methods=MethodDimension(
            column="method_variant", values=methods,
            variants=[MethodVariantDefinition(raw_name=name, method_name=name, confidence=0.95) for name in methods],
            confidence=1.0,
        ),
        metrics=[Metric(name="value", column="value", direction="unknown", confidence=1.0)],
        variables=variables,
        summary="跨实验知识库观测",
        row_meaning="一条标准化实验观测",
        column_meanings=[
            ColumnMeaning(column="dataset", meaning="数据集名称", role="dataset", confidence=1.0),
            ColumnMeaning(column="method_variant", meaning="方法及其设置", role="method", confidence=1.0),
            ColumnMeaning(column="metric", meaning="指标名称", role="metadata", confidence=1.0),
            ColumnMeaning(column="value", meaning="指标数值", role="metric", confidence=1.0),
        ],
        repeat_column=repeat_column,
    )
