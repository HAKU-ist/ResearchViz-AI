from pathlib import Path

from backend.app.tools.graph_tools import GRAPH_TOOL_DEFINITIONS, GraphToolRuntime
from backend.tests.test_graph_query import add_experiment
from backend.app.storage import Repository


def runtime(tmp_path: Path) -> GraphToolRuntime:
    repository = Repository(tmp_path / "graph.db")
    add_experiment(repository, "exp-c10", "cifar10", [("Ours", 1000, .81), ("BADGE", 1000, .77)])
    return GraphToolRuntime(repository)


def test_graph_tool_contract_has_three_bounded_read_only_tools():
    assert {item["name"] for item in GRAPH_TOOL_DEFINITIONS} == {
        "search_graph_entities", "get_graph_neighbors", "query_result_subgraph",
    }
    assert all(item["type"] == "function" for item in GRAPH_TOOL_DEFINITIONS)
    assert all(item["parameters"]["additionalProperties"] is False for item in GRAPH_TOOL_DEFINITIONS)


def test_runtime_search_and_result_query(tmp_path: Path):
    tools = runtime(tmp_path)
    searched = tools.search_graph_entities({"query": "Ours", "entity_types": ["method_variant"]})
    assert searched["count"] == 1
    result = tools.query_result_subgraph({
        "datasets": ["cifar10"], "methods": ["Ours"], "metrics": ["accuracy"],
        "conditions": {"budget": 1000},
    })
    assert result["status"] == "READY"
    assert result["observation_count"] == 1


def test_runtime_neighbor_query_and_error_are_structured(tmp_path: Path):
    tools = runtime(tmp_path)
    match = tools.search_graph_entities({"query": "Ours", "entity_types": ["method_variant"]})["items"][0]
    result = tools.get_graph_neighbors({
        "experiment_id": "exp-c10", "entity_id": match["entity"]["id"],
        "relation_types": ["variant_of"], "max_depth": 1,
    })
    assert result["status"] == "READY"
    assert len(result["subgraph"]["entities"]) == 2
    error = tools.get_graph_neighbors({"experiment_id": "exp-c10", "entity_id": "missing"})
    assert error["status"] == "ERROR"


def test_runtime_clamps_limits_in_service(tmp_path: Path):
    tools = runtime(tmp_path)
    result = tools.query_result_subgraph({"limit": 999999})
    assert result["observation_count"] == 2
