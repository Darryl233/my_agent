# Mini Agent TUI

一个极简 Python terminal agent harness：用户在终端输入任务，Agent 调用 DeepSeek Chat Completions，模型按需发起 tool calls，本地工具执行后把 observation 回灌给模型，直到得到最终回复。当前会话内保留多轮上下文。

## 运行

基础功能只使用 Python 标准库，可以直接运行。若需要更好的中文输入法、退格和光标体验，建议安装可选依赖 `prompt_toolkit`：

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY="sk-..."
python tui.py
```

不安装依赖也能运行，程序会退回标准库 `input()`；为了避免 ANSI prompt 干扰中文输入，fallback 模式下输入提示符保持纯文本。

可选环境变量：

```bash
export DEEPSEEK_MODEL="deepseek-v4-flash"      # 默认值
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_THINKING="disabled"            # 默认关闭 thinking，便于观察 tool loop
export DEEPSEEK_TIMEOUT="60"
export MINI_AGENT_SESSION_DIR=".mini_agent_sessions"
```

TUI 内置命令：

```text
/help    查看命令
/tools   查看工具
/session 查看当前会话
/sessions 列出已保存会话
/resume ID 恢复会话，支持唯一前缀
/new [name] 新建会话
/save    手动保存当前会话
/delete ID 删除指定会话，支持唯一前缀
/reset   清空当前会话上下文
/exit    退出
```

示例：

```text
> 请分析当前项目，并给出一个简短总结。
> 基于刚才的结果，指出最需要改进的地方。
```

## 整体设计

- `agent_tui/llm.py`：DeepSeek client，直接调用 OpenAI-compatible `/chat/completions`，传入 `messages`、`tools`、`tool_choice=auto`。
- `agent_tui/agent.py`：最小 Agent Loop。流程是 `user message -> LLM -> tool_calls -> local tools -> role=tool observation -> LLM -> final answer`，最多循环 8 步。
- `agent_tui/sessions.py`：JSON 会话存储。每个 session 一个文件，保存当前上下文、session id、名称、创建/更新时间和模型名。
- `agent_tui/tools/`：工具包。`base.py` 放通用 schema/校验/observation，`registry.py` 负责注册和执行，`workspace.py` 放当前 workspace 只读工具；后续新增工具时可以继续拆新模块。
- `agent_tui/ui.py` 和 `tui.py`：简单 ANSI TUI，展示用户输入、step note、tool decision、tool call、简洁 observation 摘要和最终回答。完整 observation 会回灌给模型，但 TUI 只显示一行摘要，避免终端被文件内容或文件列表刷屏。

## 会话保存与恢复

启动 TUI 时会自动创建一个新 session，并保存到 `.mini_agent_sessions/`。每轮成功得到最终回答后会自动保存当前上下文。

常用命令：

```text
/session          查看当前 session id、名称、更新时间和文件路径
/sessions         按更新时间列出保存过的 session
/resume abc123    恢复指定 session，支持唯一前缀
/new 调研任务      新建一个命名 session
/save             手动保存当前 session
/delete abc123    删除指定 session；如果删除当前 session，会自动新建空 session
/reset            清空当前 session 的上下文并保存
```

也可以启动时直接恢复：

```bash
python tui.py --resume abc123
python tui.py --name "project review"
python tui.py --session-dir /tmp/mini-agent-sessions
```

## LLM 错误处理

`llm.py` 会把 DeepSeek 调用失败分类成结构化 `LLMError`：

- `429`、`408`、`5xx`、网络错误、无效 JSON 等标记为可重试。
- `400`、`401`、`403`、缺少 API key 等标记为不可重试，并附带用户友好建议。

`agent.py` 对可重试错误做指数退避重试，默认初始等待 `0.5s`，最多重试 2 次。每次重试会向 TUI 发出 `retrying` 事件。最终失败时会回滚本轮新增的上下文，避免失败的用户消息或半截 tool observation 污染后续对话。

参考资料：

- Pi repo: https://github.com/earendil-works/pi
- DeepSeek Tool Calls: https://api-docs.deepseek.com/guides/tool_calls
- DeepSeek Chat Completion: https://api-docs.deepseek.com/api/create-chat-completion

## 工具设计

当前提供 3 个真实可用的本地工具：

- `list_files`：列出 workspace 内文件和目录，支持 `path`、`max_results`、`include_hidden`。
- `read_text_file`：读取 workspace 内 UTF-8 文本文件，支持 `start_line`、`max_lines`，返回行号。
- `search_text`：在 workspace 内搜索文本文件，支持 literal/regex、大小写开关和结果上限。

所有工具都有 JSON schema，并在执行前做本地校验。模型生成非法 JSON、缺少必填参数、越界路径、读取二进制/过大文件等情况都会返回结构化 observation，而不是中断 agent loop。

## 安全边界

这个 prototype 的工具是只读的，不提供 shell、写文件、删除文件或网络访问工具。所有路径都会 resolve 到当前启动目录内，`../` 逃逸会被拒绝。工具输出会限制行数、结果数和单文件大小，避免把过大的本地内容塞回模型上下文。

需要注意：用户输入、工具 observation 和读取到的文件内容会发送给 DeepSeek API，并会随 session JSON 落盘保存。不要在包含敏感代码或密钥的目录中运行，除非你确认这些内容可以发给外部模型服务并保存在本地会话文件中。默认 `.mini_agent_sessions/` 已加入 `.gitignore`。

## 当前不足

- **上下文治理较弱**：Agent 会把完整 `messages` 持续传给 LLM，也会把完整上下文保存到 session JSON。当前没有 token 预算、上下文压缩、摘要滚动窗口或过期策略，长会话会逐渐变大并增加成本。
- **session 缺少隐私保护**：会话文件会保存用户输入、assistant 回复、tool observation 和读到的文件片段。当前没有加密、脱敏、敏感信息扫描、按消息清理或最大文件大小限制。
- **工具能力仍是只读分析型**：目前只有 `list_files`、`read_text_file`、`search_text`。它能完成项目观察和总结，但还不是 coding agent；没有写文件、生成 patch、运行测试、执行 shell 或权限确认流程。
- **工具 schema 校验是轻量手写版**：能覆盖当前参数类型、默认值和简单边界，但不是完整 JSON Schema 实现；复杂嵌套、数组元素约束、`oneOf/anyOf`、`pattern` 等都未支持。
- **Agent loop 还不是显式状态机**：当前 loop 是清晰的 generator 流程，但 step、retry、tool execution、rollback 等状态没有独立建模。功能继续增加后，事件顺序和失败恢复会更难维护。
- **错误恢复策略有限**：LLM 可重试错误已有指数退避和上下文回滚，但 tool 失败只是作为 observation 回灌给模型。还没有重复失败抑制、工具参数自动修复策略、熔断或用户介入机制。
- **TUI 是轻量打印式界面**：当前基于 ANSI print 和可选 `prompt_toolkit` 输入，不是全屏 curses/Textual UI；没有可折叠 trace、可展开 observation、滚动面板、状态栏、快捷键或取消中的状态管理。
- **没有 streaming 和取消机制**：LLM 请求是非流式的，长回答需要等待完整响应；也没有 `/cancel`、请求超时中的交互状态或后台任务管理。
- **Provider 抽象还比较薄**：`Agent` 通过 protocol 隔离了 client，但 `llm.py` 仍是 DeepSeek 专用。接入 OpenAI、Anthropic 或本地模型时，还需要统一 message normalization、tool calling 差异和错误分类。
- **测试还偏单元级**：已有 agent loop、tools、session 和 LLM error 分类测试，但缺少 TUI 命令序列、session resume/delete 的端到端测试，以及真实 DeepSeek tool calling 的自动化 smoke test。

## 本地验证

```bash
python -m unittest
```

默认测试不会调用 DeepSeek API，只验证工具边界和 agent loop 的 observation 回灌。

如需执行真实 DeepSeek smoke test：

```bash
export DEEPSEEK_API_KEY="sk-..."
RUN_DEEPSEEK_LIVE=1 python -m unittest tests.test_deepseek_live
```
