# 真机冒烟清单

自动化测试用的是假 `claude`。下面这些步骤用真 Claude Code 和真 Codex 走一遍，确认整条链路可用。
每一步的"预期"都达成才算通过。

## 0. 准备

```bat
mkdir E:\bridge-smoke && cd E:\bridge-smoke
echo hello > readme.txt
bridge --version
```
预期：打印版本号。

## 1. init

```bat
bridge init --project E:\bridge-smoke
```
预期：`.bridge\` 下有 `config.json`、`notebook.jsonl`、`notebook.md`、`work\`；`AGENTS.md` 含 `<!-- bridge:start -->`。

## 2. watch（终端 A）

```bat
bridge watch --project E:\bridge-smoke
```
预期：先探测 `claude --version` 成功，然后打印 `[bridge] watching …`，不退出。

## 3. analyze 一轮（终端 B）

```bat
cd E:\bridge-smoke
bridge send --mode analyze "列出这个目录里有哪些文件，说明各自内容。"
bridge wait
```
预期：
- `send` 打印 `1`。
- 终端 A 出现 `#1 → claude (analyze) 开始` 和 `完成`。
- `wait` 打印三段式总结并退出码 0，末尾有 `详情：.bridge/work/0001-claude.md`。
- `bridge status` 显示 `session:` 不为 `-`。

## 4. execute 一轮

```bat
bridge send --mode execute "在当前目录创建 hello.txt，内容写 hi，然后用命令确认文件存在。"
bridge wait
```
预期：`hello.txt` 真的被创建；总结里【做了什么】提到创建文件。这一步验证 `acceptEdits` 在非交互下可写文件、`Bash` 被放行。

## 5. 人工插话

```bat
bridge note "以后回复请用中文。"
bridge send --mode analyze "readme.txt 里写了什么？"
bridge wait
```
预期：回复为中文，说明 note 被一并喂给了 Claude。

## 6. Codex 主导

终端 B 里启动 `codex`，对它说：
> 让 Claude 检查一下这个目录的结构并告诉我它的建议。

预期：Codex 自己调用 `bridge send` 和 `bridge wait`（沙箱首次可能要你批准），然后基于返回的总结回答你。

## 7. 中断恢复

在 Claude 正在跑的时候（终端 A 显示 `开始` 但还没 `完成`），按 Ctrl+C 关掉 watcher，再重新 `bridge watch`。
预期：笔记本里出现一条 `system`：`watcher 重启：#N 上次未完成，将重跑。`，随后该指示被重跑并产生 report。

## 8. watcher 未运行

关掉终端 A，然后：
```bat
bridge send "ping"
bridge wait --timeout 60
```
预期：约 30 秒后 `wait` 打印 `watcher 未运行…`，退出码 3。
