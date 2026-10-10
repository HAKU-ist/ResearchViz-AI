---
name: plan-visualization
description: 根据机器学习实验的数据结构、实验语义、有限样例和用户可视化需求，自主搜索可用字段与取值、筛选数据系列、推理图表类型，并输出结构化 Visualization Spec。用于比较指定或模糊指代的方法族、绘制趋势/类别比较/关系/分布图，以及处理 long-format 和 wide-format 实验表。
---

# 规划实验可视化

根据 Data Schema、Table Sample、Experiment Schema 和用户本次图表需求，自主完成语义检索、数据查询规划和图表决策。输出两阶段 Visualization Plan，不生成 Python 代码。

## 工作流

1. 读取 `data_schema`、`table_sample`、`experiment_schema` 和用户本次请求。
2. 先在真实的列名、方法取值、指标和变量中搜索与用户表达语义相符的候选。支持大小写、简称、版本名和方法族表达，例如 `EMA 相关` 可以匹配所有包含 EMA 语义的真实候选，但不得创造不存在的方法。
3. 结合数量约束和修饰语筛选候选。先解析数量修饰语的作用域，再把数量作为对应作用域的硬约束：
   - “A ，和 B 的两种设置，”表示选择 A，并选择属于 B 的两种设置，因此通常总共三个系列；
   - “A 和 B 两种方法”表示 A、B 总共两个系列。
   若一个方法族对应的候选多于所需数量，依次根据请求修饰语、实验描述、候选版本/配置语义以及数值统计与分析目标排序，选择满足数量所需的候选；在 `assumptions` 记录选中了什么、排除了什么以及理由。
4. 先生成 `data_query`：
   - long-format 用 filters 表达方法、数据集、噪声率和其他条件；
   - wide-format 用 `reshape.mode=wide_to_long`，只把用户选择的方法真实列放入 `value_columns`；
   - 第一/最后观测才使用 selection；指定值、范围和值列表一律使用 filters；
   - 聚合明确写出 group_by、指标来源、输出列和误差输出列。
5. 再生成 `chart`，且只能引用 DataQuerySpec 最终输出字段。ChartSpec 不得承担筛选、reshape 或聚合。
6. 根据分析目标和字段语义推理图表类型、X/Y、视觉分组与误差展示。类别比较用 bar，趋势用 line，关系用 scatter，分布用 box。
7. 处理百分比条件时，先从 Experiment Schema 的 external_facts 和变量语义确定分母，再把计算后的绝对值写入 filter。缺少可靠分母时不得用 CSV 最大值代替。
8. 按 [visualization-spec.md](references/visualization-spec.md) 校验结果。用户指定的方法与条件必须完整保留。
9. 只输出一个 VisualizationPlan JSON。

输出前执行一致性检查：filters/reshape 是否完整表达用户硬约束；ChartSpec 是否只引用查询结果；标题与 rationale 是否和实际数据选择一致。

命令行入口：

   ```bash
   python skills/plan-visualization/scripts/plan.py \
     --experiment <experiment.json> \
     --request "<可视化请求>" \
     --output <spec.json>
   ```

如果请求引用的概念没有精确同名字段，允许在真实候选中做语义匹配；如果没有可信候选，返回可操作错误，不猜造字段。

## 输出要求

只输出一个符合契约的 Visualization Plan。必须包含 `data_query`、`chart`、`rationale` 和 `assumptions`。`rationale` 用一至三句话说明最终决策，不输出思维过程、自我争论或反复修正。
