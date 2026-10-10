from pathlib import Path

import pytest

from app.agent import plan_visualization
from app.codegen import execute_code, generate_code
from app.llm import LLMError
from app.llm_workflow import _validate_visualization_columns, _validate_visualization_values
from app.models import (
    Aggregation,
    ChartSpec,
    DataFilter,
    DataQuerySpec,
    QueryAggregation,
    QueryMetric,
    RowSelection,
    VisualizationPlan,
    VisualizationSpec,
)
from app.profiler import infer_experiment_schema, profile_csv
from app.visualization_plan import validate_visualization_plan


def test_end_to_end_pipeline(tmp_path: Path):
    source = Path(__file__).parents[2] / "examples" / "active_learning.csv"
    frame, profile = profile_csv(source)
    schema = infer_experiment_schema(
        "这是 CIFAR10 主动学习实验，比较不同 query strategy 在 label budget 下的 accuracy。",
        frame, profile,
    )
    assert schema.experiment_type == "active_learning"
    assert schema.methods.column == "method"
    assert schema.metrics[0].column == "accuracy"
    assert schema.repeat_column == "seed"

    spec = plan_visualization("生成不同方法 accuracy 随 budget 变化曲线", schema, profile)
    assert spec.chart_type == "line"
    assert spec.x == "budget"
    assert spec.y == "accuracy"
    assert spec.group == "method"
    assert spec.aggregation.error == "std"

    code_path = tmp_path / "visualization.py"
    image_path = tmp_path / "figure.png"
    code_path.write_text(generate_code(spec), encoding="utf-8")
    execute_code(code_path, source, image_path)
    assert image_path.exists()
    assert image_path.stat().st_size > 1000


def test_wide_table_last_observation_method_comparison(tmp_path: Path):
    source = Path(__file__).parents[2] / "testdata" / "cifar10.csv"
    spec = VisualizationSpec(
        chart_type="bar",
        x="method",
        y="value",
        series_columns=["Random", "Entropy", "CoreSet", "BADGE", "EMA-v2 CE", "EMA-v4 kNN CE"],
        series_name="method",
        row_selection=RowSelection(mode="last", order_by="round"),
        aggregation=Aggregation(group_by=["method"], y_function="none", error="none"),
        title="Final-round accuracy by method",
        x_label="Method",
        y_label="Accuracy",
        rationale="Compare the final observation across all available methods.",
        assumptions=[],
    )
    code_path = tmp_path / "visualization.py"
    image_path = tmp_path / "figure.png"
    code_path.write_text(generate_code(spec), encoding="utf-8")
    execute_code(code_path, source, image_path)
    generated = code_path.read_text(encoding="utf-8")
    assert 'selection_mode = row_selection.get("mode", "all")' in generated
    assert "df.tail(1)" in generated
    assert image_path.exists()
    assert image_path.stat().st_size > 1000


def test_wide_table_exact_budget_method_comparison(tmp_path: Path):
    source = Path(__file__).parents[2] / "testdata" / "cifar10.csv"
    spec = VisualizationSpec(
        chart_type="bar",
        x="method",
        y="value",
        series_columns=["Random", "Entropy", "CoreSet", "BADGE", "EMA-v2 CE", "EMA-v4 kNN CE"],
        series_name="method",
        row_selection=RowSelection(mode="match", column="n_labeled", value=10000, match_strategy="exact"),
        aggregation=Aggregation(group_by=["method"], y_function="none", error="none"),
        title="Accuracy at 10,000 labeled samples",
        x_label="Method",
        y_label="Accuracy",
        rationale="Compare methods at one exact labeling condition.",
        assumptions=[],
    )
    code_path = tmp_path / "visualization.py"
    image_path = tmp_path / "figure.png"
    code_path.write_text(generate_code(spec), encoding="utf-8")
    execute_code(code_path, source, image_path)
    generated = code_path.read_text(encoding="utf-8")
    assert 'selection_mode == "match"' in generated
    assert image_path.exists()
    assert image_path.stat().st_size > 1000


def test_long_table_filters_two_methods_at_one_noise_ratio(tmp_path: Path):
    source = Path(__file__).parents[2] / "testdata" / "cifar10_noise_long.csv"
    frame, profile = profile_csv(source)
    schema = infer_experiment_schema(
        "CIFAR10 噪声学习实验，比较不同方法在不同噪声率下的 best accuracy",
        frame,
        profile,
    )
    plan = VisualizationPlan(
        data_query=DataQuerySpec(
            filters=[
                DataFilter(column="noise_ratio", operator="eq", value=0.4),
                DataFilter(column="method", operator="in", values=["Ours", "JoCoR"]),
            ],
            aggregation=QueryAggregation(
                group_by=["method"],
                metrics=[QueryMetric(
                    source="best_acc", output="best_acc_mean", function="mean",
                    error="std", error_output="best_acc_std",
                )],
            ),
        ),
        chart=ChartSpec(
            chart_type="bar", x="method", y="best_acc_mean", group=None,
            error_y="best_acc_std", title="Ours vs JoCoR at 40% noise",
            x_label="Method", y_label="Best accuracy",
        ),
        rationale="在 40% 噪声率下比较用户指定的两种方法。",
        assumptions=[],
    )
    validate_visualization_plan(plan, profile, schema)
    invalid_chart = plan.chart.model_copy(update={"group": "method"})
    with pytest.raises(LLMError, match="x 与 group"):
        validate_visualization_plan(plan.model_copy(update={"chart": invalid_chart}), profile, schema)

    code_path = tmp_path / "visualization.py"
    image_path = tmp_path / "figure.png"
    code_path.write_text(generate_code(plan), encoding="utf-8")
    execute_code(code_path, source, image_path)
    generated = code_path.read_text(encoding="utf-8")
    assert "for item in query.get(\"filters\")" in generated
    assert "df = aggregate_data" in generated
    assert image_path.exists()
    assert image_path.stat().st_size > 1000
