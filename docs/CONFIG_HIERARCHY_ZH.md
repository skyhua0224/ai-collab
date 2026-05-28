# ai-collab 配置层级参考

> 本文档描述三层结构：**菜单层**（用户看到的）→ **JSON 层**（`config.json` 实际字段）→ **编排行为层**（运行时影响点）。
>
> 核心 schema 定义：`ai_collab/core/config.py:287`
> 菜单根入口：`ai_collab/config_prompt.py:2671`

---

## 一、先记住这 5 个最重要的配置

如果你暂时不想看完整树状结构，先记这 5 个就够了：

1. **`current_controller`**
   - 决定默认谁当主控。
   - 也就是谁先理解任务、出计划、汇总结果。

2. **`providers.*.enabled`**
   - 决定哪些 Agent 默认可参与协作。
   - 关闭后，默认编排不会再选它。

3. **`routing.intent_preferences`**
   - 决定不同任务类型里，谁排第一。
   - 比如实现类任务先给 Codex，测试类任务先给 Claude。

4. **`providers.*.models` + `model_selection`**
   - 决定选中某个 Agent 后，默认用什么模型档位。
   - 这是“选中谁之后，用哪个档位”的配置。

5. **`auto_collaboration.preset`**
   - 决定整体协作倾向。
   - 比如更偏实现、更偏调研、更偏调试。

---

## 二、三层对照图

> 注意：
>
> - **schema 默认值** 和 **模板默认值** 不一定完全相同。
> - `ai_collab/core/config.py` 里的默认值更像“代码层兜底”；
> - `config/config.template.json` 里的默认值更像“产品实际初始推荐值”。
> - 所以你看到 `schema` 默认主控还是 `claude`，但模板里推荐默认主控已经是 `codex`，这并不冲突。

```text
菜单层（用户交互）          JSON 层（config.json）              编排行为层（运行时）
─────────────────────────────────────────────────────────────────────────────────
常用默认项
  启用 Agent            → providers.{codex|claude|gemini}.enabled → 谁进入默认协作池
  默认主控              → current_controller                       → 谁理解任务/生成计划/汇总结果
  默认运行方式          → runtime_mode                            → tmux 还是 direct
  默认入口              → entry_surface                           → guided 还是 command
  自动协作              → auto_collaboration.enabled              → 主控是否可派发其他 Agent
                          auto_collaboration.auto_orchestration_enabled

协作与路由
  协作预设              → auto_collaboration.preset               → 默认职责倾向（实现/调研/调试）
  按任务类型 Agent 偏好 → routing.intent_preferences              → 实现/调研/架构/测试谁排第一
  Agent 偏好            → （说明页，不写 JSON）                  → 无直接写回，只负责解释默认分工

模型与计费
  各 Agent 默认模型     → providers.*.models                     → 选中 Agent 后用哪个模型档位
                          providers.*.model_selection
  计费与配额            → economics.*                             → 价格感知时降档/保配额/跨提供方回退

应用设置
  显示语言              → ui_language                             → 终端 UI 语言
  检查更新              → （只读状态页）                         → 无写回
  自动检查更新          → application.auto_check_updates          → 启动时是否自动检查更新
  关于 ai-collab        → （说明页）                             → 无写回
```

---

## 三、菜单层详细结构

菜单根结构位于 `ai_collab/config_prompt.py:2671`。

```text
ai-collab config
├─ 1. 常用默认项
│  ├─ 启用 Agent
│  │  落点：providers.{codex|claude|gemini}.enabled
│  │  影响：决定谁在默认协作池里可被调度
│  │  写回：ai_collab/tui/setup.py:128-132
│  │
│  ├─ 默认主控
│  │  落点：current_controller
│  │  影响：决定谁默认理解任务、生成计划、汇总结果
│  │  写回：ai_collab/tui/setup.py:134
│  │
│  ├─ 默认运行方式
│  │  落点：runtime_mode
│  │  影响：决定走 tmux 还是 direct
│  │  写回：ai_collab/tui/setup.py:123-124
│  │
│  ├─ 默认入口
│  │  落点：entry_surface
│  │  影响：决定启动先进引导式入口还是命令入口
│  │  写回：ai_collab/tui/setup.py:122-123
│  │
│  └─ 自动协作
│     落点：auto_collaboration.enabled
│           auto_collaboration.auto_orchestration_enabled
│     影响：决定主控是否默认可派发其他 Agent
│     写回：ai_collab/tui/setup.py:136-139
│
├─ 2. 协作与路由
│  ├─ 协作预设
│  │  落点：auto_collaboration.preset
│  │  影响：决定默认职责倾向（实现优先 / 调研优先 / 调试优先）
│  │
│  ├─ 按任务类型的 Agent 偏好
│  │  落点：routing.intent_preferences
│  │  影响：决定实现 / 调研 / 架构 / 测试等任务谁排第一
│  │  normalize 逻辑：ai_collab/core/config.py:202
│  │
│  └─ Agent 偏好（说明页）
│     落点：无（当前是说明页）
│     影响：帮助用户理解默认分工，不直接改 JSON
│     页面位置：ai_collab/config_prompt.py:4076
│
├─ 3. 模型与计费
│  ├─ 各 Agent 的默认模型偏好
│  │  落点：providers.*.models + providers.*.model_selection
│  │  影响：决定选中某个 Agent 后默认具体用哪个模型档位
│  │
│  └─ 计费与配额
│     落点：economics
│     影响：当开启价格感知时，影响降档、保配额、跨提供方回退
│     normalize 逻辑：ai_collab/core/config.py:240
│
└─ 4. 应用设置
   ├─ 显示语言
   │  落点：ui_language
   │  影响：终端 UI / 文案语言
   │
   ├─ 检查更新（只读状态页）
   │  落点：无
   │
   ├─ 自动检查更新
   │  落点：application.auto_check_updates
   │  影响：启动时是否自动检查更新
   │  normalize 逻辑：ai_collab/core/config.py:280
   │
   └─ 关于 ai-collab（说明页）
      落点：无
```

---

## 四、底层 JSON 层级（`config.json` 完整字段树）

```text
Config（ai_collab/core/config.py:287）
│
├─ version
│  作用：配置版本标识，用于迁移
│
├─ ui_language
│  作用：界面和文案语言
│
├─ entry_surface
│  作用：启动入口形态（guided / command）
│
├─ runtime_mode
│  作用：执行后端（tmux / direct）
│
├─ current_controller
│  作用：默认主控 Agent
│
├─ providers
│  ├─ codex
│  ├─ claude
│  └─ gemini
│     ├─ cli
│     │  作用：真正调用哪个 CLI 命令
│     │
│     ├─ enabled
│     │  作用：是否可进入默认协作池
│     │
│     ├─ timeout
│     │  作用：单次调用超时容忍度
│     │
│     ├─ strengths
│     │  作用：能力标签，主要是说明性元数据
│     │  备注：当前更偏“描述能力”，不是硬路由规则本身
│     │
│     ├─ models
│     │  作用：该 Agent 的模型档位与默认模型
│     │
│     └─ model_selection
│        作用：当前默认档位选择
│
├─ delegation_strategy
│  作用：旧总开关字段
│  备注：schema 里仍保留，但现在不是主菜单一等公民
│
├─ quality_gate
│  ├─ enabled
│  └─ threshold
│     作用：质量门槛
│     备注：目前也不是主菜单一等公民
│
├─ routing
│  ├─ mode
│  │  作用：recommended / custom
│  │
│  ├─ cost_bias
│  │  作用：价格在路由中的权重
│  │
│  └─ intent_preferences
│     作用：按任务类型排列 Agent 优先级
│
├─ economics
│  ├─ pricing_mode
│  │  作用：是否启用价格参考
│  │
│  ├─ quota_strategy
│  │  作用：优先消耗还是保留已付费配额
│  │
│  ├─ cross_provider_fallback
│  │  作用：价格敏感时是否允许跨提供方回退
│  │
│  └─ providers
│     └─ {provider}
│        ├─ billing_mode
│        ├─ quota_window
│        └─ relative_cost_tier
│
├─ application
│  └─ auto_check_updates
│     作用：启动时是否自动检查更新
│
└─ auto_collaboration
   ├─ enabled
   ├─ auto_orchestration_enabled
   │  作用：是否默认允许自动协作与编排
   │
   ├─ preset
   │  作用：默认协作风格
   │
   ├─ default_session_preset
   │  作用：V2 session preset 默认值
   │
   ├─ workflow_engine
   │  作用：当前固定走 v2
   │
   ├─ persona_auto_assign
   │  作用：是否自动分配 persona
   │
   ├─ persona_phase_map
   │  作用：阶段 → persona 映射
   │
   ├─ persona_skill_map
   │  作用：persona → 默认技能集合
   │
   ├─ phase_completion_criteria
   │  作用：阶段完成判断门槛
   │
   ├─ escalation_policy
   │  作用：失败重试、接管、是否询问用户
   │
   ├─ intent_trigger_map
   │  作用：意图 → trigger 的默认桥接
   │
   ├─ profile_trigger_map
   │  作用：项目画像 / profile → trigger 的默认桥接
   │
   ├─ skill_map
   │  作用：trigger → skills 集合
   │
   ├─ profile_skill_map
   │  作用：profile → skills 集合
   │
   └─ triggers[]
      ├─ name / patterns
      ├─ primary / reviewers
      ├─ session_preset
      └─ workflow_blueprint
         作用：任务命中后的主路由与执行蓝图
```

---

## 五、关键影响链

| 决策维度 | 字段 | 代码位置 |
|---|---|---|
| **谁来做**（主控） | `current_controller` | `ai_collab/core/config.py:294` |
| **谁来做**（协作池） | `providers.*.enabled` | `ai_collab/tui/setup.py:128-132` |
| **谁来做**（任务类型路由） | `routing.intent_preferences` | `ai_collab/core/config.py:202` |
| **谁来做**（角色 lead 合并） | `auto_collaboration.preset` + `routing.intent_preferences` | `ai_collab/core/config.py:212` |
| **怎么做**（执行后端） | `runtime_mode` | `ai_collab/tui/setup.py:123-124` |
| **怎么做**（具体模型） | `providers.*.models` + `model_selection` | `config/config.template.json` |
| **怎么做**（任务蓝图） | `auto_collaboration.triggers[].workflow_blueprint` | `ai_collab/core/config.py:373` |
| **价格敏感时** | `economics.*` | `ai_collab/core/config.py:240` |
| **失败时** | `auto_collaboration.escalation_policy` | `config/config.template.json:173` |
| **技能挂载** | `intent_trigger_map / profile_trigger_map / skill_map / profile_skill_map / triggers` | `config/config.template.json:180` |
| **纯应用行为** | `application.auto_check_updates` | `ai_collab/core/config.py:280` |

---

## 六、真正的运行顺序，要怎么理解

很多人看到字段很多，会误以为这些层级是并列生效的。

其实更接近下面这个顺序：

1. **先确定谁能参与**
   - 看 `providers.*.enabled`

2. **先确定谁当主控**
   - 看 `current_controller`

3. **再看整体协作倾向**
   - 看 `auto_collaboration.preset`

4. **再看任务类型偏好**
   - 看 `routing.intent_preferences`

5. **如果命中 trigger / profile**
   - 再进一步落到 `session_preset` / `workflow_blueprint`

6. **等确定用哪个 Agent 后**
   - 才看 `providers.*.models` / `model_selection`

7. **如果价格感知启用**
   - 再看 `economics.*`

也就是说：

- `preset` 是高层倾向；
- `intent_preferences` 是任务类型层偏好；
- `triggers` / `workflow_blueprint` 是更具体的落地路线；
- `models` 是“选中这个 Agent 以后具体用哪个档位”。

所以 `auto_collaboration` 这块，真正要理解的是：

> **运行时不是死看某一个字段，而是看 `preset / intent preference / trigger / blueprint` 这些信息合成后的结果。**

---

## 七、层级合理性评估

**合理之处：**

- 菜单分区（常用 / 协作路由 / 模型计费 / 应用）和字段功能域基本一致，用户容易理解。
- `routing` 和 `economics` 是分开的，避免“价格策略”污染“任务路由逻辑”。
- `auto_collaboration` 这层既管总开关，也管预设、trigger、技能桥接，职责上是连贯的。

**待关注点：**

- `delegation_strategy` 和 `quality_gate` 还在 schema 里，但不是现在的主菜单重点，后续要么继续弱化，要么重新收编。
- `auto_collaboration.enabled` 与 `auto_orchestration_enabled` 目前是同步写回的，长期看可以考虑是否合并。
- `Agent 偏好` 现在还是解释层，不是配置层；如果未来做成可编辑页，本文档也需要同步更新。

---

## 八、如果只从产品角度看，这个配置系统在回答什么

你也可以把它简单理解成 4 个问题：

1. **默认谁来主导？**
   - `current_controller`

2. **默认谁可以参与？**
   - `providers.*.enabled`

3. **不同任务默认先找谁？**
   - `routing.intent_preferences`
   - `auto_collaboration.preset`

4. **选中某个 Agent 以后，默认怎么跑？**
   - `providers.*.models`
   - `runtime_mode`
   - `economics.*`

如果以后继续做减法，最优先保留的，也应该是这四层。
