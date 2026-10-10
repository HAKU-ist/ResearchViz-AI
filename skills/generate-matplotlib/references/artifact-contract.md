# Artifact 契约

生成目录必须包含：

- `visualization.py`：UTF-8 Python 源码；
- `figure.png`：非空 PNG 图片。

生成代码必须：

- 支持 `python visualization.py --input data.csv --output figure.png`；
- 对缺失列、清洗后空数据返回非零退出码；
- 关闭 figure，避免批量运行时内存泄漏；
- 不访问网络、环境密钥或 CSV 之外的输入文件。

