import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .graph_builder import build_experiment_subgraph
from .llm import get_llm_provider
from .knowledge import normalize_experiment
from .knowledge_visualization import (
    build_combined_experiment_schema,
    materialize_observations,
    select_knowledge_sources,
)
from .tools.csv_tools import fingerprint_file
from .models import (
    ChartStyle,
    ChartSpec,
    DataFilter,
    DataQuerySpec,
    ExperimentSchema,
    KnowledgeVisualizationRequest,
    QueryAggregation,
    QueryMetric,
    VisualizationPlan,
    VisualizationRequest,
    VisualizationStyleRequest,
)
from .orchestrator import (
    create_visualization_via_skills,
    run_generate_skill,
    run_validate_skill,
    understand_experiment,
)
from .profiler import load_frame, preprocess_csv
from .storage import Repository
from .visualization_agent import run_visualization_react_agent

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
ARTIFACT_DIR = DATA_DIR / "artifacts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
repo = Repository(DATA_DIR / "researchviz.db")
# Resolve the configured execution mode once when the API process starts.
# Tests may still replace this with None to exercise the offline fallback.
llm_provider = get_llm_provider()


def force_rule_fallback() -> bool:
    return llm_provider is None

app = FastAPI(title="ResearchViz AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/v1/experiments", status_code=201)
@app.post("/api/v2/knowledge", status_code=201)
def create_experiment(name: str = Form(...), description: str = Form(...), file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Version 1 仅支持 CSV 文件")
    experiment_id = str(uuid4())
    csv_path = UPLOAD_DIR / f"{experiment_id}.csv"
    try:
        with csv_path.open("wb") as target:
            shutil.copyfileobj(file.file, target)
        fingerprint = fingerprint_file(csv_path)
        if fingerprint["size_bytes"] > 100 * 1024 * 1024:
            raise ValueError("CSV 不能超过 100 MB")
        duplicate = repo.get_experiment_by_file_hash(fingerprint["sha256"])
        if duplicate:
            raise HTTPException(
                409,
                f"该 CSV 已存在于知识库：{duplicate['name']}（experiment_id={duplicate['id']}）",
            )
        frame, data_schema, table_sample = preprocess_csv(csv_path)
        understand_result = understand_experiment(
            csv_path,
            description.strip(),
            data_schema=data_schema.model_dump(mode="json"),
            table_sample=table_sample.model_dump(mode="json"),
            force_rules=force_rule_fallback(),
        )
        record = {"id": experiment_id, "name": name.strip(), "description": description.strip(),
                  "filename": Path(file.filename).name, "file_path": str(csv_path),
                  "file_hash": fingerprint["sha256"], "status": "READY",
                  "profile": understand_result["profile"], "schema": understand_result["schema"],
                  "data_schema": understand_result["data_schema"],
                  "table_sample": understand_result["table_sample"],
                  "experiment_schema": understand_result["experiment_schema"],
                  "created_at": datetime.now(UTC).isoformat()}
        experiment_schema = ExperimentSchema.model_validate(understand_result["experiment_schema"])
        knowledge = normalize_experiment(
            experiment_id,
            frame,
            experiment_schema,
            name=record["name"],
            description=record["description"],
        )
        graph = build_experiment_subgraph(record, knowledge, experiment_schema)
        repo.create_experiment(record, knowledge, graph)
        return {
            **record,
            "knowledge_summary": knowledge["summary"],
            "graph_summary": repo.get_graph_summary(experiment_id),
        }
    except HTTPException:
        csv_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        csv_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/experiments")
def list_experiments():
    records = repo.list_experiments()
    for record in records:
        record["data_schema"] = record["profile"]
        record["experiment_schema"] = record["schema"]
        record.setdefault("table_sample", {"columns": [], "rows": [], "strategy": "missing"})
    return records


@app.get("/api/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    record = repo.get_experiment(experiment_id)
    if not record:
        raise HTTPException(404, "实验不存在")
    record["data_schema"] = record["profile"]
    record["experiment_schema"] = record["schema"]
    record.setdefault("table_sample", {"columns": [], "rows": [], "strategy": "missing"})
    return record


@app.get("/api/v2/knowledge")
def list_knowledge(query: str = ""):
    return repo.list_knowledge(query)


@app.get("/api/v2/knowledge/{experiment_id}")
def get_knowledge(experiment_id: str):
    result = repo.get_knowledge(experiment_id)
    if not result:
        raise HTTPException(404, "知识项不存在")
    return {**result, "graph_summary": repo.get_graph_summary(experiment_id)}


@app.get("/api/v2/knowledge/{experiment_id}/graph")
def get_knowledge_graph(experiment_id: str):
    graph = repo.get_experiment_graph(experiment_id)
    if graph is None:
        raise HTTPException(404, "知识项不存在")
    return graph.model_dump(mode="json")


@app.post("/api/v2/knowledge/{experiment_id}/reindex")
def reindex_knowledge(experiment_id: str):
    experiment = repo.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "实验不存在")
    try:
        experiment_schema = ExperimentSchema.model_validate(experiment["schema"])
        knowledge = normalize_experiment(
            experiment_id,
            load_frame(Path(experiment["file_path"])),
            experiment_schema,
            name=experiment["name"],
            description=experiment["description"],
        )
        graph = build_experiment_subgraph(experiment, knowledge, experiment_schema)
        repo.replace_knowledge(experiment_id, knowledge, graph)
        return {
            **knowledge["summary"],
            "graph_summary": repo.get_graph_summary(experiment_id),
        }
    except Exception as exc:
        raise HTTPException(422, f"知识库索引失败: {exc}") from exc


@app.post("/api/v1/experiments/{experiment_id}/visualizations", status_code=201)
def create_visualization(experiment_id: str, payload: VisualizationRequest):
    experiment = repo.get_experiment(experiment_id)
    if not experiment:
        raise HTTPException(404, "实验不存在")
    visualization_id = str(uuid4())
    out_dir = ARTIFACT_DIR / visualization_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = create_visualization_via_skills(
            experiment=experiment,
            request=payload.request,
            output_dir=out_dir,
            force_rules=force_rule_fallback(),
        )
        if result["status"] != "SUCCEEDED":
            record = {"id": visualization_id, "experiment_id": experiment_id,
                      "request_text": payload.request, "status": "FAILED",
                      "spec": result["spec"], "code_path": result["code_path"],
                      "image_path": None, "svg_path": result.get("svg_path"), "error_message": result["last_error"],
                      "attempt_count": result["attempt_count"],
                      "model_name": result["model_name"],
                      "created_at": datetime.now(UTC).isoformat()}
            repo.create_visualization(record)
            raise HTTPException(422, {"message": "可视化生成失败", "terminal_reason": result["terminal_reason"],
                                      "attempts_used": result["attempt_count"], "last_error": record["error_message"]})
        record = {"id": visualization_id, "experiment_id": experiment_id, "request_text": payload.request,
                  "status": "SUCCEEDED", "spec": result["spec"], "code_path": result["code_path"],
                  "image_path": result["image_path"], "svg_path": result.get("svg_path"), "error_message": None, "attempt_count": result["attempt_count"],
                  "model_name": result["model_name"],
                  "created_at": datetime.now(UTC).isoformat()}
        repo.create_visualization(record)
        return {**record, "attempts": result["attempts"], "validation": result["validation"]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"可视化生成失败: {exc}") from exc


def _compact_tool_trace(trace: list[dict]) -> list[dict]:
    compact: list[dict] = []
    for step in trace:
        result = step.get("result", {})
        compact.append({
            "round": step.get("round"),
            "tool": step.get("tool"),
            "arguments": step.get("arguments", {}),
            "result_count": result.get("count"),
            "result_status": result.get("status"),
            "valid": result.get("valid"),
            "error": result.get("error"),
        })
    return compact


@app.post("/api/v2/visualizations", status_code=201)
def create_knowledge_visualization(payload: KnowledgeVisualizationRequest):
    """Run the model-directed visualization ReAct agent."""
    visualization_id = str(uuid4())
    out_dir = ARTIFACT_DIR / visualization_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if llm_provider is not None:
            result = run_visualization_react_agent(repo, llm_provider, payload.request, out_dir)
            source_ids = result["source_experiment_ids"]
            if not source_ids:
                raise HTTPException(422, {
                    "message": "知识库可视化生成失败",
                    "terminal_reason": result["terminal_reason"],
                    "last_error": result["last_error"],
                    "agent_trace": _compact_tool_trace(result["agent_trace"]),
                    "token_usage": result["token_usage"],
                })
            record = {
                "id": visualization_id,
                "experiment_id": source_ids[0],
                "source_experiment_ids": source_ids,
                "request_text": payload.request,
                "status": result["status"],
                "spec": result["spec"],
                "code_path": result["code_path"],
                "image_path": result.get("image_path"),
                "svg_path": result.get("svg_path"),
                "error_message": result.get("last_error"),
                "attempt_count": result["attempt_count"],
                "model_name": result["model_name"],
                "token_usage": result["token_usage"],
                "created_at": datetime.now(UTC).isoformat(),
            }
            repo.create_visualization(record)
            if result["status"] != "SUCCEEDED":
                raise HTTPException(422, {
                    "message": "可视化 ReAct Agent 未完成任务",
                    "terminal_reason": result["terminal_reason"],
                    "attempts_used": result["attempt_count"],
                    "last_error": result["last_error"],
                    "agent_trace": _compact_tool_trace(result["agent_trace"]),
                    "token_usage": result["token_usage"],
                })
            stored = repo.get_visualization(visualization_id) or record
            return {
                **stored,
                "attempts": result["attempts"],
                "validation": result["validation"],
                "source_selection": {
                    "experiment_ids": source_ids,
                    "rationale": result["source_selection_reason"],
                },
                "agent_final": result["agent_final"],
                "agent_trace": _compact_tool_trace(result["agent_trace"]),
                "token_usage": result["token_usage"],
            }

        # Deterministic fixed chain is retained only for offline tests and local
        # development with MODEL_PROVIDER=rules. Production Qwen mode uses ReAct.
        selection, source_trace = select_knowledge_sources(repo, payload.request, llm_provider)
        rows = repo.export_observations(selection.experiment_ids)
        combined_csv = out_dir / "selected_observations.csv"
        frame = materialize_observations(rows, combined_csv)
        _, data_schema, table_sample = preprocess_csv(combined_csv)
        experiment_schema = build_combined_experiment_schema(frame)
        source_names = [repo.get_experiment(item)["name"] for item in selection.experiment_ids]  # type: ignore[index]
        combined_experiment = {
            "id": f"knowledge-query:{visualization_id}",
            "name": " + ".join(source_names),
            "description": f"知识库自动选源结果。用户需求：{payload.request}",
            "filename": combined_csv.name,
            "file_path": str(combined_csv),
            "profile": data_schema.model_dump(mode="json"),
            "data_schema": data_schema.model_dump(mode="json"),
            "table_sample": table_sample.model_dump(mode="json"),
            "schema": experiment_schema.model_dump(mode="json"),
            "experiment_schema": experiment_schema.model_dump(mode="json"),
        }
        result = create_visualization_via_skills(
            experiment=combined_experiment,
            request=payload.request,
            output_dir=out_dir,
            force_rules=force_rule_fallback(),
            skip_request_understanding=True,
        )
        record = {
            "id": visualization_id,
            "experiment_id": selection.experiment_ids[0],
            "source_experiment_ids": selection.experiment_ids,
            "request_text": payload.request,
            "status": result["status"],
            "spec": result["spec"],
            "code_path": result["code_path"],
            "image_path": result.get("image_path"),
            "svg_path": result.get("svg_path"),
            "error_message": result.get("last_error"),
            "attempt_count": result["attempt_count"],
            "model_name": result["model_name"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        repo.create_visualization(record)
        if result["status"] != "SUCCEEDED":
            raise HTTPException(422, {
                "message": "可视化生成失败",
                "terminal_reason": result["terminal_reason"],
                "attempts_used": result["attempt_count"],
                "last_error": record["error_message"],
            })
        stored = repo.get_visualization(visualization_id) or record
        return {
            **stored,
            "attempts": result["attempts"],
            "validation": result["validation"],
            "source_selection": selection.model_dump(mode="json"),
            "source_tool_trace": _compact_tool_trace(source_trace),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"知识库可视化生成失败: {exc}") from exc


@app.patch("/api/v2/visualizations/{visualization_id}/style")
def update_visualization_style(visualization_id: str, payload: VisualizationStyleRequest):
    """Regenerate image and Python code from user-edited ChartSpec styles without an LLM call."""
    record = repo.get_visualization(visualization_id)
    if not record:
        raise HTTPException(404, "可视化不存在")
    try:
        plan = VisualizationPlan.model_validate(record["spec"])
        style_updates = payload.style.model_dump(exclude_none=True)
        style = ChartStyle.model_validate({**plan.chart.style.model_dump(), **style_updates})
        chart_updates = {"style": style}
        for field in ("title", "x_label", "y_label", "dpi"):
            value = getattr(payload, field)
            if value is not None:
                chart_updates[field] = value
        plan = plan.model_copy(update={"chart": plan.chart.model_copy(update=chart_updates)})

        artifact_root = Path(record["code_path"]).parent
        data_path = artifact_root / "selected_observations.csv"
        if not data_path.exists():
            experiment = repo.get_experiment(record["experiment_id"])
            if not experiment:
                raise ValueError("找不到重新渲染所需的数据")
            data_path = Path(experiment["file_path"])

        with TemporaryDirectory(prefix="canvas_", dir=artifact_root) as temp_dir:
            temp_root = Path(temp_dir)
            spec_path = temp_root / "canvas_plan.json"
            spec_path.write_text(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            generated = run_generate_skill(spec_path, data_path, temp_root)
            validation = run_validate_skill(Path(generated["image"]), Path(generated["code"]))
            if not validation.get("valid"):
                raise ValueError(f"画布重新渲染未通过验证: {validation.get('errors', [])}")
            target_code = Path(record["code_path"])
            target_image = Path(record["image_path"])
            target_svg = Path(record.get("svg_path") or artifact_root / "figure.svg")
            shutil.copy2(generated["code"], target_code)
            shutil.copy2(generated["image"], target_image)
            shutil.copy2(generated["svg"], target_svg)

        repo.update_visualization_artifacts(
            visualization_id,
            spec=plan.model_dump(mode="json"),
            code_path=str(target_code),
            image_path=str(target_image),
            svg_path=str(target_svg),
        )
        updated = repo.get_visualization(visualization_id)
        return {**(updated or record), "validation": validation, "style_updated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"画布样式更新失败: {exc}") from exc


@app.post("/api/v2/visualizations/demo", status_code=201)
def create_canvas_demo():
    """Create a deterministic canvas artifact from existing knowledge without any model call."""
    candidates = [item for item in repo.list_knowledge() if item.get("indexed") and item.get("observation_count", 0)]
    if not candidates:
        raise HTTPException(422, "知识库中没有可用于零 Token 示例的观测数据")
    source = candidates[0]
    visualization_id = str(uuid4())
    out_dir = ARTIFACT_DIR / visualization_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        frame = materialize_observations(repo.export_observations([source["id"]]), out_dir / "selected_observations.csv")
        metric_name = str(frame["metric"].mode().iloc[0])
        group = "method_variant" if frame["method_variant"].nunique() > 1 else None
        excluded = {"value", "source_row", "source_column", "experiment_id", "experiment_name", "dataset_variant"}
        priority = ["n_labeled", "budget", "round", "noise_ratio", "dataset", "method_variant"]
        available = [column for column in priority if column in frame.columns and column not in excluded]
        x = available[0] if available else (group or "dataset")
        if x == group:
            group = None
        numeric_x = frame[x].dtype.kind in "iufc" and frame[x].nunique() > 1
        chart_type = "line" if numeric_x else "bar"
        group_by = [x] + ([group] if group else [])
        plan = VisualizationPlan(
            data_query=DataQuerySpec(
                filters=[DataFilter(column="metric", operator="eq", value=metric_name)],
                aggregation=QueryAggregation(
                    group_by=group_by,
                    metrics=[QueryMetric(
                        source="value", output="value_mean", function="mean",
                        error="std", error_output="value_std",
                    )],
                ),
            ),
            chart=ChartSpec(
                chart_type=chart_type, x=x, y="value_mean", group=group,
                error_y="value_std", title=f"Zero-token canvas demo · {source['name']}",
                x_label=x.replace("_", " ").title(), y_label=metric_name.replace("_", " ").title(),
            ),
            rationale="使用知识库真实观测确定性生成，用于测试直接画布编辑。",
            assumptions=["该示例没有调用大模型。"],
        )
        spec_path = out_dir / "demo_plan.json"
        spec_path.write_text(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        generated = run_generate_skill(spec_path, out_dir / "selected_observations.csv", out_dir)
        validation = run_validate_skill(Path(generated["image"]), Path(generated["code"]))
        if not validation.get("valid"):
            raise ValueError(f"示例图未通过验证: {validation.get('errors', [])}")
        record = {
            "id": visualization_id, "experiment_id": source["id"], "source_experiment_ids": [source["id"]],
            "request_text": "Zero-token canvas demo", "status": "SUCCEEDED",
            "spec": plan.model_dump(mode="json"), "code_path": generated["code"], "image_path": generated["image"], "svg_path": generated["svg"],
            "error_message": None, "attempt_count": 1, "model_name": None,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "api_calls": 0, "by_endpoint": {}},
            "created_at": datetime.now(UTC).isoformat(),
        }
        repo.create_visualization(record)
        return {**(repo.get_visualization(visualization_id) or record), "validation": validation, "demo": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"零 Token 示例生成失败: {exc}") from exc


def _artifact(visualization_id: str, kind: str) -> FileResponse:
    record = repo.get_visualization(visualization_id)
    if not record:
        raise HTTPException(404, "可视化不存在")
    path = Path(record[f"{kind}_path"])
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    media = {"image": "image/png", "svg": "image/svg+xml", "code": "text/x-python"}[kind]
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/v1/visualizations/{visualization_id}")
def get_visualization(visualization_id: str):
    record = repo.get_visualization(visualization_id)
    if not record:
        raise HTTPException(404, "可视化不存在")
    return record


@app.get("/api/v1/visualizations/{visualization_id}/image")
def get_image(visualization_id: str):
    return _artifact(visualization_id, "image")


@app.get("/api/v1/visualizations/{visualization_id}/code")
def get_code(visualization_id: str):
    return _artifact(visualization_id, "code")


@app.get("/api/v1/visualizations/{visualization_id}/svg")
def get_svg(visualization_id: str):
    return _artifact(visualization_id, "svg")
