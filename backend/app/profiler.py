import csv
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

from .models import (
    ColumnMeaning,
    ColumnProfile,
    DataProfile,
    DatasetDimension,
    ExperimentSchema,
    MethodDimension,
    MethodVariantDefinition,
    Metric,
    SampleRow,
    TableSample,
    Variable,
)


METHOD_KEYWORDS = ("method", "strategy", "model", "algorithm", "算法", "方法")
REPEAT_KEYWORDS = ("seed", "repeat", "run", "trial", "fold")
METRIC_KEYWORDS = ("accuracy", "acc", "loss", "error", "f1", "precision", "recall", "auc", "map", "mae", "rmse", "准确率", "损失")
VARIABLE_KEYWORDS = (
    "budget", "n_labeled", "labeled", "label", "query",
    "noise_ratio", "noise", "ratio", "corruption",
    "epoch", "step", "round", "time", "temperature", "threshold",
    "预算", "轮次", "噪声", "比例",
)
DATASET_KEYWORDS = ("dataset", "data", "corpus", "split", "数据集")
CONTROL_KEYWORDS = ("setting", "config", "configuration", "backbone", "arch", "scheduler", "optimizer")


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                sample = handle.read(8192)
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    delimiter = ","
            frame = pd.read_csv(path, encoding=encoding, sep=delimiter)
            if frame.empty or not len(frame.columns):
                raise ValueError("CSV 没有可分析的数据")
            return frame
        except (UnicodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise ValueError(f"CSV 解析失败: {last_error}")


def load_frame(path: Path) -> pd.DataFrame:
    return _read_csv(path)


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _lower_name(name: str) -> str:
    return name.strip().lower()


def _contains_any(name: str, keywords: tuple[str, ...]) -> bool:
    lower = _lower_name(name)
    return any(keyword in lower for keyword in keywords)


def _metric_direction(name: str) -> str:
    lower = _lower_name(name)
    if any(token in lower for token in ("loss", "error", "mae", "rmse", "wer", "cer", "损失")):
        return "minimize"
    return "maximize"


def _match_dataset_names(description: str, df: pd.DataFrame) -> list[str]:
    found: list[str] = []
    lower_desc = description.lower()
    candidates = ("cifar10", "cifar100", "imagenet", "mnist", "bloodmnist", "fashionmnist", "svhn")
    for candidate in candidates:
        if candidate in lower_desc:
            found.append(candidate.upper())
    if found:
        return found
    for column in df.columns:
        if _contains_any(str(column), DATASET_KEYWORDS):
            values = [str(v).strip() for v in df[column].dropna().unique().tolist()[:8]]
            guessed = [v.upper() for v in values if re.fullmatch(r"[A-Za-z0-9_-]{2,32}", v)]
            if guessed:
                return guessed
    return []


def _method_candidates(df: pd.DataFrame, profile: DataProfile) -> list[str]:
    candidates: list[str] = []
    for column in profile.columns:
        name = column.name
        if column.semantic_type not in ("categorical", "text"):
            continue
        if _contains_any(name, METHOD_KEYWORDS):
            candidates.append(name)
            continue
        if _contains_any(name, DATASET_KEYWORDS + CONTROL_KEYWORDS):
            continue
        if 2 <= column.unique_count <= min(32, max(4, profile.row_count // 2)):
            candidates.append(name)
    return candidates


def _repeat_candidate(profile: DataProfile) -> str | None:
    for column in profile.columns:
        if _contains_any(column.name, REPEAT_KEYWORDS):
            return column.name
    return None


def _metric_candidates(profile: DataProfile) -> list[str]:
    numeric = [column.name for column in profile.columns if column.semantic_type == "numeric"]
    matched = [name for name in numeric if _contains_any(name, METRIC_KEYWORDS)]
    return matched


def _variable_candidates(profile: DataProfile, excluded: set[str]) -> list[str]:
    numeric = [column.name for column in profile.columns if column.semantic_type == "numeric" and column.name not in excluded]
    matched = [name for name in numeric if _contains_any(name, VARIABLE_KEYWORDS)]
    return sorted(
        matched,
        key=lambda name: (
            0 if name.lower() in {"budget", "n_labeled", "noise_ratio"} else 1,
            name,
        ),
    )


def _wide_method_columns(profile: DataProfile, variable_cols: list[str], metric_cols: list[str], repeat_col: str | None) -> list[str]:
    numeric = [column.name for column in profile.columns if column.semantic_type == "numeric"]
    protected = set(variable_cols) | ({repeat_col} if repeat_col else set())
    candidate_cols = [name for name in numeric if name not in protected]
    keyword_metrics = [name for name in metric_cols if _contains_any(name, METRIC_KEYWORDS)]
    if keyword_metrics:
        return []
    if len(candidate_cols) < 2 or len(variable_cols) < 1:
        return []
    return candidate_cols


def profile_csv(path: Path) -> tuple[pd.DataFrame, DataProfile]:
    df = _read_csv(path)
    columns: list[ColumnProfile] = []
    for name in df.columns:
        series = df[name]
        unique_count = int(series.nunique(dropna=True))
        if is_bool_dtype(series):
            semantic = "boolean"
        elif is_numeric_dtype(series):
            semantic = "numeric"
        elif is_datetime64_any_dtype(series):
            semantic = "datetime"
        elif unique_count <= min(50, max(10, len(series) // 10)):
            semantic = "categorical"
        else:
            semantic = "text"
        samples = [_jsonable(v) for v in series.dropna().drop_duplicates().head(8).tolist()]
        stats: dict[str, Any] | None = None
        if semantic == "numeric":
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            stats = {"min": float(numeric.min()), "max": float(numeric.max()),
                     "mean": float(numeric.mean()), "median": float(numeric.median())}
        null_count = int(series.isna().sum())
        columns.append(ColumnProfile(
            name=str(name), physical_type=str(series.dtype), semantic_type=semantic,
            nullable=null_count > 0, null_count=null_count,
            null_ratio=round(null_count / len(df), 6), unique_count=unique_count,
            sample_values=samples, statistics=stats,
        ))
    warnings = []
    if df.duplicated().any():
        warnings.append(f"检测到 {int(df.duplicated().sum())} 行重复数据")
    return df, DataProfile(row_count=len(df), column_count=len(df.columns), columns=columns, warnings=warnings)


def sample_table(df: pd.DataFrame, *, max_rows: int = 8) -> TableSample:
    if df.empty:
        return TableSample(columns=[str(c) for c in df.columns], rows=[], strategy="empty")
    candidate_indices: list[int] = []
    head_count = min(5, len(df), max_rows)
    candidate_indices.extend(range(head_count))
    if len(candidate_indices) < min(max_rows, len(df)):
        remaining_slots = min(max_rows, len(df)) - len(candidate_indices)
        spread = [
            round((len(df) - 1) * step / (remaining_slots + 1))
            for step in range(1, remaining_slots + 1)
        ]
        candidate_indices.extend(spread)
    seen: set[int] = set()
    rows: list[SampleRow] = []
    for idx in candidate_indices:
        if idx in seen:
            continue
        seen.add(idx)
        row = df.iloc[idx]
        rows.append(SampleRow(row_index=int(idx), values={str(col): _jsonable(row[col]) for col in df.columns}))
        if len(rows) >= max_rows:
            break
    return TableSample(columns=[str(c) for c in df.columns], rows=rows, strategy="head_plus_spread")


def preprocess_csv(path: Path) -> tuple[pd.DataFrame, DataProfile, TableSample]:
    df, profile = profile_csv(path)
    return df, profile, sample_table(df)


def infer_experiment_schema(description: str, df: pd.DataFrame, profile: DataProfile) -> ExperimentSchema:
    lower_desc = description.lower()
    method_candidates = _method_candidates(df, profile)
    method_col = method_candidates[0] if method_candidates and _contains_any(method_candidates[0], METHOD_KEYWORDS) else None
    metric_cols = _metric_candidates(profile)
    repeat_col = _repeat_candidate(profile)
    variable_cols = _variable_candidates(profile, set(metric_cols) | ({repeat_col} if repeat_col else set()))
    wide_method_cols = _wide_method_columns(profile, variable_cols, metric_cols, repeat_col)
    if wide_method_cols:
        metric_cols = wide_method_cols
        method_col = None

    datasets = _match_dataset_names(description, df)
    dataset_col = next(
        (column.name for column in profile.columns if _contains_any(column.name, DATASET_KEYWORDS)),
        None,
    )
    dataset_values = (
        [str(value) for value in df[dataset_col].dropna().drop_duplicates().tolist()]
        if dataset_col else datasets
    )
    dataset_setting_cols = [
        column.name
        for column in profile.columns
        if column.name != dataset_col
        and _contains_any(column.name, ("noise", "corruption", "setting", "version", "variant", "噪声", "设置"))
    ]
    experiment_type = "active_learning" if any(x in lower_desc for x in ("active learning", "主动学习", "query strategy", "label budget")) else "machine_learning"
    warnings = list(profile.warnings)
    if not metric_cols:
        warnings.append("未找到数值指标列")
        numeric = [c.name for c in profile.columns if c.semantic_type == "numeric"]
        if numeric:
            metric_cols = numeric[-1:]
    if wide_method_cols:
        warnings.append("检测到宽表方法布局：多个方法以独立数值列存储，可在绘图时自动转成长表")
    if not method_col and not wide_method_cols and method_candidates:
        warnings.append(f"方法列不够确定，候选列: {', '.join(method_candidates[:3])}")
    if not variable_cols:
        fallback_numeric = [c.name for c in profile.columns if c.semantic_type == "numeric" and c not in metric_cols]
        variable_cols = fallback_numeric[:2]
        if variable_cols:
            warnings.append("未找到明确自变量，已按数值列顺序提供候选变量")
    metric_set = set(metric_cols)
    variable_set = set(variable_cols)
    method_set = set(wide_method_cols)

    def fallback_column_meaning(column: ColumnProfile) -> ColumnMeaning:
        if column.name in method_set:
            role, meaning = "metric", "该方法对应的实验结果"
        elif column.name in metric_set:
            role, meaning = "metric", "该条件下的实验指标值"
        elif column.name == method_col:
            role, meaning = "method", "区分实验方法或设置"
        elif column.name == repeat_col:
            role, meaning = "repeat", "区分不同重复实验"
        elif column.name in variable_set:
            role, meaning = "independent_variable", "该行采用的实验条件"
        else:
            role, meaning = "metadata", "辅助实验信息"
        return ColumnMeaning(column=column.name, meaning=meaning, role=role, confidence=0.5)

    row_meaning = "每行是一组条件下的实验观测"
    method_values = (
        wide_method_cols
        if wide_method_cols
        else [str(v) for v in df[method_col].dropna().unique()[:30]] if method_col else []
    )
    description_metric = next(
        (token for token in ("accuracy", "acc", "f1", "auc", "loss", "error") if token in lower_desc),
        None,
    )
    return ExperimentSchema(
        experiment_type=experiment_type, datasets=datasets,
        dataset_dimension=DatasetDimension(
            column=dataset_col,
            values=dataset_values,
            setting_columns=dataset_setting_cols,
            confidence=0.8 if dataset_col else 0.6 if datasets else 0.3,
        ),
        methods=MethodDimension(
            column=method_col,
            values=method_values,
            variants=[
                MethodVariantDefinition(
                    raw_name=value,
                    method_name=value,
                    parameters={},
                    confidence=0.5,
                )
                for value in method_values
            ],
            metric_name=description_metric if wide_method_cols else None,
            confidence=0.95 if wide_method_cols else 0.85 if method_col else 0.35,
        ),
        metrics=[Metric(name=c, column=c, direction=_metric_direction(c), confidence=0.75 if _contains_any(c, METRIC_KEYWORDS) else 0.45) for c in metric_cols],
        variables=[
            Variable(
                name=c,
                column=c,
                role="control" if _contains_any(c, ("seed", "trial", "fold")) else "independent",
                ordered=True,
                confidence=0.8 if _contains_any(c, VARIABLE_KEYWORDS) else 0.5,
            )
            for c in variable_cols
        ],
        summary="记录机器学习实验结果",
        row_meaning=row_meaning,
        column_meanings=[fallback_column_meaning(column) for column in profile.columns],
        repeat_column=repeat_col, warnings=warnings,
    )
