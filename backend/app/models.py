from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    physical_type: str
    semantic_type: Literal["numeric", "categorical", "text", "boolean", "datetime"]
    nullable: bool
    null_count: int
    null_ratio: float
    unique_count: int
    sample_values: list[Any] = Field(default_factory=list)
    statistics: dict[str, Any] | None = None


class DataSchema(BaseModel):
    schema_version: str = "1.0"
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    warnings: list[str] = Field(default_factory=list)


class DataProfile(DataSchema):
    """Backward-compatible alias for the old profiling layer."""


class SampleRow(BaseModel):
    row_index: int
    values: dict[str, Any]


class TableSample(BaseModel):
    schema_version: str = "1.0"
    columns: list[str]
    rows: list[SampleRow] = Field(default_factory=list)
    strategy: str = "head_plus_spread"


class Metric(BaseModel):
    name: str
    column: str
    direction: Literal["maximize", "minimize", "neutral", "unknown"] = "unknown"
    confidence: float = Field(ge=0, le=1)


class Variable(BaseModel):
    name: str
    column: str
    role: Literal["independent", "dependent", "control"] = "independent"
    ordered: bool = False
    confidence: float = Field(ge=0, le=1)


class MethodVariantDefinition(BaseModel):
    raw_name: str
    method_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)


class MethodDimension(BaseModel):
    column: str | None = None
    values: list[str] = Field(default_factory=list)
    setting_columns: list[str] = Field(default_factory=list)
    variants: list[MethodVariantDefinition] = Field(default_factory=list)
    metric_name: str | None = None
    confidence: float = Field(ge=0, le=1)


class DatasetDimension(BaseModel):
    column: str | None = None
    values: list[str] = Field(default_factory=list)
    setting_columns: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


class ExternalFact(BaseModel):
    key: str
    value: Any
    unit: str | None = None
    scope: str | None = None
    source_type: Literal["user_description", "project_metadata", "web_search"] = "web_search"
    source_title: str
    source_url: str | None = None
    confidence: float = Field(ge=0, le=1)


class InformationGap(BaseModel):
    key: str
    question: str
    reason: str


class ColumnMeaning(BaseModel):
    column: str
    meaning: str = Field(max_length=20)
    role: Literal[
        "metric",
        "independent_variable",
        "control_variable",
        "method",
        "dataset",
        "repeat",
        "identifier",
        "metadata",
        "unknown",
    ] = "unknown"
    confidence: float = Field(ge=0, le=1)


class ExperimentSchema(BaseModel):
    schema_version: str = "1.0"
    experiment_type: str
    datasets: list[str] = Field(default_factory=list)
    dataset_dimension: DatasetDimension = Field(default_factory=DatasetDimension)
    methods: MethodDimension
    metrics: list[Metric]
    variables: list[Variable]
    summary: str = Field(default="", max_length=20)
    row_meaning: str = Field(default="", max_length=20)
    column_meanings: list[ColumnMeaning] = Field(default_factory=list)
    repeat_column: str | None = None
    external_facts: list[ExternalFact] = Field(default_factory=list)
    unresolved_gaps: list[InformationGap] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExperimentUnderstandingResult(BaseModel):
    data_schema: DataSchema
    experiment_schema: ExperimentSchema
    meta: dict[str, Any] = Field(default_factory=dict)


class Aggregation(BaseModel):
    group_by: list[str] = Field(default_factory=list)
    y_function: Literal["mean", "median", "min", "max", "sum", "count", "none"] = "mean"
    error: Literal["std", "sem", "none"] = "none"


class RowSelection(BaseModel):
    mode: Literal["all", "first", "last", "match"] = "all"
    order_by: str | None = None
    column: str | None = None
    value: Any | None = None
    match_strategy: Literal["exact", "nearest"] = "exact"
    group_by: list[str] = Field(default_factory=list)


class VisualizationSpec(BaseModel):
    schema_version: str = "1.0"
    chart_type: Literal["line", "bar", "scatter", "box"]
    x: str
    y: str
    group: str | None = None
    group_values: list[str] = Field(default_factory=list)
    series_columns: list[str] = Field(default_factory=list)
    series_name: str | None = None
    row_selection: RowSelection = Field(default_factory=RowSelection)
    aggregation: Aggregation
    title: str
    x_label: str
    y_label: str
    dpi: int = Field(default=200, ge=72, le=600)
    rationale: str
    assumptions: list[str] = Field(default_factory=list)


class DataFilter(BaseModel):
    column: str
    operator: Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between"]
    value: Any | None = None
    values: list[Any] = Field(default_factory=list)


class ReshapePlan(BaseModel):
    mode: Literal["none", "wide_to_long"] = "none"
    id_columns: list[str] = Field(default_factory=list)
    value_columns: list[str] = Field(default_factory=list)
    variable_name: str = "series"
    value_name: str = "value"


class QueryMetric(BaseModel):
    source: str
    output: str
    function: Literal["mean", "median", "min", "max", "sum", "count", "none"] = "mean"
    error: Literal["std", "sem", "none"] = "none"
    error_output: str | None = None


class QueryAggregation(BaseModel):
    group_by: list[str] = Field(default_factory=list)
    metrics: list[QueryMetric] = Field(default_factory=list)


class QuerySelection(BaseModel):
    mode: Literal["all", "first", "last"] = "all"
    order_by: str | None = None
    group_by: list[str] = Field(default_factory=list)


class DataQuerySpec(BaseModel):
    filters: list[DataFilter] = Field(default_factory=list)
    reshape: ReshapePlan = Field(default_factory=ReshapePlan)
    selection: QuerySelection = Field(default_factory=QuerySelection)
    aggregation: QueryAggregation | None = None


class CanvasObject(BaseModel):
    """Editable figure object in normalized, top-left-origin canvas coordinates."""

    id: str = Field(min_length=1, max_length=80)
    kind: Literal["plot", "text", "legend", "series"]
    x: float = Field(ge=-0.5, le=1.5)
    y: float = Field(ge=-0.5, le=1.5)
    width: float = Field(gt=0, le=2)
    height: float = Field(gt=0, le=2)
    base_width: float = Field(gt=0, le=2)
    base_height: float = Field(gt=0, le=2)
    rotation: float = Field(default=0, ge=-180, le=180)
    visible: bool = True
    locked: bool = False


class ChartStyle(BaseModel):
    figure_width: float = Field(default=7.2, ge=4, le=20)
    figure_height: float = Field(default=4.8, ge=3, le=15)
    font_size: int = Field(default=11, ge=8, le=24)
    title_size: int = Field(default=14, ge=10, le=32)
    line_width: float = Field(default=2, ge=0.5, le=6)
    marker: Literal["o", "s", "^", "D", "x", "none"] = "o"
    palette: list[str] = Field(
        default_factory=lambda: ["#126149", "#d28b36", "#5378a5", "#a65353", "#7b62a3"],
        min_length=1,
        max_length=10,
    )
    background_color: str = Field(default="#ffffff", min_length=4, max_length=32)
    grid: bool = True
    legend_position: Literal[
        "best", "upper right", "upper left", "lower left", "lower right", "center left", "center right"
    ] = "best"
    legend_x: float | None = Field(default=None, ge=0, le=1)
    legend_y: float | None = Field(default=None, ge=0, le=1)
    x_tick_rotation: int = Field(default=0, ge=0, le=90)
    bar_width: float = Field(default=0.82, ge=0.2, le=1.0)
    canvas_objects: list[CanvasObject] = Field(default_factory=list, max_length=40)


class ChartSpec(BaseModel):
    chart_type: Literal["line", "bar", "scatter", "box"]
    x: str
    y: str
    group: str | None = None
    error_y: str | None = None
    title: str
    x_label: str
    y_label: str
    dpi: int = Field(default=200, ge=72, le=600)
    style: ChartStyle = Field(default_factory=ChartStyle)


class VisualizationPlan(BaseModel):
    schema_version: str = "2.0"
    data_query: DataQuerySpec
    chart: ChartSpec
    rationale: str
    assumptions: list[str] = Field(default_factory=list)


class VisualizationRequest(BaseModel):
    request: str = Field(min_length=2, max_length=2000)


class KnowledgeVisualizationRequest(BaseModel):
    """A request whose knowledge sources are selected by the agent."""

    request: str = Field(min_length=2, max_length=2000)


class KnowledgeSourceSelection(BaseModel):
    experiment_ids: list[str] = Field(min_length=1, max_length=20)
    rationale: str


class ChartStyleUpdate(BaseModel):
    figure_width: float | None = Field(default=None, ge=4, le=20)
    figure_height: float | None = Field(default=None, ge=3, le=15)
    font_size: int | None = Field(default=None, ge=8, le=24)
    title_size: int | None = Field(default=None, ge=10, le=32)
    line_width: float | None = Field(default=None, ge=0.5, le=6)
    marker: Literal["o", "s", "^", "D", "x", "none"] | None = None
    palette: list[str] | None = Field(default=None, min_length=1, max_length=10)
    background_color: str | None = Field(default=None, min_length=4, max_length=32)
    grid: bool | None = None
    legend_position: Literal[
        "best", "upper right", "upper left", "lower left", "lower right", "center left", "center right"
    ] | None = None
    legend_x: float | None = Field(default=None, ge=0, le=1)
    legend_y: float | None = Field(default=None, ge=0, le=1)
    x_tick_rotation: int | None = Field(default=None, ge=0, le=90)
    bar_width: float | None = Field(default=None, ge=0.2, le=1.0)
    canvas_objects: list[CanvasObject] | None = Field(default=None, max_length=40)


class VisualizationStyleRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    x_label: str | None = Field(default=None, min_length=1, max_length=100)
    y_label: str | None = Field(default=None, min_length=1, max_length=100)
    dpi: int | None = Field(default=None, ge=72, le=600)
    style: ChartStyleUpdate = Field(default_factory=ChartStyleUpdate)
