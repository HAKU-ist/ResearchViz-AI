---
name: understand-experiment
description: 分析机器学习实验 CSV，生成数据画像和结构化 Experiment Schema。用户上传、引用或要求理解实验结果 CSV，识别数据集、方法、指标、独立变量、重复实验列、字段类型或数据质量问题时使用。
---

# 理解机器学习实验

将预处理工具生成的 Data Schema 和有限 Table Sample 转换成下游 Agent 可验证的实验语义，不生成图表。正常模型流程不读取完整 CSV。

## 工作流

1. 读取实验描述、`data_schema` 与 `table_sample`。把描述视为语义上下文，把真实列名、类型、统计和样例视为数据证据。
2. 逐列推理其在实验中的含义：指标、独立变量、控制变量、方法维度、数据集标识或重复实验维度。结合多列之间的取值变化理解每行代表的实验观测单位。
3. 用中文生成 `summary`、`row_meaning` 和 `column_meanings`。`column_meanings` 必须逐一覆盖 Data Schema 的所有列，说明字段在本实验中的具体意义，不能只把列名换一种说法。保持简洁：每项只写一句且不超过 20 个字符，不输出分析过程。
4. 判断 long-format 与 wide-format：long-format 的方法应记录真实方法列及其取值；wide-format 的多个方法结果列应记录到 `methods.values`，同时将这些列作为可绘制指标，并在 `methods.metric_name` 写明这些结果列共同表示的指标。
5. 识别数据集维度：用 `dataset_dimension.column` 表示数据集列，用 `dataset_dimension.setting_columns` 表示噪声率、噪声类型、数据版本等会形成不同数据集设置的列。单数据集无数据集列时保留 `column=null`。
6. 拆分方法与设置：保留每个原始标签到 `methods.variants[].raw_name`，把方法族写入 `method_name`，把列名、独立配置列或用户描述中明确给出的 beta、loss、backbone 等写入 `parameters`。没有证据的参数不得猜测。
7. 所有 `column` 必须来自 `data_schema.columns`；无法确定时降低 `confidence` 或写入 `warnings`，不得补造字段。
8. 判断缺失事实是否会改变实验语义或后续分析。如果该事实无法从 CSV、样例和用户描述推出，调用 `search_experiment_knowledge`；不要用模型记忆冒充检索证据，也不要搜索可直接从输入计算的内容。
9. 使用搜索结果时核对实体、版本、split、单位和实验范围。把实际采用的事实及来源写入 `external_facts`：来自用户描述或项目元数据的事实分别标记对应 `source_type`，来自搜索工具的事实标记 `web_search` 并使用工具实际返回的 URL；证据不足或来源冲突时写入 `unresolved_gaps`，不要强行下结论。
10. 按 [experiment-schema.md](references/experiment-schema.md) 输出一个 Experiment Schema。

## 搜索终止规则
- 搜索的目标是补全完成当前任务必需的事实，而不是进行全面调研。
- 如果搜索结果已经从可信来源明确回答缺失信息，必须停止搜索并生成结果。
- 同一个事实最多搜索两次。
- 只有第一轮结果存在冲突、歧义、来源不可靠或缺少单位时，才允许再次搜索。
- 不得搜索 CSV、用户描述或已有证据中已经明确的信息。

命令行入口：

   ```bash
   python skills/understand-experiment/scripts/analyze.py \
     --csv <文件路径> \
     --description "<实验描述>" \
     --output <输出 JSON 路径>
   ```

模型应根据字段语义、统计、样例之间的关系与实验描述推理，不依赖固定数据集或固定列名列表。

## 输出要求

模型只输出符合契约的 Experiment Schema。Skill 脚本负责把它与确定性的 `data_schema`、`table_sample` 和 `meta` 组装为完整结果。不要把完整 CSV 内容写入模型提示词或输出。
