---
name: validate-figure
description: 验证 ResearchViz AI 生成的 PNG 和 Python Artifact，检测空白图、尺寸不足、文件损坏、代码不可编译及论文图基本规范问题。图表生成后需要质量门禁、失败诊断或比较 Skill 优化效果时使用。
---

# 验证生成图表

对生成物执行确定性质量门禁，输出机器可读报告。此 Skill 不修改图片。

## 工作流

1. 获取 PNG；如果同时存在生成代码，一并传入。
2. 执行：

   ```bash
   python skills/validate-figure/scripts/validate.py \
     --image <figure.png> \
     --code <visualization.py> \
     --output <report.json>
   ```

3. 按 [quality-rubric.md](references/quality-rubric.md) 解读结果。
4. `valid=false` 时返回所有错误，不在第一个错误处停止。
5. 将可修复问题反馈给上游 Skill；不可擅自放宽最低质量阈值。

## 通过条件

- 图片可以被 Pillow 解码，格式为 PNG；
- 宽度至少 800 px，高度至少 500 px；
- 文件大于 1 KB，且不是接近全白或全黑；
- 可选 Python 文件能够通过语法编译；
- 所有 error 为空。warning 不阻塞，但必须展示。

## 输出要求

输出包含 `valid`、`score`、`checks`、`errors` 和 `warnings`。Score 用于回归比较，不替代 `valid`。

