import sqlite3
from pathlib import Path

import pytest

from backend.app.graph_builder import build_experiment_subgraph
from backend.app.graph_ontology import EntityType, KnowledgeSubgraph
from backend.app.knowledge import normalize_experiment
from backend.app.models import ExperimentSchema
from backend.app.storage import Repository


def fixture_payload(experiment_id: str = "exp-graph"):
    import pandas as pd

    frame = pd.DataFrame({
        "dataset": ["cifar10", "cifar10"],
        "method": ["Ours", "BADGE"],
        "budget": [1000, 1000],
        "accuracy": [0.91, 0.87],
    })
    schema = ExperimentSchema.model_validate({
        "experiment_type": "active_learning",
        "datasets": ["cifar10"],
        "dataset_dimension": {"column": "dataset", "values": ["cifar10"], "confidence": 0.99},
        "methods": {"column": "method", "values": ["Ours", "BADGE"], "confidence": 0.99},
        "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 0.99}],
        "variables": [{"name": "budget", "column": "budget", "role": "independent", "ordered": True, "confidence": 0.99}],
    })
    record = {
        "id": experiment_id, "name": "Graph storage", "description": "CIFAR10 AL",
        "filename": "source.csv", "file_path": "/tmp/source.csv", "file_hash": f"hash-{experiment_id}",
        "status": "READY", "profile": {"row_count": 2}, "table_sample": {"rows": []},
        "schema": schema.model_dump(mode="json"), "created_at": "2026-08-13T00:00:00Z",
    }
    knowledge = normalize_experiment(
        experiment_id, frame, schema, name=record["name"], description=record["description"],
    )
    graph = build_experiment_subgraph(record, knowledge, schema)
    return record, knowledge, graph


def test_repository_persists_and_round_trips_validated_subgraph(tmp_path: Path):
    repository = Repository(tmp_path / "graph.db")
    record, knowledge, graph = fixture_payload()
    repository.create_experiment(record, knowledge, graph)

    restored = repository.get_experiment_graph(record["id"])
    assert isinstance(restored, KnowledgeSubgraph)
    assert restored.source_experiment_id == record["id"]
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {item.id for item in restored.relations} == {item.id for item in graph.relations}
    observations = [item for item in restored.entities if item.entity_type == EntityType.OBSERVATION]
    assert {item.evidence[0].source_row for item in observations} == {0, 1}
    assert {item.evidence[0].source_column for item in observations} == {"accuracy"}

    summary = repository.get_graph_summary(record["id"])
    assert summary is not None
    assert summary["ontology_versions"] == ["1.0"]
    assert summary["entity_count"] == len(graph.entities)
    assert summary["relation_count"] == len(graph.relations)
    assert summary["entities_by_type"]["observation"] == 2


def test_replace_knowledge_replaces_graph_idempotently(tmp_path: Path):
    repository = Repository(tmp_path / "graph.db")
    record, knowledge, graph = fixture_payload()
    repository.create_experiment(record, knowledge, graph)
    initial = repository.get_graph_summary(record["id"])

    repository.replace_knowledge(record["id"], knowledge, graph)
    replaced = repository.get_graph_summary(record["id"])
    assert replaced == initial


def test_create_experiment_rolls_back_when_graph_is_for_another_experiment(tmp_path: Path):
    repository = Repository(tmp_path / "graph.db")
    record, knowledge, graph = fixture_payload()
    graph.source_experiment_id = "different-experiment"
    with pytest.raises(ValueError, match="experiment_id 不一致"):
        repository.create_experiment(record, knowledge, graph)
    assert repository.get_experiment(record["id"]) is None
    assert repository.list_knowledge() == []


def test_existing_database_is_migrated_with_graph_tables(tmp_path: Path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE legacy_marker (id TEXT PRIMARY KEY)")
    Repository(database)
    with sqlite3.connect(database) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"graph_entities", "graph_relations"}.issubset(tables)
    assert {"idx_graph_entities_type", "idx_graph_relations_type"}.issubset(indexes)


def test_get_graph_returns_none_for_unknown_experiment(tmp_path: Path):
    repository = Repository(tmp_path / "graph.db")
    assert repository.get_experiment_graph("missing") is None
    assert repository.get_graph_summary("missing") is None
