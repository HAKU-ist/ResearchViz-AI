#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.app.llm import get_llm_provider  # noqa: E402
from backend.app.llm_workflow import plan_visualization_with_skill  # noqa: E402
from backend.app.models import DataProfile, ExperimentSchema, TableSample  # noqa: E402
from backend.app.skill_runtime import load_skill_prompt  # noqa: E402
from backend.app.visualization_plan import legacy_spec_to_plan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="根据实验结构规划可视化")
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = json.loads(args.experiment.read_text(encoding="utf-8"))
    schema = ExperimentSchema.model_validate(source.get("experiment_schema", source["schema"]))
    profile = DataProfile.model_validate(source.get("data_schema", source["profile"]))
    table_sample = TableSample.model_validate(
        source.get(
            "table_sample",
            {"columns": [column.name for column in profile.columns], "rows": [], "strategy": "profile_only"},
        )
    )
    provider = None if os.getenv("RESEARCHVIZ_FORCE_RULES") == "1" else get_llm_provider()
    if provider:
        skill_prompt = load_skill_prompt(
            "plan-visualization",
            references=("references/visualization-spec.md",),
        )
        plan = plan_visualization_with_skill(
            provider,
            args.request,
            schema,
            profile,
            table_sample,
            skill_prompt,
        )
    else:
        # Deterministic fallback is retained only for offline tests.
        from backend.app.agent import plan_visualization

        plan = legacy_spec_to_plan(plan_visualization(args.request, schema, profile))
    text = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
