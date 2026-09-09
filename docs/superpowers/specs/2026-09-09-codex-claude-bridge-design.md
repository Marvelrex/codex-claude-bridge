# Codex ↔ Claude Bridge — 设计文档

日期：2026-09-09

## 目标

让 Codex CLI（主导）与 Claude Code（跟随）通过一个共享笔记本协作。Codex 用量珍贵，
只消费精炼总结；Claude 用量宽松，承担调研、执行等重活，并把过程压缩成短报告。

## 运行形态（方案 C）

- Codex：用户手里的交互式终端，通过 `bridge send` / `bridge wait` 与 Claude 对话。
- Claude：后台 `bridge watch` 监听笔记本，发现新指示即按 mode 启动 `claude -p`。
- 人：随时 `bridge note` 插话，或直接阅读 `notebook.md`。
- 通信单向：Codex → directive → Claude → report → Codex。Claude 不主动发指示。

## 目录结构

框架（`E:\AgentsCrossPlatformFramework`，Python 3.13 标准库，零依赖）：

```
bridge/
  __main__.py     # python -m bridge <子命令>
  cli.py          # init / watch / send / wait / note / status / reset
  notebook.py     # JSONL 追加读取 + Markdown 渲染 + seq 生成
  runner.py       # 封装 claude -p，解析 stream-json，生成 detail
  watcher.py      # 轮询循环、state 管理、心跳、中断恢复
  config.py       # 默认配置与加载
templates/
  AGENTS.snippet.md
  claude_system.md
tests/
scripts/smoke.md
bridge.cmd
README.md
```

项目工作区（`bridge init --project <dir>` 生成）：

```
<project>/.bridge/
  notebook.jsonl   # 唯一事实源，只追加
  notebook.md      # 每次追加后重渲染
  state.json       # session_id, last_processed, running_seq, heartbeat
  work/NNNN-claude.md
  config.json
<project>/AGENTS.md  # 追加 Codex 指令段（标记包裹，幂等）
```

## 消息格式（notebook.jsonl 每行）

```json
{"seq": 3, "ts": "2026-09-09T01:20:00", "from": "codex", "to": "claude",
 "kind": "directive", "mode": "execute", "body": "...", "reply_to": null,
 "detail": null, "status": "open"}
```

- `kind`: `directive` | `report` | `note` | `system`
- `mode`: `analyze` | `execute`（directive 缺省 `analyze`；report 复制 directive 的 mode）
- `status`: `open` | `done` | `error`
- `body` 上限 `config.max_body_chars`（默认 400），超出由 watcher 截断并附注。
- `detail`: 相对 `.bridge/` 的路径，仅 report 使用。

## 配置（config.json 默认值）

```json
{
  "max_body_chars": 400,
  "claude_timeout_sec": 1200,
  "poll_interval_sec": 1.0,
  "heartbeat_stale_sec": 30,
  "claude_bin": "claude",
  "analyze_args": ["--permission-mode", "plan"],
  "execute_args": ["--permission-mode", "acceptEdits",
                    "--allowedTools", "Edit,Write,Bash"],
  "claude_model": null
}
```

## 一轮流程

1. `send` 追加 directive（status open），打印 seq。
2. watcher 每 `poll_interval_sec` 刷新 heartbeat；比较 mtime，读取 seq > last_processed 的条目。
3. 若存在 `to == claude` 的 directive：收集 last_processed 之后的所有条目组成提示词
   （note 也一并送入），写 `running_seq`，启动 claude。
   - 首轮：`--append-system-prompt-file templates/claude_system.md`，并附项目路径。
   - 后续：`--resume <session_id>`。
   - 始终：`-p`, `--output-format stream-json`, `--verbose`, mode 对应参数。
4. runner 解析 stream：assistant 文本与 tool_use 渲染进 `work/NNNN-claude.md`；
   `result` 事件给出最终文本与 session_id。
5. watcher 追加 report（reply_to = directive.seq，body 截断，detail 路径），
   更新 state（session_id, last_processed = directive.seq, running_seq = null），
   重渲染 md，控制台 `\a` 提醒。
6. `wait` 轮询 notebook，发现 reply_to 匹配的 report 或 system(error) 即打印 body 退出。

## 权限模式

| mode | claude 参数 | 能力 |
|---|---|---|
| analyze | `--permission-mode plan` | 只读、搜索、联网 |
| execute | `--permission-mode acceptEdits --allowedTools Edit,Write,Bash` | 改文件、跑命令 |

## 报告格式（claude_system.md 要求）

最后一段回复固定三段式，总长不超过上限：
`【做了什么】…【结果/结论】…【待你决策】…`

## 错误处理

- JSONL 读取跳过残缺末行；写入一次性 write+flush。
- watcher 重启发现 `running_seq` 非空且无对应 report：追加 system 说明并重跑。
- 启动时探测 `claude --version`，失败即退出。
- `wait` 检查 heartbeat，超过 `heartbeat_stale_sec` 无更新则提示 watcher 未运行并退出（非零码）。
- Claude 超时：kill，追加 system(status error)，`wait` 返回。
- Claude 非零退出：stderr 前 20 行进 system 条目。
- 空输出或不含三段式：原样入库，另加 system 提醒。

## 测试

- notebook：追加/读取/残行/seq/渲染快照。
- runner：假 claude 脚本输出预录 stream-json；参数拼装、超时、解析、detail、截断。
- watcher：假 runner 跑一轮；state、report、恢复。
- cli：send → 模拟 report → wait；无心跳时 wait 退出。
- scripts/smoke.md：真机手工验证步骤。

## 不做

Claude 主动指示；多 Claude 并发；Web UI；Codex 侧自动化。
