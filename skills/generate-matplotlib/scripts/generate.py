#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.app.codegen import execute_code, generate_code  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.app.models import VisualizationPlan, VisualizationSpec  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="生成并执行可复现 Matplotlib 代码")
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    source = args.spec.read_text(encoding="utf-8")
    try:
        spec = VisualizationPlan.model_validate_json(source)
    except ValidationError:
        spec = VisualizationSpec.model_validate_json(source)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    code_path = args.output_dir / "visualization.py"
    image_path = args.output_dir / "figure.png"
    svg_path = args.output_dir / "figure.svg"
    code_path.write_text(generate_code(spec), encoding="utf-8")
    execute_code(code_path, args.csv, image_path, svg_path)
    print(json.dumps({
        "skill": "generate-matplotlib", "status": "SUCCEEDED",
        "code": str(code_path), "image": str(image_path),
        "svg": str(svg_path),
        "image_size_bytes": image_path.stat().st_size,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
