from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .knowledge_visualization import build_combined_experiment_schema, materialize_observations
from .llm import QwenProvider
from .models import DataSchema, ExperimentSchema, TableSample, VisualizationPlan
from .orchestrator import run_generate_skill, run_plan_skill, run_validate_skill
from .profiler import preprocess_csv
from .storage import Repository
from .tools.graph_tools import GRAPH_TOOL_DEFINITIONS, GraphToolRuntime
from .tools.knowledge_tools import KNOWLEDGE_TOOL_DEFINITIONS, KnowledgeToolRuntime


PREPARE_DATA_TOOL = {
    "type": "function",
    "name": "prepare_visualization_data",
    "description": "选择一个或多个真实知识项，将其标准化观测合并为本次可视化数据集，并返回数据概况。",
    "parameters": {
        "type": "object",
        "properties": {
            "experiment_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
            "reason": {"type": "string", "description": "选择这些来源的简短理由。"},
        },
        "required": ["experiment_ids", "reason"],
        "additionalProperties": False,
    },
}

INSPECT_PREPARED_DATA_TOOL = {
    "type": "function",
    "name": "inspect_prepared_data",
    "description": "检查当前已准备数据的列、样例、数据集、方法和指标；制定图表计划前可调用。",
    "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}

PLAN_TOOL = {
    "type": "function",
    "name": "plan_visualization",
    "description": "调用 Visualization Planning Skill，基于当前数据和用户需求生成并校验 DataQuerySpec 与 ChartSpec。",
    "parameters": {
        "type": "object",
        "properties": {
            "instruction": {"type": "string", "description": "给规划 Skill 的补充关注点；首次可为空。"},
        },
        "required": [],
        "additionalProperties": False,
    },
}

GENERATE_TOOL = {
    "type": "function",
    "name": "generate_visualization",
    "description": "使用当前已校验计划生成 Matplotlib Python 代码并执行出图。执行失败最多允许调用三次。",
    "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}

VALIDATE_TOOL = {
    "type": "function",
    "name": "validate_visualization",
    "description": "验证当前图片尺寸、内容有效性和 Python 代码语法。只有 valid=true 后任务才可声明成功。",
    "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}

STATE_TOOL = {
    "type": "function",
    "name": "get_visualization_state",
    "description": "查看当前选源、数据准备、计划、生成次数和验证状态。",
    "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}

_REACT_KNOWLEDGE_TOOL_NAMES = {"list_knowledge_catalog", "search_knowledge", "inspect_knowledge_items"}

VISUALIZATION_REACT_TOOLS = [
    *[tool for tool in KNOWLEDGE_TOOL_DEFINITIONS if tool["name"] in _REACT_KNOWLEDGE_TOOL_NAMES],
    *GRAPH_TOOL_DEFINITIONS,
    PREPARE_DATA_TOOL,
    INSPECT_PREPARED_DATA_TOOL,
    PLAN_TOOL,
    GENERATE_TOOL,
    VALIDATE_TOOL,
    STATE_TOOL,
]

VISUALIZATION_REACT_PROMPT = """你是 ResearchViz Visualization ReAct Agent。
你会看到用户需求和一组工具，但没有预设的固定工作流。每一轮根据目标、已有观察和工具能力自主决定下一步。

约束：
1. 所有数据必须来自知识库工具返回的真实 experiment_id，禁止编造数据或列。
2. 你可以搜索目录、批量检查候选，或直接准备你已有充分证据的数据源。批量检查已经返回数据集、方法、指标和观测数量，不要重复查询同一候选。
3. 准备数据后应确认当前数据是否足以满足需求；不足时可重新检索并重新准备。
4. 图表计划、代码生成和验证都作为工具能力，由你决定何时调用以及失败后如何调整。
5. generate_visualization 最多可执行 3 次；不要通过重复调用绕过限制。
6. 只有 validate_visualization 返回 valid=true，才能最终声明 SUCCEEDED。
7. 如果知识库确实缺少所需数据，返回 FAILED 并说明缺少什么。
8. 行动轮预算有限。一旦候选覆盖用户所需数据集、方法和指标，应立即调用 prepare_visualization_data，不要继续做等价检查。
9. 图谱工具是可选的：简单名称检索优先使用知识目录；涉及方法族/变体、多跳关系、跨实验实体对齐或精确条件时，使用图谱工具。
10. query_result_subgraph 返回的是带来源 experiment_id 的证据子图。找到满足需求的来源后，仍需调用 prepare_visualization_data 准备真实绘图数据。
11. 图谱没有返回结果不代表可以猜测；应回到知识目录检查，或报告缺少数据。不要对同一条件重复调用等价的图谱查询。

最终只返回 JSON：
{"status":"SUCCEEDED或FAILED","rationale":"最终决定","summary":"结果摘要"}
不要输出 Markdown，也不要泄露隐藏推理过程。"""


class VisualizationToolRuntime:
    def __init__(self, repository: Repository, request: str, output_dir: Path, *, force_rules: bool = False):
        self.repository = repository
        self.request = request
        self.output_dir = output_dir
        self.force_rules = force_rules
        self.usage_path = output_dir / "token_usage.jsonl"
        self.usage_path.unlink(missing_ok=True)
        self.knowledge = KnowledgeToolRuntime(repository)
        self.graph = GraphToolRuntime(repository)
        self.selected_ids: list[str] = []
        self.selection_reason = ""
        self.csv_path: Path | None = None
        self.data_schema: DataSchema | None = None
        self.table_sample: TableSample | None = None
        self.experiment_schema: ExperimentSchema | None = None
        self.plan: VisualizationPlan | None = None
        self.code_path: Path | None = None
        self.image_path: Path | None = None
        self.svg_path: Path | None = None
        self.validation: dict[str, Any] | None = None
        self.attempts: list[dict[str, Any]] = []

    def prepare_visualization_data(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(value) for value in arguments.get("experiment_ids", [])))[:20]
        available = {item["id"] for item in self.repository.list_knowledge() if item.get("indexed")}
        invalid = [item for item in ids if item not in available]
        if not ids or invalid:
            return {"status": "ERROR", "error": f"无效或未索引的 experiment_id: {', '.join(invalid) or 'empty'}"}
        try:
            rows = self.repository.export_observations(ids)
            csv_path = self.output_dir / "selected_observations.csv"
            frame = materialize_observations(rows, csv_path)
            _, data_schema, table_sample = preprocess_csv(csv_path)
            experiment_schema = build_combined_experiment_schema(frame)
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)[-1200:]}
        self.selected_ids = ids
        self.selection_reason = str(arguments.get("reason", ""))
        self.csv_path = csv_path
        self.data_schema = data_schema
        self.table_sample = table_sample
        self.experiment_schema = experiment_schema
        self.plan = None
        self.code_path = None
        self.image_path = None
        self.svg_path = None
        self.validation = None
        sources = [self.repository.get_experiment(item) for item in ids]
        return {
            "status": "READY",
            "sources": [{"id": item["id"], "name": item["name"], "filename": item["filename"]} for item in sources if item],
            "row_count": data_schema.row_count,
            "columns": [column.name for column in data_schema.columns],
            "datasets": experiment_schema.datasets,
            "methods": experiment_schema.methods.values,
            "metrics": sorted(str(value) for value in frame["metric"].dropna().unique()),
        }

    def inspect_prepared_data(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.data_schema or not self.table_sample or not self.experiment_schema:
            return {"status": "ERROR", "error": "尚未调用 prepare_visualization_data"}
        return {
            "status": "READY",
            "data_schema": self.data_schema.model_dump(mode="json"),
            "experiment_schema": self.experiment_schema.model_dump(mode="json"),
            "table_sample": self.table_sample.model_dump(mode="json"),
        }

    def plan_visualization(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.csv_path or not self.data_schema or not self.table_sample or not self.experiment_schema:
            return {"status": "ERROR", "error": "规划前必须先准备数据"}
        experiment_payload = {
            "data_schema": self.data_schema.model_dump(mode="json"),
            "experiment_schema": self.experiment_schema.model_dump(mode="json"),
            "table_sample": self.table_sample.model_dump(mode="json"),
            "profile": self.data_schema.model_dump(mode="json"),
            "schema": self.experiment_schema.model_dump(mode="json"),
        }
        experiment_path = self.output_dir / "agent_experiment.json"
        experiment_path.write_text(json.dumps(experiment_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        instruction = str(arguments.get("instruction", "")).strip()
        planning_request = self.request if not instruction else f"{self.request}\n\nAgent 补充要求：{instruction}"
        try:
            self.plan = VisualizationPlan.model_validate(
                run_plan_skill(
                    experiment_path,
                    planning_request,
                    force_rules=self.force_rules,
                    usage_path=self.usage_path,
                )
            )
            self.validation = None
            return {"status": "PLANNED", "plan": self.plan.model_dump(mode="json")}
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)[-1600:]}

    def generate_visualization(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if len(self.attempts) >= 3:
            return {"status": "TERMINATED", "error": "MAX_EXECUTION_ATTEMPTS_REACHED", "attempt_count": 3}
        if not self.plan or not self.csv_path:
            return {"status": "ERROR", "error": "生成前必须先获得有效 VisualizationPlan"}
        attempt = len(self.attempts) + 1
        plan_path = self.output_dir / f"agent_plan_{attempt}.json"
        plan_path.write_text(json.dumps(self.plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            generated = run_generate_skill(plan_path, self.csv_path, self.output_dir)
            self.code_path = Path(generated["code"])
            self.image_path = Path(generated["image"])
            self.svg_path = Path(generated["svg"])
            self.validation = None
            self.attempts.append({"attempt": attempt, "status": "SUCCEEDED"})
            return {"status": "GENERATED", "attempt": attempt, "image_size_bytes": generated["image_size_bytes"]}
        except Exception as exc:
            error = str(exc)[-1600:]
            self.attempts.append({"attempt": attempt, "status": "FAILED", "error": error})
            return {"status": "ERROR", "attempt": attempt, "error": error, "remaining_attempts": 3 - attempt}

    def validate_visualization(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.image_path or not self.code_path:
            return {"status": "ERROR", "error": "尚无可验证的图片和代码"}
        try:
            self.validation = run_validate_skill(self.image_path, self.code_path)
            return {"status": "VALIDATED" if self.validation.get("valid") else "INVALID", **self.validation}
        except Exception as exc:
            self.validation = {"valid": False, "errors": [str(exc)[-1200:]]}
            return {"status": "ERROR", **self.validation}

    def get_visualization_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "selected_experiment_ids": self.selected_ids,
            "data_prepared": self.csv_path is not None,
            "plan_ready": self.plan is not None,
            "generation_attempts": len(self.attempts),
            "validation": self.validation,
        }

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            **self.knowledge.handlers,
            **self.graph.handlers,
            "prepare_visualization_data": self.prepare_visualization_data,
            "inspect_prepared_data": self.inspect_prepared_data,
            "plan_visualization": self.plan_visualization,
            "generate_visualization": self.generate_visualization,
            "validate_visualization": self.validate_visualization,
            "get_visualization_state": self.get_visualization_state,
        }


def run_visualization_react_agent(
    repository: Repository,
    provider: QwenProvider,
    request: str,
    output_dir: Path,
) -> dict[str, Any]:
    runtime = VisualizationToolRuntime(repository, request, output_dir)
    final, trace = provider.generate_json_with_tools(
        VISUALIZATION_REACT_PROMPT,
        json.dumps({
            "user_request": request,
            "current_state": "尚未选择知识库来源，也尚未准备数据或生成图表。",
            "success_condition": "使用真实知识库数据生成图片和 Python 代码，且验证 valid=true。",
        }, ensure_ascii=False),
        tools=VISUALIZATION_REACT_TOOLS,
        tool_handlers=runtime.handlers,
        max_tool_rounds=10,
        max_tokens=1000,
        force_first_tool=False,
        usage_path=runtime.usage_path,
    )
    succeeded = bool(
        runtime.validation and runtime.validation.get("valid")
        and runtime.image_path and runtime.image_path.exists()
        and runtime.code_path and runtime.code_path.exists()
    )
    usage_records: list[dict[str, Any]] = []
    if runtime.usage_path.exists():
        for line in runtime.usage_path.read_text(encoding="utf-8").splitlines():
            try:
                usage_records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    token_usage = {
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in usage_records),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in usage_records),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in usage_records),
        "api_calls": len(usage_records),
        "by_endpoint": {
            endpoint: sum(int(item.get("total_tokens", 0)) for item in usage_records if item.get("endpoint") == endpoint)
            for endpoint in sorted({str(item.get("endpoint")) for item in usage_records})
        },
    }
    return {
        "status": "SUCCEEDED" if succeeded else "FAILED",
        "spec": runtime.plan.model_dump(mode="json") if runtime.plan else {},
        "code_path": str(runtime.code_path or output_dir / "visualization.py"),
        "image_path": str(runtime.image_path) if runtime.image_path else None,
        "svg_path": str(runtime.svg_path) if runtime.svg_path else None,
        "attempts": runtime.attempts,
        "attempt_count": len(runtime.attempts),
        "model_name": provider.settings.model,
        "validation": runtime.validation or {"valid": False, "errors": ["Agent 未完成图表验证"]},
        "terminal_reason": None if succeeded else "REACT_AGENT_INCOMPLETE",
        "last_error": None if succeeded else "Agent 在行动轮预算内未生成通过验证的图表",
        "source_experiment_ids": runtime.selected_ids,
        "source_selection_reason": runtime.selection_reason or str(final.get("rationale", "")),
        "agent_final": final,
        "agent_trace": trace,
        "token_usage": token_usage,
    }
