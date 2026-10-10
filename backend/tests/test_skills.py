import json
import os
import subprocess
import sys
from pathlib import Path

from backend.app.llm_workflow import plan_visualization_with_skill
from backend.app.models import DataProfile, ExperimentSchema, TableSample
from backend.app.skill_runtime import load_skill_prompt


ROOT = Path(__file__).parents[2]
SKILLS = ROOT / "skills"
TESTDATA = ROOT / "testdata"


def _run_skill(command: list[str], *, accept_json_on_error: bool = False, output_path: Path | None = None) -> dict:
    env = dict(os.environ)
    env["RESEARCHVIZ_FORCE_RULES"] = os.getenv("RESEARCHVIZ_FORCE_RULES", "1")
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, env=env)
    output = (result.stdout or "").strip()
    if result.returncode != 0 and not (accept_json_on_error and output):
        raise AssertionError(result.stderr or result.stdout or "skill failed")
    if output_path is not None:
        assert output_path.exists(), f"expected output file: {output_path}"
        return json.loads(output_path.read_text(encoding="utf-8"))
    assert output, "skill should print JSON"
    return json.loads(output)


def test_understand_skill_outputs_schema():
    result = _run_skill(
        [
            sys.executable,
            str(SKILLS / "understand-experiment" / "scripts" / "analyze.py"),
            "--csv",
            str(TESTDATA / "cifar10.csv"),
            "--description",
            "这是 CIFAR10 主动学习实验，比较不同 query strategy 在不同 label budget 下的 accuracy",
        ]
    )

    data_schema = result.get("data_schema") or result.get("profile")
    experiment_schema = result.get("experiment_schema") or result.get("schema")

    assert data_schema is not None
    assert experiment_schema is not None
    assert data_schema["row_count"] > 0
    assert any(column["name"] == "n_labeled" for column in data_schema["columns"])
    assert experiment_schema["experiment_type"] == "active_learning"


def test_plan_skill_generates_visualization_spec(tmp_path: Path):
    experiment_json = tmp_path / "experiment.json"
    understand = _run_skill(
        [
            sys.executable,
            str(SKILLS / "understand-experiment" / "scripts" / "analyze.py"),
            "--csv",
            str(TESTDATA / "cifar10.csv"),
            "--description",
            "这是 CIFAR10 主动学习实验，比较不同 query strategy 在不同 label budget 下的 accuracy",
            "--output",
            str(experiment_json),
        ],
        output_path=experiment_json,
    )
    assert experiment_json.exists()
    assert (understand.get("schema") or understand.get("experiment_schema")) is not None

    result = _run_skill(
        [
            sys.executable,
            str(SKILLS / "plan-visualization" / "scripts" / "plan.py"),
            "--experiment",
            str(experiment_json),
            "--request",
            "生成不同方法 accuracy 随 budget 变化曲线",
        ]
    )

    assert result["chart"]["chart_type"] == "line"
    assert result["chart"]["x"] in {"budget", "n_labeled"}
    assert result["chart"]["y"]


def test_generate_and_validate_skills_end_to_end(tmp_path: Path):
    experiment_json = tmp_path / "experiment.json"
    spec_json = tmp_path / "spec.json"
    output_dir = tmp_path / "artifacts"

    _run_skill(
        [
            sys.executable,
            str(SKILLS / "understand-experiment" / "scripts" / "analyze.py"),
            "--csv",
            str(TESTDATA / "cifar10_noise_long.csv"),
            "--description",
            "这是 CIFAR10 噪声学习实验，比较不同噪声学习方法在 20% 40% 60% noise ratio 下的 best acc",
            "--output",
            str(experiment_json),
        ],
        output_path=experiment_json,
    )

    _run_skill(
        [
            sys.executable,
            str(SKILLS / "plan-visualization" / "scripts" / "plan.py"),
            "--experiment",
            str(experiment_json),
            "--request",
            "生成不同方法 best acc 随 noise ratio 变化曲线",
            "--output",
            str(spec_json),
        ],
        output_path=spec_json,
    )

    generate = _run_skill(
        [
            sys.executable,
            str(SKILLS / "generate-matplotlib" / "scripts" / "generate.py"),
            "--spec",
            str(spec_json),
            "--csv",
            str(TESTDATA / "cifar10_noise_long.csv"),
            "--output-dir",
            str(output_dir),
        ]
    )

    image_path = Path(generate["image"])
    code_path = Path(generate["code"])
    assert image_path.exists()
    assert code_path.exists()
    assert image_path.stat().st_size > 1000

    validation = _run_skill(
        [
            sys.executable,
            str(SKILLS / "validate-figure" / "scripts" / "validate.py"),
            "--image",
            str(image_path),
            "--code",
            str(code_path),
        ],
        accept_json_on_error=True,
    )

    assert validation["valid"] is True
    assert validation["score"] > 0


def test_plan_skill_filters_requested_methods(tmp_path: Path):
    experiment_json = tmp_path / "experiment.json"
    result = _run_skill(
        [
            sys.executable,
            str(SKILLS / "understand-experiment" / "scripts" / "analyze.py"),
            "--csv",
            str(TESTDATA / "cifar10.csv"),
            "--description",
            "这是 CIFAR10 主动学习实验，比较不同 query strategy 在不同 label budget 下的 accuracy",
            "--output",
            str(experiment_json),
        ],
        output_path=experiment_json,
    )
    assert (result.get("experiment_schema") or result.get("schema")) is not None

    spec = _run_skill(
        [
            sys.executable,
            str(SKILLS / "plan-visualization" / "scripts" / "plan.py"),
            "--experiment",
            str(experiment_json),
            "--request",
            "只比较 BADGE 和 EMA-v4 kNN CE 两种方法的 accuracy 随 budget 变化曲线",
        ]
    )

    selected = spec["data_query"]["reshape"]["value_columns"]
    assert set(selected) == {"BADGE", "EMA-v4 kNN CE"}


def test_model_planner_receives_runtime_skill_and_available_data():
    class FakeProvider:
        def __init__(self):
            self.system_prompt = ""
            self.user_prompt = ""

        def generate_json(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 0) -> dict:
            self.system_prompt = system_prompt
            self.user_prompt = user_prompt
            return {
                "schema_version": "1.0",
                "chart_type": "line",
                "x": "n_labeled",
                "y": "BADGE",
                "group": "method",
                "group_values": ["BADGE", "EMA-v4 kNN CE"],
                "series_columns": ["BADGE", "EMA-v4 kNN CE"],
                "series_name": "method",
                "aggregation": {"group_by": ["n_labeled", "method"], "y_function": "mean", "error": "none"},
                "title": "BADGE 与 EMA 方法对比",
                "x_label": "Label budget",
                "y_label": "Accuracy",
                "dpi": 200,
                "rationale": "比较两种主动学习方法随标注预算的性能变化",
                "assumptions": ["将 EMA 相关方法映射为 EMA-v4 kNN CE"],
            }

    profile = DataProfile.model_validate({
        "row_count": 7,
        "column_count": 4,
        "columns": [
            {"name": "n_labeled", "physical_type": "int64", "semantic_type": "numeric", "nullable": False, "null_count": 0, "null_ratio": 0, "unique_count": 7, "sample_values": [2500, 5000]},
            {"name": "BADGE", "physical_type": "float64", "semantic_type": "numeric", "nullable": False, "null_count": 0, "null_ratio": 0, "unique_count": 7, "sample_values": [0.57, 0.66]},
            {"name": "EMA-v2 CE", "physical_type": "float64", "semantic_type": "numeric", "nullable": False, "null_count": 0, "null_ratio": 0, "unique_count": 7, "sample_values": [0.58, 0.66]},
            {"name": "EMA-v4 kNN CE", "physical_type": "float64", "semantic_type": "numeric", "nullable": False, "null_count": 0, "null_ratio": 0, "unique_count": 7, "sample_values": [0.57, 0.67]},
        ],
    })
    schema = ExperimentSchema.model_validate({
        "experiment_type": "active_learning",
        "datasets": ["CIFAR10"],
        "methods": {"column": None, "values": ["BADGE", "EMA-v2 CE", "EMA-v4 kNN CE"], "confidence": 0.95},
        "metrics": [
            {"name": name, "column": name, "direction": "maximize", "confidence": 0.9}
            for name in ["BADGE", "EMA-v2 CE", "EMA-v4 kNN CE"]
        ],
        "variables": [{"name": "label budget", "column": "n_labeled", "role": "independent", "ordered": True, "confidence": 0.95}],
        "warnings": [],
    })
    sample = TableSample(columns=[column.name for column in profile.columns], rows=[], strategy="test")
    provider = FakeProvider()
    skill_prompt = load_skill_prompt("plan-visualization", references=("references/visualization-spec.md",))

    plan = plan_visualization_with_skill(
        provider,
        "生成 BADGE 和 EMA 相关的两个方法的曲线图",
        schema,
        profile,
        sample,
        skill_prompt,
    )

    assert plan.data_query.reshape.value_columns == ["BADGE", "EMA-v4 kNN CE"]
    assert plan.chart.group == "method"
    assert "自主搜索可用字段与取值" in provider.system_prompt
    assert "EMA-v2 CE" in provider.user_prompt
    assert "生成 BADGE 和 EMA 相关的两个方法的曲线图" in provider.user_prompt
