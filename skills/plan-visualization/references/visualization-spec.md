# Visualization Plan 规范

规划结果必须拆成 `data_query` 和 `chart`，禁止让 ChartSpec 承担数据筛选或 reshape。

```json
{
  "schema_version": "2.0",
  "data_query": {
    "filters": [
      {"column": "noise_ratio", "operator": "eq", "value": 0.4, "values": []},
      {"column": "method", "operator": "in", "value": null, "values": ["Ours", "JoCoR"]}
    ],
    "reshape": {
      "mode": "none",
      "id_columns": [],
      "value_columns": [],
      "variable_name": "series",
      "value_name": "value"
    },
    "selection": {"mode": "all", "order_by": null, "group_by": []},
    "aggregation": {
      "group_by": ["method"],
      "metrics": [
        {"source": "best_acc", "output": "best_acc_mean", "function": "mean", "error": "std", "error_output": "best_acc_std"}
      ]
    }
  },
  "chart": {
    "chart_type": "bar",
    "x": "method",
    "y": "best_acc_mean",
    "group": null,
    "error_y": "best_acc_std",
    "title": "Ours vs JoCoR at 40% Noise",
    "x_label": "Method",
    "y_label": "Best Accuracy",
    "dpi": 200
  },
  "rationale": "筛选40%噪声率和两种指定方法，再按方法汇总准确率。",
  "assumptions": []
}
```

## DataQuerySpec

- `filters` 支持 `eq`、`ne`、`in`、`not_in`、`gt`、`gte`、`lt`、`lte`、`between`。
- `eq/ne/gt/gte/lt/lte` 使用 `value`；`in/not_in/between` 使用 `values`。
- 所有 filter column 必须是真实 CSV 列。方法筛选值必须来自 Experiment Schema。
- long-format 不 reshape。方法、数据集、噪声率等限制全部放入 filters。
- wide-format 使用 `wide_to_long`：`value_columns` 只放用户需要的方法真实列，`variable_name` 和 `value_name` 是转换后字段。
- `selection` 只表示排序后的 first/last；普通值匹配必须使用 filters。
- `aggregation.group_by` 和 `metrics[].source` 引用筛选/reshape 后字段。
- 设置 `std/sem` 时必须提供 `error_output`。

## ChartSpec

- ChartSpec 只能引用 DataQuerySpec 最终输出的字段。
- `x` 表示横轴，`y` 表示数值，`group` 只表示视觉系列，`error_y` 只表示误差列。
- `x` 和 `group` 不得相同。
- 类别柱形图比较方法时通常 `x=method`、`group=null`。
- ChartSpec 中不得出现方法值筛选、原始行筛选或宽表列选择。

## 不变量

- 用户指定的方法、数据集和实验条件都是硬约束，不得为了生成可执行图表而放宽。
- 规划理由只描述最终选择，不输出思维过程、自我争论或能力限制。
- 所有自动转换和必要假设写入 `assumptions`。
