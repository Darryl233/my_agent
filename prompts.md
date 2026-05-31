## 关键prompt

题目本身的描述非常清晰，包含可参考实现 pi-mono / pi-agent, 有明确的实现标准和约束，因此我对题目描述做一些简单的整理，将整理后的描述交给codex实现

```text
请你完成一个极简 Agent TUI 框架。

请你先简单调研一下 pi-mono / pi-agent 这类 terminal agent harness 的设计思路，然后实现一个极简版本：

用户在终端 TUI 中输入任务 → Agent 调用 DeepSeek API → 模型决定是否调用工具 → 本地工具执行 → observation 回灌给模型 → Agent 继续循环 → 输出结果 → 用户可以继续追问或发起新任务。

不要求实现 Memory、RAG、MCP、多 Agent、复杂权限系统或安全评测，只需要完成一个最小可运行框架。

基本要求
请实现：

一个可以调用 DeepSeek API 的 LLM client；
一个最小 Agent Loop，支持多轮 tool calling；
一个简单 Terminal TUI，支持多轮对话、用户输入、assistant 输出和工具执行过程展示；
当前会话内需要保留对话上下文，但不要求实现跨会话 Memory；
至少 2 个本地工具，由你自行设计和实现；
工具需要真实可用，不能只是 mock、固定返回或仅用于演示；
工具需要有清晰的调用 schema、参数校验、错误处理和 observation 返回；
一个简短的 README.md，说明如何运行、整体设计、工具设计、安全边界和当前不足；
TUI 不需要复杂，但应能让用户清楚看到：

用户输入；
assistant 回复；
agent loop 的执行步骤；
tool call；
tool observation；
当前轮最终结果。
示例运行方式可以类似：

python tui.py
进入 TUI 后可以进行多轮对话，例如：

User: 请分析当前项目，并给出一个简短总结。
Assistant: ...
User: 基于刚才的结果，指出最需要改进的地方。
Assistant: ...

我会重点检查
是否真的跑通了 DeepSeek API 调用；
是否实现了 LLM → tool call → tool execution → observation → LLM 的 Agent Loop；
是否支持当前会话内的多轮对话；
TUI 是否简单可用，能清楚展示中间执行过程；
工具是否具备实际可用性，而不是硬编码 demo；
工具 schema、参数校验和错误处理是否合理；
代码结构是否清晰；
README 是否能说明设计取舍和安全边界；

请使用python来实现。实现完成请补充关键功能的单元测试来验证功能是否正常。
```

## 对 AI 输出的判断与修改

我主要按以下标准审查和修正代码：

- 是否满足真实闭环：能正常理解上下文，且支持多轮对话。第一次 LLM 返回 tool call 后，必须把 assistant 的 `tool_calls` 和工具 `role=tool` observation 放回 `messages`，再请求第二次 LLM。
- 是否真实可用：工具必须真的读文件、列目录、搜索文本，而不是硬编码 demo。
- 是否有边界：禁止路径逃逸，拒绝过大/二进制文件，工具异常转为 observation。
- 是否容易展示：TUI 必须明确打印 `[agent] step`、`[tool call]`、`[observation]` 和最终 `Assistant`。

## 迭代过程中的关键 prompt

除了初始需求，试用 TUI 输出后，根据实际体验，持续用更具体的 prompt 约束 AI coding 工具。

### 1. 控制 observation 的展示粒度
观察到 TUI 把 `read_text_file` 的完整行内容直接打印出来，导致终端被大段 JSON 和源码刷屏。这个输出虽然对模型有用，但对用户没有必要。

```text
user prompt: read_text_file 的输出太冗余，不用输出读到的具体内容
```

修改方向：要求 AI 保留完整 observation 回灌给模型，但 TUI 只展示摘要。后续我又用类似反馈指出：


```text
user prompt: list files 工具也有一样的问题，请修改
```
最终形成的约束是：工具 observation 应该完整进入 agent context，但人类界面只显示简洁摘要，例如文件数、命中数、读取行数，而不是完整 JSON。


### 2. 改进 TUI 可读性和中文输入体验

```text
user prompt: TUI 对话的颜色只有纯白，难以区分 user、assistant、tool call、observation 和 error等信息，能优化一下吗
```

修改方向：用户体验角度发现纯白输出难以区分不同信息，要求 AI 增加角色化配色，但保持轻量 ANSI，不引入复杂 TUI 框架。

修改后发现新问题：

```text
user prompt: 用中文输入法和 TUI 交互的时候很奇怪，比如退格显示会有残留，且输入 agent 的内容和 terminal 显示不一致，排查原因并修复
```

修改方向：fallback 输入提示符保持纯文本，同时引入可选 `prompt_toolkit`，让支持 Unicode display width 的行编辑器处理中文输入。

### 3. 要求展示 agent 的关键决策过程
体验发现TUI的输出无效信息多，且看不到一些关键思考和决策

```text
user prompt: 现在的实现形式，每轮迭代 agent 的执行只能看到 calling DeepSeek...，我希望看到一些关键的中间思考过程和决策过程
```

修改方向：要求 AI 不伪造隐藏 chain-of-thought，而是展示可见的 progress note 和 harness 根据工具参数生成的 decision summary。随后我进一步收紧输出：

```text
[agent] step 1: calling DeepSeek...
[assistant note]
...
```

再进一步优化：

```text
user prompt: 这两部分的信息输出能合并到一起吗，每个 step 都输出 calling DeepSeek... 对用户来讲是个无效信息
```


最终输出被改成一行 `[step n] <可见说明>`，再接 `[tool call]` 和 `[decision]`。


### 4. 审查 LLM 失败路径并提出错误处理设计
观察到当前对LLM调用失败的处理比较简单粗暴，先让codex分析问题，并给出具体改进方案，按照方案执行修改

```text
user_promt: 当前的调用 llm 失败的处理方式很直接：
...
没有重试机制
错误信息直接透传
不区分错误类型
上下文被污染
...
可以怎么改进
LLM 调用失败
├── 可重试错误（429 限流、5xx 临时故障）
│   └── 指数退避重试 2-3 次，每次 yield 一个 "retrying" 事件让 UI 展示
├── 不可重试错误（400 参数错误、401/403 认证失败）
│   └── yield error + return，但附带友好提示
└── 网络超时 / 连接失败
    └── 可重试 1 次，然后 fallback 到 error
```

修改方向：要求 AI 把错误分类放到 LLM client，把重试策略放到 agent loop，并新增 `retrying` 事件和失败 turn 回滚。这个 prompt 不是泛泛要求“增强错误处理”，而是给出了分类、重试、UI 事件和上下文一致性的具体验收标准。


### 5. 增加会话持久化和生命周期管理

当前只支持进程内上下文，如果会话意外退出则无法恢复，使用体验比较差。需要能在退出后恢复历史消息。

```text
增加一个保存会话上下文功能，支持会话保存、删除、resume
```


### 6. 根据可扩展性重构工具目录

```text
把 tools 整理成一个目录，方便扩展
```

判断方式：单文件 `tools.py` 在 prototype 阶段可以接受，但后续增加写文件、运行测试、shell、网络等工具时会变得混乱。

修改方向：要求 AI 把工具拆成包结构：通用类型/校验、registry、具体 workspace 工具分离，同时保持外部 import `from agent_tui.tools import ToolRegistry` 不变，降低重构影响面。

### 7. 要求显式记录项目不足

```text
分析下当前项目的不足
```

以及：

```text
总结下当前项目的主要不足并更新到 README
```

判断方式：我把项目定位为面试题里的最小闭环，而不是完整产品。因此 README 需要诚实说明哪些是 deliberate trade-off，哪些是未来需要工程化的短板。

修改方向：要求 AI 从上下文治理、session 隐私、工具能力、schema 校验、agent 状态机、错误恢复、TUI、streaming/provider 抽象和测试层次等方面总结不足，并写入 README。


