<div align="right">

[English](README.md) | **简体中文**

</div>

# codex-claude-bridge

**让交互式 Codex CLI（主导）通过一个共享的追加式笔记本，指挥后台运行的 Claude Code（执行）。**

Codex 用量珍贵，所以它只读 Claude 的精炼总结；Claude 用量宽松，承担调研、改代码、跑测试等重活，长输出不进 Codex 的上下文。

```
你 ──对话──▶ codex（交互窗口）
                │  bridge send / bridge wait
                ▼
        <project>/.bridge/notebook.jsonl   ◀── 你随时 bridge note 插话
                ▲
                │  bridge watch（后台，自动调用 claude -p）
             claude
```

- **零依赖**：Python 3.12+ 标准库，一个 `bridge` 命令。
- **只追加的 JSONL 笔记本**：格式不会被两个模型互相改坏，另有自动渲染的 `notebook.md` 给人看。
- **每条指示可选权限**：`analyze` 只读，`execute` 可改文件跑命令。
- **Claude 跨轮记忆**：自动 `--resume`，不必每轮重喂历史。
- **省 Codex 用量**：Claude 的回复被限制为三段式短总结，完整过程另存文件，Codex 需要时才看。

## 环境要求

- Windows 10/11（主要测试平台），Python 3.12+（通过 `py` 启动器）
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI 与 [Codex CLI](https://github.com/openai/codex) 均已安装并登录

## 安装

```bat
git clone https://github.com/Marvelrex/codex-claude-bridge.git E:\codex-claude-bridge
```

然后让 `bridge` 命令在任何终端都可用，二选一：

1. **加 PATH**：把仓库目录加入用户 PATH，cmd / PowerShell 会直接找到 `bridge.cmd`。
   注意：已经打开的 Windows Terminal 需要整个关掉重开才能读到新 PATH。
2. **放一个 shim**：在任意已在 PATH 里的目录（例如 `%USERPROFILE%\.local\bin`）新建 `bridge.cmd`：
   ```bat
   @echo off
   setlocal
   set "PYTHONPATH=E:\codex-claude-bridge;%PYTHONPATH%"
   py -3 -m bridge %*
   ```

Git Bash 用户加一个别名：`alias bridge='/e/codex-claude-bridge/bridge.sh'`

验证：`bridge --version`

## 快速开始

```bat
:: 1. 初始化目标项目（生成 .bridge/，并把 Codex 指令注入项目的 AGENTS.md）
bridge init --project E:\MyProject

:: 2. 终端 A：启动 Claude 侧监听，放着不管
bridge watch --project E:\MyProject

:: 3. 终端 B：在项目目录启动 codex，像平常一样对它说任务
cd E:\MyProject
codex
```

Codex 读到 `AGENTS.md` 后，会自己在合适的时候调用 `bridge send` 派活、`bridge wait` 等结果。
你也可以直接对 Codex 说"这个让 Claude 去做，你只看结果"。首次执行 `bridge` 时 Codex 可能请求批准一次。

## 两种 mode

| mode | Claude 启动参数 | 能做什么 |
|---|---|---|
| `analyze`（默认） | `--permission-mode plan` | 只读：读文件、搜索、联网调研、分析 |
| `execute` | `--permission-mode acceptEdits --allowedTools Edit,Write,Bash` | 改文件、跑命令、跑测试 |

Codex 在每条指示上指定：`bridge send --mode execute "..."`。可在 `config.json` 里收窄 `execute_args`，
例如把 `Bash` 换成 `Bash(git:*),Bash(py:*)`。

## 子命令

| 命令 | 谁用 | 作用 |
|---|---|---|
| `bridge init --project <dir>` | 你 | 建 `.bridge/`，写默认 config，注入 AGENTS.md（幂等） |
| `bridge watch --project <dir>` | 你 | Claude 侧常驻监听 |
| `bridge send [--mode analyze\|execute] "..."` | Codex | 追加一条指示，打印 seq |
| `bridge wait [--seq N] [--timeout 秒]` | Codex | 阻塞直到回复出现，打印 Claude 的总结 |
| `bridge note "..."` | 你 | 人工插话，下一轮一并喂给 Claude |
| `bridge status [-n 5]` | 你 / Codex | 最近 n 条的单行摘要 + watcher 是否存活 |
| `bridge reset` | 你 | 清掉 Claude 的 session，让它下轮从头开始（笔记本保留） |

`send / wait / note / status / reset` 不带 `--project` 时以当前目录为项目根。

### `wait` 的退出码

| 码 | 含义 |
|---|---|
| 0 | 拿到正常 report |
| 1 | 没有可等待的指示 |
| 2 | Claude 这一轮出错（超时 / 进程失败），正文是错误说明 |
| 3 | watcher 没在运行（超过 `heartbeat_stale_sec` 无心跳） |
| 4 | 等待超过 `--timeout`，再跑一次 `wait` 即可继续等 |

## 工作区结构

```
<project>/.bridge/
  notebook.jsonl      # 唯一事实源，一行一条，只追加
  notebook.md         # 每次追加后自动渲染，给人看
  state.json          # Claude session_id、last_processed、running_seq、heartbeat
  work/0003-claude.md # 第 3 条指示的 Claude 完整过程（工具调用、中间思路、最终回复）
  config.json         # 见下
  claude_system.rendered.md  # 首轮注入给 Claude 的角色说明
<project>/AGENTS.md   # 含 <!-- bridge:start --> … <!-- bridge:end --> 段
```

建议把 `.bridge/` 加进目标项目的 `.gitignore`。

### 消息格式

```json
{"seq": 3, "ts": "2026-09-09T01:20:00", "from": "codex", "to": "claude",
 "kind": "directive", "mode": "execute", "body": "...", "reply_to": null,
 "detail": null, "status": "open"}
```

- `kind`：`directive`（Codex 指示）/ `report`（Claude 回复）/ `note`（人插话）/ `system`（框架事件）
- `status`：`open` / `done` / `error`
- Claude 的 `report.body` 固定三段式：`[What I did]`、`[Result]`、`[Decisions for you]`，超过
  `max_body_chars` 由 watcher 截断（优先保留 `[Decisions for you]` 段），全文永远在 `detail` 文件里。
- CLI 提示、Claude 的角色说明和注入 Codex 的 AGENTS 段均为英文。

### config.json

| 键 | 默认 | 说明 |
|---|---|---|
| `max_body_chars` | 600 | Claude 总结的字数上限 |
| `claude_timeout_sec` | 1200 | 单轮 Claude 最长运行时间 |
| `poll_interval_sec` | 1.0 | watcher 轮询间隔 |
| `heartbeat_stale_sec` | 30 | 超过此秒数无心跳视为 watcher 未运行 |
| `claude_bin` | `"claude"` | 可执行文件名或参数列表 |
| `analyze_args` / `execute_args` | 见上表 | 两种 mode 的 Claude 参数 |
| `claude_model` | null | 指定 `--model`，null 用 Claude Code 默认 |

## zh2en：给 agent 用的 DeepL 翻译

同一仓库里的独立命令，通过 [DeepL API](https://developers.deepl.com/docs/api-reference/translate) 把中文翻成英文。不依赖 `.bridge/` 工作区，任何 agent 在任何项目里都能调用。零依赖。

```bat
zh2en "把这段翻成英文"          :: 位置参数
echo 中文 | zh2en                :: stdin
zh2en -f notes.md                :: 文件
zh2en --to EN-GB --formality more "…"
zh2en --from auto "…"            :: 让 DeepL 自动识别源语言
```

- 译文以 UTF-8 打印到 stdout，错误信息走 stderr。
- Key：设置环境变量 `DEEPL_AUTH_KEY`，或用 `--key` 传入。以 `:fx` 结尾的 key 走 Free 接口，其他走 Pro。
- 输入里没有中文字符时原文直接输出、不调 API，agent 可以把所有文本都经它过一遍。`--force` 可强制翻译。
- 临时性错误（HTTP 429、500、529）带退避重试两次；403（key 无效）和 456（配额用完）不重试。

退出码：

| 码 | 含义 |
|---|---|
| 0 | 已翻译（或直通） |
| 1 | 没有输入 |
| 2 | 没有 API key |
| 3 | DeepL 拒绝了 key（403）或配额用完（456） |
| 4 | 网络错误或超时 |
| 5 | 其他 HTTP 错误，stderr 里有 DeepL 的原话 |

启用方式和 `bridge` 相同：仓库目录在 PATH 上就有 `zh2en.cmd`；Git Bash 用户给 `zh2en.sh` 加别名；或者在已在 PATH 的目录放一个 shim：

```bat
@echo off
setlocal
set "PYTHONPATH=E:\codex-claude-bridge;%PYTHONPATH%"
py -3 -m bridge.translate %*
```

## 设计取舍

- **通信单向**：只有 Codex → Claude 的指示和 Claude → Codex 的回复，Claude 不能反过来下指示，避免两个模型互相喊话死循环。
- **单 Claude 串行**：同一时间只跑一个 Claude，多条指示排队按顺序处理。
- **没有 Web UI**：`notebook.md` 就是界面。
- **Codex 侧不自动化**：Codex 始终是你手里的交互窗口，你随时能插手。

## 故障排查

- **`wait` 返回 3**：终端 A 的 `bridge watch` 没在跑，或被关掉了。重新启动即可，watcher 会自动重跑上次未完成的指示。
- **Claude 一直超时**：调大 `claude_timeout_sec`，或让 Codex 把指示拆小。
- **Claude 回复格式跑偏**：笔记本里会出现一条 `system` 提醒；可 `bridge reset` 清 session 让它重新读角色说明。
- **想看 Claude 到底干了什么**：打开 `.bridge/work/NNNN-claude.md`。
- **Codex 的 `wait` 被它自己的 shell 超时打断**：AGENTS 指令已让它用 `--timeout 240` 并在退出码 4 时重跑；仍有问题就调大 Codex 的 shell 工具超时。

## 开发

```bat
py -m unittest discover -s tests -v
```

测试用一个假的 `claude` 脚本（`tests/fake_claude.py`）模拟 stream-json 输出，不消耗真实用量。

- 设计文档：`docs/superpowers/specs/2026-09-09-codex-claude-bridge-design.md`
- 实现计划：`docs/superpowers/plans/2026-09-09-codex-claude-bridge.md`
- 真机冒烟清单：`scripts/smoke.md`

## License

MIT
