# Pipeline V2 Plan

目标：让系统基于 `用户描述 + CSV` 先理解实验表，再规划可视化，再生成绘图代码。

## 总体流程

1. `CSV Profiling`
2. `Table Understanding`
3. `Visualization Planning`
4. `Code Generation`
5. `Execution + Repair`

---

## 1. CSV Profiling

职责：只做客观数据画像，不主导实验语义判断。

输入：

- `csv_path`
- 可选 `user_description`

输出：

- `DataProfile`
- `TableSample`

传给下一个模块：

- `profile`
- `sample`

应该包含的信息：

- 行数、列数
- 每列物理类型 / 语义类型
- 空值比例
- 唯一值数量
- 数值统计
- 有限样例行

当前对应：

- `backend/app/profiler.py`

后续修改原则：

- 保留读 CSV、列统计、样例提取
- 弱化“直接猜 schema”的职责

---

## 2. Table Understanding

职责：模型读取 `用户描述 + profile + sample`，理解整张表的实验语义。

输入：

- `user_description`
- `DataProfile`
- `TableSample`

输出：

- `TableUnderstanding`

传给下一个模块：

- `table_understanding`

建议输出字段：

- `row_semantics`：每一行代表什么
- `layout_type`：`long` / `wide` / `mixed`
- `column_semantics`：每一列的角色和语义
- `method_dimension`
- `metric_dimension`
- `independent_variables`
- `repeat_dimension`
- `reshape_plan`
- `warnings`
- `confidence`

当前对应：

- `skills/understand-experiment/`
- `backend/app/llm_workflow.py` 中的理解逻辑

后续修改原则：

- 改成模型主导理解
- 输出比 `ExperimentSchema` 更强的中间层

---

## 3. Visualization Planning

职责：基于用户请求和表理解结果，决定图表设计。

输入：

- `user_request`
- `TableUnderstanding`
- 可选 `DataProfile`

输出：

- `VisualizationPlan`

传给下一个模块：

- `visualization_plan`

建议输出字段：

- `chart_type`
- `x`
- `y`
- `group`
- `series_columns`
- `reshape_plan`
- `aggregation`
- `error_bar`
- `title`
- `x_label`
- `y_label`
- `assumptions`
- `rationale`

当前对应：

- `backend/app/agent.py`
- `backend/app/llm_workflow.py` 中的可视化规划逻辑

后续修改原则：

- 不再承担“顺便理解整张表”的职责
- 专注做图表映射和设计决策

---

## 4. Code Generation

职责：把可视化设计转成 matplotlib 代码。

输入：

- `VisualizationPlan`

输出：

- `PythonCodeArtifact`

传给下一个模块：

- `code`
- `visualization_plan`

当前对应：

- `backend/app/codegen.py`

后续修改原则：

- 显式支持 `reshape_plan`
- 保证 wide / long 两类表都能正确执行

---

## 5. Execution + Repair

职责：执行绘图代码，失败时修复 spec 或终止。

输入：

- `csv_path`
- `VisualizationPlan`
- `code`

输出：

- 成功：`image_path`、`final_plan`、`code_path`
- 失败：`error`、`attempt_log`、`terminal_reason`

修复子流程输入：

- `user_request`
- `TableUnderstanding`
- 当前 `VisualizationPlan`
- 执行错误
- `attempt_count`

修复子流程输出：

- 修正后的 `VisualizationPlan`

当前对应：

- `backend/app/main.py`
- `backend/app/llm_workflow.py`

后续修改原则：

- 最多重试 3 次
- 相同错误重复时提前终止
- 修复逻辑只改设计，不乱改事实字段

---

## 模块边界原则

- `Profiling` 只提供事实，不拍板语义
- `Understanding` 负责解释表结构和实验含义
- `Planning` 负责把用户需求映射成图表设计
- `Codegen` 负责把设计变成 matplotlib
- `Execution` 负责验证是否真的能跑

不要再让一个模块同时做两件事。

---

## 建议实现顺序

1. 先定义新的 `TableUnderstanding` 数据结构
2. 再改 `understand-experiment` skill 和 `analyze.py`
3. 再改 `llm_workflow.py`，拆出 `understand_table_with_llm`
4. 再让 `plan_visualization` 改为消费新的 understanding 输出
5. 最后整理 `codegen.py` 的 `reshape_plan` 执行逻辑

---

## 当前下一步

下一条先做：

1. 设计新的 `TableUnderstanding` schema

完成这个之后，再逐步改代码。
