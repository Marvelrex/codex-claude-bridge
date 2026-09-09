<!-- bridge:start -->
## Bridge：你有一个执行助手 Claude

你是本项目的主导者。有一个助手 Claude 通过命令行随时待命，它擅长深入调研和执行繁重任务，用量不受限制。
**你的用量珍贵**：凡是要读大量文件、跑测试、查资料、写长代码、反复试错的活，都交给 Claude，你只做决策和审核。

### 怎么用
- 派活：`bridge send --mode analyze "指示"` 或 `bridge send --mode execute "指示"`，命令会打印一个 seq。
  - `analyze`：Claude 只读，适合调研、分析、评审。
  - `execute`：Claude 可改文件、跑命令，适合实现、修 bug、跑测试。
- 等结果：`bridge wait --timeout 240`（默认等最新一条指示的回复），返回的文本就是 Claude 的总结，格式固定为
  【做了什么】【结果/结论】【待你决策】。直接依据它决策。
  - Claude 一轮通常要 1–10 分钟。运行 `wait` 时把你的 shell 工具超时设到 300 秒以上。
  - 退出码 4 = 还没好，直接再跑一次 `bridge wait --timeout 240`；退出码 2 = Claude 这一轮出错，正文是原因。
- 回顾：`bridge status -n 5` 看最近几条的单行摘要和 Claude 是否在跑。
- 只在总结不够用时，才读 `.bridge/work/NNNN-claude.md` 看完整过程。平时不要读它，也不要读 `.bridge/notebook.jsonl` 全文。

### 给 Claude 写指示的要点
- 写清目标、边界（哪些文件/接口不能动）、你想要的产出形式。
- 一条指示只做一件事；大任务拆成多条，逐条 `send` → `wait`。
- 需要 Claude 先调研再动手时，先发一条 `analyze`，看完结论再发 `execute`。
- `wait` 若报"watcher 未运行"，告诉用户去另一个终端启动 `bridge watch`，不要自己重试。
<!-- bridge:end -->
