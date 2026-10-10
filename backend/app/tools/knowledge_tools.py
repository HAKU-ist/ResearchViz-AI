from typing import Any

from ..storage import Repository


LIST_KNOWLEDGE_CATALOG_TOOL = {
    "type": "function",
    "name": "list_knowledge_catalog",
    "description": "列出本地知识库中所有可用实验的摘要、数据集、方法、指标和观测数量。选取可视化数据源前应先调用。",
    "parameters": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50}},
        "required": [],
        "additionalProperties": False,
    },
}

SEARCH_KNOWLEDGE_TOOL = {
    "type": "function",
    "name": "search_knowledge",
    "description": "按实验名称、描述、数据集、方法或指标搜索本地实验知识库，返回候选知识项。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户需求中用于召回实验的关键词或短语。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

LIST_DATASET_VARIANTS_TOOL = {
    "type": "function",
    "name": "list_dataset_variants",
    "description": "列出一个知识项包含的数据集及数据集设置。",
    "parameters": {
        "type": "object",
        "properties": {"experiment_id": {"type": "string"}},
        "required": ["experiment_id"],
        "additionalProperties": False,
    },
}

LIST_METHOD_VARIANTS_TOOL = {
    "type": "function",
    "name": "list_method_variants",
    "description": "列出一个知识项包含的方法族、方法设置、原始标签和参数。",
    "parameters": {
        "type": "object",
        "properties": {"experiment_id": {"type": "string"}},
        "required": ["experiment_id"],
        "additionalProperties": False,
    },
}

INSPECT_KNOWLEDGE_ITEMS_TOOL = {
    "type": "function",
    "name": "inspect_knowledge_items",
    "description": "批量检查多个候选知识项的数据集设置、方法设置、指标和观测数量，适合跨实验选源。",
    "parameters": {
        "type": "object",
        "properties": {
            "experiment_ids": {
                "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20,
            },
        },
        "required": ["experiment_ids"],
        "additionalProperties": False,
    },
}

QUERY_OBSERVATIONS_TOOL = {
    "type": "function",
    "name": "query_observations",
    "description": "从选定实验中按数据集设置、方法设置和指标精确查询数值观测。",
    "parameters": {
        "type": "object",
        "properties": {
            "experiment_id": {"type": "string"},
            "dataset_variant_ids": {"type": "array", "items": {"type": "string"}},
            "method_variant_ids": {"type": "array", "items": {"type": "string"}},
            "metric_names": {"type": "array", "items": {"type": "string"}},
            "dimension_filters": {"type": "object", "additionalProperties": True},
            "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
        },
        "required": ["experiment_id"],
        "additionalProperties": False,
    },
}

KNOWLEDGE_TOOL_DEFINITIONS = [
    LIST_KNOWLEDGE_CATALOG_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    LIST_DATASET_VARIANTS_TOOL,
    LIST_METHOD_VARIANTS_TOOL,
    INSPECT_KNOWLEDGE_ITEMS_TOOL,
    QUERY_OBSERVATIONS_TOOL,
]

# Source selection only needs catalog metadata. Keeping the unrestricted
# dimension_filters schema out of this model call also improves compatibility
# with providers that accept only a strict JSON-Schema subset for tools.
SOURCE_SELECTION_TOOL_DEFINITIONS = [
    LIST_KNOWLEDGE_CATALOG_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    LIST_DATASET_VARIANTS_TOOL,
    LIST_METHOD_VARIANTS_TOOL,
    INSPECT_KNOWLEDGE_ITEMS_TOOL,
]


class KnowledgeToolRuntime:
    """Validated capability boundary for a future Visualization ReAct agent."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def search_knowledge(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 10)), 1), 20)
        items = self.repository.list_knowledge(str(arguments["query"]))[:limit]
        return {"items": items, "count": len(items)}

    def list_knowledge_catalog(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 50)), 1), 50)
        items = self.repository.list_knowledge()[:limit]
        return {"items": items, "count": len(items)}

    def list_dataset_variants(self, arguments: dict[str, Any]) -> dict[str, Any]:
        detail = self.repository.get_knowledge(str(arguments["experiment_id"]))
        return {"dataset_variants": detail["dataset_variants"] if detail else []}

    def list_method_variants(self, arguments: dict[str, Any]) -> dict[str, Any]:
        detail = self.repository.get_knowledge(str(arguments["experiment_id"]))
        return {"method_variants": detail["method_variants"] if detail else []}

    def query_observations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(arguments.get("limit", 500)), 1), 2000)
        rows = self.repository.query_observations(
            str(arguments["experiment_id"]),
            dataset_variant_ids=[str(value) for value in arguments.get("dataset_variant_ids", [])],
            method_variant_ids=[str(value) for value in arguments.get("method_variant_ids", [])],
            metric_names=[str(value) for value in arguments.get("metric_names", [])],
            dimension_filters=arguments.get("dimension_filters", {}),
            limit=limit,
        )
        return {"observations": rows, "count": len(rows)}

    def inspect_knowledge_items(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(value) for value in arguments.get("experiment_ids", [])))[:20]
        items = []
        for experiment_id in ids:
            detail = self.repository.get_knowledge(experiment_id)
            if not detail:
                items.append({"experiment_id": experiment_id, "found": False})
                continue
            experiment = detail["experiment"]
            items.append({
                "experiment_id": experiment_id,
                "found": True,
                "name": experiment["name"],
                "description": experiment["description"],
                "datasets": [
                    {"id": item["id"], "name": item["dataset_name"], "display_name": item["display_name"]}
                    for item in detail["dataset_variants"]
                ],
                "methods": [
                    {"id": item["id"], "name": item["method_name"], "display_name": item["display_name"]}
                    for item in detail["method_variants"]
                ],
                "metrics": detail["metrics"],
                "observation_count": detail["observation_count"],
            })
        return {"items": items, "count": len(items)}

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "list_knowledge_catalog": self.list_knowledge_catalog,
            "search_knowledge": self.search_knowledge,
            "list_dataset_variants": self.list_dataset_variants,
            "list_method_variants": self.list_method_variants,
            "inspect_knowledge_items": self.inspect_knowledge_items,
            "query_observations": self.query_observations,
        }
