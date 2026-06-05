# AI Agent 项目问题分析与优化建议

本文档基于当前 `ai-agent` 仓库代码和文档状态整理，用于后续开发排期、任务拆分和代码优化。

当前项目已经从“最小工程骨架”推进到“可运行的单 Agent Runtime 原型”阶段。项目已经具备 `AgentRuntime`、`PlannerAgent`、`AgentReasoner`、`Executor`、`ToolRouter`、`SessionRecord`、`InMemorySessionStore`、`JsonlEventLogger`、CLI 和六个核心工具。

但项目距离生产级 Runtime 仍有几个关键闭环没有打通，主要集中在：

```text
审批续跑
状态持久化
安全默认配置
LLM 反思验收
Executor 稳定性
可观测与恢复
```

## 一、当前项目阶段判断

当前主链路已经形成：

```text
用户请求
-> ContextAssembler 组装上下文
-> PlannerAgent 生成 Plan / ToolCall
-> Executor 执行步骤
-> ToolRouter 调用工具
-> AgentReasoner 根据工具结果继续决策
-> Reflector 判断是否完成
-> AgentEvent 输出
-> SessionRecord 写回状态
```

这说明项目已经不是简单 demo，而是一个具备基础运行能力的本地 Agent Runtime 原型。

当前已具备的核心模块：

```text
AgentRuntime
PlannerAgent
AgentReasoner
Executor
Reflector
ToolRouter
ToolRegistry
SessionRecord
InMemorySessionStore
InMemoryCheckpointStore
JsonlEventLogger
OpenAICompatibleClient
Read / Write / Edit / Grep / Glob / Bash
```

当前不建议马上进入多 Agent、MCP 工具市场或 Web UI。更合理的路线是：

```text
先把单 Agent Runtime 闭环做稳定
再做插件化和 MCP
最后做多 Agent 和 UI
```

## 二、当前存在的主要问题

## 问题 1：审批机制能停住，但不能继续

当前 `ToolRouter` 已经能根据权限策略返回 `approval_required`，Runtime 也能输出：

```text
run.waiting_for_tool_approval
```

但是审批之后还不能自然恢复执行。

当前流程更接近：

```text
工具需要审批
-> Runtime 停止
-> 返回 run.waiting_for_tool_approval
```

缺少完整闭环：

```text
用户 /approve
-> 找回原来的 ToolCall
-> 设置 approved=True
-> 继续执行原 task
-> 写回结果
```

### 影响

如果没有审批续跑，Agent 的安全执行只能做到“拦截”，不能做到“人类确认后继续执行”。这会导致：

- 高风险工具调用无法自然完成。
- `run.waiting_for_tool_approval` 成为终点事件。
- 后续实现 Web UI 审批按钮、CLI 审批命令都会缺少基础。
- 持久化任务恢复也缺少 pending approval 状态。

### 优化建议

优先实现：

```text
PendingToolApproval
/approve <call_id>
/deny <call_id>
/approvals
/resume <task_id>
```

建议在 `SessionRecord` 中增加：

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

```python
pending_tool_approvals: list[PendingToolApproval] = Field(default_factory=list)
```

Runtime 遇到审批请求时，不只是返回事件，还要把待审批工具调用保存到 session。

### 涉及文件

```text
src/agent_system/runtime/session.py
src/agent_system/runtime/loop.py
src/agent_system/api/cli.py
src/agent_system/models/tools.py
tests/unit/runtime/test_runtime_loop.py
```

### 优先级

```text
P0 / P1：最高优先级
```

## 问题 2：Session 和 Checkpoint 还是内存版，不能恢复

当前已经实现：

```text
SessionRecord
InMemorySessionStore
InMemoryCheckpointStore
```

`SessionRecord` 能保存：

```text
messages
recent_events
recent_tool_results
recent_plan
summary
```

但它们都只存在当前进程内。

进程退出后：

```text
对话历史丢失
recent plan 丢失
tool results 丢失
pending approval 无法保存
task_id 无法 resume
```

### 影响

这会限制项目进入真正可用的 Runtime 状态：

- 无法跨进程恢复会话。
- 无法查看历史任务。
- 无法继续之前中断的工具调用。
- 无法支撑后续 Web UI 或任务面板。

### 优化建议

实现 SQLite 版本：

```text
SQLiteSessionStore
SQLiteCheckpointStore
```

建议新增：

```text
src/agent_system/runtime/session_store.py
src/agent_system/runtime/sqlite_store.py
```

或拆分为：

```text
src/agent_system/runtime/session_store.py
src/agent_system/runtime/checkpoint_store.py
```

建议表结构：

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

建议配置：

```yaml
runtime:
  session_store:
    type: sqlite
    path: .agent/sessions.db
```

### 优先级

```text
P1
```

## 问题 3：默认权限配置过于开放

当前 `configs/default.yaml` 中：

```yaml
permissions:
  default_shell: allow
  workspace_write: allow
  network: allow
  destructive_commands: allow
```

这意味着默认情况下：

```text
Bash 可以执行
写文件可以执行
网络可以允许
破坏性命令也允许
```

这对本地开发很方便，但对 Agent Runtime 来说风险较高。

### 影响

- 审批机制虽然存在，但默认情况下很少触发。
- `Bash` 执行风险较大。
- destructive command 识别目前主要依赖正则，不能完全覆盖所有危险命令。
- 如果用户把默认配置直接用于更真实的场景，风险较高。

### 优化建议

保留 `default.yaml` 作为本地开发配置，同时新增安全配置：

```text
configs/safe.yaml
```

建议内容：

```yaml
runtime:
  max_iterations: 20
  default_mode: act
  stream_events: true

permissions:
  default_shell: ask
  workspace_write: ask
  network: deny
  destructive_commands: ask
```

或者反过来：

```text
configs/default.yaml      # 安全默认
configs/local-dev.yaml    # 本地开发开放配置
```

### 优先级

```text
P1
```

## 问题 4：Reflector 仍然太简单

当前 `Reflector` 基本只做一件事：

```text
所有 step 成功 -> done=True
有 step 没完成 -> done=False, ask_user
```

但工具执行成功不等于任务真的完成。

典型问题：

```text
Grep 成功，但没有匹配结果
Read 成功，但读错文件
Bash 返回 returncode=0，但 stderr 有关键警告
Glob 成功，但列出的文件不是用户想要的
Write 成功，但内容不符合目标
```

### 影响

当前 Runtime 容易把“工具成功”误判为“任务成功”。这会影响最终回答质量，也会影响 Agent 是否继续查证。

### 优化建议

拆成两层：

```text
RuleBasedReflector
LLMReflector
```

保留现有 `Critique` 协议：

```text
done
confidence
issues
next_action
```

LLM Reflector 输入：

```text
用户目标
Plan
StepResult
ToolResult 摘要
Session summary
风险信息
```

建议逻辑：

```text
优先调用 LLMReflector
如果 LLM 输出非法 -> 回退 RuleBasedReflector
```

### 涉及文件

```text
src/agent_system/agents/reflector.py
src/agent_system/prompts/templates/reflector.md
src/agent_system/runtime/factory.py
src/agent_system/runtime/loop.py
tests/unit/agents/test_reflector.py
```

### 优先级

```text
P2
```

## 问题 5：Executor 只是顺序执行，没有真正的执行策略

当前 `Executor.execute()` 是按 `plan.steps` 顺序执行。

当前能力：

```text
优先执行 step.tool_calls
没有 tool_calls 时从 suggested_tools 推断参数
工具全部成功则 step 完成
工具失败则 step 失败
审批请求会停止后续 step
```

但它目前缺少：

```text
depends_on 依赖排序
blocked step
失败类型分类
自动重试
循环依赖检测
执行状态机
```

虽然 `Step` 模型里已经有 `depends_on` 字段，但 Executor 还没有真正使用它。

### 影响

- 多步骤任务难以可靠执行。
- Reasoner 无法清楚知道失败原因。
- 后续恢复任务时缺少明确 step 状态。
- 日志和 UI 无法展示准确的执行状态。

### 优化建议

先不要做复杂 DAG 并发，先做基础执行状态。

建议 `StepResult` 增加：

```python
class StepResult(BaseModel):
    step_id: str
    ok: bool
    status: Literal[
        "completed",
        "failed",
        "blocked",
        "approval_required",
        "skipped",
    ]
    failure_type: str | None = None
    summary: str
```

建议失败类型：

```text
unknown_tool
validation_failed
permission_denied
approval_required
execution_failed
empty_result
blocked
timeout
```

建议 `depends_on` 规则：

```text
依赖完成 -> 执行
依赖失败 -> blocked
依赖不存在 -> plan_invalid
循环依赖 -> plan_invalid
```

### 涉及文件

```text
src/agent_system/execution/executor.py
src/agent_system/models/planning.py
tests/unit/execution/
```

### 优先级

```text
P2
```

## 问题 6：Planner / Reasoner / Reflector 职责边界需要继续收敛

当前大体分工是：

```text
Planner：初始计划
Reasoner：观察工具结果后继续决策
Reflector：判断是否完成
```

这个方向是对的。

但现在 Runtime 中存在两条路径：

```text
有 reasoner -> 走 reasoner
没有 reasoner -> 走 reflector
```

这会让后续理解有些混乱。当前 Reflector 更像兜底判断器，Reasoner 更像主控制器。

### 优化建议

未来可以统一为：

```text
Planner：只负责初始计划
Executor：只负责执行工具
Reasoner：负责观察后下一步动作
Reflector：负责验收是否完成
```

更理想的循环：

```text
Planner 生成初始 plan
while not done:
    Executor 执行工具
    Reflector 判断当前结果是否满足目标
    如果完成 -> final answer
    如果不完成 -> Reasoner 决定下一步 tool_calls / ask_user / replan
```

### 优先级

```text
P3
```

## 问题 7：ToolResult 内容缺少统一结构

当前不同工具返回的 `content` 差异较大：

```text
Read  -> {"path", "content"}
Write -> {"path", "bytes_written"}
Edit  -> {"path", "replacements", "bytes_written"}
Grep  -> {"matches", "count"}
Bash  -> {"stdout", "stderr", "returncode"}
```

这种设计可以工作，但缺少统一的工具结果摘要字段。

### 影响

- Reasoner 需要理解很多不同工具结构。
- 最终回复合成需要为每个工具单独适配。
- 日志中很难统一展示工具结果。
- 长输出截断策略不统一。

### 优化建议

不破坏现有 `content`，但在 `ToolResult.metadata` 中补充统一字段：

```python
metadata={
    "summary": "...",
    "content_type": "text/file/search/shell",
    "truncated": False,
    "artifact_paths": [],
    "failure_type": None,
}
```

对 Bash 输出增加限制：

```text
stdout 最大 N 字符
stderr 最大 N 字符
超长则 truncated=True
```

### 优先级

```text
P3
```

## 问题 8：Context 预算是字符级，不是真 token 级

当前 `TokenBudget` 实际是字符预算，不是真 token 预算。

同时配置中使用：

```yaml
context:
  max_tokens: 180000
```

但 `ContextAssembler` 实际使用的是 `max_chars` 逻辑。

### 影响

- 配置命名容易误导。
- 不同模型 token 计算差异无法准确控制。
- 超长上下文时可能出现不可预期截断。

### 优化建议

短期先把命名改清楚：

```text
max_context_chars
tool_schema_chars
history_chars
tool_result_chars
```

长期再接入模型 tokenizer。

### 优先级

```text
P3
```

## 问题 9：CLI 缺少工程化命令

当前 CLI 有：

```text
run
plan
runtime-chat
```

`runtime-chat` 有：

```text
/help
/clear
/tools
/exit
/quit
```

但还缺少 Runtime 状态管理命令：

```text
/tasks
/task <task_id>
/approvals
/approve <call_id>
/deny <call_id>
/resume <task_id>
/logs
/doctor
```

### 优化建议

优先增加：

```text
agent-system doctor
agent-system tasks
agent-system task <task_id>
```

`doctor` 用来检查：

```text
配置文件是否存在
base_url 是否可访问
模型是否存在
workspace 是否可读写
日志目录是否可写
权限配置是否危险
Bash 是否启用
```

### 优先级

```text
P2 / P3
```

## 问题 10：测试还缺少关键闭环覆盖

当前测试已经覆盖：

```text
Runtime event flow
Reasoner 修复未知工具
validation error 后 Reasoner 修复
session 保存与隔离
tool approval event
JSONL logging
PLAN 模式等待审批
checkpoint 保存
```

但还缺少：

```text
审批后继续执行测试
SQLite 恢复测试
Bash ask / deny / destructive command 测试
Reflector LLM fallback 测试
depends_on 依赖排序测试
tool output 截断测试
CLI doctor 测试
配置安全性测试
```

### 优化建议

后续每做一个能力，先补测试：

```text
test_tool_approval_resume.py
test_sqlite_session_store.py
test_llm_reflector.py
test_executor_dependencies.py
test_safe_config.py
test_cli_doctor.py
```

### 优先级

```text
持续进行
```

## 三、推荐优化路线

## P0：工具审批续跑闭环

目标：

```text
run.waiting_for_tool_approval 不再是终点，而是中间状态
```

需要实现：

```text
PendingToolApproval
Session 保存 pending approvals
/approvals
/approve
/deny
/resume
```

建议先只支持 `runtime-chat` 内的审批续跑，不要一开始就做复杂 task 管理。

## P1：安全默认配置

建议新增：

```text
configs/safe.yaml
```

内容：

```yaml
permissions:
  default_shell: ask
  workspace_write: ask
  network: deny
  destructive_commands: ask
```

并在 README 中说明：

```text
default.yaml 用于本地开发
safe.yaml 用于更接近真实使用的安全模式
```

## P2：SQLite 持久化

目标：

```text
进程重启后 session / checkpoint / pending approval 不丢
```

建议先用标准库 `sqlite3`，不要引入 SQLAlchemy，保持依赖轻。

## P3：LLM Reflector

目标：

```text
工具执行成功以后，不直接等于任务完成
```

LLM Reflector 用来判断：

```text
是否真的完成
是否需要继续查证
是否需要重试
是否需要 ask_user
```

## P4：Executor 稳定性增强

目标：

```text
让执行结果更可解释、更可恢复
```

实现：

```text
depends_on
blocked
failure_type
retry
empty_result
```

## P5：可观测和 CLI 增强

实现：

```text
agent-system doctor
agent-system tasks
agent-system task <task_id>
agent-system logs --tail
agent-system replay <task_id>
```

## 四、建议立即创建的开发任务

## Task 1：实现工具审批续跑

```text
实现 PendingToolApproval、/approve、/deny、/approvals、/resume，使 run.waiting_for_tool_approval 可以恢复执行。
```

涉及文件：

```text
src/agent_system/runtime/session.py
src/agent_system/runtime/loop.py
src/agent_system/api/cli.py
src/agent_system/models/tools.py
tests/unit/runtime/test_runtime_loop.py
```

## Task 2：新增安全配置

```text
新增 configs/safe.yaml，把 shell、workspace_write、destructive_commands 设为 ask，network 设为 deny。
```

涉及文件：

```text
configs/safe.yaml
README.md
docs/project-status.md
docs/next-development.md
```

## Task 3：实现 SQLiteSessionStore

```text
新增 SQLiteSessionStore / SQLiteCheckpointStore，使 session、task、pending approval 可以持久化。
```

涉及文件：

```text
src/agent_system/runtime/session.py
src/agent_system/runtime/checkpoint.py
src/agent_system/runtime/sqlite_store.py
src/agent_system/runtime/factory.py
src/agent_system/config/models.py
```

## Task 4：实现 LLMReflector

```text
新增 LLMReflector，使用模型判断执行结果是否真正满足用户目标，并保留 RuleBasedReflector 兜底。
```

涉及文件：

```text
src/agent_system/agents/reflector.py
src/agent_system/prompts/templates/reflector.md
src/agent_system/runtime/factory.py
tests/unit/agents/test_reflector.py
```

## Task 5：增强 Executor 状态和失败分类

```text
为 StepResult 增加 status / failure_type，支持 depends_on、blocked、approval_required、validation_failed 等状态。
```

涉及文件：

```text
src/agent_system/execution/executor.py
src/agent_system/models/planning.py
tests/unit/execution/
```

## Task 6：增加 doctor 命令

```text
新增 agent-system doctor，检查配置、模型服务、workspace、日志目录、权限风险。
```

涉及文件：

```text
src/agent_system/api/cli.py
src/agent_system/llm/client.py
src/agent_system/config/loader.py
tests/unit/api/test_cli.py
```

## 五、总结

当前项目最大的问题可以概括为：

```text
主链路已经跑通，但生产级闭环还没打通。
```

已经有：

```text
Planner
Executor
ToolRouter
Reasoner
Session
Logging
CLI
```

但还缺：

```text
审批后继续执行
持久化恢复
LLM 反思验收
执行失败分类
安全默认配置
任务查询与 replay
```

因此下一步不建议直接做多 Agent、MCP、Web UI，而应先把单 Agent Runtime 做扎实。

推荐立即从：

```text
Task 1：工具审批续跑
```

开始。
