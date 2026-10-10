import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .llm import LLMError, get_llm_provider
from .llm_workflow import repair_visualization_with_llm
from .models import DataSchema, ExperimentSchema, TableSample, VisualizationPlan
from .react_planner import build_planner_trace_step

ROOT_DIR = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT_DIR / "skills"


def normalize_understand_result(
    result: dict[str, Any],
    *,
    fallback_data_schema: dict[str, Any] | None = None,
    fallback_table_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_schema = result.get("data_schema") or result.get("profile") or fallback_data_schema
    experiment_schema = result.get("experiment_schema") or result.get("schema")
    table_sample = result.get("table_sample") or fallback_table_sample
    if not data_schema or not experiment_schema:
        raise RuntimeError("understand skill 必须返回 data_schema/experiment_schema 或 profile/schema")
    normalized = dict(result)
    normalized["data_schema"] = data_schema
    normalized["experiment_schema"] = experiment_schema
    normalized["profile"] = data_schema
    normalized["schema"] = experiment_schema
    normalized["table_sample"] = table_sample or {"columns": [], "rows": [], "strategy": "missing"}
    return normalized


def _run_skill(
    command: list[str],
    *,
    cwd: Path = ROOT_DIR,
    accept_json_on_error: bool = False,
    force_rules: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    if force_rules:
        env["RESEARCHVIZ_FORCE_RULES"] = "1"
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd, env=env)
    output = (result.stdout or "").strip()
    if result.returncode != 0 and not (accept_json_on_error and output):
        stderr = (result.stderr or result.stdout or "Skill 执行失败").strip()
        raise RuntimeError(stderr[-2000:])
    if not output:
        raise RuntimeError("Skill 未返回输出")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Skill 返回了无效 JSON: {output[-400:]}") from exc


def run_understand_skill(csv_path: Path, description: str, *, force_rules: bool = False) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SKILLS_DIR / "understand-experiment" / "scripts" / "analyze.py"),
        "--csv",
        str(csv_path),
        "--description",
        description,
    ]
    return _run_skill(command, force_rules=force_rules)


def run_plan_skill(
    experiment_json_path: Path,
    request: str,
    *,
    force_rules: bool = False,
    usage_path: Path | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SKILLS_DIR / "plan-visualization" / "scripts" / "plan.py"),
        "--experiment",
        str(experiment_json_path),
        "--request",
        request,
    ]
    overrides = {"RESEARCHVIZ_USAGE_FILE": str(usage_path)} if usage_path else None
    return _run_skill(command, force_rules=force_rules, env_overrides=overrides)


def run_generate_skill(spec_json_path: Path, csv_path: Path, output_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SKILLS_DIR / "generate-matplotlib" / "scripts" / "generate.py"),
        "--spec",
        str(spec_json_path),
        "--csv",
        str(csv_path),
        "--output-dir",
        str(output_dir),
    ]
    return _run_skill(command)


def run_validate_skill(image_path: Path, code_path: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SKILLS_DIR / "validate-figure" / "scripts" / "validate.py"),
        "--image",
        str(image_path),
        "--code",
        str(code_path),
    ]
    return _run_skill(command, accept_json_on_error=True)


def understand_experiment(
    csv_path: Path,
    description: str,
    *,
    data_schema: dict[str, Any] | None = None,
    table_sample: dict[str, Any] | None = None,
    force_rules: bool = False,
) -> dict[str, Any]:
    return normalize_understand_result(
        run_understand_skill(csv_path, description, force_rules=force_rules),
        fallback_data_schema=data_schema,
        fallback_table_sample=table_sample,
    )


def create_visualization_via_skills(
    *,
    experiment: dict[str, Any],
    request: str,
    output_dir: Path,
    force_rules: bool = False,
    skip_request_understanding: bool = False,
) -> dict[str, Any]:
    llm_provider = None if force_rules else get_llm_provider()
    attempts: list[dict[str, Any]] = []
    planner_trace: list[dict[str, Any]] = []
    terminal_reason: str | None = None

    with TemporaryDirectory(prefix="researchviz_") as temp_dir:
        temp_root = Path(temp_dir)
        data_schema = DataSchema.model_validate(experiment.get("data_schema", experiment["profile"]))
        profile = data_schema
        table_sample = TableSample.model_validate(experiment.get("table_sample", {"columns": [], "rows": [], "strategy": "missing"}))
        schema = ExperimentSchema.model_validate(experiment.get("experiment_schema", experiment["schema"]))

        if not force_rules and not skip_request_understanding:
            enriched = understand_experiment(
                Path(experiment["file_path"]),
                (
                    f"{experiment['description']}\n\n"
                    f"当前可视化任务：{request}\n"
                    "检查完成当前任务是否缺少会改变数据选择、计算或结论的关键信息；"
                    "缺失时按 Skill 调用搜索工具获取证据。"
                ),
                data_schema=data_schema.model_dump(mode="json"),
                table_sample=table_sample.model_dump(mode="json"),
                force_rules=False,
            )
            data_schema = DataSchema.model_validate(enriched["data_schema"])
            table_sample = TableSample.model_validate(enriched["table_sample"])
            schema = ExperimentSchema.model_validate(enriched["experiment_schema"])
            search_trace = enriched.get("meta", {}).get("tool_trace", [])
            planner_trace.append(
                build_planner_trace_step(
                    "request_aware_understanding",
                    "SUCCEEDED",
                    notes=["Understanding Skill 已结合当前图表任务检查信息缺口并按需调用搜索工具"],
                    payload={
                        "tool_calls": len(search_trace),
                        "external_facts": len(schema.external_facts),
                        "unresolved_gaps": len(schema.unresolved_gaps),
                    },
                )
            )

        experiment_payload = {
            "data_schema": data_schema.model_dump(mode="json"),
            "experiment_schema": schema.model_dump(mode="json"),
            "table_sample": table_sample.model_dump(mode="json"),
            "profile": data_schema.model_dump(mode="json"),
            "schema": schema.model_dump(mode="json"),
        }
        planner_trace.append(
            build_planner_trace_step(
                "inspect_input",
                "SUCCEEDED",
                notes=["Visual ReAct Planner 已读取 data schema、table sample、experiment schema"],
                payload={"row_count": data_schema.row_count, "column_count": data_schema.column_count, "sample_rows": len(table_sample.rows)},
            )
        )

        planner_trace.append(
            build_planner_trace_step(
                "load_skill_context",
                "SUCCEEDED",
                notes=["已把用户图表需求、Data Schema、Table Sample 和 Experiment Schema 交给规划 Skill"],
            )
        )

        experiment_json_path = temp_root / "experiment.json"
        experiment_json_path.write_text(json.dumps(experiment_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        plan_result = run_plan_skill(experiment_json_path, request, force_rules=force_rules)
        spec = VisualizationPlan.model_validate(plan_result)
        planner_trace.append(
            build_planner_trace_step(
                "call_plan_skill",
                "SUCCEEDED",
                notes=["规划模型已分别生成 DataQuerySpec 与 ChartSpec"],
            )
        )

        for attempt_count in range(1, 4):
            spec_json_path = temp_root / f"spec_attempt_{attempt_count}.json"
            spec_json_path.write_text(json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                generate_result = run_generate_skill(spec_json_path, Path(experiment["file_path"]), output_dir)
                validation_result = run_validate_skill(Path(generate_result["image"]), Path(generate_result["code"]))
                attempts.append(
                    {
                        "attempt": attempt_count,
                        "status": "SUCCEEDED",
                    }
                )
                return {
                    "status": "SUCCEEDED",
                    "spec": spec.model_dump(mode="json"),
                    "code_path": str(generate_result["code"]),
                    "image_path": str(generate_result["image"]),
                    "svg_path": str(generate_result["svg"]),
                    "attempts": attempts,
                    "planner_trace": planner_trace,
                    "attempt_count": len(attempts),
                    "model_name": llm_provider.settings.model if llm_provider else None,
                    "validation": validation_result,
                }
            except RuntimeError as execution_error:
                message = str(execution_error)[-1600:]
                attempts.append({"attempt": attempt_count, "status": "FAILED", "error": message})
                if attempt_count >= 3:
                    terminal_reason = "MAX_ATTEMPTS_REACHED"
                    break
                if not llm_provider:
                    terminal_reason = "NO_REPAIR_PROVIDER"
                    break
                try:
                    spec = repair_visualization_with_llm(
                        llm_provider,
                        request,
                        schema,
                        profile,
                        spec,
                        message,
                        attempt_count,
                    )
                except LLMError:
                    terminal_reason = "REPAIR_FAILED"
                    break

    return {
        "status": "FAILED",
        "spec": spec.model_dump(mode="json"),
        "code_path": str(output_dir / "visualization.py"),
        "image_path": None,
        "svg_path": None,
        "attempts": attempts,
        "planner_trace": planner_trace,
        "attempt_count": len(attempts),
        "model_name": llm_provider.settings.model if llm_provider else None,
        "terminal_reason": terminal_reason or "MAX_ATTEMPTS_REACHED",
        "last_error": attempts[-1]["error"] if attempts else "生成失败",
    }
