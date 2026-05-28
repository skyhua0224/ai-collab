# ai-collab 下一阶段开发方针

> 本文用于统一下一阶段产品与工程推进节奏。外部调研材料可作为能力地图与竞品参照，实际开发以本仓库已有 vNext Rust 平台、Run/Event/Projection 协议、多 Agent 编排目标为主线。

## 1. 总体定位

ai-collab 下一阶段应聚焦为跨端多 Agent 协作控制台。Rust 平台核心负责统一管理 Run 生命周期、Agent 调度、事件流、产物、审批、恢复与权限；TUI、WebUI、Electron、远程端、消息连接器均作为同一协议之上的客户端入口。

产品主线围绕以下能力展开：

1. 多 Agent 编排：主控规划、子控执行、验收复核、纠偏接管。
2. 过程可视化：实时展示计划、步骤、Agent 状态、日志、diff、产物与审批请求。
3. 人机协作控制：用户可在运行中回复、批准、拒绝、中断、重试、改派、接管。
4. 交付沉淀：Run 结果可形成 Artifact、任务、设计文档、测试记录与知识页。
5. 跨端一致：TUI、WebUI、Electron 使用同一套 Action API 与 Event/Projection 数据模型。

## 1.1 历史承接与项目初心

这份方针不是重开一个新项目，而是把 ai-collab 从创立之初的目的继续往前推。

项目最初的目标一直是：

1. 面向 Codex / Claude / Gemini 的多 Agent 协作编排。
2. 让规划、实现、审查、交付变成可观察、可接管、可恢复的过程。
3. 让终端用户不用只面对黑盒对话，而是面对一套可执行的协作工作流。
4. 让一次 run 产出的计划、代码、报告、文档、审查记录都能被沉淀下来。

这和当前 Python 代码、原本编排、Rust 迁移计划是连续的，不是替换关系：

1. 现有 Python 代码仍然是当前产品行为与用户体验的现实基础，尤其是 init/config、detector、selector、workflow、orchestrator、tmux 运行面。
2. `docs/AI_COLLAB_FULL_FLOW_REFERENCE_ZH.md` 和 `docs/AI_COLLAB_ORCHESTRATION_BASELINE_ZH.md` 仍然是当前编排与默认路由的行为基准。
3. Rust 计划不是另起炉灶，而是把上述能力迁到更稳定的 daemon / protocol / client 架构里。
4. 新增的 WebUI、TUI、Electron、任务/知识沉淀能力，都应服务于同一个核心目标，而不是把项目带离原来的多 Agent 编排主线。

因此，当前方针的核心不是“改成一个新产品”，而是：

**把旧有 Python 协作框架的真实能力、既有编排基准、以及 Rust 平台化路线，统一收束成一条连续的产品演进链。**

## 2. 外部调研材料的使用方式

三份 Docmost 材料价值不同：

1. 开源仓库全面分析报告：作为生态参照，帮助选择可借鉴项目，如 Dify、Open WebUI、RAGFlow、Docmost、vibe-kanban、browser-use、PaddleOCR 等。
2. 开源仓库调研任务书：作为后续持续调研的方法模板，可用于补充竞品分析与模块选型。
3. AI Collab 接入设计文档与工作清单：作为能力蓝图，包含 Wiki、TaskBoard、RAG、桌宠观察、Skill/Plugin、事件总线等完整构想。

执行层面建议把第三份材料拆成“能力池”，避免一次性把 Wiki、看板、RAG、桌宠、插件市场全部压进同一个 MVP。当前仓库已有 Rust engine、daemon API、event log、projection、contract schema，下一步应优先把这些主干做稳定。

## 3. 工程原则

1. 协议优先：先稳定 `RunAction`、`RunEvent`、`RunProjection`、`Artifact`、`ApprovalRequest`，再推进客户端 UI。
2. 事件驱动：`RunEvent` 作为事实源，`Projection` 作为 UI 状态，客户端只订阅与提交 action。
3. 后端一源：编排、权限、审批、恢复、Agent adapter 均落在 Rust daemon，不在 WebUI、TUI、Electron 中重复实现。
4. 客户端并行：前端可基于 contract mock server 先做界面，Rust 后端按同一 schema 回归验证。
5. 外延后置：Wiki、看板、RAG、桌宠、插件市场围绕 Run/Task/Knowledge/Skill 扩展，不能反向拖慢 Session Console 主干。
6. 审批先行：涉及 shell、网络、越目录写入、长任务、远程控制、Agent 扩边界操作时，统一走 approval 生命周期。
7. 人工守门：Agent 写 Wiki、创建正式任务、沉淀到知识库等动作默认进入草稿或 inbox，由人确认后进入主干。

## 4. MVP 边界

MVP 目标是做出可演示、可日常试用的多 Agent Session Console。优先交付以下内容：

1. Rust daemon：创建 run、生成计划、执行步骤、注册产物、处理审批、恢复 run、WebSocket/SSE 实时订阅。
2. Runtime adapter：至少接入 Codex 与 Claude Code，Gemini CLI 可先保留 mock 或半自动接入。
3. Session Console：展示 run timeline、plan、agent 状态、artifact、approval center、日志摘要与操作按钮。
4. TUI/WebUI 同源：TUI 作为专业入口，WebUI 作为可视化入口，两者共享协议与数据模型。
5. Artifact 闭环：支持计划、总结、日志片段、diff/report 等产物登记与导出。
6. Human-in-the-loop：支持批准、拒绝、中断、重试、改派、接管。
7. 最小远程能力：本地 daemon + WebUI 访问 + webhook/消息提醒的基础接口。

MVP 暂缓内容：

1. 完整 Jira/Linear 式项目管理。
2. 完整 Notion 式 Wiki 编辑体验。
3. 公开 Skill/Plugin 市场。
4. 重型 RAG 平台与复杂评测系统。
5. 桌宠长期常驻与自动巡检。
6. 多人实时会议、白板、页面点评等强协同功能。

## 5. 阶段路线

### Phase 0：协议冻结与主干补齐，1-2 周

目标是让前后端都能稳定围绕 contract 开发。

交付项：

1. 补齐 `RunAction`：`plan.edit`、`step.assign`、`step.reassign`、`step.skip`、`agent.interrupt`、`agent.takeover`、`artifact.export`。
2. 补齐事件：`plan.revised`、`step.reassigned`、`agent.interrupted`、`correction.triggered`、`run.resumed`。
3. 完善 projection：加入 agents、current_step、latest_events、pending_approval_count、artifact summary。
4. 建立 mock event stream，用于 WebUI/TUI 并行开发。
5. 将 schema 导出与测试纳入回归流程。

### Phase 1：Rust daemon 与真实运行闭环，2-4 周

目标是让一个 run 能从创建、计划、执行、审批到总结完整跑通。

交付项：

1. `ai-collabd` 本地服务稳定化。
2. 文件事件存储继续可用，评估 SQLite 切换点。
3. Codex adapter 接入真实执行流程。
4. Claude Code adapter 接入验收/审查流程。
5. shell/fs/search tool 接入审批策略。
6. run resume、interrupt、retry、artifact register 可用。

### Phase 2：Session Console MVP，3-5 周

目标是形成可以对外演示的主产品界面。

交付项：

1. WebUI：运行列表、运行详情、Agent 轨道、Timeline、Plan、Inspector、Approval Center。
2. TUI：同一信息架构的键盘高频入口，支持 slash commands。
3. Electron：先作为 WebUI + daemon 管理壳，提供本地通知、启动 daemon、打开 workspace。
4. 统一 UI 状态：全部来自 `RunProjection` 与 event stream。
5. 演示脚本：从需求输入到多 Agent 执行、审批、产物汇总的完整路径。

### Phase 3：任务与文档沉淀，4-6 周

目标是把一次 run 的结果落到团队可继续使用的任务和文档中。

交付项：

1. TaskBoard light：Project、Task、Comment、Event、Inbox、Promote。
2. Task MCP/REST：`task.create`、`task.update`、`task.comment`、`task.link`、`task.list`。
3. Wiki 接入：优先通过 Docmost API/MCP 做页面读写、任务链接、文档模板。
4. 文档货架：PRD、Design、Dev、Test、Review、ADR 的状态槽位。
5. Agent 生成内容进入草稿或 inbox，人工确认后进入正式知识库。

### Phase 4：RAG、文档分析与 OCR，4-8 周

目标是提升项目知识召回能力，为跨角色协作打基础。

交付项：

1. Docmost 页面、Task、Run summary、Artifact 的增量索引。
2. Hybrid search + rerank 的最小可用链路。
3. PDF/DOC/OCR 入库，支持引用回链。
4. `rag.search`、`rag.cite`、`rag.ingest` MCP 工具。
5. 过滤 source=agent 的策略，降低知识污染。

### Phase 5：桌宠、Skill/Plugin、多人协作，长期演进

目标是扩展到更丰富的一人公司与小团队工作台形态。

交付项：

1. 桌宠观察：截图、脱敏、场景预设、观察结果转任务/文档。
2. Skill Manifest 与私有 Registry。
3. Role/Skill/Tool 组合配置。
4. 远程审批、通知中转、TG/QQ/Webhook。
5. 多人协作：viewer、operator、approver、owner 角色与项目空间。

## 6. 模块优先级

| 模块 | 优先级 | 当前建议 |
| --- | --- | --- |
| Rust Platform Core | P0 | 所有客户端与扩展能力的地基，立即推进 |
| Run/Event/Projection Contract | P0 | 前后端并行开发的接口基准，立即冻结第一版 |
| Runtime Adapter | P0 | 先 Codex + Claude Code，Gemini 保留扩展位 |
| TUI Session Console | P0 | 专业用户默认入口，与 Web 共用协议 |
| WebUI | P0 | 演示、远程观察、可视化协作的主界面 |
| Electron | P1 | 先做壳与本地集成，不承载核心业务逻辑 |
| TaskBoard light | P1 | 只做 Agent 可写、人可审、知识可回流 |
| Docmost Wiki | P1 | 先通过 API/MCP 接入，降低二开维护成本 |
| RAG | P2 | 有足够任务/文档/Run 数据后再做深 |
| OCR/PDF/DOC 分析 | P2 | 作为 RAG 数据源与文档入口推进 |
| 桌宠观察 | P2/P3 | 可做展示亮点，核心闭环稳定后推进 |
| Skill/Plugin 市场 | P3 | 先私有 registry，公开市场长期演进 |
| 多人会议/页面点评 | P3 | 适合商业版或团队版，等待基础协作模型稳定 |

## 7. 商业化技术边界

项目主体保持开源友好，商业化能力与核心开源能力分层设计。

开源核心建议包含：

1. Rust daemon 与本地运行模型。
2. TUI/基础 WebUI。
3. 本地多 Agent 编排。
4. 基础 adapter 与 tool registry。
5. 本地事件存储、artifact、approval。

商业化探索建议优先放在服务侧：

1. Relay/中转站：远程访问、移动端审批、多设备会话。
2. 通知与连接器：TG、QQ、企业微信、Webhook、邮件。
3. 团队空间：成员、角色、权限、审计、共享 run。
4. 托管 Skill/Plugin Registry：私有市场、版本管理、签名扫描。
5. 托管知识库/RAG：团队级索引、权限过滤、跨项目检索。
6. 成本与模型网关：额度、路由、统计、统一账单。

## 8. 团队分工建议

下一阶段最需要两类人：

1. Rust/平台后端工程师：负责 daemon、protocol、event store、adapter、approval、runtime integration。
2. 前端/客户端工程师：负责 WebUI、Electron、TUI 信息架构落地、可视化状态、交互与设计系统。

AI 应用工程能力仍然重要，但当前最紧迫的是平台工程与客户端工程。RAG、OCR、Skill 市场可以在主干稳定后引入更专门的人。

## 9. 近期执行清单

建议下一轮工作按以下顺序启动：

1. 合并当前战略结论到 vNext 文档体系。
2. 确认 MVP demo 剧本：输入需求、主控规划、两 Agent 执行/验收、审批、产物汇总。
3. 冻结 contract v0.1，并生成 mock event stream。
4. 前端基于 mock stream 开发 WebUI Session Console。
5. Rust 侧补齐 action/event/projection 与真实 adapter。
6. 建立每日可跑的端到端 smoke test。
7. 评估 happy/docmost/vibe-kanban 等开源项目的接入点，只做“薄集成”验证。
