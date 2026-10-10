"""知识图谱只读 Function Calling Tools。"""

from __future__ import annotations

from typing import Any

from ..graph_query import GraphQueryService
from ..storage import Repository


SEARCH_GRAPH_ENTITIES_TOOL = {
    "type": "function",
    "name": "search_graph_entities",
    "description": "按名称和属性搜索实验知识图谱实体，返回来源实验、实体类型、属性、置信度和证据。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "entity_types": {
                "type": "array",
                "items": {"type": "string", "enum": [
                    "experiment", "dataset", "dataset_variant", "method", "method_variant",
                    "metric", "observation", "condition", "visualization", "artifact", "external_fact",
                ]},
            },
            "experiment_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


GET_GRAPH_NEIGHBORS_TOOL = {
    "type": "function",
    "name": "get_graph_neighbors",
    "description": "在一个来源实验子图中，从指定实体出发查询最多三跳的受限邻居和关系。",
    "parameters": {
        "type": "object",
        "properties": {
            "experiment_id": {"type": "string"},
            "entity_id": {"type": "string"},
            "relation_types": {
                "type": "array",
                "items": {"type": "string", "enum": [
                    "uses_dataset", "evaluates_method", "produces_observation", "variant_of",
                    "evaluated_on", "produced_by", "measures", "under_condition",
                    "uses_observation", "generated_from", "has_artifact", "has_fact", "same_as", "extends",
                ]},
            },
            "direction": {"type": "string", "enum": ["out", "in", "both"], "default": "both"},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 100},
        },
        "required": ["experiment_id", "entity_id"],
        "additionalProperties": False,
    },
}


QUERY_RESULT_SUBGRAPH_TOOL = {
    "type": "function",
    "name": "query_result_subgraph",
    "description": (
        "按真实数据集、方法、指标和实验条件精确查询 Observation 子图。"
        "数值条件只做精确匹配，不会自动使用最近值。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "experiment_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "datasets": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "methods": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
            "metrics": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
            "conditions": {
                "type": "object",
                "description": "实验条件名到精确值的映射，例如 budget=10000 或 noise_ratio=0.4。",
                "additionalProperties": True,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
        },
        "required": [],
        "additionalProperties": False,
    },
}


GRAPH_TOOL_DEFINITIONS = [
    SEARCH_GRAPH_ENTITIES_TOOL,
    GET_GRAPH_NEIGHBORS_TOOL,
    QUERY_RESULT_SUBGRAPH_TOOL,
]


class GraphToolRuntime:
    def __init__(self, repository: Repository):
        self.service = GraphQueryService(repository)

    def search_graph_entities(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.service.search_entities(
                str(arguments.get("query", "")),
                entity_types=arguments.get("entity_types"),
                experiment_ids=arguments.get("experiment_ids"),
                limit=int(arguments.get("limit", 20)),
            )
        except (ValueError, KeyError) as exc:
            return {"status": "ERROR", "error": str(exc)}

    def get_graph_neighbors(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            graph = self.service.get_neighbors(
                str(arguments.get("experiment_id", "")),
                str(arguments.get("entity_id", "")),
                relation_types=arguments.get("relation_types"),
                direction=str(arguments.get("direction", "both")),
                max_depth=int(arguments.get("max_depth", 1)),
                limit=int(arguments.get("limit", 100)),
            )
            return {"status": "READY", "subgraph": graph.model_dump(mode="json")}
        except (ValueError, KeyError) as exc:
            return {"status": "ERROR", "error": str(exc)}

    def query_result_subgraph(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return {
                "status": "READY",
                **self.service.query_observations(
                    experiment_ids=arguments.get("experiment_ids"),
                    datasets=arguments.get("datasets"),
                    methods=arguments.get("methods"),
                    metrics=arguments.get("metrics"),
                    conditions=arguments.get("conditions"),
                    limit=int(arguments.get("limit", 200)),
                ),
            }
        except (ValueError, KeyError) as exc:
            return {"status": "ERROR", "error": str(exc)}

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "search_graph_entities": self.search_graph_entities,
            "get_graph_neighbors": self.get_graph_neighbors,
            "query_result_subgraph": self.query_result_subgraph,
        }
