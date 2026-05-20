# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Phorni — Project Vision

Phorni 是一个融合了**情感陪伴**与**专业编码代理**能力的双核 AI Agent 桌面应用。

### 基因来源

| 能力维度 | 参考项目 | 继承内容 |
|---------|---------|---------|
| **情感陪伴** | Shinsekai (../Shinsekai/) | 角色驱动对话、精灵/情绪表达、TTS/ASR 语音交互、插件系统、多 LLM 适配器模式 |
| **专业代理** | claude-code-from-scratch (../claude-code-from-scratch/) | Agent 循环、工具调用系统、上下文压缩、权限控制、子代理、Plan Mode、MCP 客户端 |
| **通用接口** | 两者融合 | 统一的多提供商 LLM 接口（OpenAI/DeepSeek/Gemini/Claude 等），标准化的工具注册与执行协议 |

### 核心设计理念

1. **双模式切换**：用户可在"陪伴模式"（角色对话、情感交互）和"专业模式"（代码任务、工具链）之间无缝切换
2. **角色即代理**：陪伴模式中的角色本身具备专业能力——角色不仅是聊天对象，更是能帮你完成任务的智能代理
3. **模块化适配器**：所有外部服务（LLM、TTS、ASR、工具）通过工厂+适配器模式接入，可替换、可扩展
4. **通用工具协议**：工具定义与执行层抽象，同时支持内置工具、插件工具、MCP 外部工具

### 技术选型建议

- **语言**：Python 3.10+（与 Shinsekai 一致，社区生态丰富）
- **GUI**：PySide6（与 Shinsekai 一致）或考虑 Web UI（更灵活的部署）
- **架构**：参考 Shinsekai 的队列 Worker 管道 + claude-code-from-scratch 的 Agent 循环

---

## 项目结构（规划中）

```
Phorni/
├── agent/          # Agent 核心循环、工具调用、子代理
├── companion/      # 情感陪伴层：角色管理、情绪系统、对话记忆
├── llm/            # LLM 适配器（多提供商统一接口）
├── tools/          # 工具定义、执行器、权限控制
├── tts/            # TTS 适配器
├── asr/            # ASR 适配器
├── mcp/            # MCP 客户端与桥接
├── memory/         # 长期记忆与上下文管理
├── ui/             # 用户界面
├── plugins/        # 插件系统
├── config/         # 配置管理
├── test/           # 测试
└── sdk/            # 插件开发 SDK
```

---

## 开发原则

- **从最简代理循环开始**：先跑通 "用户输入 → LLM → 回复" 的核心回路，再逐步叠加工具、记忆、UI
- **先 CLI 后 GUI**：命令行界面快速验证代理逻辑，GUI 作为后续体验层
- **测试驱动**：每个核心模块先写测试，参考 Shinsekai 的 test/ 结构
- **适配器模式贯穿始终**：任何外部依赖都通过适配器接入，绝不硬编码具体实现
- **安全第一**：工具执行需权限分级（低风险自动执行、高风险需确认）
