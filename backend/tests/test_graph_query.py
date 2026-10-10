from pathlib import Path

from backend.app.graph_builder import build_experiment_subgraph
from backend.app.graph_ontology import EntityType, RelationType
from backend.app.graph_query import GraphQueryService
from backend.app.knowledge import normalize_experiment
from backend.app.models import ExperimentSchema
from backend.app.storage import Repository


def add_experiment(repository: Repository, experiment_id: str, dataset: str, values: list[tuple[str, int, float]]):
    import pandas as pd

    frame = pd.DataFrame([
        {"dataset": dataset, "method": method, "budget": budget, "accuracy": accuracy}
        for method, budget, accuracy in values
    ])
    schema = ExperimentSchema.model_validate({
        "experiment_type": "active_learning", "datasets": [dataset],
        "dataset_dimension": {"column": "dataset", "values": [dataset], "confidence": 0.99},
        "methods": {"column": "method", "values": sorted(frame["method"].unique()), "confidence": 0.99},
        "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 0.99}],
        "variables": [{"name": "budget", "column": "budget", "role": "independent", "ordered": True, "confidence": 0.99}],
    })
    record = {
        "id": experiment_id, "name": f"{dataset} results", "description": "active learning",
        "filename": f"{dataset}.csv", "file_path": f"/tmp/{dataset}.csv", "file_hash": f"hash-{experiment_id}",
        "status": "READY", "profile": {}, "table_sample": {}, "schema": schema.model_dump(mode="json"),
        "created_at": "2026-08-13T00:00:00Z",
    }
    knowledge = normalize_experiment(experiment_id, frame, schema, name=record["name"], description=record["description"])
    graph = build_experiment_subgraph(record, knowledge, schema)
    repository.create_experiment(record, knowledge, graph)


def query_service(tmp_path: Path) -> GraphQueryService:
    repository = Repository(tmp_path / "graph.db")
    add_experiment(repository, "exp-c10", "cifar10", [("Ours", 1000, .81), ("BADGE", 1000, .77), ("Ours", 2000, .86)])
    add_experiment(repository, "exp-c100", "cifar100", [("Ours", 1000, .61), ("BADGE", 1000, .58)])
    return GraphQueryService(repository)


def test_search_entities_returns_scored_source_qualified_results(tmp_path: Path):
    service = query_service(tmp_path)
    result = service.search_entities("Ours", entity_types=["method", "method_variant"])
    assert result["count"] == 4
    assert {item["source_experiment_id"] for item in result["items"]} == {"exp-c10", "exp-c100"}
    assert all(item["match_score"] >= 1 for item in result["items"])


def test_neighbor_query_is_bounded_and_respects_relation_filter(tmp_path: Path):
    service = query_service(tmp_path)
    match = service.search_entities("Ours", entity_types=["method_variant"], experiment_ids=["exp-c10"])["items"][0]
    graph = service.get_neighbors(
        "exp-c10", match["entity"]["id"], relation_types=[RelationType.VARIANT_OF], max_depth=3,
    )
    assert len(graph.entities) == 2
    assert {item.entity_type for item in graph.entities} == {EntityType.METHOD, EntityType.METHOD_VARIANT}
    assert {item.relation_type for item in graph.relations} == {RelationType.VARIANT_OF}


def test_observation_query_filters_across_experiments_and_conditions(tmp_path: Path):
    service = query_service(tmp_path)
    result = service.query_observations(
        datasets=["cifar10", "cifar100"], methods=["Ours"], metrics=["accuracy"],
        conditions={"budget": 1000},
    )
    assert result["observation_count"] == 2
    assert result["fragment_count"] == 2
    assert {item["source_experiment_id"] for item in result["fragments"]} == {"exp-c10", "exp-c100"}
    for fragment in result["fragments"]:
        observations = [item for item in fragment["entities"] if item["entity_type"] == "observation"]
        assert len(observations) == 1


def test_observation_query_does_not_use_nearest_numeric_match(tmp_path: Path):
    service = query_service(tmp_path)
    result = service.query_observations(methods=["Ours"], conditions={"budget": 1001})
    assert result["observation_count"] == 0


def test_limits_bound_returned_observations(tmp_path: Path):
    service = query_service(tmp_path)
    result = service.query_observations(metrics=["accuracy"], limit=2)
    assert result["observation_count"] == 2
