"""受限、只读的知识图谱查询服务。"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from .graph_ontology import EntityType, KnowledgeSubgraph, RelationType
from .storage import Repository


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).casefold()


def _matches(value: Any, candidates: list[str]) -> bool:
    if not candidates:
        return True
    haystack = _text(value)
    return any(str(candidate).strip().casefold() in haystack for candidate in candidates if str(candidate).strip())


def _same_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(actual) - float(expected)) <= 1e-9
    return str(actual).casefold() == str(expected).casefold()


class GraphQueryService:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _experiment_ids(self, experiment_ids: list[str] | None = None) -> list[str]:
        available = [item["id"] for item in self.repository.list_knowledge()]
        if not experiment_ids:
            return available
        requested = set(experiment_ids)
        return [item for item in available if item in requested]

    def search_entities(
        self,
        query: str,
        *,
        entity_types: list[EntityType | str] | None = None,
        experiment_ids: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        needle = query.strip().casefold()
        if not needle:
            raise ValueError("图谱实体搜索 query 不能为空")
        allowed = {EntityType(item) for item in entity_types or []}
        results: list[dict[str, Any]] = []
        for experiment_id in self._experiment_ids(experiment_ids):
            graph = self.repository.get_experiment_graph(experiment_id)
            if not graph:
                continue
            for entity in graph.entities:
                if allowed and entity.entity_type not in allowed:
                    continue
                searchable = _text(entity.properties)
                if needle not in searchable:
                    continue
                canonical = str(
                    entity.properties.get("canonical_name")
                    or entity.properties.get("display_name")
                    or entity.properties.get("name")
                    or ""
                ).casefold()
                score = 3 if canonical == needle else 2 if canonical.startswith(needle) else 1
                results.append({
                    "source_experiment_id": experiment_id,
                    "entity": entity.model_dump(mode="json"),
                    "match_score": score,
                })
        results.sort(key=lambda item: (-item["match_score"], item["entity"]["entity_type"], item["entity"]["id"]))
        bounded = results[: min(max(limit, 1), 100)]
        return {"query": query, "count": len(bounded), "items": bounded}

    def get_neighbors(
        self,
        experiment_id: str,
        entity_id: str,
        *,
        relation_types: list[RelationType | str] | None = None,
        direction: str = "both",
        max_depth: int = 1,
        limit: int = 100,
    ) -> KnowledgeSubgraph:
        if direction not in {"out", "in", "both"}:
            raise ValueError("direction 必须为 out、in 或 both")
        depth_limit = min(max(int(max_depth), 1), 3)
        node_limit = min(max(int(limit), 1), 300)
        graph = self.repository.get_experiment_graph(experiment_id)
        if graph is None:
            raise KeyError("实验不存在")
        entities = {item.id: item for item in graph.entities}
        if entity_id not in entities:
            raise KeyError("图谱实体不存在于该实验子图")
        allowed = {RelationType(item) for item in relation_types or []}
        adjacent: dict[str, list[tuple[str, Any]]] = {}
        for relation in graph.relations:
            if allowed and relation.relation_type not in allowed:
                continue
            if direction in {"out", "both"}:
                adjacent.setdefault(relation.source_id, []).append((relation.target_id, relation))
            if direction in {"in", "both"}:
                adjacent.setdefault(relation.target_id, []).append((relation.source_id, relation))

        selected_ids = {entity_id}
        selected_relations: dict[str, Any] = {}
        queue = deque([(entity_id, 0)])
        while queue and len(selected_ids) < node_limit:
            current, depth = queue.popleft()
            if depth >= depth_limit:
                continue
            for neighbor_id, relation in adjacent.get(current, []):
                selected_relations[relation.id] = relation
                if neighbor_id not in selected_ids:
                    selected_ids.add(neighbor_id)
                    queue.append((neighbor_id, depth + 1))
                if len(selected_ids) >= node_limit:
                    break
        return KnowledgeSubgraph(
            source_experiment_id=experiment_id,
            entities=[entities[item] for item in selected_ids],
            relations=list(selected_relations.values()),
        )

    def query_observations(
        self,
        *,
        experiment_ids: list[str] | None = None,
        datasets: list[str] | None = None,
        methods: list[str] | None = None,
        metrics: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        datasets = datasets or []
        methods = methods or []
        metrics = metrics or []
        conditions = conditions or {}
        remaining = min(max(int(limit), 1), 2000)
        fragments: list[dict[str, Any]] = []
        total_observations = 0

        for experiment_id in self._experiment_ids(experiment_ids):
            if remaining <= 0:
                break
            graph = self.repository.get_experiment_graph(experiment_id)
            if not graph:
                continue
            entities = {item.id: item for item in graph.entities}
            outgoing: dict[str, list[Any]] = {}
            incoming: dict[str, list[Any]] = {}
            for relation in graph.relations:
                outgoing.setdefault(relation.source_id, []).append(relation)
                incoming.setdefault(relation.target_id, []).append(relation)

            matched_observations: list[str] = []
            for observation in (item for item in graph.entities if item.entity_type == EntityType.OBSERVATION):
                links = outgoing.get(observation.id, [])
                dataset_nodes = [entities[item.target_id] for item in links if item.relation_type == RelationType.EVALUATED_ON]
                method_nodes = [entities[item.target_id] for item in links if item.relation_type == RelationType.PRODUCED_BY]
                metric_nodes = [entities[item.target_id] for item in links if item.relation_type == RelationType.MEASURES]
                condition_nodes = [entities[item.target_id] for item in links if item.relation_type == RelationType.UNDER_CONDITION]

                dataset_values: list[Any] = [item.properties for item in dataset_nodes]
                for variant in dataset_nodes:
                    dataset_values.extend(
                        entities[item.target_id].properties
                        for item in outgoing.get(variant.id, [])
                        if item.relation_type == RelationType.VARIANT_OF
                    )
                method_values: list[Any] = [item.properties for item in method_nodes]
                for variant in method_nodes:
                    method_values.extend(
                        entities[item.target_id].properties
                        for item in outgoing.get(variant.id, [])
                        if item.relation_type == RelationType.VARIANT_OF
                    )
                condition_values = {item.properties["name"]: item.properties["value"] for item in condition_nodes}
                if datasets and not any(_matches(value, datasets) for value in dataset_values):
                    continue
                if methods and not any(_matches(value, methods) for value in method_values):
                    continue
                if metrics and not any(_matches(item.properties, metrics) for item in metric_nodes):
                    continue
                if any(key not in condition_values or not _same_value(condition_values[key], value) for key, value in conditions.items()):
                    continue
                matched_observations.append(observation.id)
                if len(matched_observations) >= remaining:
                    break

            if not matched_observations:
                continue
            selected_ids = set(matched_observations)
            selected_relations: dict[str, Any] = {}
            for observation_id in matched_observations:
                for relation in outgoing.get(observation_id, []) + incoming.get(observation_id, []):
                    selected_relations[relation.id] = relation
                    selected_ids.add(relation.source_id)
                    selected_ids.add(relation.target_id)
            # Include canonical Dataset/Method parents for explainable matching.
            for entity_id in list(selected_ids):
                for relation in outgoing.get(entity_id, []):
                    if relation.relation_type == RelationType.VARIANT_OF:
                        selected_relations[relation.id] = relation
                        selected_ids.add(relation.target_id)
            fragment = KnowledgeSubgraph(
                source_experiment_id=experiment_id,
                entities=[entities[item] for item in selected_ids],
                relations=list(selected_relations.values()),
            )
            fragments.append(fragment.model_dump(mode="json"))
            count = len(matched_observations)
            total_observations += count
            remaining -= count

        return {
            "observation_count": total_observations,
            "fragment_count": len(fragments),
            "fragments": fragments,
            "filters": {
                "experiment_ids": experiment_ids or [], "datasets": datasets,
                "methods": methods, "metrics": metrics, "conditions": conditions,
            },
        }
