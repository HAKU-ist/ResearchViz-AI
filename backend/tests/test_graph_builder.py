from pathlib import Path

from backend.app.graph_builder import build_experiment_subgraph
from backend.app.graph_ontology import EntityType, RelationType
from backend.app.knowledge import normalize_experiment
from backend.app.models import ExperimentSchema
from backend.app.profiler import infer_experiment_schema, profile_csv


ROOT = Path(__file__).parents[2]


def build_from_csv(filename: str, description: str, experiment_id: str = "source-exp"):
    source = ROOT / "testdata" / filename
    frame, profile = profile_csv(source)
    schema = infer_experiment_schema(description, frame, profile)
    normalized = normalize_experiment(
        experiment_id, frame, schema, name="Graph fixture", description=description,
    )
    graph = build_experiment_subgraph({
        "id": experiment_id, "name": "Graph fixture", "description": description,
        "filename": filename, "status": "READY",
    }, normalized, schema)
    return frame, normalized, graph


def test_wide_experiment_builds_traceable_graph():
    frame, normalized, graph = build_from_csv(
        "cifar10.csv", "CIFAR10 主动学习 accuracy，n_labeled 是预算",
    )
    by_type = {kind: [item for item in graph.entities if item.entity_type == kind] for kind in EntityType}
    assert len(by_type[EntityType.EXPERIMENT]) == 1
    assert len(by_type[EntityType.DATASET]) == 1
    assert len(by_type[EntityType.DATASET_VARIANT]) == 1
    assert len(by_type[EntityType.METHOD_VARIANT]) == normalized["summary"]["method_variant_count"]
    assert len(by_type[EntityType.OBSERVATION]) == normalized["summary"]["observation_count"]
    expected_conditions = frame["n_labeled"].nunique() + frame["round"].nunique()
    assert len(by_type[EntityType.CONDITION]) == expected_conditions
    first_observation = by_type[EntityType.OBSERVATION][0]
    assert first_observation.evidence[0].source_row == 0
    assert first_observation.evidence[0].source_column in frame.columns


def test_long_noise_experiment_builds_dataset_variants_and_conditions():
    frame, normalized, graph = build_from_csv(
        "cifar10_noise_long.csv",
        "CIFAR10 噪声学习实验，比较方法在不同 noise ratio 下的 best acc",
        "noise-exp",
    )
    dataset_variants = [item for item in graph.entities if item.entity_type == EntityType.DATASET_VARIANT]
    conditions = [item for item in graph.entities if item.entity_type == EntityType.CONDITION]
    noise_conditions = [item for item in conditions if item.properties["name"] == "noise_ratio"]
    assert len(dataset_variants) == frame["noise_ratio"].nunique()
    assert {item.properties["value"] for item in noise_conditions} == set(frame["noise_ratio"])
    assert len([item for item in graph.relations if item.relation_type == RelationType.EVALUATED_ON]) == len(frame)
    assert len([item for item in graph.relations if item.relation_type == RelationType.MEASURES]) == len(frame)


def test_every_relation_is_resolved_and_stable():
    _, _, first = build_from_csv("cifar10.csv", "CIFAR10 主动学习 accuracy")
    _, _, second = build_from_csv("cifar10.csv", "CIFAR10 主动学习 accuracy")
    assert {item.id for item in first.entities} == {item.id for item in second.entities}
    assert {item.id for item in first.relations} == {item.id for item in second.relations}
    entity_ids = {item.id for item in first.entities}
    assert all(item.source_id in entity_ids and item.target_id in entity_ids for item in first.relations)


def test_metric_direction_comes_from_experiment_schema():
    _, _, graph = build_from_csv("cifar10.csv", "CIFAR10 主动学习 accuracy")
    metrics = [item for item in graph.entities if item.entity_type == EntityType.METRIC]
    assert metrics
    assert all(item.properties["direction"] in {"maximize", "minimize", "neutral", "unknown"} for item in metrics)
