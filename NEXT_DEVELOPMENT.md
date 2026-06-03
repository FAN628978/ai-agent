# 下一步开发建议：Runtime 多轮任务状态

## 目标

让 Runtime 对话具备真正的多轮任务状态。

当前 `agent-system runtime-chat` 已经可以像对话一样使用，但每一轮本质上还是重新跑一次 Runtime，只是 CLI 把历史拼进用户输入。下一步应把多轮状态下沉到 Runtime 层，让 Runtime 自己持有 session 状态。

目标形态：

```text
同一个 session_id 下：
保留历史摘要 -> 保留上轮 plan/tool_results -> 支持继续追问 -> 支持任务恢复
```

## 背景

当前已具备：

- `AgentRuntime`
- `PlannerAgent`
- `Executor`
- `Reflector`
- `ToolRouter`
- `runtime-chat`
- Prompt Registry
- ContextAssembler
- 结构化 `ToolCall`
- Skills 模块

当前不足：

- Runtime 不保存长期 session 状态。
- `runtime-chat` 的多轮上下文主要由 CLI 拼接。
- 后续追问无法自然引用上轮 tool results。
- 任务恢复、继续执行、历史摘要还没有统一存储。

## 建议实现内容

### 1. 新增 Session Store

建议新增：

```text
src/agent_system/runtime/session.py
```

建议实现：

- `SessionRecord`
- `InMemorySessionStore`

建议保存内容：

- `session_id`
- 历史 user / assistant 消息
- 最近 events
- 最近 tool_results
- 最近 plan
- 最近 summary

示例结构：

```python
class SessionRecord(BaseModel):
    session_id: str
    messages: list[dict[str, str]] = Field(default_factory=list)
    recent_events: list[AgentEvent] = Field(default_factory=list)
    recent_tool_results: list[ToolResult] = Field(default_factory=list)
    recent_plan: Plan | None = None
    summary: str = ""
```

### 2. Runtime 使用 Session

让 `AgentRuntime.run()`：

- 根据 `request.session_id` 读取 session。
- 执行前将 session summary 交给 Context 层。
- 执行完成后写回 session。
- 保存本轮 events、tool_results、plan。

建议保持第一版为内存实现：

```python
class InMemorySessionStore:
    async def get(self, session_id: str) -> SessionRecord
    async def save(self, session: SessionRecord) -> None
```

### 3. ContextAssembler 接入 Session Summary

把现在 CLI 拼接历史的逻辑迁移到 Runtime / Context 层。

建议在 Planner context 中注入：

```text
Conversation summary:
- 用户之前问过什么
- 上次执行了哪些工具
- 上次工具结果摘要是什么
- 当前请求是什么
```

这样 Planner 可以更稳定地处理继续追问。

### 4. 简化 runtime-chat

当前 `runtime-chat` 自己维护 history 并拼接到请求里。

改造后 CLI 只需要：

```text
输入用户内容 -> 创建 UserRequest(session_id=固定) -> 调用 Runtime -> 显示 Assistant 回复
```

历史维护由 Runtime / SessionStore 负责。

### 5. 测试

建议新增测试：

- 同一个 `session_id` 多轮对话会保存历史。
- 不同 `session_id` 状态隔离。
- Runtime 执行完成后写入 events。
- Runtime 执行完成后写入 tool_results。
- Runtime 执行完成后写入 recent plan。
- ContextAssembler 能注入 session summary。
- `runtime-chat` 不再手动拼 history 也能工作。

## 验收标准

- `AgentRuntime` 支持传入 session store。
- 同一 session 的历史可以被读取和更新。
- `runtime-chat` 多轮对话不再依赖 CLI 手动拼历史。
- Context 中能看到 session summary。
- 现有 CLI、工具执行和测试不回退。
- `uv run pytest` 通过。

## 非目标

第一版先不做：

- 持久化数据库。
- 向量记忆。
- 自动长期记忆。
- 多 Agent session 合并。
- 分布式 session store。

这些可以在内存版 session 模型稳定后再扩展。

## 后续扩展方向

内存版 Session Store 稳定后，可以继续扩展：

- SQLite / Postgres SessionStore。
- 会话摘要压缩。
- Tool result TTL。
- Checkpoint 与 Session 关联。
- 用户可执行 `resume task_id`。
- 多轮任务 fork。

## 后续大模块清单

当前主体闭环已经能跑，但完整 Agent Runtime 还缺以下大模块。建议优先保持单 Agent 主体稳定，再逐步扩展。

### 1. Runtime 多轮任务状态

状态：下一步优先开发。

目标：

- Runtime 自己持有 session 状态。
- 同一 `session_id` 支持继续追问和任务恢复。
- 保存历史摘要、最近 plan、最近 tool_results、最近 events。
- `runtime-chat` 不再依赖 CLI 手动拼接历史。

### 2. 权限审批与工具审计

状态：未完成。

目标：

- 将 `permissions.default_shell` 和 `ToolPermission` 检查接入 `ToolRouter`。
- 高风险工具返回审批需求事件，而不是直接执行。
- 增加工具调用审计记录，包括 call_id、tool name、arguments 摘要、结果状态。
- 保持 `shell.run` 默认禁用，启用需显式配置。

### 3. LLM 驱动的 Reflector / Executor

状态：未完成。

目标：

- Reflector 使用 LLM 检查执行结果、风险和是否完成。
- Executor 支持更明确的执行策略，而不是只依赖当前保守工具调用路径。
- LLM 输出不可解析时保留明确降级策略。

### 4. Memory 系统

状态：未完成。

目标：

- 会话摘要记忆。
- 用户偏好和项目规则记忆。
- 工具结果摘要记忆。
- 后续可扩展到 SQLite / Postgres / Vector Store。

### 5. 可观测与恢复

状态：未完成。

目标：

- 结构化日志。
- 持久化 Checkpoint。
- `task_id` / `trace_id` 查询。
- Replay 和失败恢复。
- 工具调用输入、输出摘要和错误信息可追踪。

### 6. MCP / 插件化工具

状态：未完成。

目标：

- MCP Client / Server 接入。
- 外部工具通过统一 schema 注册。
- 插件化工具加载机制。
- 工具命名空间隔离。

### 7. 多 Agent / Supervisor

状态：未完成。

目标：

- Supervisor 调度。
- 子 Agent 分工。
- 多 Agent 状态共享和隔离。
- 多 Agent 审查、执行、记忆写入协作。

### 8. Web UI / Streaming

状态：未完成。

目标：

- Web UI 或运行面板。
- WebSocket / SSE 事件流。
- 实时展示 plan、tool calls、tool results、reflection。
