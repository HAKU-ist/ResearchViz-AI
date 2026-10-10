"""把 ResearchViz 标准化实验知识确定性地转换为知识子图。"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .graph_ontology import (
    EntityType,
    EvidenceType,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    KnowledgeSubgraph,
    RelationType,
)
from .models import ExperimentSchema


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _clean_value(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def _confidence(value: Any, default: float = 1.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _relation(
    relation_type: RelationType,
    source: GraphEntity,
    target: GraphEntity,
    experiment_id: str,
    *,
    evidence: list[GraphEvidence] | None = None,
) -> GraphRelation:
    return GraphRelation(
        id=_stable_id("rel", relation_type.value, source.id, target.id),
        relation_type=relation_type,
        source_id=source.id,
        source_type=source.entity_type,
        target_id=target.id,
        target_type=target.entity_type,
        evidence=evidence or [],
        source_experiment_id=experiment_id,
    )


def build_experiment_subgraph(
    experiment: dict[str, Any],
    normalized: dict[str, Any],
    schema: ExperimentSchema,
) -> KnowledgeSubgraph:
    """从 normalize_experiment() 输出构建一个经过本体校验的子图。

    该函数不访问数据库、不调用模型，也不猜测新的语义事实。
    """

    experiment_id = str(experiment["id"])
    filename = str(experiment.get("filename") or "unknown.csv")
    entities: dict[str, GraphEntity] = {}
    relations: dict[str, GraphRelation] = {}

    def add_entity(item: GraphEntity) -> GraphEntity:
        existing = entities.get(item.id)
        if existing and (existing.entity_type != item.entity_type or existing.properties != item.properties):
            raise ValueError(f"实体 ID 冲突: {item.id}")
        entities[item.id] = existing or item
        return entities[item.id]

    def add_relation(item: GraphRelation) -> None:
        relations[item.id] = item

    experiment_node = add_entity(GraphEntity(
        id=_stable_id("exp", experiment_id),
        entity_type=EntityType.EXPERIMENT,
        properties={
            "name": str(experiment.get("name") or experiment_id),
            "description": str(experiment.get("description") or ""),
            "experiment_type": schema.experiment_type,
            "status": str(experiment.get("status") or "READY"),
            **({"created_at": experiment["created_at"]} if experiment.get("created_at") else {}),
        },
        confidence=1.0,
        evidence=[GraphEvidence(
            evidence_type=EvidenceType.USER_DESCRIPTION,
            source_ref=f"experiment:{experiment_id}/description",
            excerpt=str(experiment.get("description") or "")[:500] or None,
        )],
        source_experiment_id=experiment_id,
    ))

    dataset_nodes: dict[str, GraphEntity] = {}
    for item in normalized.get("datasets", []):
        node = add_entity(GraphEntity(
            id=str(item["id"]), entity_type=EntityType.DATASET,
            properties={
                "canonical_name": str(item["name"]),
                "metadata": item.get("metadata", {}),
            },
            source_experiment_id=experiment_id,
        ))
        dataset_nodes[str(item["id"])] = node

    dataset_variant_nodes: dict[str, GraphEntity] = {}
    for item in normalized.get("dataset_variants", []):
        node = add_entity(GraphEntity(
            id=str(item["id"]), entity_type=EntityType.DATASET_VARIANT,
            properties={
                "display_name": str(item["display_name"]),
                "parameters": item.get("parameters", {}),
                "raw_name": str(item.get("raw_name") or ""),
            },
            confidence=_confidence(item.get("confidence")),
            evidence=[GraphEvidence(
                evidence_type=EvidenceType.EXPERIMENT_SCHEMA,
                source_ref=f"experiment:{experiment_id}/schema/dataset_dimension",
            )],
            source_experiment_id=experiment_id,
        ))
        dataset_variant_nodes[str(item["id"])] = node
        parent = dataset_nodes.get(str(item["dataset_id"]))
        if not parent:
            raise ValueError(f"DatasetVariant {item['id']} 缺少 Dataset: {item['dataset_id']}")
        add_relation(_relation(RelationType.VARIANT_OF, node, parent, experiment_id))
        add_relation(_relation(RelationType.USES_DATASET, experiment_node, node, experiment_id))

    method_nodes: dict[str, GraphEntity] = {}
    for item in normalized.get("methods", []):
        node = add_entity(GraphEntity(
            id=str(item["id"]), entity_type=EntityType.METHOD,
            properties={"canonical_name": str(item["name"])},
            source_experiment_id=experiment_id,
        ))
        method_nodes[str(item["id"])] = node

    method_variant_nodes: dict[str, GraphEntity] = {}
    for item in normalized.get("method_variants", []):
        node = add_entity(GraphEntity(
            id=str(item["id"]), entity_type=EntityType.METHOD_VARIANT,
            properties={
                "display_name": str(item["display_name"]),
                "parameters": item.get("parameters", {}),
                "raw_name": str(item.get("raw_name") or ""),
                "source_column": str(item.get("source_column") or ""),
            },
            confidence=_confidence(item.get("confidence")),
            evidence=[GraphEvidence(
                evidence_type=EvidenceType.EXPERIMENT_SCHEMA,
                source_ref=f"experiment:{experiment_id}/schema/methods",
            )],
            source_experiment_id=experiment_id,
        ))
        method_variant_nodes[str(item["id"])] = node
        parent = method_nodes.get(str(item["method_id"]))
        if not parent:
            raise ValueError(f"MethodVariant {item['id']} 缺少 Method: {item['method_id']}")
        add_relation(_relation(RelationType.VARIANT_OF, node, parent, experiment_id))
        add_relation(_relation(RelationType.EVALUATES_METHOD, experiment_node, node, experiment_id))

    metric_schema = {metric.name.casefold(): metric for metric in schema.metrics}
    condition_columns = {variable.column for variable in schema.variables}
    if schema.repeat_column:
        condition_columns.add(schema.repeat_column)
    metric_nodes: dict[str, GraphEntity] = {}
    for observation in normalized.get("observations", []):
        name = str(observation["metric_name"])
        key = name.casefold()
        if key in metric_nodes:
            continue
        definition = metric_schema.get(key)
        metric_nodes[key] = add_entity(GraphEntity(
            id=_stable_id("metric", key), entity_type=EntityType.METRIC,
            properties={
                "canonical_name": name,
                "direction": definition.direction if definition else "unknown",
            },
            confidence=definition.confidence if definition else 0.5,
            evidence=[GraphEvidence(
                evidence_type=EvidenceType.EXPERIMENT_SCHEMA,
                source_ref=f"experiment:{experiment_id}/schema/metrics",
            )],
            source_experiment_id=experiment_id,
        ))

    condition_nodes: dict[tuple[str, str], GraphEntity] = {}
    for item in normalized.get("observations", []):
        source_row = int(item["source_row"])
        source_column = str(item["source_column"])
        cell_evidence = [GraphEvidence(
            evidence_type=EvidenceType.CSV_CELL,
            source_ref=filename,
            source_row=source_row,
            source_column=source_column,
        )]
        observation_node = add_entity(GraphEntity(
            id=_stable_id("obs", experiment_id, source_row, source_column),
            entity_type=EntityType.OBSERVATION,
            properties={
                "value": float(item["metric_value"]),
                "source_row": source_row,
                "source_column": source_column,
            },
            evidence=cell_evidence,
            source_experiment_id=experiment_id,
        ))
        add_relation(_relation(
            RelationType.PRODUCES_OBSERVATION, experiment_node, observation_node,
            experiment_id, evidence=cell_evidence,
        ))

        dataset_variant = dataset_variant_nodes.get(str(item["dataset_variant_id"]))
        if not dataset_variant:
            raise ValueError(f"Observation {item['id']} 缺少 DatasetVariant")
        add_relation(_relation(
            RelationType.EVALUATED_ON, observation_node, dataset_variant,
            experiment_id, evidence=cell_evidence,
        ))

        method_variant_id = item.get("method_variant_id")
        if method_variant_id:
            method_variant = method_variant_nodes.get(str(method_variant_id))
            if not method_variant:
                raise ValueError(f"Observation {item['id']} 缺少 MethodVariant")
            add_relation(_relation(
                RelationType.PRODUCED_BY, observation_node, method_variant,
                experiment_id, evidence=cell_evidence,
            ))

        metric = metric_nodes[str(item["metric_name"]).casefold()]
        add_relation(_relation(
            RelationType.MEASURES, observation_node, metric,
            experiment_id, evidence=cell_evidence,
        ))

        for raw_name, raw_value in (item.get("dimensions") or {}).items():
            if raw_name not in condition_columns:
                continue
            value = _clean_value(raw_value)
            if value is None:
                continue
            name = str(raw_name)
            serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            condition_key = (name.casefold(), serialized)
            condition = condition_nodes.get(condition_key)
            if not condition:
                condition = add_entity(GraphEntity(
                    id=_stable_id("condition", name.casefold(), value),
                    entity_type=EntityType.CONDITION,
                    properties={
                        "name": name,
                        "value": value,
                        "value_type": type(value).__name__,
                    },
                    evidence=[GraphEvidence(
                        evidence_type=EvidenceType.CSV_CELL,
                        source_ref=filename,
                        source_row=source_row,
                        source_column=name,
                    )],
                    source_experiment_id=experiment_id,
                ))
                condition_nodes[condition_key] = condition
            add_relation(_relation(
                RelationType.UNDER_CONDITION, observation_node, condition,
                experiment_id, evidence=cell_evidence,
            ))

    return KnowledgeSubgraph(
        source_experiment_id=experiment_id,
        entities=list(entities.values()),
        relations=list(relations.values()),
    )
