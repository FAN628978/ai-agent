# 项目说明与进展

## 项目概览

本项目目标是实现一个面向生产级场景的 Python AI Agent Runtime。

当前设计参考 Claude Code、Codex、Cursor Agent 等现代 Agent 产品的公开设计思想，核心形态是：

```text
用户请求 -> 上下文组装 -> Planner 生成计划 -> Executor 执行工具 -> Reasoner/Reflector 判断下一步 -> 输出响应 -> 写回 Session
```

当前项目已经从“最小工程骨架”推进到“可运行的单 Agent Runtime 原型”阶段。代码中已经具备 Runtime 主循环、OpenAI-compatible MiniMax 接入、工具系统、结构化 ToolCall、Prompt / Context / Skills 注入、AgentReasoner、内存 Session、内存 Checkpoint、JSONL 事件日志和 CLI 对话入口。

当前还没有完成：审批后的继续执行、持久化 Session / Checkpoint、LLM Reflector、Executor 依赖排序和失败分类、多 Agent、MCP、Web UI。

## 重要文档

| 文件 | 说明 |
| --- | --- |
| `docs/README.md` | 文档索引和推荐阅读顺序 |
| `docs/codebase-guide.md` | 当前代码结构、运行链路、模块职责和扩展点 |
| `docs/architecture.md` | 完整架构设计方案，包含部分尚未实现的目标设计 |
| `docs/development-plan.md` | 分阶段开发计划，偏长期路线 |
| `docs/next-development.md` | 下一步开发建议：审批续跑、持久化 Session 与 LLM Reflector |
| `docs/project-status.md` | 当前项目状态和交接说明，供后续 Agent 快速接手 |
| `README.md` | 项目简介、安装方式、CLI 使用方式 |
| `AGENTS.md` | 开发偏好、代码修改原则、后续 agent 接手规则 |

## 当前目录结构

```text
.
├── README.md
├── AGENTS.md
├── configs/
│   └── default.yaml
├── docs/
│   ├── README.md
│   ├── architecture.md
│   ├── development-plan.md
│   ├── next-development.md
│   ├── codebase-guide.md
│   └── project-status.md
├── pyproject.toml
├── src/
│   └── agent_system/
│       ├── __init__.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── planner.py
│       │   ├── reasoner.py
│       │   └── reflector.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── cli.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   └── models.py
│       ├── context/
│       │   ├── __init__.py
│       │   ├── assembler.py
│       │   └── budget.py
│       ├── execution/
│       │   ├── __init__.py
│       │   └── executor.py
│       ├── llm/
│       │   ├── __init__.py
│       │   └── client.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── events.py
│       │   ├── planning.py
│       │   ├── request.py
│       │   ├── runtime.py
│       │   └── tools.py
│       ├── observability/
│       │   ├── __init__.py
│       │   └── logging.py
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   └── templates/
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── checkpoint.py
│       │   ├── factory.py
│       │   ├── loop.py
│       │   └── session.py
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── builtin.py
│       │   ├── registry.py
│       │   └── schemas.py
│       └── tools/
│           ├── __init__.py
│           ├── base.py
│           ├── registry.py
│           ├── router.py
│           ├── schemas.py
│           └── builtin/
│               ├── __init__.py
│               ├── file.py
│               ├── glob.py
│               ├── grep.py
│               └── shell.py
└── tests/
    ├── test_import.py
    ├── integration/
    └── unit/
```

## 当前已完成能力

### Phase 0：项目初始化

状态：已完成。

已交付：

- `pyproject.toml`
- `README.md`
- `configs/default.yaml`
- `src/agent_system/__init__.py`
- `tests/test_import.py`
- `.gitignore`

影响范围：

- 项目具备标准 Python 包结构。
- CLI 入口通过 `pyproject.toml` 暴露为 `agent-system`。
- 可使用 `pytest` 或 `uv run pytest` 执行测试。

### Phase 1：核心数据模型

状态：已完成。

已实现模型：

- `RunMode`
- `UserRequest`
- `Step`
- `Plan`
- `ToolCall`
- `ToolResult`
- `Critique`
- `AgentState`
- `AgentEvent`

关键说明：

- `RunMode` 当前支持 `ask`、`plan`、`act`、`review`、`background`。
- `Step` 已包含 `depends_on`，但 Executor 还没有真正做依赖排序。
- `ToolCall` 已包含 `requires_approval` 和 `approved`，但审批后的继续执行闭环还未完成。

### Phase 2：Runtime 主循环

状态：已完成第一版。

已交付：

- `src/agent_system/runtime/loop.py`
- `src/agent_system/runtime/checkpoint.py`
- `src/agent_system/runtime/factory.py`
- `src/agent_system/agents/planner.py`
- `src/agent_system/agents/reasoner.py`
- `src/agent_system/agents/reflector.py`
- `src/agent_system/execution/executor.py`

已实现：

- `AgentRuntime`
- LLM 驱动 `PlannerAgent`
- Planner 失败后的保守规则兜底
- 顺序执行版 `Executor`
- 简化规则版 `Reflector`
- 观察后决策的 `AgentReasoner`
- 内存版 `InMemoryCheckpointStore`
- 执行结果模型 `StepResult` 和 `ExecutionResult`

Runtime 当前事件流包括：

- `run.started`
- `plan.created`
- `run.waiting_for_approval`
- `execution.completed`
- `run.waiting_for_tool_approval`
- `reasoning.completed`
- `answer.created`
- `reflection.completed`
- `run.completed`
- `run.needs_user_input`
- `run.stopped`

关键说明：

- ACT 模式会执行 plan。
- PLAN 模式会在 `plan.created` 后输出 `run.waiting_for_approval` 并停止。
- Runtime 会读取 session，并把 `session.context_summary()` 传给 Planner / Reasoner。
- Runtime 在完成、停止、需要用户输入、等待审批等路径会写回 session。
- 如果配置了 `reasoner`，Runtime 会优先通过 Reasoner 根据工具观察继续决策或生成最终回答。
- 如果没有 Reasoner，则使用 Reflector 判断是否完成。

### ChatGPT 式 CLI

状态：已完成第一版。

已交付：

- `src/agent_system/api/cli.py`
- `pyproject.toml` 中的 `agent-system` 命令入口

已支持命令：

- `agent-system run "任务内容"`
- `agent-system plan "任务内容"`
- `agent-system runtime-chat`

当前 `runtime-chat` 支持斜杠命令：

- `/help`
- `/clear`
- `/tools`
- `/exit`
- `/quit`

说明：

- `runtime-chat` 每轮都会创建 `UserRequest` 并调用 `AgentRuntime`。
- `runtime-chat` 使用固定 `session_id`，Runtime 内部可以保存多轮 session 状态。
- CLI 仍维护一份本地 `history`，用于最终回复合成。
- 目前没有 `/approve`、`/deny`、`/resume`。

### 本地 MiniMax / OpenAI-compatible 接入

状态：已接入默认配置和 Runtime 工厂。

默认服务：

```text
http://localhost:8500
```

默认模型：

```text
MiniMax-M2.5
```

已实现：

- `OpenAICompatibleClient.list_models()` 调用 `/v1/models`。
- `OpenAICompatibleClient.chat()` 调用 `/v1/chat/completions`。
- 支持传入原生 OpenAI-compatible `tools` 字段。
- 支持读取 `message.tool_calls`。

默认配置重点：

```yaml
model:
  provider: openai-compatible
  base_url: http://localhost:8500
  chat: MiniMax-M2.5
  planner: MiniMax-M2.5
  executor: MiniMax-M2.5
  reflector: MiniMax-M2.5
  timeout_s: 30
  max_tokens: 100000
  temperature: 0.7
```

注意：`reflector` 模型字段已存在于配置，但当前 `Reflector` 还没有使用 LLM。

### Phase 3：工具系统

状态：已完成第一版。

已交付：

- `src/agent_system/tools/base.py`
- `src/agent_system/tools/schemas.py`
- `src/agent_system/tools/registry.py`
- `src/agent_system/tools/router.py`
- `src/agent_system/tools/builtin/file.py`
- `src/agent_system/tools/builtin/grep.py`
- `src/agent_system/tools/builtin/glob.py`
- `src/agent_system/tools/builtin/shell.py`

已实现：

- `BaseTool`
- `ToolSchema`
- `ToolPermission`
- `ToolPermissionPolicy`
- `ToolPermissionDecision`
- `ToolRegistry`
- `ToolRouter`
- `Workspace`
- `ToolContext`
- `Read`
- `Write`
- `Edit`
- `Grep`
- `Glob`
- `Bash`

影响范围：

- 工具可以注册、查询和调用。
- 工具统一返回 `ToolResult`。
- 工具名会做常见别名归一化。
- 工具输入会根据 schema required 字段做基础校验。
- 未知工具会返回可观察错误，并附带 available_tools / tool_definitions，方便 Reasoner 修复。
- 输入校验失败会返回 required_args / input_schema，方便 Reasoner 修复。
- 权限检查已经接入 `ToolRouter`。
- 需要审批时会返回 `approval_required` 工具结果。
- 审计 metadata 已包含 call_id、tool、arguments_summary、status 和 permission decision。

### 文件与 Shell 权限现状

当前 `configs/default.yaml` 中：

```yaml
permissions:
  default_shell: allow
  workspace_write: allow
  network: allow
  destructive_commands: allow
```

这意味着默认开发配置偏开放。

工具实际行为：

- `Read`：可读取 workspace 内相对路径；绝对路径 / `~` 路径允许在 workspace 或 home read roots 下读取。
- `Write` / `Edit`：只能写 workspace 内路径，防止写出 workspace。
- `Grep`：在 UTF-8 文本文件中正则搜索。
- `Glob`：按路径模式列出文件或目录。
- `Bash`：在 workspace 下执行 shell 命令；如果 `default_shell=allow` 且命令不触发 destructive 策略，则可以直接执行。

安全提醒：

- 当前默认配置适合本地快速开发，不适合直接作为生产安全默认值。
- 后续建议把高风险权限切换为 `ask` 或 `deny`，并完善审批续跑。

### Session 基础能力

状态：已完成第一版。

已交付：

- `src/agent_system/runtime/session.py`
- `SessionRecord`
- `InMemorySessionStore`

`SessionRecord` 当前保存：

- `session_id`
- `messages`
- `recent_events`
- `recent_tool_results`
- `recent_plan`
- `summary`

已实现方法：

- `context_summary()`
- `record_run()`

当前限制：

- 仅内存存储。
- 进程退出后 session 丢失。
- 没有 pending approval 持久化。
- 没有 SQLite / Postgres 实现。
- 没有向量记忆。

### Observability

状态：已完成第一版。

已交付：

- `src/agent_system/observability/logging.py`
- `JsonlEventLogger`

默认日志：

```text
logs/agent-system.jsonl
```

当前记录：

- event_type
- timestamp
- session_id
- task_id
- user_id
- workspace_id
- plan 摘要
- execution 摘要
- reflection 摘要

当前限制：

- 不记录完整 `tool_results`。
- 没有日志轮转。
- 没有 trace 查询。
- 没有 replay。
- 没有 OpenTelemetry / metrics。

## 当前主要不足

### 1. 审批后继续执行未完成

当前已经能返回：

```text
run.waiting_for_tool_approval
```

但缺少：

- pending approval 数据模型。
- `/approve <call_id>`。
- `/deny <call_id>`。
- `/resume <task_id>`。
- 审批后把原 ToolCall 设置为 `approved=True` 并继续执行。

### 2. Session / Checkpoint 未持久化

当前只有：

- `InMemorySessionStore`
- `InMemoryCheckpointStore`

缺少：

- `SQLiteSessionStore`
- `SQLiteCheckpointStore`
- task 查询
- 进程重启恢复

### 3. Reflector 仍是规则版

当前 Reflector 只根据 step 是否完成判断 done / not done。

缺少：

- LLM Reflector。
- 对空结果、错误结果、部分完成结果的语义判断。
- retry / replan / ask_user 的智能判断。

### 4. Executor 仍偏简单

当前 Executor：

- 顺序执行 steps。
- 优先执行 `step.tool_calls`。
- 没有 `tool_calls` 时尝试从 `suggested_tools` 推断参数。
- 没有可执行工具时 step 失败。

缺少：

- `depends_on` 依赖排序。
- blocked step。
- 失败分类。
- 自动重试。
- DAG 并发。

### 5. MCP / 多 Agent / Web UI 未实现

这些属于后续扩展，建议在单 Agent 闭环稳定后再进入。

## 建议下一步

优先顺序：

1. 工具审批后的继续执行。
2. SQLite SessionStore / CheckpointStore。
3. LLM Reflector。
4. Executor 依赖排序、失败分类和重试策略。
5. 可观测查询、task 查询和 replay。
6. MCP / 插件化工具。
7. 多 Agent / Supervisor。
8. Web UI / Streaming。

详细路线见 `docs/next-development.md`。

## 交接给后续 Agent 的建议

后续接手时建议先做：

```text
1. 阅读 docs/project-status.md 和 docs/codebase-guide.md。
2. 跑 uv run pytest。
3. 跑 uv run agent-system --help。
4. 确认 configs/default.yaml 的权限是否符合当前开发目标。
5. 不要重复实现 SessionRecord / InMemorySessionStore。
6. 优先实现审批续跑，而不是直接进入多 Agent 或 Web UI。
```

修改代码时优先保证：

- 现有 CLI 不回退。
- 现有 Runtime 事件流不随意破坏。
- `ToolCall` / `ToolResult` 协议保持兼容。
- `Critique` 协议保持兼容。
- 新能力先补测试，再改实现。
