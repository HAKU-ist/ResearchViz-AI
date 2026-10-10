#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.app.profiler import infer_experiment_schema, preprocess_csv  # noqa: E402
from backend.app.llm import get_llm_provider  # noqa: E402
from backend.app.llm_workflow import infer_experiment_with_skill  # noqa: E402
from backend.app.skill_runtime import load_skill_prompt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="分析实验 CSV 并生成 Experiment Schema")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--description", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    frame, profile, table_sample = preprocess_csv(args.csv)
    provider = None if os.getenv("RESEARCHVIZ_FORCE_RULES") == "1" else get_llm_provider()
    if provider:
        skill_prompt = load_skill_prompt(
            "understand-experiment",
            references=("references/experiment-schema.md",),
        )
        schema, tool_trace = infer_experiment_with_skill(
            provider,
            args.description,
            profile,
            table_sample,
            skill_prompt,
        )
    else:
        # Deterministic fallback is retained only for offline tests.
        schema = infer_experiment_schema(args.description, frame, profile)
        tool_trace = []
    result = {
        "meta": {"skill": "understand-experiment", "version": "1.0", "source": str(args.csv),
                 "provider": provider.name if provider else "rules",
                 "model": provider.settings.model if provider else None,
                 "tool_trace": tool_trace},
        "data_schema": profile.model_dump(mode="json"),
        "table_sample": table_sample.model_dump(mode="json"),
        "experiment_schema": schema.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "schema": schema.model_dump(mode="json"),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
