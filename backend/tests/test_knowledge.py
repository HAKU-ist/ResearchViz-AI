from pathlib import Path

import pandas as pd

from backend.app.knowledge import normalize_experiment
from backend.app.models import ExperimentSchema
from backend.app.profiler import infer_experiment_schema, profile_csv
from backend.app.storage import Repository
from backend.app.tools.knowledge_tools import KNOWLEDGE_TOOL_DEFINITIONS, KnowledgeToolRuntime


ROOT = Path(__file__).parents[2]


def test_wide_csv_splits_dataset_method_settings_and_observations():
    source = ROOT / "testdata" / "cifar10.csv"
    frame, profile = profile_csv(source)
    raw = infer_experiment_schema("CIFAR10 主动学习 accuracy", frame, profile).model_dump(mode="json")
    raw["methods"]["variants"] = [
        {
            "raw_name": "EMA-v4 kNN CE",
            "method_name": "EMA",
            "parameters": {"version": "v4", "head": "kNN", "loss": "CE"},
            "confidence": 0.97,
        },
        *[
            {"raw_name": name, "method_name": name, "parameters": {}, "confidence": 0.9}
            for name in raw["methods"]["values"]
            if name != "EMA-v4 kNN CE"
        ],
    ]
    schema = ExperimentSchema.model_validate(raw)
    knowledge = normalize_experiment("exp-wide", frame, schema, name="CIFAR10 AL", description="test")

    assert knowledge["summary"]["dataset_count"] == 1
    assert knowledge["summary"]["dataset_variant_count"] == 1
    assert knowledge["summary"]["method_variant_count"] == 6
    assert knowledge["summary"]["observation_count"] == len(frame) * 6
    ema = next(item for item in knowledge["method_variants"] if item["raw_name"] == "EMA-v4 kNN CE")
    assert next(item for item in knowledge["methods"] if item["id"] == ema["method_id"])["name"] == "EMA"
    assert ema["parameters"] == {"version": "v4", "head": "kNN", "loss": "CE"}
    assert knowledge["observations"][0]["source_row"] == 0


def test_long_csv_splits_noise_ratios_as_dataset_variants():
    source = ROOT / "testdata" / "cifar10_noise_long.csv"
    frame, profile = profile_csv(source)
    schema = infer_experiment_schema(
        "CIFAR10 噪声学习实验，比较不同方法在不同 noise ratio 下的 best acc",
        frame,
        profile,
    )
    knowledge = normalize_experiment("exp-long", frame, schema, name="Noise learning", description="test")

    assert knowledge["summary"]["dataset_count"] == 1
    assert knowledge["summary"]["dataset_variant_count"] == frame["noise_ratio"].nunique()
    assert knowledge["summary"]["method_variant_count"] == frame["method"].nunique()
    assert knowledge["summary"]["observation_count"] == len(frame)
    assert {item["parameters"]["noise_ratio"] for item in knowledge["dataset_variants"]} == {0.2, 0.4, 0.6}


def test_multiple_datasets_are_separate_entities():
    frame = pd.DataFrame({
        "dataset": ["cifar10", "cifar100"],
        "method": ["EMA", "EMA"],
        "accuracy": [0.9, 0.7],
    })
    schema = ExperimentSchema.model_validate({
        "experiment_type": "classification",
        "datasets": ["CIFAR10", "CIFAR100"],
        "dataset_dimension": {"column": "dataset", "values": ["cifar10", "cifar100"], "confidence": 0.99},
        "methods": {
            "column": "method", "values": ["EMA"], "metric_name": None, "confidence": 0.99,
            "variants": [{"raw_name": "EMA", "method_name": "EMA", "parameters": {}, "confidence": 0.99}],
        },
        "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 0.99}],
        "variables": [],
    })
    knowledge = normalize_experiment("exp-multi", frame, schema, name="multi", description="multi dataset")
    assert {item["name"] for item in knowledge["datasets"]} == {"cifar10", "cifar100"}
    assert len(knowledge["dataset_variants"]) == 2
    assert len(knowledge["observations"]) == 2


def test_repository_persists_and_searches_normalized_knowledge(tmp_path: Path):
    frame = pd.DataFrame({"dataset": ["cifar10"], "method": ["EMA"], "accuracy": [0.9]})
    schema = ExperimentSchema.model_validate({
        "experiment_type": "classification",
        "datasets": ["CIFAR10"],
        "dataset_dimension": {"column": "dataset", "values": ["cifar10"], "confidence": 0.99},
        "methods": {"column": "method", "values": ["EMA"], "confidence": 0.99},
        "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 0.99}],
        "variables": [],
    })
    knowledge = normalize_experiment("exp-db", frame, schema, name="CIFAR knowledge", description="EMA accuracy")
    repository = Repository(tmp_path / "test.db")
    record = {
        "id": "exp-db", "name": "CIFAR knowledge", "description": "EMA accuracy",
        "filename": "source.csv", "file_path": "/tmp/source.csv", "status": "READY",
        "profile": {"row_count": 1}, "table_sample": {"rows": []},
        "schema": schema.model_dump(mode="json"), "created_at": "2026-07-18T00:00:00Z",
    }
    repository.create_experiment(record, knowledge)

    matches = repository.list_knowledge("EMA")
    assert len(matches) == 1
    assert matches[0]["observation_count"] == 1
    assert matches[0]["datasets"] == ["cifar10"]
    assert matches[0]["methods"] == ["EMA"]
    detail = repository.get_knowledge("exp-db")
    assert detail is not None
    assert detail["dataset_variants"][0]["dataset_name"] == "cifar10"
    assert detail["method_variants"][0]["method_name"] == "EMA"
    assert detail["metrics"] == ["accuracy"]

    runtime = KnowledgeToolRuntime(repository)
    assert {tool["name"] for tool in KNOWLEDGE_TOOL_DEFINITIONS} == {
        "list_knowledge_catalog", "search_knowledge", "list_dataset_variants", "list_method_variants",
        "inspect_knowledge_items", "query_observations",
    }
    assert runtime.list_knowledge_catalog({})["count"] == 1
    inspected = runtime.inspect_knowledge_items({"experiment_ids": ["exp-db"]})
    assert inspected["items"][0]["metrics"] == ["accuracy"]
    assert runtime.search_knowledge({"query": "EMA"})["count"] == 1
    observations = runtime.query_observations({
        "experiment_id": "exp-db",
        "dimension_filters": {},
    })
    assert observations["count"] == 1
    assert observations["observations"][0]["metric_value"] == 0.9
    exported = repository.export_observations(["exp-db"])
    assert exported[0]["experiment_name"] == "CIFAR knowledge"
    assert exported[0]["dataset"] == "cifar10"
    assert exported[0]["method_variant"] == "EMA"
