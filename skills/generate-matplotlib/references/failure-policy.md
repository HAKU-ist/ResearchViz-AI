# 代码执行失败策略

## 次数定义

最多执行 3 次，包含第一次执行：

```text
attempt 1：原始 Visualization Spec
attempt 2：第一次修复后的 Spec
attempt 3：第二次修复后的 Spec
```

第 3 次失败后设置 `terminal_reason=MAX_ATTEMPTS_REACHED`，禁止执行第 4 次。

## 错误分类

- `RETRYABLE`：类型转换、聚合结果形状、绘图参数或布局错误。生成修复 Prompt，并要求模型只返回新 Spec。
- `NON_RETRYABLE`：输入 CSV 不存在、引用列不存在、安全检查失败、依赖缺失或文件损坏。立即终止。
- `TRANSIENT`：模型限流、Worker 或存储临时故障。交给基础设施重试，不计入代码执行次数。

## 修复 Prompt 输入

只提供：原始请求、当前 Spec、数据画像摘要、错误类型、脱敏错误和已用次数。不要提供服务器绝对路径、密钥或完整堆栈。

## 提前终止

计算错误 fingerprint：错误类型、规范化消息与 Spec hash 的组合。相同 fingerprint 连续出现两次，说明修复没有产生有效变化，应提前终止。

不得在 Spec 和代码都没有变化时重新执行。
