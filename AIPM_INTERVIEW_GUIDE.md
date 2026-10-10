# ResearchViz AI：AIPM 面试项目说明

## 1. 一句话介绍

ResearchViz AI 是一个面向机器学习研究人员的实验可视化 Agent：系统将格式不统一的实验 CSV 转换成结构化实验知识，并根据自然语言需求自主检索数据、规划图表、生成并执行 Matplotlib 代码，最终输出 PNG、SVG 和可复现 Python 文件。

---

## 2. 30 秒项目介绍

用户上传实验 CSV 和实验描述后，系统会理解每一行、每一列的含义，识别数据集、方法、指标、实验变量以及宽表或长表结构，并将其标准化存入知识库。

后续用户不需要指定某张表，只需输入“比较 Ours 在 CIFAR10 和 CIFAR100 上的准确率”，ReAct Agent 就会自主搜索知识库、选择并合并相关实验、生成可视化计划、执行绘图代码并验证结果。

项目的核心价值不是简单生成绘图代码，而是把非结构化实验文件转换成可检索、可推理、可验证的实验知识。

---

## 3. 用户痛点

### 3.1 实验结果格式不统一

长表可能是：

```csv
dataset,method,budget,accuracy
cifar10,BADGE,1000,0.71
cifar10,Ours,1000,0.75
```

宽表可能是：

```csv
n_labeled,BADGE,Ours,Random
1000,0.71,0.75,0.65
2000,0.76,0.81,0.70
```

同一个实验语义可以对应完全不同的数据结构。

### 3.2 绘图过程重复

研究人员需要反复判断横轴、纵轴、分组、筛选、聚合和误差棒，再编写和修改 Matplotlib 代码。

### 3.3 实验数据分散

不同数据集或方法可能保存在多个 CSV 中。传统单表工具很难直接完成跨实验比较。

---

## 4. V1 到 V2 的产品演进

### 4.1 V1：单 CSV 固定工作流

```text
CSV + 实验描述
      ↓
CSV Profiling
      ↓
Experiment Understanding
      ↓
Visualization Planning
      ↓
Matplotlib Code Generation
      ↓
Execution + Validation
      ↓
PNG + SVG + Python
```

V1 完成了单张 CSV 的自动理解和可视化，但存在以下限制：

- 每次必须先上传或选择一张表；
- 无法跨实验、跨数据集比较；
- 宽表与长表难以用一套固定字段表示；
- 用户请求可能依赖 CSV 中不存在的外部信息；
- 固定工作流无法自主判断是否需要继续检索数据。

### 4.2 V2：实验知识库 + ReAct Agent

V2 将系统拆成两条链路。

#### 实验导入链路

```text
CSV
 ↓
文件检查与重复检测
 ↓
客观数据画像
 ↓
LLM 实验理解
 ↓
实验数据标准化
 ↓
写入知识库
```

#### 知识库可视化链路

```text
自然语言需求
 ↓
Agent 搜索和检查知识库
 ↓
自主选择一个或多个实验
 ↓
准备并合并标准化数据
 ↓
规划图表
 ↓
生成并执行代码
 ↓
验证图片
 ↓
成功或继续修复
```

---

## 5. 为什么采用“固定工作流 + ReAct”混合架构

是否使用 Agent，取决于任务路径的不确定性，而不是功能是否包含 AI。

### 实验导入使用固定工作流

导入步骤明确且不可跳过：

- 检查文件；
- 读取 CSV；
- 生成数据画像；
- 理解实验 Schema；
- 标准化并写入知识库。

固定工作流更加稳定、可测试且节省 Token。

### 可视化使用 ReAct

可视化需求具有开放性：

- 可能需要一个或多个实验；
- 可能缺少方法、指标或数据集；
- 有时需要搜索，有时已有充分信息；
- 规划失败后可能需要重新检查或更换数据源。

因此由模型根据当前状态和工具返回结果自主决定下一步。

---

## 6. CSV 理解链路

### 6.1 Data Profiler

Profiler 使用 Pandas 提取客观信息：

- 行数与列数；
- 物理类型和基础语义类型；
- 空值比例；
- 唯一值数量；
- 数值范围；
- 类别样例；
- 有限样例行。

Profiler 不最终决定 `n_labeled` 是否等于 `budget`，因为这种判断需要实验上下文。

系统不会把完整 CSV 发送给模型，只传递结构、统计摘要、有限样例和用户描述，从而控制 Token、延迟和隐私风险。

实现位置：`backend/app/profiler.py`。

### 6.2 Experiment Understanding Skill

模型结合实验描述、Data Schema 和 Table Sample，输出：

#### Data Schema

描述 CSV 的客观结构。

```json
{
  "row_count": 100,
  "columns": [
    {
      "name": "n_labeled",
      "physical_type": "integer",
      "semantic_type": "numeric"
    }
  ]
}
```

#### Experiment Schema

描述实验语义。

```json
{
  "experiment_type": "active_learning",
  "row_meaning": "一次方法在特定标注预算下的实验结果",
  "datasets": ["CIFAR10"],
  "methods": {
    "column": null,
    "values": ["BADGE", "Ours", "Random"]
  },
  "metrics": [
    {
      "name": "accuracy",
      "column": "Ours",
      "direction": "maximize"
    }
  ],
  "variables": [
    {
      "name": "budget",
      "column": "n_labeled",
      "role": "independent"
    }
  ]
}
```

`direction: maximize` 表示指标越大越好；loss 一般是 `minimize`。

Skill 位置：`skills/understand-experiment/`。

---

## 7. 知识库设计

本地版本使用 SQLite 保存结构化元数据，CSV、PNG、SVG 和 Python 文件保存在本地文件系统。

### 7.1 核心数据表

```text
experiments
datasets
dataset_variants
methods
method_variants
observations
knowledge_documents
visualizations
visualization_sources
```

数据库实现：`backend/app/storage.py`。

### 7.2 为什么不能只保存原始 CSV

如果只保存文件，每次跨实验查询时都需要让模型重新理解所有 CSV，成本高且结果不稳定。

导入时系统会把不同 CSV 标准化成 Observation：

```json
{
  "experiment_id": "experiment-id",
  "dataset_variant_id": "dataset-variant-id",
  "method_variant_id": "method-variant-id",
  "metric_name": "accuracy",
  "metric_value": 0.91,
  "dimensions": {
    "budget": 10000,
    "noise_ratio": 0.4,
    "seed": 42
  },
  "source_row": 5,
  "source_column": "best_acc"
}
```

其中 `source_row` 和 `source_column` 用于保证结果可以追溯回原始 CSV。

### 7.3 Dataset Variant

数据集设置会被拆分保存：

```text
CIFAR10
CIFAR10 (noise_ratio=0.2)
CIFAR10 (noise_ratio=0.4)
```

### 7.4 Method Variant

方法及其不同配置也会拆分：

```text
Ours (loss=CE)
Ours (loss=GCE)
EMA (beta=0.9)
EMA (beta=0.99)
```

标准化实现：`backend/app/knowledge.py`。

### 7.5 为什么当前没有使用向量数据库

当前主要检索维度是数据集、方法、指标和实验设置，这些字段已经结构化，SQL 精确查询更加可控。

向量数据库更适合未来的模糊语义检索，例如：

> 找出所有与标签噪声鲁棒学习相关的实验。

未来可以为 `knowledge_documents` 增加 Embedding，而不是从一开始就把所有实验信息只存入向量数据库。

---

## 8. ReAct Agent 与工具

当前可视化 Agent 可以调用 8 个核心工具。

### 8.1 知识检索

- `list_knowledge_catalog`
- `search_knowledge`
- `inspect_knowledge_items`

### 8.2 数据准备

- `prepare_visualization_data`
- `inspect_prepared_data`

### 8.3 可视化执行

- `plan_visualization`
- `generate_visualization`
- `validate_visualization`

### 8.4 状态检查

- `get_visualization_state`

Agent 实现：`backend/app/visualization_agent.py`。

### 8.5 一次跨实验任务示例

用户输入：

> 比较 Ours 在 CIFAR10 和 CIFAR100 上的 accuracy。

可能的工具轨迹：

```text
Round 1: list_knowledge_catalog
→ 获取知识库实验摘要

Round 2: inspect_knowledge_items
→ 实验 A 包含 CIFAR10 + Ours
→ 实验 B 包含 CIFAR100 + Ours

Round 3: prepare_visualization_data
→ 合并实验 A 和 B 的标准化观测

Round 4: plan_visualization
→ 生成 DataQuerySpec + ChartSpec

Round 5: generate_visualization
→ 生成 Python、PNG 和 SVG

Round 6: validate_visualization
→ valid=true

Final: SUCCEEDED
```

Agent 最多有 8 个工具轮次；代码执行最多 3 次。只有图片验证返回 `valid=true`，Agent 才能宣布成功。

---

## 9. Visualization Plan

系统不让模型直接生成任意 Python，而是先生成结构化计划。

### 9.1 DataQuerySpec

负责决定画哪些数据。

```json
{
  "filters": [
    {
      "column": "method_variant",
      "operator": "in",
      "values": ["Ours", "JoCoR"]
    },
    {
      "column": "noise_ratio",
      "operator": "eq",
      "value": 0.4
    }
  ],
  "aggregation": {
    "group_by": ["method_variant"],
    "metrics": [
      {
        "source": "value",
        "output": "accuracy_mean",
        "function": "mean",
        "error": "std"
      }
    ]
  }
}
```

### 9.2 ChartSpec

负责决定如何展示。

```json
{
  "chart_type": "bar",
  "x": "method_variant",
  "y": "accuracy_mean",
  "error_y": "accuracy_std",
  "title": "Accuracy under 40% Noise"
}
```

中间 Spec 的价值：

- 禁止引用不存在的列；
- 数据查询和视觉呈现解耦；
- 执行前可以结构化校验；
- 失败时优先修复 Spec；
- 能记录 Agent 的决策理由；
- 支持 Figure-Code 同步。

模型负责理解和决策，确定性程序负责计算和执行。

---

## 10. 代码生成与验证

Code Generation Skill 根据已经验证的 Visualization Plan 生成受控 Matplotlib 代码，而不是让模型自由编写任意代码。

输出包括：

```text
selected_observations.csv
visualization.py
figure.png
figure.svg
```

优势：

- 代码可复现；
- 更容易进行安全检查；
- 相同 Spec 可以稳定执行；
- 样式调整不需要再次调用模型。

代码生成实现：`backend/app/codegen.py`。

---

## 11. Figure Canvas

前端加载生成的真实 SVG，支持：

- 拖动标题、轴名称、图例和绘图区；
- 缩放、旋转和方向键微调；
- 双击编辑文字；
- 点击曲线或图例修改颜色；
- 撤销和重做；
- 调整画布尺寸。

点击“应用保存”后：

```text
画布编辑
 ↓
更新 ChartStyle / CanvasObject
 ↓
重新生成 Matplotlib Python
 ↓
重新执行和验证
 ↓
同步更新 PNG、SVG 和 Python
```

画布修改不调用模型。系统还提供 0 Token 示例，用于直接测试编辑能力。

---

## 12. Skill 与 Tool 的区别

### Skill

Skill 是一套可复用的领域能力，包含：

- 中文 `SKILL.md`；
- 输入输出契约；
- 领域规则；
- Reference Schema；
- 确定性执行脚本。

当前有四个核心 Skill：

1. `understand-experiment`
2. `plan-visualization`
3. `generate-matplotlib`
4. `validate-figure`

### Tool

Tool 是 ReAct Agent 运行时能够调用的函数接口。

例如：

```text
plan_visualization Tool
        ↓
调用 plan-visualization Skill
```

Skill 定义能力应该如何完成，Tool 定义 Agent 如何调用该能力。

---

## 13. 可靠性设计

### 13.1 输入层

- 只允许 CSV；
- 文件最大 100 MB；
- 使用 SHA-256 检测重复文件；
- 自动处理编码和分隔符；
- 完整 CSV 不直接进入 Prompt。

### 13.2 Schema 层

- Pydantic 结构化输出；
- 所有列引用必须真实存在；
- 检查数据类型和筛选值；
- 保存 warning 和 confidence。

### 13.3 Agent 层

- Tool 参数使用 JSON Schema；
- 最多 8 个工具轮次；
- 代码最多执行 3 次；
- 验证通过后才能成功；
- 保存工具轨迹、终止原因和错误摘要。

### 13.4 执行层

- 独立子进程执行；
- 超时控制；
- 检查图片存在性和有效尺寸；
- 验证 Python 语法。

### 13.5 可观测性

系统记录：

- Input/Output/Total Token；
- API 调用次数；
- 每个 Endpoint 的 Token 消耗；
- Agent Tool Trace；
- 代码执行次数；
- 最终错误和终止原因。

---

## 14. 关键产品决策

### 决策一：固定工作流与 ReAct 混合

导入强调稳定性，采用固定工作流；可视化强调适应性，采用 ReAct。这样避免不必要的 Agent 调用，降低成本和不可预测性。

### 决策二：建立标准化 Observation 层

不同 CSV 最终统一为：

```text
dataset + method + metric + dimensions + value
```

这是系统支持跨实验可视化的基础。

### 决策三：模型生成 Spec，而不是直接生成代码

模型擅长意图理解和决策；程序擅长确定性计算、校验和执行。两者分工可以降低字段幻觉，提高可解释性和可维护性。

---

## 15. 典型失败案例

用户提出：

> 比较 CIFAR10 在 20% label budget 下不同方法的准确率。

CSV 只有 `n_labeled`，没有百分比，也没有 CIFAR10 训练集总样本量。早期 Planner 会错误地选择最后一轮，因为它无法把 20% 转换成具体标注数量。

这个案例说明需要区分：

1. CSV 中已有的信息；
2. 用户描述提供的信息；
3. 知识库中的信息；
4. 需要通过外部工具获得的信息；
5. 无法确认、必须询问用户的信息。

它推动了缺失信息检测和工具调用设计，而不是继续在 Prompt 中增加写死规则。

---

## 16. 评测指标设计

### 实验理解

- 列角色识别准确率；
- Dataset/Method/Metric 提取 F1；
- 宽表/长表识别准确率；
- Schema 合法率；
- 不存在字段幻觉率。

### 知识检索

- Source Recall@K；
- Source Precision；
- 跨表任务选源成功率；
- 不相关实验误召回率。

### 可视化规划

- 图表类型准确率；
- 字段映射准确率；
- 筛选条件准确率；
- 聚合策略准确率；
- Error Bar 使用正确率。

### 执行与成本

- 首次执行成功率；
- 三次以内成功率；
- 平均执行次数；
- P95 延迟；
- 平均工具轮数；
- 每个成功任务的 Token 消耗。

### 用户价值

- 从上传到获得可用图表的时间；
- 图表首次接受率；
- 用户重新生成次数；
- 手动修改次数；
- PNG/SVG/Python 下载率。

当前自动化测试证明工程链路能够运行，但不等于模型理解质量已经被充分验证。下一阶段需要构建覆盖不同实验类型、宽长表和跨表任务的 benchmark。

---

## 17. 三分钟面试讲述模板

> 我做的是一个面向机器学习研究人员的实验可视化 Agent。用户真正的问题不是不会写 Matplotlib，而是实验结果分散在不同格式的 CSV 中，系统很难知道每一列代表方法、指标还是实验变量。
>
> V1 我先实现了一个单 CSV 固定工作流：使用 Pandas 做客观数据画像，再让 Qwen 根据实验描述和有限样例生成结构化 Experiment Schema，之后生成 Visualization Spec，使用模板生成 Matplotlib 代码并执行验证。
>
> 测试中发现，单表模式无法完成跨数据集比较，而且宽表、长表和方法不同配置很难统一。因此 V2 增加了实验知识库。导入时把 CSV 标准化拆成 Dataset Variant、Method Variant 和 Observation，同时保存 Source Row 和 Source Column，保证结果可追溯。
>
> 在架构上，我没有把全部流程都做成 Agent。上传导入路径明确，所以使用固定工作流；可视化需求开放，所以使用 ReAct。Agent 可以自主搜索知识库、检查候选实验、选择多个数据源、准备数据、规划图表、生成代码和验证图片。只有验证通过才能成功，执行最多三次，防止无限循环。
>
> 另一个关键决策是模型不直接生成任意 Python，而是先生成 DataQuerySpec 和 ChartSpec。模型负责理解和决策，确定性程序负责过滤、聚合、代码生成和执行，这样降低了幻觉，也使错误可以定位到选源、规划或执行中的具体环节。
>
> 最终系统生成 PNG、SVG 和可复现 Python，并支持直接编辑 SVG。编辑不再调用模型，而是修改结构化样式并重新生成代码，实现 Figure-Code 同步。
>
> 下一阶段我会重点建立端到端 benchmark，评估 Schema 准确率、选源 Recall、规划准确率、首次执行成功率、Token 成本和用户首次接受率。

---

## 18. 面试高频追问

### 为什么不直接让模型读取 CSV 并生成代码？

完整 CSV 可能很大，会增加 Token、延迟和隐私风险；直接生成代码还会把语义理解、字段选择和执行安全耦合在一起。因此系统只把结构和样例交给模型，并使用可验证的中间 Spec。

### 为什么不是所有环节都使用 ReAct？

导入路径固定，使用 Agent 只会增加成本和随机性；可视化路径开放，才需要模型根据观察自主选择工具。

### 为什么不用向量数据库？

当前数据集、方法、指标和实验设置都是结构化字段，SQL 精确查询更稳定。未来出现大规模模糊语义检索需求时，再为知识文档增加向量索引。

### 如何防止模型引用不存在的列？

模型输出必须经过 Pydantic 和列引用校验；所有 `x`、`y`、`group`、筛选和聚合字段必须存在于准备后的真实数据中。

### Agent 如何判断任务成功？

不能只依赖模型自己声明成功。必须生成真实文件，并由验证工具确认图片和代码有效，Agent 才能返回 `SUCCEEDED`。

### 为什么最大执行次数是 3？

为了平衡恢复能力、延迟和 Token 成本。超过三次通常说明根因不是简单代码错误，而是数据、选源或计划存在结构性问题，应终止并暴露原因。

---

## 19. 面试中必须保持准确的边界

- 当前实现使用 Qwen Function Calling 驱动显式 ReAct 循环，不是真正的 LangGraph；LangGraph 是可演进方向。
- 当前知识库使用 SQLite 和本地文件系统，不是向量数据库。
- 当前代码执行使用独立子进程和超时控制，还不是完整 Docker 沙箱。
- 当前已经有工程自动化测试和 Token 统计，但没有大规模真实用户 A/B 数据。
- 模型读取的是结构化摘要和有限样例，不是完整 CSV。
- `.py` 脚本本身不是 Skill；Skill 是 `SKILL.md + 契约 + References + Scripts` 组成的能力包。
- 面试时不要编造准确率、成功率或用户增长数字；没有正式测量的指标应作为下一阶段评测计划说明。

---

## 20. 技术栈

```text
Frontend: Next.js + React + TypeScript
Backend: FastAPI + Pydantic
LLM: Qwen 系列模型，支持配置
Agent: Function Calling + ReAct
Data: Pandas
Visualization: Matplotlib + SVG
Database: SQLite
Artifact Storage: Local filesystem
Testing: Pytest + TypeScript/Next.js build
```
