# ai-collab UX Flow Lab（已归档 / 过时）

> 状态：已归档，仅保留为历史参考，不再代表当前 `ai-collab` 的产品方向。
>
> 说明：当前主线已经转向新的 V2 编排、配置层级与交互设计；这里的原型不再参与后续实现决策。

这个文件夹不是生产代码，是早期用来直接对比 CLI/TUI 交互方案的 throwaway 原型。

目标：
- 先不改 `ai-collab` 真正实现。
- 先把几套“操作流程 + 显示方式”跑出来。
- 你可以自己逐套看，判断哪种最符合你的预期。

## 文件

- `preview.py`
  终端预览器。按不同方案打印一整段用户视角流程。
- `run_all.sh`
  一次性把所有方案都跑一遍，方便横向对比。

## 方案

### 1. `baseline-current`

用途：
- 复刻你现在最不满意的感觉，作为对照组。

特点：
- 一上来先打很多 detector/workflow 摘要。
- 暴露过多内部信息，比如自动技能、prompt 文件、briefing 文件、run_id、日志目录。
- planner 失败后容易出现“自动回退到内置分工”。

适合：
- 只用于对照，不推荐保留。

### 2. `strict-param`

用途：
- 参数模式专用，强调“命令即合同”。

特点：
- 只显示关键状态，不显示 detector 摘要。
- planner 失败就直接退出。
- 明确禁止隐式 fallback。
- tmux 创建、S1/S2、关闭询问都只显示必要信息。

适合：
- `--provider codex --execution-mode tmux --controller-first` 这类显式参数启动。

### 3. `compact-operator`

用途：
- 给真实使用者看的默认日常模式。

特点：
- 开头只给一个很小的概要卡片。
- 后续只显示“当前正在做什么”。
- 内部路径和调试信息默认隐藏。
- 关闭/保留决策会以明显但不吓人的方式提示。

适合：
- 未来默认用户体验。

### 4. `timeline-focused`

用途：
- 适合外部 iTerm2 + tmux 观察型工作流。

特点：
- 用时间线/阶段感展示流程。
- 用户能一眼看到现在卡在哪一环。
- 很适合长任务，但比 `strict-param` 多一点信息。

适合：
- “我就想看编排进行到第几步了”的场景。

### 5. `two-stage-gate`

用途：
- 强调“先规划，后执行”的严格 controller-first 语义。

特点：
- 分成 Stage 1 `Plan` 和 Stage 2 `Execute`。
- 只要 planner 没成功，就绝不进入 tmux。
- 最符合你对“不要偷偷 fallback”的要求。

适合：
- 对主控规划真实性要求最高的场景。

## 运行方式

先列出方案：

```bash
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --list
```

看某一套成功流程：

```bash
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --scheme strict-param --scenario success
```

看某一套 planner 失败流程：

```bash
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --scheme two-stage-gate --scenario planner-fail
```

一次看完全部方案：

```bash
/Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/run_all.sh
```

加一点延迟，模拟真实滚动感：

```bash
python3 /Users/skyhua/ai-collab/docs/archive/ux-flow-lab-obsolete/preview.py --scheme compact-operator --scenario success --delay 0.25
```

## 我建议你重点比较的点

1. planner 失败时，用户是否能立刻看懂“系统停住了”，而不是误以为已经成功启动。
2. tmux 何时创建，是否说得足够清楚。
3. S1 / S2 是否足够醒目，但又不过度吓人。
4. “关闭还是保留”的提示是否像真正产品，而不是开发日志。
5. 内部信息是否被压到 `verbose/debug`，而不是默认暴露。

## 当前推荐顺序

如果按你的最新诉求排序，我建议你先看：

1. `two-stage-gate`
2. `strict-param`
3. `compact-operator`
4. `timeline-focused`
5. `baseline-current`
