# AI Collaboration System / 智能协作系统

面向 Codex / Claude / Gemini 的终端多 Agent 协作编排框架。

[![CI](https://img.shields.io/github/actions/workflow/status/skyhua/ai-collab/ci.yml?branch=main)](https://github.com/skyhua/ai-collab/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-collab)](https://pypi.org/project/ai-collab/)
[![Python](https://img.shields.io/pypi/pyversions/ai-collab)](https://pypi.org/project/ai-collab/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

本框架将真实开发流程中的规划、实现、审查与交付环节拆分至不同模型，并提供可观测、可回放、可降级的协作机制。

[English Documentation](./README_EN.md)

## 核心特性

1. **主控优先**：先规划再执行，避免单 Agent 盲目推进
2. **配置驱动**：模型与角色通过配置文件管理，无硬编码依赖
3. **过程可见**：基于 tmux 的协作模式支持实时交互、日志记录与会话回放
4. **故障可控**：针对命令不可用、权限受限、子 Agent 失败等场景提供显式降级策略

## 统一命令接口

项目采用单一命令入口：`ai-collab`

- **执行任务**：`ai-collab "<task>"`
- **管理操作**：`ai-collab <subcommand>`（如 `init`、`status`、`config`）

查看完整执行参数：

```bash
ai-collab run --help
```

## 安装方式

### 从源码安装

```bash
git clone https://github.com/skyhua/ai-collab.git
cd ai-collab
python3 -m pip install -e .
```

### 从 PyPI 安装

```bash
pip install ai-collab
```

## 快速开始

### 1. 初始化配置

```bash
ai-collab init
ai-collab status
```

### 2. 执行协作任务

```bash
ai-collab "设计并实现一个带鉴权的 REST API，并给出测试与发布建议"
```

### 3. 启用 tmux 可视化协作

```bash
ai-collab \
  --provider codex \
  --execution-mode tmux \
  --tmux-target inline \
  --tmux-prewarm-subagents \
  "实现一个包含前端与后端的最小业务功能，并完成审查"
```

## 常用子命令

| 命令 | 功能说明 |
|---|---|
| `ai-collab init` | 初始化配置文件模板 |
| `ai-collab status` | 查看当前配置与 Agent 可用性状态 |
| `ai-collab detect` | 检测协作需求并生成编排建议 |
| `ai-collab monitor` | 手动启动 tmux 协作工作区 |
| `ai-collab config` | 管理配置项 |
| `ai-collab select` | 根据任务复杂度选择模型策略 |

## 可观测性与故障排查

### 日志目录结构

```text
.ai-collab/logs/<session>/
```

### 常用排查命令

```bash
# 实时查看日志
tail -f .ai-collab/logs/<session>/*.log

# 检测任务编排建议（JSON 格式）
ai-collab detect "<task>" --output json

# 模拟执行（不实际运行）
ai-collab --dry-run --output json "<task>"
```

## 文档导航

- [快速开始指南](./QUICKSTART.md)
- [详细使用文档](./docs/USAGE.md)
- [版本发布流程](./docs/RELEASE.md)

## 开发与验证

```bash
# 运行测试
pytest -q

# 构建分发包
python3 -m build

# 验证分发包
python3 -m twine check dist/*
```

## 开源协议

[MIT License](./LICENSE)
