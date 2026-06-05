# 下一步开发建议：审批续跑、持久化 Session 与 LLM Reflector

> 状态更新：Runtime 多轮 session 基础能力已经完成，包括 `SessionRecord`、`InMemorySessionStore`、Runtime 写回 session、Context 注入 session summary，以及 `runtime-chat` 使用固定 `session_id` 调用 Runtime。文档已同步到当前代码状态，下一步重点是审批续跑、持久化 session、LLM Reflector 和可观测恢复。

## 当前阶段结论

项目当前已经不是单纯的工程骨架，而是具备可运行闭环的单 Agent Runtime 原型。

当前主体链路已经形成：

```text
用户请求 -> ContextAssembler -> PlannerAgent -> Executor -> ToolRouter -> Reasoner / Reflector -> AgentEvent -> SessionRecord
```

当前已具备：

- `AgentRuntime` 主循环。
- `PlannerAgent` 基于 OpenAI-compatible LLM 生成结构化计划，并保留保守规则兜底。
- `Executor` 顺序执行 `Plan.steps`。
- `ToolRouter` 统一路由工具调用。
- `Read`、`Write`、`Edit`、`Grep`、`Glob`、`Bash` 六个核心工具。
- `ToolCall` / `ToolResult` 结构化工具协议。
- 工具名别名归一化和参数归一化。
- 工具输入校验、权限检查、审批请求和审计 metadata。
- `SessionRecord` 与 `InMemorySessionStore`。
- Runtime 读取 session、注入 session summary、执行后写回 session。
- `AgentReasoner` 根据 plan、session context 和 tool observations 决定下一步动作。
- `JsonlEventLogger` 记录 Runtime 事件摘要。
- `runtime-chat` 使用固定 `session_id` 进入多轮 Runtime 调用。

## 已完成的 Session 能力

内存版 Session Store 已经完成第一版，不再作为下一步新增目标。

已完成内容：

- `src/agent_system/runtime/session.py`
- `SessionRecord`
- `InMemorySessionStore`
- `messages`
- `recent_events`
- `recent_tool_results`
- `recent_plan`
- `summary`
- `context_summary()`
- `record_run()`

Runtime 已经在执行开始时读取 session：

```text
session = await self.session_store.get(request.session_id)
```

Planner / Reasoner 已经可以接收 session summary：

```text
session_context=session.context_summary()
```

Runtime 在结束、等待审批、需要用户输入、停止等路径上会写回 session。

因此，下一步不应该重复实现内存版 Session，而应该围绕“恢复、持久化、审批续跑、反思判断”继续开发。

## 当前权限现状

当前 `configs/default.yaml` 为本地开发便利，权限配置较开放：

```yaml
permissions:
  default_shell: allow
  workspace_write: allow
  network: allow
  destructive_commands: allow
```

这意味着：

- `Bash` 默认启用。
- 普通 shell 命令在默认配置下可以直接执行。
- workspace 写入在默认配置下可以直接执行。
- destructive command 当前也配置为 `allow`。

虽然 `ToolRouter` 已支持 `ask` / `deny` 策略，并且能产生 `run.waiting_for_tool_approval`，但默认配置本身偏开放。因此后续做审批续跑时，应同时补充更安全的推荐配置，例如：

```yaml
permissions:
  default_shell: ask
  workspace_write: ask
  network: deny
  destructive_commands: ask
```

## 当前主要不足

### 1. 审批后不能自然继续执行

当前 Runtime 能返回：

```text
run.waiting_for_tool_approval
```

但还缺少完整的 approve / deny 后续跑闭环。

当前效果更接近：

```text
发现需要审批 -> 停止并返回事件
```

目标效果应该是：

```text
发现需要审批 -> 保存 pending tool calls -> 用户 approve / deny -> Runtime resume -> 继续执行原任务
```

### 2. Session 仍是内存版

`InMemorySessionStore` 只能在当前进程内保存状态。进程退出后：

- 对话历史丢失。
- 最近 plan 丢失。
- 最近 tool_results 丢失。
- pending approval 无法恢复。
- task_id 无法查询或 resume。

### 3. Reflector 仍偏规则化

当前 Reflector 主要根据 step 是否成功判断 done / not done。后续应让 LLM Reflector 判断：

- 工具成功是否真的满足用户目标。
- 工具结果是否为空或证据不足。
- 是否需要 retry、replan、ask_user。
- 是否可以给出 partial answer。

### 4. Executor 缺少更细的执行策略

当前 Executor 仍以顺序执行为主，后续需要补充：

- `depends_on` 依赖排序。
- blocked step 判断。
- 失败分类。
- 重试策略。
- 更清晰的 execution status。

### 5. 可观测与恢复能力还不够

当前已有 JSONL 日志，但还缺少：

- `trace_id`。
- `task_id` 查询。
- checkpoint 持久化。
- replay。
- 工具调用级审计查询。

## 下一步优先级

建议优先保持单 Agent 主体稳定，不要马上进入多 Agent、Web UI 或大规模 MCP 集成。

推荐顺序：

```text
P0：文档同步和状态确认
P1：工具审批后的继续执行
P2：SQLite SessionStore / CheckpointStore
P3：LLM Reflector
P4：Executor 稳定性增强
P5：可观测与恢复
P6：MCP / 插件化工具
P7：多 Agent / Supervisor
P8：Web UI / Streaming
```

## P0：文档同步和状态确认

状态：已完成第一轮同步。

已同步：

- `README.md`
- `docs/README.md`
- `docs/project-status.md`
- `docs/codebase-guide.md`
- `docs/next-development.md`

同步重点：

- 文档不再把 `SessionRecord` / `InMemorySessionStore` 描述为未实现。
- 文档明确 Planner 有规则兜底。
- 文档明确 Reasoner 已经接入 Runtime 工厂。
- 文档明确 ToolRouter 权限检查和审批事件已经接入。
- 文档明确当前默认权限为 `allow`，不再误写为 Bash 默认禁用或默认 deny。

后续如果继续改代码，应同步更新上述文档。

## P1：工具审批后的继续执行

状态：下一步最高优先级。

目标：

让高风险工具调用具备完整的人类审批闭环。

目标链路：

```text
ToolRouter 返回 approval_required
AgentRuntime 输出 run.waiting_for_tool_approval
Session 保存 pending approval
用户输入 /approve <call_id> 或 /deny <call_id>
Runtime 恢复原 task
被批准的 ToolCall 设置 approved=True
Executor 继续执行
Session 写回最终结果
```

建议新增字段：

```python
class PendingToolApproval(BaseModel):
    call_id: str
    task_id: str
    tool: str
    arguments: dict[str, object]
    arguments_summary: dict[str, object]
    reason: str | None = None
    status: Literal["pending", "approved", "denied"] = "pending"
```

建议 `SessionRecord` 增加：

```python
pending_tool_approvals: list[PendingToolApproval] = Field(default_factory=list)
```

建议 CLI 增加命令：

```text
/approve <call_id>
/deny <call_id>
/approvals
/resume <task_id>
```

建议测试：

- 需要审批的工具调用会写入 pending approval。
- `/approve` 后工具调用能继续执行。
- `/deny` 后 Runtime 返回明确拒绝结果。
- 不同 session 的 pending approval 隔离。
- 审批后的 tool audit metadata 保留。

验收标准：

- `run.waiting_for_tool_approval` 不再是终点，而是可恢复中间状态。
- 把 `permissions.default_shell=ask`、`workspace_write=ask` 等场景纳入测试。
- 所有审批动作可审计。

## P2：SQLite SessionStore / CheckpointStore

状态：未完成。

目标：

把当前内存态 session 和 checkpoint 持久化到本地 SQLite，支持进程重启后的任务恢复。

建议新增：

```text
src/agent_system/runtime/session_store.py
src/agent_system/runtime/sqlite_store.py
```

建议保留接口：

```python
class SessionStore(Protocol):
    async def get(self, session_id: str) -> SessionRecord: ...
    async def save(self, session: SessionRecord) -> None: ...
```

建议 SQLite 表：

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE checkpoints (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

配置建议：

```yaml
runtime:
  session_store:
    type: sqlite
    path: .agent/sessions.db
```

验收标准：

- 进程重启后同一 `session_id` 能恢复 summary、recent plan、recent tool_results。
- pending approval 不丢失。
- checkpoint 可通过 `task_id` 查询。
- 默认测试仍可使用内存 store。

## P3：LLM Reflector

状态：未完成。

目标：

将 Reflector 从规则判断升级为 LLM 驱动判断，同时保留规则兜底。

建议结构：

```text
Reflector
├── RuleBasedReflector
└── LLMReflector
```

LLM Reflector 输入：

- 用户目标。
- 当前 plan。
- step results。
- tool results 摘要。
- session summary。
- 风险信息。

LLM Reflector 输出仍保持现有 `Critique` 协议：

```text
done
confidence
issues
next_action
```

重点判断：

- 工具是否真的完成目标。
- 是否需要补充读取文件或搜索证据。
- 是否需要重新规划。
- 是否需要询问用户。
- 是否可以输出部分完成结果。

验收标准：

- LLM 输出合法时使用 LLM Critique。
- LLM 输出不可解析时降级到规则 Reflector。
- 不破坏现有 `AgentRuntime.run()` 主循环。

## P4：Executor 稳定性增强

状态：未完成。

目标：

让 Executor 从“顺序执行工具调用”升级为“可解释、可恢复、可重试”的执行器。

建议实现：

### 1. `depends_on` 依赖排序

规则：

- 无依赖 step 先执行。
- 依赖未完成则当前 step 标记为 `blocked`。
- 依赖失败则当前 step 不执行。
- 循环依赖标记为 `plan_invalid`。

### 2. 失败分类

建议分类：

```text
validation_failed
unknown_tool
permission_denied
approval_required
execution_failed
empty_result
blocked
```

### 3. 重试策略

建议配置：

```yaml
runtime:
  max_tool_retries: 2
  max_reasoning_iterations: 5
```

验收标准：

- Executor 输出能区分失败类型。
- Reasoner 能根据失败类型修复下一步动作。
- 不会因为模型反复生成错误工具调用而无限循环。

## P5：可观测与恢复

状态：未完成。

目标：

让每次 Agent 运行可以被查询、审计和复现。

建议实现：

- `trace_id`。
- `task_id` 查询命令。
- 工具调用审计日志。
- checkpoint 持久化。
- 最近一次运行 replay。
- JSONL 日志轮转。

建议 CLI：

```text
agent-system tasks
agent-system task <task_id>
agent-system logs --tail 50
agent-system replay <task_id>
```

验收标准：

- 能根据 `task_id` 查到 plan、events、tool_results、critique。
- 能看到每个工具调用的参数摘要、权限决策、执行状态。
- 出错时能快速定位是 Planner、ToolRouter、Executor、Reasoner 还是 Reflector 的问题。

## P6：MCP / 插件化工具

状态：后续扩展。

目标：

让外部工具通过统一 schema 接入 Runtime。

建议在单 Agent 闭环稳定后再做：

- MCP Client。
- MCP Server。
- 外部工具注册。
- 工具命名空间隔离。
- 插件加载配置。

验收标准：

- 外部工具能转换为当前 `ToolSchema`。
- 外部工具能通过 `ToolRouter` 调用。
- 外部工具权限仍走统一审批机制。

## P7：多 Agent / Supervisor

状态：后续扩展。

目标：

在单 Agent Runtime 稳定后，增加 Supervisor 调度多个子 Agent。

建议暂缓原因：

- 当前单 Agent 审批、恢复、持久化还未完全稳定。
- 过早进入多 Agent 会放大状态管理复杂度。
- 多 Agent 需要更强的 session、memory、trace 和权限隔离基础。

后续目标：

- Supervisor 调度。
- 子 Agent 分工。
- 多 Agent 状态共享和隔离。
- 多 Agent 审查、执行、记忆写入协作。

## P8：Web UI / Streaming

状态：后续扩展。

目标：

为 Runtime 增加可视化运行面板和实时事件流。

建议能力：

- Web UI。
- WebSocket / SSE 事件流。
- 实时展示 plan。
- 实时展示 tool calls。
- 实时展示 tool results。
- 实时展示 reflection。
- 审批按钮。

建议在 P1 到 P5 稳定后再做。

## 建议立即创建的任务

### Task 1：实现工具审批续跑

```text
实现 pending_tool_approvals、/approve、/deny、/resume，让 run.waiting_for_tool_approval 成为可恢复状态。
```

### Task 2：实现 SQLiteSessionStore

```text
新增 SQLiteSessionStore 和 SQLiteCheckpointStore，支持进程重启后恢复 session、task、pending approval。
```

### Task 3：实现 LLMReflector

```text
新增 LLMReflector，使用 LLM 判断任务是否真正完成，并保留 RuleBasedReflector 兜底。
```

### Task 4：增强 Executor 失败分类

```text
为工具执行结果增加 validation_failed、unknown_tool、permission_denied、approval_required、execution_failed、empty_result、blocked 等分类。
```

### Task 5：补充安全默认配置示例

```text
新增一个 configs/safe.yaml 或 docs/security.md，推荐 default_shell=ask、workspace_write=ask、network=deny、destructive_commands=ask。
```

## 非目标

近期先不做：

- 多 Agent。
- Web UI。
- 大规模 MCP 工具市场。
- 向量数据库长期记忆。
- 分布式 Runtime。
- 复杂 DAG 并发执行。

这些应在审批续跑、持久化 session、LLM Reflector 和可观测恢复稳定后再进入。
