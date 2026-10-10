# ResearchViz 实验知识图谱本体 v1.0

## 1. 当前阶段状态

已完成：

- 本体与机器校验契约；
- 确定性 Graph Builder；
- SQLite `graph_entities` / `graph_relations` 持久化；
- 上传与重新索引时事务化写入子图；
- 子图读取、统计和 API 查询。

- 只读 Graph Query Service；
- 三个受限 Graph Function Calling Tools；
- 以可选推理路径接入 Visualization ReAct Agent。

后续模块必须共同使用 `backend/app/graph_ontology.py`：

```text
Experiment Schema
       ↓
Graph Builder
       ↓
KnowledgeSubgraph 校验
       ↓
Graph Repository
       ↓
Graph Query Tools
       ↓
Visualization ReAct Agent
```

## 2. 设计原则

1. 现有 `observations` 仍是数值事实的业务来源，图谱不会替代 SQL 聚合。
2. 只有具有复用或推理价值的概念才成为实体。
3. CSV 单元格不会批量建成节点，而是作为 Evidence 保存。
4. 每个推断实体和关系必须保存置信度、生成方式和证据。
5. Relation 的起点、终点类型必须通过本体白名单校验。
6. 第一版本体只覆盖当前产品已经处理的实验数据，不提前引入论文、作者、机构等概念。

## 3. 实体类型

| 实体 | 含义 | 必需属性 | ID 前缀 |
|---|---|---|---|
| `experiment` | 一次导入的实验资产 | `name` | `exp_` |
| `dataset` | 规范化数据集 | `canonical_name` | `dataset_` |
| `dataset_variant` | 带划分、噪声率等配置的数据集 | `display_name`, `parameters` | `dataset_variant_` |
| `method` | 规范化算法或方法族 | `canonical_name` | `method_` |
| `method_variant` | 带超参数或组件的方法版本 | `display_name`, `parameters` | `method_variant_` |
| `metric` | 规范化评价指标 | `canonical_name`, `direction` | `metric_` |
| `observation` | 一个实验数值结果 | `value` | `obs_` |
| `condition` | budget、noise ratio、seed 等条件 | `name`, `value` | `condition_` |
| `visualization` | 使用观测生成的图表 | `request`, `status` | `vis_` |
| `artifact` | CSV、PNG、SVG、Python 等制品 | `artifact_type`, `path` | `artifact_` |
| `external_fact` | 来自项目外部的推理事实 | `key`, `value` | `fact_` |

### 不在 v1 中建模的实体

- `Claim`：当前系统生成图表，不自动生成研究结论；
- `Paper/Author/Institution`：当前没有论文知识库；
- 每一个 CSV Cell：使用 Evidence 表达，避免图谱爆炸；
- 每一个数值 Value：保存在 Observation 或 Condition 属性中。

## 4. 关系类型

```text
Experiment ─uses_dataset→ DatasetVariant
Experiment ─evaluates_method→ MethodVariant
Experiment ─produces_observation→ Observation

DatasetVariant ─variant_of→ Dataset
MethodVariant ─variant_of→ Method

Observation ─evaluated_on→ DatasetVariant
Observation ─produced_by→ MethodVariant
Observation ─measures→ Metric
Observation ─under_condition→ Condition

Visualization ─uses_observation→ Observation
Visualization ─generated_from→ Experiment
Experiment|Visualization ─has_artifact→ Artifact

Dataset|DatasetVariant|Method|Metric ─has_fact→ ExternalFact
Dataset|Method|Metric ─same_as→ 同类型实体
Method ─extends→ Method
```

所有合法端点组合由 `RELATION_DEFINITIONS` 唯一维护。比如以下关系会被拒绝：

```text
Method ─measures→ Metric
Observation ─variant_of→ Dataset
Dataset ─same_as→ Method
```

## 5. Evidence 与断言治理

Evidence 类型：

| 类型 | 例子 |
|---|---|
| `csv_cell` | `cifar10.csv` 第 5 行 `accuracy` 列 |
| `user_description` | 用户填写的实验说明 |
| `experiment_schema` | Understanding Skill 的结构化输出 |
| `deterministic_rule` | `normalize_experiment()` 建立的确定关系 |
| `external_source` | 数据集官网或可信公开来源 |
| `user_confirmation` | 用户人工确认的实体或关系 |

每个实体和关系还保存：

- `confidence`：0 到 1；
- `assertion_method`：`deterministic`、`llm_inferred`、`user_confirmed` 或 `external_import`；
- `status`：`proposed`、`validated` 或 `rejected`；
- `ontology_version`：用于后续本体迁移。

非确定性断言没有 Evidence 时不能通过校验。`csv_cell` 必须包含原始行号和列名，外部来源必须包含 URL。

## 6. 示例子图

原始 CSV：

```csv
dataset,method,noise_ratio,seed,best_acc
cifar10,Ours,0.4,42,0.913
```

对应子图：

```text
exp_noise_01
 ├─uses_dataset→ dataset_variant_cifar10_noise04
 ├─evaluates_method→ method_variant_ours_default
 └─produces_observation→ obs_noise_01_row0_best_acc

dataset_variant_cifar10_noise04 ─variant_of→ dataset_cifar10
method_variant_ours_default ─variant_of→ method_ours

obs_noise_01_row0_best_acc
 ├─evaluated_on→ dataset_variant_cifar10_noise04
 ├─produced_by→ method_variant_ours_default
 ├─measures→ metric_accuracy
 ├─under_condition→ condition_noise_ratio_04
 └─under_condition→ condition_seed_42
```

Observation 的 `value=0.913`，并附带：

```json
{
  "evidence_type": "csv_cell",
  "source_ref": "cifar10_noise.csv",
  "source_row": 0,
  "source_column": "best_acc"
}
```

## 7. 唯一标识策略

后续 Graph Builder 使用稳定 Hash 生成 ID：

```text
Dataset          = hash(canonical_name)
Method           = hash(canonical_name)
Metric           = hash(canonical_name)
DatasetVariant   = hash(experiment_id, dataset_id, parameters)
MethodVariant    = hash(experiment_id, method_id, raw_name, parameters)
Observation      = hash(experiment_id, source_row, source_column)
Condition        = hash(name, normalized_value, unit)
Relation         = hash(relation_type, source_id, target_id)
```

全局语义实体使用规范名生成 ID；实验内变体保留 `experiment_id`，避免错误合并不同实验中的同名配置。

## 8. 本体约束

`KnowledgeSubgraph` 会校验：

- 实体和关系 ID 唯一；
- ID 前缀符合实体类型；
- 必需属性存在；
- 未声明属性不能进入图谱；
- 关系端点符合本体白名单；
- 关系引用的实体真实存在；
- 关系声明类型与真实实体类型一致；
- 非确定性断言必须包含 Evidence；
- 关系不能连接实体自身。

## 9. SQLite 持久化

图谱使用来源实验作为命名空间：

```text
graph_entities PRIMARY KEY (id, source_experiment_id)
graph_relations PRIMARY KEY (id, source_experiment_id)
```

同一个规范化 Dataset、Method 或 Metric 可以出现在多个实验子图中，并分别保留各自 Evidence。上传时，Experiment、标准化知识和知识子图在同一事务内写入；Graph 校验或写入失败会整体回滚。

接口：

```text
GET /api/v2/knowledge/{experiment_id}/graph
POST /api/v2/knowledge/{experiment_id}/reindex
```

旧知识项不会被自动推断迁移，调用 `reindex` 后会基于原始 CSV 与已保存的 Experiment Schema 确定性重建图谱。

## 10. 图谱查询与 Agent Tools

当前提供三个只读工具：

```text
search_graph_entities
get_graph_neighbors
query_result_subgraph
```

约束：

- 邻居查询最多 3 跳、最多 300 个节点；
- Observation 查询最多返回 2000 条观测；
- 数值条件只做精确匹配，不自动使用最近值；
- 跨实验结果按来源实验拆分为多个子图；
- 图谱结果只用于找到关系和来源，绘图前仍必须调用 `prepare_visualization_data`；
- 简单名称查询仍可走原知识目录，避免每次任务额外消耗图谱工具轮次。

ReAct Agent 的工具轮预算从 8 调整为 10；代码生成上限仍为 3 次。

## 11. 下一步

下一阶段构建图谱推理 Benchmark，对比“结构化知识库”和“结构化知识库 + 图谱工具”在方法变体、跨实验实体对齐、精确条件筛选和缺失事实检测任务上的成功率、工具轮数与 Token 消耗。评测证明有增益后，再增加 ExternalFact 和实体消歧能力。
