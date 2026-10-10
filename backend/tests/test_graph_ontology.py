import pytest
from pydantic import ValidationError

from backend.app.graph_ontology import (
    AssertionMethod,
    EntityType,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    KnowledgeSubgraph,
    RelationType,
    ontology_manifest,
)


def entity(entity_id: str, entity_type: EntityType, properties: dict) -> GraphEntity:
    return GraphEntity(id=entity_id, entity_type=entity_type, properties=properties)


def test_valid_experiment_observation_subgraph():
    experiment = entity("exp_01", EntityType.EXPERIMENT, {"name": "CIFAR10 AL"})
    observation = entity("obs_01", EntityType.OBSERVATION, {"value": 0.91})
    relation = GraphRelation(
        id="rel_exp_produces_obs",
        relation_type=RelationType.PRODUCES_OBSERVATION,
        source_id=experiment.id,
        source_type=experiment.entity_type,
        target_id=observation.id,
        target_type=observation.entity_type,
    )
    graph = KnowledgeSubgraph(entities=[experiment, observation], relations=[relation])
    assert graph.ontology_version == "1.0"


def test_relation_rejects_illegal_endpoint_types():
    with pytest.raises(ValidationError, match="非法关系端点"):
        GraphRelation(
            id="rel_invalid",
            relation_type=RelationType.MEASURES,
            source_id="method_ours",
            source_type=EntityType.METHOD,
            target_id="metric_accuracy",
            target_type=EntityType.METRIC,
        )


def test_entity_requires_declared_properties_and_prefix():
    with pytest.raises(ValidationError, match="缺少必需属性"):
        entity("metric_accuracy", EntityType.METRIC, {"canonical_name": "accuracy"})
    with pytest.raises(ValidationError, match="ID 必须使用前缀"):
        entity("wrong_accuracy", EntityType.METRIC, {"canonical_name": "accuracy", "direction": "maximize"})
    with pytest.raises(ValidationError, match="未声明属性"):
        entity(
            "metric_accuracy", EntityType.METRIC,
            {"canonical_name": "accuracy", "direction": "maximize", "random_field": True},
        )


def test_inferred_assertion_requires_evidence():
    with pytest.raises(ValidationError, match="必须提供 evidence"):
        GraphEntity(
            id="method_ema", entity_type=EntityType.METHOD,
            properties={"canonical_name": "EMA"}, assertion_method=AssertionMethod.LLM_INFERRED,
        )
    inferred = GraphEntity(
        id="method_ema", entity_type=EntityType.METHOD,
        properties={"canonical_name": "EMA"}, assertion_method=AssertionMethod.LLM_INFERRED,
        evidence=[GraphEvidence(
            evidence_type="experiment_schema", source_ref="experiment:01/schema",
            excerpt="EMA-v4 属于 EMA 方法族",
        )],
    )
    assert inferred.confidence == 1.0


def test_csv_and_external_evidence_require_locations():
    with pytest.raises(ValidationError, match="source_row"):
        GraphEvidence(evidence_type="csv_cell", source_ref="results.csv", source_column="accuracy")
    with pytest.raises(ValidationError, match="source_url"):
        GraphEvidence(evidence_type="external_source", source_ref="CIFAR10 facts")


def test_subgraph_rejects_dangling_and_mismatched_references():
    experiment = entity("exp_01", EntityType.EXPERIMENT, {"name": "test"})
    dangling = GraphRelation(
        id="rel_dangling", relation_type=RelationType.PRODUCES_OBSERVATION,
        source_id="exp_01", source_type=EntityType.EXPERIMENT,
        target_id="obs_missing", target_type=EntityType.OBSERVATION,
    )
    with pytest.raises(ValidationError, match="不存在的实体"):
        KnowledgeSubgraph(entities=[experiment], relations=[dangling])


def test_manifest_is_machine_readable_and_complete():
    manifest = ontology_manifest()
    assert manifest["ontology_version"] == "1.0"
    assert {item["entity_type"] for item in manifest["entities"]} == {item.value for item in EntityType}
    assert {item["relation_type"] for item in manifest["relations"]} == {item.value for item in RelationType}
