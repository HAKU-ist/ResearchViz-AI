---
name: generate-matplotlib
description: 根据经过校验的 Visualization Plan 执行 DataQuerySpec，并按照 ChartSpec 生成可复现的 Matplotlib Python 代码和 PNG 图片。
---

# 生成 Matplotlib 图表

把 Visualization Plan 转换为确定性 Python Artifact。先执行 data_query，再把查询结果交给 chart，不重新解释用户意图。

## 工作流

1. 确认 Spec 符合 `plan-visualization` 契约，并确认 CSV 路径。
2. 运行生成器：

   ```bash
   python skills/generate-matplotlib/scripts/generate.py \
     --spec <spec.json> \
     --csv <data.csv> \
     --output-dir <输出目录>
   ```

3. 检查输出目录包含 `visualization.py` 和 `figure.png`。
4. 将生成物交给 `validate-figure`，不要仅根据进程退出码判断成功。
5. 执行失败时遵守 [failure-policy.md](references/failure-policy.md)，不得原样重复运行相同代码。

## 生成约束

- 使用 Matplotlib `Agg` 后端，禁止交互窗口。
- 代码通过 `--input` 和 `--output` 接收路径，不写死用户绝对路径。
- 固定允许的依赖为 pandas、matplotlib 和 Python 标准库。
- 生成脚本必须包含 `main()`，可在相同环境中重新执行。
- 不执行用户提供的 Python；只执行本 Skill 根据结构化 Spec 生成的代码。
- 一个任务最多执行代码 3 次；第 2、3 次必须来自经过重新校验的修复 Spec。
- 通用执行 filters、selection、wide_to_long 和 aggregation；Matplotlib 只消费查询结果字段。

更完整的输出要求见 [artifact-contract.md](references/artifact-contract.md)。
