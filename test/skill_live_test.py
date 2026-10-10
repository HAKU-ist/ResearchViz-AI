import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
TESTDATA = ROOT / "testdata"


def run_skill(command: list[str], *, accept_json_on_error: bool = False) -> dict:
    env = dict(os.environ)
    result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT, env=env)
    output = (result.stdout or "").strip()
    if result.returncode != 0 and not (accept_json_on_error and output):
        raise RuntimeError(result.stderr or result.stdout or "skill failed")
    if not output:
        raise RuntimeError("skill did not output JSON")
    return json.loads(output)


def main() -> None:
    experiment_json = ROOT / "test" / "_skill_experiment.json"
    spec_json = ROOT / "test" / "_skill_spec.json"
    output_dir = ROOT / "test" / "_skill_artifacts"

    understand = run_skill(
        [
            sys.executable,
            str(SKILLS / "understand-experiment" / "scripts" / "analyze.py"),
            "--csv",
            str(TESTDATA / "cifar10.csv"),
            "--description",
            "这是 CIFAR10 主动学习实验，比较不同 query strategy 在不同 label budget 下的 accuracy",
            "--output",
            str(experiment_json),
        ]
    )
    print("=== UNDERSTAND ===")
    print(json.dumps(understand, ensure_ascii=False, indent=2))

    plan = run_skill(
        [
            sys.executable,
            str(SKILLS / "plan-visualization" / "scripts" / "plan.py"),
            "--experiment",
            str(experiment_json),
            "--request",
            "生成不同方法 accuracy 随 budget 变化曲线",
            "--output",
            str(spec_json),
        ]
    )
    print("\n=== PLAN ===")
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    generate = run_skill(
        [
            sys.executable,
            str(SKILLS / "generate-matplotlib" / "scripts" / "generate.py"),
            "--spec",
            str(spec_json),
            "--csv",
            str(TESTDATA / "cifar10.csv"),
            "--output-dir",
            str(output_dir),
        ]
    )
    print("\n=== GENERATE ===")
    print(json.dumps(generate, ensure_ascii=False, indent=2))

    validate = run_skill(
        [
            sys.executable,
            str(SKILLS / "validate-figure" / "scripts" / "validate.py"),
            "--image",
            generate["image"],
            "--code",
            generate["code"],
        ],
        accept_json_on_error=True,
    )
    print("\n=== VALIDATE ===")
    print(json.dumps(validate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
