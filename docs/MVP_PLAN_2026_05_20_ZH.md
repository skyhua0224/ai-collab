# ai-collab MVP 阶段计划表

> 计划起点：2026-05-20  
> 建议周期：6 周完成可演示 MVP，8 周完成较稳定 MVP  
> 计划目标：在不丢失现有 Python 编排能力和项目初心的前提下，完成 Rust vNext 平台主干、WebUI/TUI Session Console、基础任务沉淀与最小远程观察能力。

## 1. 原有需求与开发方向分析

ai-collab 创立之初的目标是面向 Codex、Claude、Gemini 等 Coding Agent，提供多 Agent 协作编排能力。项目核心不是单一聊天界面，也不是单一 Agent CLI，而是把真实开发流程中的规划、实现、审查、交付拆给不同 Agent，并让整个过程可观察、可回放、可恢复、可接管。

现有 Python 版本已经形成了几个重要基础：

1. `init/config`：提供用户配置、默认主控、provider 启用、runtime 选择与协作偏好。
2. `detector/selector/workflow/orchestrator`：支持任务检测、模型选择、工作流编排、主控优先与子 Agent 派发。
3. `tmux` 运行面：提供当前可用的多 Agent 可视化执行方式、日志记录与会话回放。
4. 配置驱动：通过 `config.template.json` 和用户配置控制 provider、routing、auto collaboration 等行为。

之前确定的编排基准仍然有效：

1. 稳定单元是职责阶段和目标产物，不是固定 Agent 顺序。
2. 默认流程应先判断目标产物，再判断当前缺口，再路由给合适 Agent。
3. Codex 默认承担主控/执行，Gemini 更偏建模/方案，Claude 更偏验收/复核；实际路由受配置与可用 Agent 影响。
4. 主控需要具备纠偏、收束、重排、中止与接管能力。

Rust vNext 的方向是把上述能力迁移到平台化架构中：

1. `ai-collabd` 作为统一 daemon，持有 run 状态、事件流、审批、产物、恢复与 adapter 调度。
2. `RunAction / RunEvent / RunProjection` 成为所有客户端共享的协议。
3. WebUI、TUI、Electron、远程 Web、消息连接器都作为协议客户端，不重复实现编排逻辑。
4. Python 版本在过渡期保留安装入口、配置经验、tmux backend 与历史能力，逐步把运行时核心迁到 Rust。

MVP 的判断是：先把多 Agent Session Console 做成可运行闭环，再接任务/看板、Wiki、RAG、OCR、桌宠、Skill 市场等外延能力。

## 2. MVP 范围定义

### 2.1 MVP 必须交付

1. Rust daemon 可以创建 run、生成计划、执行步骤、注册产物、处理审批、恢复 run，并通过 WebSocket/SSE 推送状态。
2. 至少接入 Codex 与 Claude Code 两类真实 runtime adapter；Gemini CLI 可以先做 mock、半自动或只保留 adapter 位。
3. WebUI Session Console 可以展示 run 列表、run 详情、计划、Agent 状态、Timeline、Artifact、Approval Center、日志摘要。
4. TUI/CLI 保留基础可用路径，至少能连接 daemon、查看 run、执行关键 action。
5. 支持 Human-in-the-loop：批准、拒绝、中断、重试、改派、接管。
6. 支持 Artifact 闭环：计划、总结、日志片段、diff/report 等可以登记、查看和导出。
7. 支持最小任务沉淀：从 run/artifact 生成任务草稿，进入 Docmost 看板或 inbox，人工确认后进入正式任务。
8. 提供一次完整演示脚本：输入需求 -> 主控规划 -> 子 Agent 执行 -> 验收复核 -> 用户审批 -> 产物汇总 -> 任务沉淀。

### 2.2 MVP 暂缓交付

1. 完整项目管理系统、复杂 Gantt、燃尽图、多人会议。
2. 完整 Notion/Confluence 级 Wiki 编辑体验。
3. 重型 RAG 平台、全量文档知识库、复杂评测。
4. 桌宠长期驻留、自动巡检、桌面 OCR 常驻监听。
5. 公开 Skill/Plugin 市场。
6. 完整 VSCode 插件和完整 Web IDE。

## 3. 技术栈与引用项目

| 模块 | MVP 建议技术栈 | 可引用项目/方案 | MVP 处理方式 |
| --- | --- | --- | --- |
| 后端编排核心 | Rust workspace：`ac_protocol`、`ac_core`、`ac_engine`、`ac_storage`、`ac_daemon` | 本仓库 Rust vNext；Axum；Tokio；Serde；Schemars | 继续沿用当前 Rust 方向，优先补齐 action/event/projection/adapter |
| HTTP/WebSocket API | Axum + Tokio + WebSocket/SSE | Axum 提供 Rust HTTP routing/request handling；当前仓库已使用 `axum` 和 `tokio` | 作为 daemon 控制面与实时事件通道 |
| 状态存储 | 过渡期 JSONL event log + snapshot；后续 SQLite | 本仓库 `FileRunStore`；vNext 文档建议 SQLite + Event Log + Artifact Store | MVP 先保留文件存储，Week 6 后评估 SQLite |
| Runtime Adapter | Rust `Command` process adapter + cancellation token + artifact capture | Codex CLI、Claude Code、Gemini CLI；Happy 的 wrapper/remote control 思路 | 先 Codex + Claude Code，Gemini 保留扩展位 |
| 权限与审批 | `ApprovalRequest` + policy engine + allow/ask/deny | Claude Code 权限体验作为理念参考；Happy 的移动端审批通知参考 | MVP 做高风险 action 审批和 WebUI Approval Center |
| WebUI | React + TypeScript + Vite 或同等轻量前端栈 | React；Happy 的 Web/mobile remote agent UI；Open WebUI 的 AI 界面布局参考 | 先做 Session Console，不做通用聊天产品 |
| 编程工具前端 | WebUI 中的 Agent 轨道、日志、diff、artifact inspector；后续接 Monaco/VSCode URI | Vibe Kanban 的 workspaces、diff review、agent switching；Happy 的 remote control | MVP 只做观察与控制，不做完整 IDE |
| TUI | Rust Ratatui 或过渡期 Python Textual/CLI | Ratatui；现有 Python TUI/Textual 代码 | 若人手紧张，MVP 先保留 Python/TUI 兼容；Rust TUI 做 skeleton |
| 桌面端 | Electron 壳优先；Tauri 作为后续候选 | Electron；Tauri | MVP 可做 Electron wrapper + daemon 管理，不在桌面端写核心逻辑 |
| 任务/看板 | 基于本地 Docmost 已有 database block/kanban 能力增强：`database_blocks`、`database_records`、tasks/kanban/table/calendar/timeline 模板 | 本地 `/Users/skyhua/docmost`；Vibe Kanban 的 coding-agent kanban/workspace 模型 | 不再从零自研 TaskBoard；MVP 复用 Docmost 原生 PostgreSQL 记录、权限和页面关联能力，补 run/artifact/task 绑定 |
| Wiki/文档 | Docmost 薄集成：API/MCP/链接/模板 | Docmost 支持协作 Wiki、Mermaid、权限、评论、历史 | MVP 只做链接和草稿页，不深 fork；注意 AGPL/企业版边界 |
| RAG/知识库 | 后续 pgvector/Qdrant + hybrid search；MVP 只做接口预留 | RAGFlow；Open WebUI RAG；MCP servers | MVP 不上重 RAG，先记录 metadata/source/run/task |
| PDF/DOC/OCR | 后续 MinerU/PaddleOCR | MinerU 可转 PDF/Office 到 markdown/JSON；PaddleOCR 可处理 PDF/图片 OCR | MVP 只预留 ingest 接口，Week 8 可做 demo stub |
| Browser/Computer Use | 后续 browser-use 或 Playwright adapter | browser-use 让网站可被 AI agents 自动化 | MVP 暂缓，仅保留 tool registry 设计 |
| MCP/工具生态 | MCP Hub + Tool Registry + 自定义 MCP servers | Model Context Protocol servers；Anthropic Agent Skills | MVP 只做内部工具抽象和 1-2 个自有 tool |
| Skill/Plugin | Skill Manifest v0.1 + 私有 registry 设计 | Anthropic skills 的 `SKILL.md`/frontmatter 思路 | MVP 只写规范草案，不做市场 |
| 远程/通知 | Webhook + 本地/远程 Web；后续 TG/QQ/手机端 | Happy 的 Web/mobile client、push notifications、加密同步 | MVP 做 webhook/通知接口，商业化 relay 后置 |

## 4. 时间计划总览

6 周版本可以完成“可演示 MVP”；8 周版本更适合对外试用和给团队持续开发使用。

| 周期 | 日期 | 阶段目标 | 后端/编排 | 前端/客户端 | 任务/知识沉淀 | 验收产物 |
| --- | --- | --- | --- | --- | --- | --- |
| Week 1 | 2026-05-20 ~ 2026-05-26 | 需求冻结与协议冻结 | 梳理 Python -> Rust 映射；冻结 contract v0.1；补齐 action/event/projection 清单 | 画出 WebUI/TUI 信息架构；确定主界面布局 | 确认 TaskBoard light 数据模型边界 | MVP 需求说明、contract v0.1、demo 剧本 |
| Week 2 | 2026-05-27 ~ 2026-06-02 | Rust daemon 主干补齐 | 补 `plan.edit`、`step.assign/reassign/skip`、`agent.interrupt/takeover`、`artifact.export`；增强 WebSocket stream | WebUI scaffold：运行列表、运行详情、Timeline mock | 定义 task inbox 和 artifact-to-task 流程 | mock event stream 可驱动前端 |
| Week 3 | 2026-06-03 ~ 2026-06-09 | 第一条真实运行链路 | Codex adapter 接入真实执行；artifact capture；基础 approval policy | WebUI 展示真实 run、plan、step status、agent output | 任务草稿 API stub | “创建 run -> Codex 执行 -> artifact 登记”跑通 |
| Week 4 | 2026-06-10 ~ 2026-06-16 | 多 Agent 与审批闭环 | Claude Code adapter 接入复核/验收；retry/resume/interrupt；approval respond | Approval Center、Agent Inspector、日志摘要、错误态 UI | artifact -> task draft 初步可用 | “Codex 执行 + Claude 复核 + 人工审批”跑通 |
| Week 5 | 2026-06-17 ~ 2026-06-23 | 任务沉淀与 Docmost 看板集成 | ai-collab 侧提供 run/artifact -> task payload；Webhook stub | 复用 Docmost database block/kanban 视图；任务卡关联 run/artifact | Docmost API/MCP PoC：创建草稿页、链接任务 | run 结果可进入 Docmost 看板或 inbox，可关联文档草稿 |
| Week 6 | 2026-06-24 ~ 2026-06-30 | 可演示 MVP Alpha | 端到端稳定化；错误恢复；测试补齐；本地安装脚本 | WebUI 体验打磨；TUI/CLI 最小可用；演示模式 | 文档模板占位；人工 promote 流程 | 6 周演示版：完整 demo 可跑 |
| Week 7 | 2026-07-01 ~ 2026-07-07 | 桌面与远程观察增强 | daemon 管理、端口发现、本地权限提示、通知 webhook | Electron wrapper；远程 Web 访问；移动端窄屏适配 | 任务/文档链接优化 | 试用版：本地桌面入口 + Web 观察 |
| Week 8 | 2026-07-08 ~ 2026-07-14 | 稳定化与交付准备 | smoke test、contract drift test、adapter 回归；评估 SQLite 切换 | UI polish、空态/错误态、交互说明、快捷操作 | RAG/OCR ingest 接口预留；Docmost/TaskBoard 文档 | 8 周 Beta：可给团队试用和对外演示 |

## 5. 每周详细计划

### Week 1：2026-05-20 ~ 2026-05-26

目标：把需求、演示脚本、协议和任务拆分一次性对齐。

关键任务：

1. 梳理现有 Python 能力与 Rust vNext 模块映射。
2. 冻结 MVP 范围，确认必须交付和暂缓交付。
3. 定义 demo 脚本：需求输入、规划、执行、复核、审批、产物、任务沉淀。
4. 冻结 `RunAction / RunEvent / RunProjection` v0.1。
5. 生成 mock event stream，支撑前端并行开发。
6. 确认 WebUI 技术栈和目录结构。

验收标准：

1. `contracts/vnext` 可作为前端开发依据。
2. WebUI 能基于 mock 数据画出第一版主界面。
3. 团队对 6 周和 8 周边界没有歧义。

### Week 2：2026-05-27 ~ 2026-06-02

目标：Rust daemon 可以表达 MVP 所需动作和状态。

关键任务：

1. 补齐 action：plan edit、step assign/reassign/skip、agent interrupt/takeover、artifact export。
2. 补齐 event：plan revised、step reassigned、agent interrupted、correction triggered、run resumed。
3. projection 加入 agents、current step、latest events、pending approval count、artifact summary。
4. WebSocket stream 增强 snapshot + event envelope。
5. WebUI 完成运行列表、运行详情、Timeline 初版。

验收标准：

1. contract drift test 通过。
2. WebUI 能显示 mock 多 Agent run。
3. 后端 action -> event -> projection 链路有测试覆盖。

### Week 3：2026-06-03 ~ 2026-06-09

目标：接入 Codex adapter，打通第一条真实执行链路。

关键任务：

1. Codex adapter 支持启动、发送任务、采集输出、记录 artifact、超时处理。
2. shell/fs/search tool 接入最小审批策略。
3. artifact 支持 report/log excerpt/code change/summary。
4. WebUI 能显示真实 agent output、step status、artifact preview。
5. CLI/TUI 可连接 daemon 并查看 run 状态。

验收标准：

1. 从 WebUI 或 CLI 创建 run 后，Codex 能真实执行一个限定任务。
2. 执行输出可以进入 event log 和 artifact。
3. 错误、超时、中断至少有一种可测试路径。

### Week 4：2026-06-10 ~ 2026-06-16

目标：形成 Codex + Claude 的多 Agent 执行与验收闭环。

关键任务：

1. Claude Code adapter 接入复核/验收步骤。
2. 主控计划中支持执行和验收分离。
3. approval center 支持 pending/approved/denied/expired。
4. WebUI 支持人工批准、拒绝、中断、重试、改派。
5. 支持 run resume 和 step retry 的基础链路。

验收标准：

1. Demo 中能体现 Codex 执行、Claude 复核、用户审批。
2. 审批事件有完整生命周期。
3. 中断和重试不会破坏 projection。

### Week 5：2026-06-17 ~ 2026-06-23

目标：把 run 结果沉淀为任务和文档草稿。

关键任务：

1. 复用本地 Docmost database block：`database_blocks`、`database_records`、tasks/kanban 模板。
2. artifact -> task draft，写入 Docmost 看板或 ai-collab inbox。
3. WebUI 增加 Inbox/Task 最小视图，Docmost 页面负责看板主视图。
4. Docmost 薄集成 PoC：创建任务记录、创建草稿页、链接 run/task/artifact。
5. Webhook stub，为后续通知和商业化 relay 留接口。

验收标准：

1. 一次 run 的修复项可以进入 Docmost 看板或任务 inbox。
2. 人工 promote 后任务成为正式任务记录。
3. 文档草稿可以关联 task/run，暂不要求完整编辑体验。

### Week 6：2026-06-24 ~ 2026-06-30

目标：形成可演示 MVP Alpha。

关键任务：

1. 端到端 demo 稳定化。
2. 补齐 smoke test：create run、generate plan、execute、approval、artifact、task draft。
3. WebUI 处理空态、错误态、loading、断线重连。
4. CLI/TUI 保留最小可用路径。
5. 安装和启动流程文档化。
6. 做一次范围裁剪：未稳定项进入 Week 7/8 或 post-MVP。

验收标准：

1. 6 周版本可以给内部演示。
2. demo 连续跑 3 次不需要手工修状态。
3. 核心测试和 contract 测试通过。

### Week 7：2026-07-01 ~ 2026-07-07

目标：补桌面壳、远程观察和体验细节。

关键任务：

1. Electron wrapper：启动/连接 daemon、打开 WebUI、系统通知。
2. 远程 Web 访问路径：token、端口、origin、基础安全提示。
3. 移动端窄屏适配：run 状态、approval、日志摘要。
4. webhook 通知：审批请求、任务完成、失败告警。
5. WebUI polish：Agent 轨道、Timeline、Inspector、Artifact 面板。

验收标准：

1. 用户可以从桌面入口打开 ai-collab。
2. 用户可以从远程 Web 查看 run 和处理审批。
3. 试用体验明显优于纯终端 tmux 观察。

### Week 8：2026-07-08 ~ 2026-07-14

目标：稳定化、试用准备和 post-MVP 路线确认。

关键任务：

1. 回归测试、端到端 smoke、adapter 稳定性、contract drift。
2. 处理日志、产物、事件存储膨胀问题。
3. 评估 SQLite 切换或继续保留 JSONL 的条件。
4. 补用户文档、开发者文档、演示脚本、已知限制。
5. 预留 RAG/OCR ingest 接口，可做简单 stub。
6. 整理 post-MVP backlog：Docmost 深集成、RAG、OCR、桌宠、Skill Registry、多人协作。

验收标准：

1. 8 周版本可给小团队试用。
2. 已知限制清楚，后续路线明确。
3. 代码、文档、演示材料可同步给新加入开发者。

## 6. 里程碑

| 里程碑 | 时间点 | 标准 |
| --- | --- | --- |
| M0：范围冻结 | 2026-05-26 | MVP 范围、协议、演示脚本确认 |
| M1：Mock Console | 2026-06-02 | WebUI 可显示 mock 多 Agent run |
| M2：真实 Codex 链路 | 2026-06-09 | Codex adapter 能真实执行并产生 artifact |
| M3：多 Agent + 审批 | 2026-06-16 | Codex 执行、Claude 复核、人工审批闭环 |
| M4：任务沉淀 | 2026-06-23 | run 结果可进入 Docmost 看板或任务 inbox，并关联文档草稿 |
| M5：Alpha Demo | 2026-06-30 | 6 周演示版可稳定跑通 |
| M6：Desktop/Remote | 2026-07-07 | Electron/远程观察/通知最小可用 |
| M7：Beta | 2026-07-14 | 8 周试用版，文档和回归测试齐备 |

## 7. 风险与裁剪策略

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Adapter 不稳定 | 真实执行链路延期 | Codex 优先，Claude 复核可先用半自动/模板化，Gemini 延后 |
| WebUI 与后端协议互相等待 | 前后端阻塞 | Week 1 必须给 mock stream，前端先按 contract 开发 |
| Electron 拖慢主线 | 桌面壳影响核心闭环 | Electron 放 Week 7，Week 6 前只做 WebUI |
| TaskBoard 变成完整项目管理 | MVP 膨胀 | 复用 Docmost 已有 tasks/kanban/table/calendar/timeline 能力，ai-collab 只补 run/artifact/task 绑定 |
| Docmost 二开成本高 | Wiki 集成延期 | MVP 只做 API/MCP 薄集成，不 fork 核心 |
| RAG/OCR 过早介入 | 工期失控 | Week 8 只预留 ingest 接口，RAG/OCR 进入 post-MVP |
| 安全/权限遗漏 | 用户不敢试用 | approval 生命周期、危险命令拦截、操作日志作为 P0 |

## 8. Post-MVP 路线

1. Docmost 看板增强：任务文档货架、迭代、依赖图、质量门禁。
2. Docmost 深集成：文档模板、PRD/Design/Test 文档货架、Mermaid、Agent 评论。
3. RAG：Docmost、Task、Run summary、Artifact 增量索引；引用回链。
4. OCR/PDF/DOC：MinerU/PaddleOCR 接入，文档一键分析和入库。
5. 桌宠观察：截图、脱敏、场景预设、观察结果转任务/文档。
6. Skill/Plugin：Skill Manifest、私有 registry、Role/Tool 组合。
7. 多人协作：viewer/operator/approver/owner，团队空间、审计、远程审批。
8. 商业化服务：relay、中转站、通知、托管 registry、团队 RAG、成本网关。

## 9. 参考项目清单

| 项目 | 用途 |
| --- | --- |
| [slopus/happy](https://github.com/slopus/happy) | Codex/Claude Code 的 Web/mobile remote control、通知、加密同步参考 |
| [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban) | coding-agent 看板、workspace、diff review、agent switching 参考；注意其 sunsetting 状态 |
| [docmost/docmost](https://github.com/docmost/docmost) | Wiki、文档、Mermaid、权限、评论、历史参考 |
| [open-webui/open-webui](https://github.com/open-webui/open-webui) | AI WebUI 信息架构和自托管体验参考 |
| [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | RAG、文档理解、引用、agentic workflow 参考 |
| [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | PDF/图片 OCR 和文档结构化数据参考 |
| [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | PDF/Office 到 Markdown/JSON 的文档解析参考 |
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | 浏览器自动化和 computer-use 方向参考 |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | MCP 工具生态参考 |
| [anthropics/skills](https://github.com/anthropics/skills) | Skill Manifest、技能目录和插件化能力参考 |
| [tauri-apps/tauri](https://github.com/tauri-apps/tauri) | Rust + WebView 桌面端候选，适合后续轻量桌宠/桌面端评估 |
| [electron/electron](https://github.com/electron/electron) | WebUI 快速桌面化和 VSCode 类生态参考 |
| [ratatui/ratatui](https://github.com/ratatui/ratatui) | Rust TUI 候选 |
| [tokio-rs/axum](https://github.com/tokio-rs/axum) | Rust HTTP/WebSocket API 框架 |
| [facebook/react](https://github.com/facebook/react) | WebUI 基础前端框架候选 |
