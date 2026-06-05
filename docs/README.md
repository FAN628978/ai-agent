# 文档索引

本目录作为项目文档入口。项目长文档统一放在 `docs/` 下，根目录保留 `README.md` 和 `AGENTS.md`。

## 快速阅读顺序

1. `project-status.md`：当前项目真实状态、已完成能力、主要不足和交接说明。
2. `codebase-guide.md`：当前代码结构、运行链路、模块职责和扩展点说明。
3. `next-development.md`：下一步开发建议：审批续跑、持久化 Session 与 LLM Reflector。
4. `development-plan.md`：阶段化开发路线。
5. `architecture.md`：生产级 Agent Runtime 架构蓝图。
6. `../README.md`：项目简介、安装方式、CLI 使用方式。
7. `../AGENTS.md`：给后续 agent 的项目约束和协作说明。

## 文档职责

| 文档 | 说明 |
| --- | --- |
| `project-status.md` | 当前项目状态和交接说明，优先反映真实代码现状 |
| `codebase-guide.md` | 当前代码结构、运行链路、模块职责和扩展点 |
| `next-development.md` | 下一步开发建议：审批续跑、SQLite Session、LLM Reflector、Executor 稳定性 |
| `development-plan.md` | 阶段化开发路线，偏长期规划 |
| `architecture.md` | 生产级 Agent Runtime 架构蓝图，可能包含尚未实现的目标设计 |
| `../README.md` | 项目简介、安装方式、CLI 使用方式 |
| `../AGENTS.md` | 开发偏好、代码修改原则、后续 agent 接手规则 |

## 阅读建议

如果要继续开发代码，优先阅读：

```text
project-status.md -> codebase-guide.md -> next-development.md
```

如果要理解长期架构，再阅读：

```text
development-plan.md -> architecture.md
```

注意：`architecture.md` 和 `development-plan.md` 包含目标架构，不一定全部等同于当前实现。判断当前实现状态时，以 `project-status.md`、`codebase-guide.md` 和源码为准。
