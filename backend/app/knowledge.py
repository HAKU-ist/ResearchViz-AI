import hashlib
import json
from collections.abc import Iterable
from typing import Any

import pandas as pd

from .models import ExperimentSchema, MethodVariantDefinition


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _variant_definition(schema: ExperimentSchema, raw_name: str) -> MethodVariantDefinition | None:
    exact = next((item for item in schema.methods.variants if item.raw_name == raw_name), None)
    if exact:
        return exact
    lower = raw_name.casefold()
    return next((item for item in schema.methods.variants if item.raw_name.casefold() == lower), None)


def _display_name(base_name: str, parameters: dict[str, Any]) -> str:
    values = [f"{key}={value}" for key, value in parameters.items() if value is not None]
    return base_name if not values else f"{base_name} ({', '.join(values)})"


def normalize_experiment(
    experiment_id: str,
    frame: pd.DataFrame,
    schema: ExperimentSchema,
    *,
    name: str,
    description: str,
) -> dict[str, Any]:
    """Convert one source CSV into dataset/method entities and numeric observations.

    Semantic choices come from ExperimentSchema. This executor only expands real
    rows and columns, preserving source_row/source_column for auditability.
    """
    columns = {str(column) for column in frame.columns}
    dataset_column = schema.dataset_dimension.column if schema.dataset_dimension.column in columns else None
    dataset_setting_columns = [column for column in schema.dataset_dimension.setting_columns if column in columns]
    method_column = schema.methods.column if schema.methods.column in columns else None
    method_setting_columns = [column for column in schema.methods.setting_columns if column in columns]
    repeat_and_variables = _unique(
        [variable.column for variable in schema.variables if variable.column in columns]
        + ([schema.repeat_column] if schema.repeat_column in columns else [])
    )

    wide_series = [value for value in schema.methods.values if value in columns] if not method_column else []
    metric_by_column = {metric.column: metric for metric in schema.metrics if metric.column in columns}
    long_metric_columns = [column for column in metric_by_column if column not in wide_series]

    datasets: dict[str, dict[str, Any]] = {}
    dataset_variants: dict[str, dict[str, Any]] = {}
    methods: dict[str, dict[str, Any]] = {}
    method_variants: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []

    fallback_dataset = (
        schema.datasets[0]
        if len(schema.datasets) == 1
        else schema.dataset_dimension.values[0]
        if len(schema.dataset_dimension.values) == 1
        else "Unknown"
    )

    def dataset_for(row: pd.Series) -> tuple[str, dict[str, Any]]:
        raw_name = str(_value(row[dataset_column])).strip() if dataset_column and _value(row[dataset_column]) is not None else fallback_dataset
        canonical_name = raw_name or "Unknown"
        dataset_id = _stable_id("dataset", canonical_name.casefold())
        datasets.setdefault(dataset_id, {
            "id": dataset_id,
            "name": canonical_name,
            "metadata": {},
        })
        parameters = {column: _value(row[column]) for column in dataset_setting_columns}
        variant_id = _stable_id("dataset_variant", experiment_id, dataset_id, parameters)
        dataset_variants.setdefault(variant_id, {
            "id": variant_id,
            "experiment_id": experiment_id,
            "dataset_id": dataset_id,
            "raw_name": raw_name,
            "display_name": _display_name(canonical_name, parameters),
            "parameters": parameters,
            "confidence": schema.dataset_dimension.confidence,
        })
        return variant_id, parameters

    def method_for(row: pd.Series, raw_name: str, source_column: str) -> tuple[str, dict[str, Any]]:
        definition = _variant_definition(schema, raw_name)
        base_name = definition.method_name if definition else raw_name
        parameters = dict(definition.parameters) if definition else {}
        for column in method_setting_columns:
            parameters[column] = _value(row[column])
        method_id = _stable_id("method", base_name.casefold())
        methods.setdefault(method_id, {"id": method_id, "name": base_name})
        variant_id = _stable_id("method_variant", experiment_id, method_id, raw_name, parameters)
        method_variants.setdefault(variant_id, {
            "id": variant_id,
            "experiment_id": experiment_id,
            "method_id": method_id,
            "raw_name": raw_name,
            "display_name": _display_name(base_name, parameters),
            "source_column": source_column,
            "parameters": parameters,
            "confidence": definition.confidence if definition else schema.methods.confidence,
        })
        return variant_id, parameters

    for position, (_, row) in enumerate(frame.iterrows()):
        dataset_variant_id, dataset_parameters = dataset_for(row)
        dimensions = {column: _value(row[column]) for column in repeat_and_variables}
        dimensions.update(dataset_parameters)

        if wide_series:
            for source_column in wide_series:
                numeric = pd.to_numeric(pd.Series([row[source_column]]), errors="coerce").iloc[0]
                if pd.isna(numeric):
                    continue
                method_variant_id, _ = method_for(row, source_column, source_column)
                metric = metric_by_column.get(source_column)
                metric_name = schema.methods.metric_name or (
                    metric.name if metric and metric.name != source_column else "value"
                )
                observations.append({
                    "id": _stable_id("observation", experiment_id, position, source_column),
                    "experiment_id": experiment_id,
                    "dataset_variant_id": dataset_variant_id,
                    "method_variant_id": method_variant_id,
                    "metric_name": metric_name,
                    "metric_value": float(numeric),
                    "dimensions": dimensions,
                    "source_row": position,
                    "source_column": source_column,
                })
            continue

        raw_method = str(_value(row[method_column])).strip() if method_column and _value(row[method_column]) is not None else "Unknown"
        method_variant_id, _ = method_for(row, raw_method, method_column or "") if method_column else (None, {})
        for source_column in long_metric_columns:
            numeric = pd.to_numeric(pd.Series([row[source_column]]), errors="coerce").iloc[0]
            if pd.isna(numeric):
                continue
            metric = metric_by_column[source_column]
            observations.append({
                "id": _stable_id("observation", experiment_id, position, source_column),
                "experiment_id": experiment_id,
                "dataset_variant_id": dataset_variant_id,
                "method_variant_id": method_variant_id,
                "metric_name": metric.name,
                "metric_value": float(numeric),
                "dimensions": dimensions,
                "source_row": position,
                "source_column": source_column,
            })

    search_parts = _unique([
        name,
        description,
        schema.summary,
        schema.row_meaning,
        *[item["name"] for item in datasets.values()],
        *[item["display_name"] for item in dataset_variants.values()],
        *[item["display_name"] for item in method_variants.values()],
        *[item["metric_name"] for item in observations],
    ])
    return {
        "datasets": list(datasets.values()),
        "dataset_variants": list(dataset_variants.values()),
        "methods": list(methods.values()),
        "method_variants": list(method_variants.values()),
        "observations": observations,
        "search_text": "\n".join(search_parts),
        "summary": {
            "dataset_count": len(datasets),
            "dataset_variant_count": len(dataset_variants),
            "method_count": len(methods),
            "method_variant_count": len(method_variants),
            "observation_count": len(observations),
        },
    }
