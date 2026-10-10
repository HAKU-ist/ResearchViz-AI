from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.profiler import profile_csv, infer_experiment_schema

csv_path = Path("testdata/cifar10.csv")
description = "这是 CIFAR10 噪声学习汇总结果，比较不同方法在不同噪声率下的 best acc"

df, profile = profile_csv(csv_path)
schema = infer_experiment_schema(description, df, profile)

print("=== PROFILE ===")
print(profile.model_dump_json(indent=2))

print("\n=== SCHEMA ===")
print(schema.model_dump_json(indent=2))
