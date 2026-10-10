# PRD：ResearchViz AI

## AI 机器学习实验智能可视化 Agent

## 1. 产品概述

### 1.1 产品定位

ResearchViz AI 是一个面向机器学习研究人员的智能实验分析与可视化平台。

用户可以上传机器学习实验数据，通过自然语言描述实验背景和分析需求，系统自动理解实验结构，选择合适的可视化方式，生成论文级实验图表以及对应
Python 绘图代码。

------------------------------------------------------------------------

## 2. 产品目标

解决机器学习实验过程中的以下问题：

-   实验结果整理繁琐
-   手动编写 matplotlib 代码耗时
-   图表格式调整重复
-   实验结果缺少统一管理

产品目标：

    实验数据
        ↓
    实验理解
        ↓
    分析规划
        ↓
    图表生成
        ↓
    代码生成
        ↓
    交互编辑
        ↓
    论文级输出

------------------------------------------------------------------------

# 3. Version 1 MVP 功能

## Feature 1：实验数据上传

### 支持文件

Version 1:

-   CSV

未来支持：

-   Excel
-   PyTorch checkpoint (.pth)
-   TensorBoard
-   wandb

### 用户输入

用户上传实验数据，并输入实验描述。

例如：

> 这是 CIFAR10 主动学习实验，比较不同 query strategy 在不同 label budget
> 下的 accuracy。

### 系统输出 Experiment Schema

示例：

``` json
{
  "experiment_type": "active_learning",
  "dataset": ["CIFAR10"],
  "methods": ["Random", "Entropy", "Ours"],
  "metrics": ["accuracy"],
  "variables": ["budget"]
}
```

------------------------------------------------------------------------

# 4. 自动生成可视化

用户输入：

> 生成不同方法 accuracy 随 budget 变化曲线

系统流程：

    用户需求

    ↓

    Intent Understanding

    ↓

    Experiment Retrieval

    ↓

    Visualization Planning

    ↓

    Code Generation

    ↓

    Python Execution

    ↓

    Figure

------------------------------------------------------------------------

## Visualization Specification

示例：

``` json
{
"type":"line_chart",
"x":"budget",
"y":"accuracy",
"group":"method",
"title":"Performance Comparison"
}
```

------------------------------------------------------------------------

# 5. Python代码生成

系统同时生成：

    figure.png

    visualization.py

要求：

-   matplotlib
-   可直接运行
-   支持复现实验图表

------------------------------------------------------------------------

# 6. AI Agent设计

系统采用多 Skill 架构。

## Experiment Understanding Skill

负责：

-   理解实验背景
-   识别数据集
-   识别实验方法
-   识别指标

## Data Analysis Skill

负责：

-   CSV解析
-   字段类型识别
-   数据统计

## Visualization Planning Skill

负责：

-   判断实验目标
-   推荐图表类型

## Code Generation Skill

负责：

-   生成 matplotlib Python代码

## Execution Skill

负责：

-   执行代码
-   输出图片

------------------------------------------------------------------------

# 7. 技术架构

## Frontend

-   Next.js
-   TypeScript
-   Tailwind CSS

## Backend

-   FastAPI
-   Python
-   LangGraph
-   Pandas
-   Matplotlib
-   Pydantic

架构：

    Frontend

        ↓

    FastAPI

        ↓

    Agent Layer

        ↓

    Pandas + LLM + Matplotlib

        ↓

    Storage

------------------------------------------------------------------------

# 8. 数据模型

## Experiment

字段：

    id
    name
    description
    file_path
    schema
    created_time

## Visualization

字段：

    id
    experiment_id
    visualization_spec
    python_code
    image_path
    created_time

------------------------------------------------------------------------

# 9. Version 2规划

## 9.1 PTH模型文件分析

支持：

model.pth

解析：

-   模型结构
-   backbone
-   参数量
-   training config

------------------------------------------------------------------------

## 9.2 实验知识库

保存：

-   实验描述
-   实验参数
-   实验数据

支持：

自然语言根据实验描述匹配搜索历史实验。

------------------------------------------------------------------------

## 9.3 交互式图片编辑器

支持：

-   修改曲线颜色
-   修改线条样式
-   调整字体大小
-   移动 legend
-   修改布局

------------------------------------------------------------------------

## 9.4 Figure-Code同步

设计 Figure JSON Schema：

``` json
{
"type":"line_chart",
"elements":[
 {
  "type":"line",
  "color":"blue",
  "style":"dashed"
 }
]
}
```

用户修改图片：

↓

更新 JSON

↓

重新生成代码

------------------------------------------------------------------------

# 10. 开发计划

## Sprint 1

完成：

-   CSV上传
-   数据解析
-   Experiment Schema

## Sprint 2

完成：

-   Agent Workflow
-   Visualization Planner
-   Code Generator

## Sprint 3

完成：

-   Frontend
-   图片展示
-   代码下载

## Sprint 4

优化：

-   Prompt
-   UI
-   Demo

------------------------------------------------------------------------

# 11. 后续扩展

-   自动生成论文实验描述
-   自动生成 Figure Caption
-   自动比较 baseline
-   自动发现异常实验
-   自动生成实验报告
