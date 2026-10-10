"""ResearchViz 实验知识图谱本体 v1。

该模块只定义图谱契约，不负责数据库持久化或图谱构建。后续 Graph
Builder、Repository 和 Agent Tool 必须共同使用这里的实体、关系和校验规则。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


ONTOLOGY_VERSION = "1.0"


class EntityType(StrEnum):
    EXPERIMENT = "experiment"
    DATASET = "dataset"
    DATASET_VARIANT = "dataset_variant"
    METHOD = "method"
    METHOD_VARIANT = "method_variant"
    METRIC = "metric"
    OBSERVATION = "observation"
    CONDITION = "condition"
    VISUALIZATION = "visualization"
    ARTIFACT = "artifact"
    EXTERNAL_FACT = "external_fact"


class RelationType(StrEnum):
    USES_DATASET = "uses_dataset"
    EVALUATES_METHOD = "evaluates_method"
    PRODUCES_OBSERVATION = "produces_observation"
    VARIANT_OF = "variant_of"
    EVALUATED_ON = "evaluated_on"
    PRODUCED_BY = "produced_by"
    MEASURES = "measures"
    UNDER_CONDITION = "under_condition"
    USES_OBSERVATION = "uses_observation"
    GENERATED_FROM = "generated_from"
    HAS_ARTIFACT = "has_artifact"
    HAS_FACT = "has_fact"
    SAME_AS = "same_as"
    EXTENDS = "extends"


class AssertionMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_INFERRED = "llm_inferred"
    USER_CONFIRMED = "user_confirmed"
    EXTERNAL_IMPORT = "external_import"


class AssertionStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"


class EvidenceType(StrEnum):
    CSV_CELL = "csv_cell"
    USER_DESCRIPTION = "user_description"
    EXPERIMENT_SCHEMA = "experiment_schema"
    DETERMINISTIC_RULE = "deterministic_rule"
    EXTERNAL_SOURCE = "external_source"
    USER_CONFIRMATION = "user_confirmation"


class GraphEvidence(BaseModel):
    """支持一条图谱断言的最小可审计证据。"""

    evidence_type: EvidenceType
    source_ref: str = Field(min_length=1, max_length=500)
    source_row: int | None = Field(default=None, ge=0)
    source_column: str | None = Field(default=None, max_length=200)
    excerpt: str | None = Field(default=None, max_length=500)
    source_url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_evidence_location(self) -> "GraphEvidence":
        if self.evidence_type == EvidenceType.CSV_CELL and self.source_row is None:
            raise ValueError("csv_cell 证据必须提供 source_row")
        if self.evidence_type == EvidenceType.CSV_CELL and not self.source_column:
            raise ValueError("csv_cell 证据必须提供 source_column")
        if self.evidence_type == EvidenceType.EXTERNAL_SOURCE and not self.source_url:
            raise ValueError("external_source 证据必须提供 source_url")
        return self


class EntityDefinition(BaseModel):
    entity_type: EntityType
    description: str
    id_prefix: str
    required_properties: tuple[str, ...]
    optional_properties: tuple[str, ...] = ()


class RelationDefinition(BaseModel):
    relation_type: RelationType
    description: str
    allowed_endpoints: tuple[tuple[EntityType, EntityType], ...]
    inverse: str | None = None
    symmetric: bool = False


ENTITY_DEFINITIONS: dict[EntityType, EntityDefinition] = {
    EntityType.EXPERIMENT: EntityDefinition(
        entity_type=EntityType.EXPERIMENT, description="一次被导入和理解的实验资产",
        id_prefix="exp", required_properties=("name",),
        optional_properties=("description", "experiment_type", "status", "created_at"),
    ),
    EntityType.DATASET: EntityDefinition(
        entity_type=EntityType.DATASET, description="规范化后的数据集概念",
        id_prefix="dataset", required_properties=("canonical_name",),
        optional_properties=("aliases", "task_type", "metadata"),
    ),
    EntityType.DATASET_VARIANT: EntityDefinition(
        entity_type=EntityType.DATASET_VARIANT, description="带划分、噪声率等设置的数据集版本",
        id_prefix="dataset_variant", required_properties=("display_name", "parameters"),
        optional_properties=("raw_name",),
    ),
    EntityType.METHOD: EntityDefinition(
        entity_type=EntityType.METHOD, description="规范化后的算法或方法族",
        id_prefix="method", required_properties=("canonical_name",),
        optional_properties=("aliases", "method_family", "metadata"),
    ),
    EntityType.METHOD_VARIANT: EntityDefinition(
        entity_type=EntityType.METHOD_VARIANT, description="带超参数或组件配置的方法版本",
        id_prefix="method_variant", required_properties=("display_name", "parameters"),
        optional_properties=("raw_name", "source_column"),
    ),
    EntityType.METRIC: EntityDefinition(
        entity_type=EntityType.METRIC, description="可被实验观测的规范化评价指标",
        id_prefix="metric", required_properties=("canonical_name", "direction"),
        optional_properties=("aliases", "unit", "metric_type"),
    ),
    EntityType.OBSERVATION: EntityDefinition(
        entity_type=EntityType.OBSERVATION, description="特定实验上下文中的一个数值结果",
        id_prefix="obs", required_properties=("value",),
        optional_properties=("unit", "source_row", "source_column"),
    ),
    EntityType.CONDITION: EntityDefinition(
        entity_type=EntityType.CONDITION, description="预算、噪声率、seed 等实验条件",
        id_prefix="condition", required_properties=("name", "value"),
        optional_properties=("unit", "value_type"),
    ),
    EntityType.VISUALIZATION: EntityDefinition(
        entity_type=EntityType.VISUALIZATION, description="由一个或多个观测生成的图表",
        id_prefix="vis", required_properties=("request", "status"),
        optional_properties=("chart_type", "created_at"),
    ),
    EntityType.ARTIFACT: EntityDefinition(
        entity_type=EntityType.ARTIFACT, description="CSV、PNG、SVG 或 Python 等文件制品",
        id_prefix="artifact", required_properties=("artifact_type", "path"),
        optional_properties=("sha256", "mime_type", "size_bytes"),
    ),
    EntityType.EXTERNAL_FACT: EntityDefinition(
        entity_type=EntityType.EXTERNAL_FACT, description="完成推理所需且来自项目外部的事实",
        id_prefix="fact", required_properties=("key", "value"),
        optional_properties=("unit", "scope", "retrieved_at"),
    ),
}


RELATION_DEFINITIONS: dict[RelationType, RelationDefinition] = {
    RelationType.USES_DATASET: RelationDefinition(
        relation_type=RelationType.USES_DATASET, description="实验使用某数据集设置",
        allowed_endpoints=((EntityType.EXPERIMENT, EntityType.DATASET_VARIANT),), inverse="used_by_experiment",
    ),
    RelationType.EVALUATES_METHOD: RelationDefinition(
        relation_type=RelationType.EVALUATES_METHOD, description="实验评估某方法设置",
        allowed_endpoints=((EntityType.EXPERIMENT, EntityType.METHOD_VARIANT),), inverse="evaluated_in_experiment",
    ),
    RelationType.PRODUCES_OBSERVATION: RelationDefinition(
        relation_type=RelationType.PRODUCES_OBSERVATION, description="实验产生某数值观测",
        allowed_endpoints=((EntityType.EXPERIMENT, EntityType.OBSERVATION),), inverse="belongs_to_experiment",
    ),
    RelationType.VARIANT_OF: RelationDefinition(
        relation_type=RelationType.VARIANT_OF, description="具体设置属于某规范化实体",
        allowed_endpoints=(
            (EntityType.DATASET_VARIANT, EntityType.DATASET),
            (EntityType.METHOD_VARIANT, EntityType.METHOD),
        ), inverse="has_variant",
    ),
    RelationType.EVALUATED_ON: RelationDefinition(
        relation_type=RelationType.EVALUATED_ON, description="观测在某数据集设置上获得",
        allowed_endpoints=((EntityType.OBSERVATION, EntityType.DATASET_VARIANT),), inverse="has_observation",
    ),
    RelationType.PRODUCED_BY: RelationDefinition(
        relation_type=RelationType.PRODUCED_BY, description="观测由某方法设置产生",
        allowed_endpoints=((EntityType.OBSERVATION, EntityType.METHOD_VARIANT),), inverse="produces_result",
    ),
    RelationType.MEASURES: RelationDefinition(
        relation_type=RelationType.MEASURES, description="观测衡量某指标",
        allowed_endpoints=((EntityType.OBSERVATION, EntityType.METRIC),), inverse="measured_by",
    ),
    RelationType.UNDER_CONDITION: RelationDefinition(
        relation_type=RelationType.UNDER_CONDITION, description="观测满足某实验条件",
        allowed_endpoints=((EntityType.OBSERVATION, EntityType.CONDITION),), inverse="conditions_observation",
    ),
    RelationType.USES_OBSERVATION: RelationDefinition(
        relation_type=RelationType.USES_OBSERVATION, description="图表使用某数值观测",
        allowed_endpoints=((EntityType.VISUALIZATION, EntityType.OBSERVATION),), inverse="used_by_visualization",
    ),
    RelationType.GENERATED_FROM: RelationDefinition(
        relation_type=RelationType.GENERATED_FROM, description="图表源于某实验",
        allowed_endpoints=((EntityType.VISUALIZATION, EntityType.EXPERIMENT),), inverse="has_visualization",
    ),
    RelationType.HAS_ARTIFACT: RelationDefinition(
        relation_type=RelationType.HAS_ARTIFACT, description="实验或图表拥有文件制品",
        allowed_endpoints=(
            (EntityType.EXPERIMENT, EntityType.ARTIFACT),
            (EntityType.VISUALIZATION, EntityType.ARTIFACT),
        ), inverse="artifact_of",
    ),
    RelationType.HAS_FACT: RelationDefinition(
        relation_type=RelationType.HAS_FACT, description="实体具有可用于推理的外部事实",
        allowed_endpoints=tuple(
            (source, EntityType.EXTERNAL_FACT)
            for source in (EntityType.DATASET, EntityType.DATASET_VARIANT, EntityType.METHOD, EntityType.METRIC)
        ), inverse="fact_about",
    ),
    RelationType.SAME_AS: RelationDefinition(
        relation_type=RelationType.SAME_AS, description="两个同类实体语义等价",
        allowed_endpoints=tuple((item, item) for item in (EntityType.DATASET, EntityType.METHOD, EntityType.METRIC)),
        symmetric=True,
    ),
    RelationType.EXTENDS: RelationDefinition(
        relation_type=RelationType.EXTENDS, description="一个方法在语义上扩展另一个方法",
        allowed_endpoints=((EntityType.METHOD, EntityType.METHOD),), inverse="extended_by",
    ),
}


class GraphEntity(BaseModel):
    id: str = Field(min_length=3, max_length=200)
    entity_type: EntityType
    properties: dict[str, Any]
    confidence: float = Field(default=1.0, ge=0, le=1)
    assertion_method: AssertionMethod = AssertionMethod.DETERMINISTIC
    status: AssertionStatus = AssertionStatus.VALIDATED
    evidence: list[GraphEvidence] = Field(default_factory=list)
    source_experiment_id: str | None = Field(default=None, max_length=200)
    ontology_version: str = ONTOLOGY_VERSION

    @model_validator(mode="after")
    def validate_against_ontology(self) -> "GraphEntity":
        definition = ENTITY_DEFINITIONS[self.entity_type]
        if not self.id.startswith(f"{definition.id_prefix}_"):
            raise ValueError(f"{self.entity_type} ID 必须使用前缀 {definition.id_prefix}_")
        missing = [key for key in definition.required_properties if key not in self.properties]
        if missing:
            raise ValueError(f"{self.entity_type} 缺少必需属性: {', '.join(missing)}")
        allowed = set(definition.required_properties + definition.optional_properties)
        unknown = sorted(set(self.properties) - allowed)
        if unknown:
            raise ValueError(f"{self.entity_type} 包含未声明属性: {', '.join(unknown)}")
        if self.assertion_method != AssertionMethod.DETERMINISTIC and not self.evidence:
            raise ValueError("非确定性实体必须提供 evidence")
        return self


class GraphRelation(BaseModel):
    id: str = Field(pattern=r"^rel_[A-Za-z0-9_-]+$", max_length=220)
    relation_type: RelationType
    source_id: str
    source_type: EntityType
    target_id: str
    target_type: EntityType
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0, le=1)
    assertion_method: AssertionMethod = AssertionMethod.DETERMINISTIC
    status: AssertionStatus = AssertionStatus.VALIDATED
    evidence: list[GraphEvidence] = Field(default_factory=list)
    source_experiment_id: str | None = Field(default=None, max_length=200)
    ontology_version: str = ONTOLOGY_VERSION

    @model_validator(mode="after")
    def validate_against_ontology(self) -> "GraphRelation":
        definition = RELATION_DEFINITIONS[self.relation_type]
        endpoint = (self.source_type, self.target_type)
        if endpoint not in definition.allowed_endpoints:
            raise ValueError(
                f"非法关系端点: {self.source_type} -[{self.relation_type}]-> {self.target_type}"
            )
        if self.source_id == self.target_id:
            raise ValueError("关系不能连接实体自身")
        if self.assertion_method != AssertionMethod.DETERMINISTIC and not self.evidence:
            raise ValueError("非确定性关系必须提供 evidence")
        return self


class KnowledgeSubgraph(BaseModel):
    ontology_version: str = ONTOLOGY_VERSION
    source_experiment_id: str | None = Field(default=None, max_length=200)
    entities: list[GraphEntity] = Field(default_factory=list)
    relations: list[GraphRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "KnowledgeSubgraph":
        entities = {entity.id: entity for entity in self.entities}
        if len(entities) != len(self.entities):
            raise ValueError("子图中存在重复实体 ID")
        relation_ids = [relation.id for relation in self.relations]
        if len(set(relation_ids)) != len(relation_ids):
            raise ValueError("子图中存在重复关系 ID")
        for relation in self.relations:
            source = entities.get(relation.source_id)
            target = entities.get(relation.target_id)
            if source is None or target is None:
                raise ValueError(f"关系 {relation.id} 引用了不存在的实体")
            if source.entity_type != relation.source_type or target.entity_type != relation.target_type:
                raise ValueError(f"关系 {relation.id} 的端点类型与实体不一致")
        return self


def ontology_manifest() -> dict[str, Any]:
    """返回可供文档、Graph Builder 或 Tool 层使用的机器可读本体。"""

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "entities": [definition.model_dump(mode="json") for definition in ENTITY_DEFINITIONS.values()],
        "relations": [definition.model_dump(mode="json") for definition in RELATION_DEFINITIONS.values()],
        "evidence_types": [item.value for item in EvidenceType],
        "assertion_methods": [item.value for item in AssertionMethod],
        "assertion_statuses": [item.value for item in AssertionStatus],
    }
