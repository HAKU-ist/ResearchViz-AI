# Experiment Schema 规范

## 顶层结构

```json
{
  "experiment_type": "active_learning",
  "datasets": ["CIFAR10"],
  "dataset_dimension": {"column": "dataset", "values": ["cifar10"], "setting_columns": [], "confidence": 0.98},
  "summary": "CIFAR10主动学习结果",
  "row_meaning": "每行对应一个标注预算",
  "column_meanings": [
    {"column": "n_labeled", "meaning": "累计标注样本数", "role": "independent_variable", "confidence": 0.98},
    {"column": "Random", "meaning": "随机方法测试准确率", "role": "metric", "confidence": 0.95}
  ],
  "methods": {
    "column": "method",
    "values": ["Random", "EMA beta=0.99 kNN"],
    "setting_columns": [],
    "metric_name": "accuracy",
    "variants": [
      {"raw_name": "Random", "method_name": "Random", "parameters": {}, "confidence": 0.99},
      {"raw_name": "EMA beta=0.99 kNN", "method_name": "EMA", "parameters": {"beta": 0.99, "head": "kNN"}, "confidence": 0.95}
    ],
    "confidence": 0.95
  },
  "metrics": [{"name": "accuracy", "column": "accuracy", "direction": "maximize", "confidence": 0.9}],
  "variables": [{"name": "budget", "column": "budget", "role": "independent", "ordered": true, "confidence": 0.85}],
  "repeat_column": "seed",
  "external_facts": [{"key": "train_split_size", "value": 50000, "unit": "samples", "scope": "dataset train split", "source_type": "web_search", "source_title": "source title", "source_url": "https://...", "confidence": 0.95}],
  "unresolved_gaps": [],
  "warnings": []
}
```

## 不变量

- `methods.column`、`metrics[].column`、`variables[].column` 和 `repeat_column` 非空时必须存在于 CSV。
- `confidence` 范围为 0 到 1。
- `summary`、`row_meaning` 和 `column_meanings[].meaning` 使用简洁、具体的中文自然语言，不只是复述列名；每项只写一句且不超过 20 个字符。
- `column_meanings` 应覆盖 Data Schema 中的每一个真实 CSV 列；不得描述不存在的列。
- `row_meaning` 描述一行数据的实验观测单位，以及哪些条件共同确定这一行。
- `column_meanings[].role` 只能是 `metric`、`independent_variable`、`control_variable`、`method`、`dataset`、`repeat`、`identifier`、`metadata` 或 `unknown`。
- `dataset_dimension.column` 是 CSV 中区分基础数据集的列；单数据集且 CSV 无该列时为 null。`setting_columns` 只包含会形成不同数据集设置的真实列，例如噪声类型、噪声率或数据版本。
- `methods.setting_columns` 用于 long-format 中独立保存方法超参数或配置的列；wide-format 的设置通常编码在结果列名中。
- wide-format 中 `methods.metric_name` 表示所有方法结果列共同测量的指标；long-format 中为 null，指标由 `metrics[].column` 表示。
- `methods.variants` 覆盖 `methods.values` 中的原始方法标签。`raw_name` 必须原样保留，`method_name` 表示方法族，`parameters` 只记录证据明确的配置；不确定时使用空对象，禁止猜测。
- 指标必须能够转换为数值。
- warning 表达可继续处理的不确定性；无法解析 CSV 属于失败。
- `external_facts` 只能包含输入证据或工具检索结果支持的事实，并保留 `source_type`。`web_search` 类型必须使用工具实际返回的 URL。
- 可能改变字段解释或后续计算但尚未解决的问题写入 `unresolved_gaps`。
