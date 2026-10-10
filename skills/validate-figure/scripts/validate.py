#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from PIL import Image, ImageStat


def validate(image_path: Path, code_path: Path | None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, object] = {}
    if not image_path.exists() or image_path.stat().st_size < 1024:
        errors.append("图片不存在或文件小于 1 KB")
        return {"valid": False, "score": 0, "checks": checks, "errors": errors, "warnings": warnings}
    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path).convert("RGB") as image:
            width, height = image.size
            mean = sum(ImageStat.Stat(image.resize((64, 64))).mean) / 3
            checks.update({"format": "PNG", "width": width, "height": height,
                           "size_bytes": image_path.stat().st_size, "mean_brightness": round(mean, 2)})
            if width < 800 or height < 500:
                errors.append("图片尺寸低于 800×500 px")
            if mean > 252:
                errors.append("图片接近全白，可能没有有效绘图内容")
            if mean < 3:
                errors.append("图片接近全黑，可能渲染失败")
    except Exception as exc:
        errors.append(f"PNG 无法解析: {exc}")
    if code_path:
        if not code_path.exists():
            errors.append("Python Artifact 不存在")
        else:
            try:
                compile(code_path.read_text(encoding="utf-8"), str(code_path), "exec")
                checks["python_syntax"] = "valid"
            except (SyntaxError, UnicodeError) as exc:
                errors.append(f"Python Artifact 无法编译: {exc}")
    score = max(0, 100 - len(errors) * 35 - len(warnings) * 5)
    return {"valid": not errors, "score": score, "checks": checks, "errors": errors, "warnings": warnings}


def main() -> None:
    parser = argparse.ArgumentParser(description="验证生成图表质量")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--code", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.image, args.code)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()

