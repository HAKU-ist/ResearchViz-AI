from pathlib import Path

import pandas as pd

from backend.app.knowledge import normalize_experiment
from backend.app.graph_builder import build_experiment_subgraph
from backend.app.models import ExperimentSchema
from backend.app.storage import Repository
from backend.app.visualization_agent import VISUALIZATION_REACT_TOOLS, VisualizationToolRuntime


def _schema(dataset: str) -> ExperimentSchema:
    return ExperimentSchema.model_validate({
        "experiment_type": "classification",
        "datasets": [dataset],
        "dataset_dimension": {"column": "dataset", "values": [dataset], "confidence": 1.0},
        "methods": {"column": "method", "values": ["Ours"], "confidence": 1.0},
        "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 1.0}],
        "variables": [],
    })


def test_visualization_tools_can_be_composed_as_agent_actions(tmp_path: Path):
    repository = Repository(tmp_path / "agent.db")
    for index, (dataset, accuracy) in enumerate((("cifar10", 0.91), ("cifar100", 0.73)), 1):
        experiment_id = f"exp-{index}"
        frame = pd.DataFrame({"dataset": [dataset], "method": ["Ours"], "accuracy": [accuracy]})
        schema = _schema(dataset)
        knowledge = normalize_experiment(experiment_id, frame, schema, name=dataset, description="Ours accuracy")
        record = {
            "id": experiment_id, "name": dataset, "description": "Ours accuracy",
            "filename": f"{dataset}.csv", "file_path": str(tmp_path / f"{dataset}.csv"),
            "status": "READY", "profile": {"row_count": 1}, "table_sample": {"rows": []},
            "schema": schema.model_dump(mode="json"), "created_at": f"2026-07-18T00:00:0{index}Z",
        }
        graph = build_experiment_subgraph(record, knowledge, schema)
        repository.create_experiment(record, knowledge, graph)

    output_dir = tmp_path / "artifacts"
    output_dir.mkdir()
    runtime = VisualizationToolRuntime(
        repository,
        "用柱状图比较 Ours 在 cifar10 和 cifar100 上的 accuracy",
        output_dir,
        force_rules=True,
    )

    assert {tool["name"] for tool in VISUALIZATION_REACT_TOOLS}.issuperset({
        "search_graph_entities", "get_graph_neighbors", "query_result_subgraph",
    })
    graph_result = runtime.handlers["query_result_subgraph"]({
        "datasets": ["cifar10", "cifar100"], "methods": ["Ours"], "metrics": ["accuracy"],
    })
    assert graph_result["status"] == "READY"
    assert graph_result["observation_count"] == 2

    prepared = runtime.prepare_visualization_data({
        "experiment_ids": ["exp-1", "exp-2"], "reason": "跨数据集比较",
    })
    assert prepared["status"] == "READY"
    assert set(prepared["datasets"]) == {"cifar10", "cifar100"}
    assert runtime.inspect_prepared_data({})["status"] == "READY"
    assert runtime.plan_visualization({})["status"] == "PLANNED"
    assert runtime.generate_visualization({})["status"] == "GENERATED"
    validation = runtime.validate_visualization({})
    assert validation["valid"] is True
    assert runtime.get_visualization_state({})["generation_attempts"] == 1
