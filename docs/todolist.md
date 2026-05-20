# Phorni 开发指导清单

> 这是你的第一个 Agent 项目。以下建议基于 Shinsekai 和 claude-code-from-scratch 两个项目的实战经验整理。

---

## 第一阶段：最小可行代理 (MVP)

### 1.1 搭一个最简 Agent 循环（优先级最高）

**目标**：一个 Python 脚本，能接收用户输入，调用 LLM，流式输出回复。不超过 200 行。

```
用户输入 → LLM API 调用 → 流式打印回复 → 等待下一条输入
```

- [ ] 创建 `agent/agent_loop.py`：单文件 CLI 代理
- [ ] 接入一个 LLM（推荐先用 DeepSeek 或 OpenAI，接口最标准）
- [ ] 实现流式输出（SSE 解析）
- [ ] 支持多轮对话（维护 messages 列表）

**关键参考**：
- `claude-code-from-scratch/python/mini_claude/agent.py` — Agent 类结构
- `claude-code-from-scratch/python/mini_claude/session.py` — 会话管理
- `Shinsekai/llm/llm_manager.py` — 多提供商适配器模式

**陷阱提醒**：不要一上来就建几十个文件和目录。从一个能跑的单文件开始，等它"长胖了"再拆分。

### 1.2 加入 System Prompt（角色灵魂）

- [ ] 设计一个角色 System Prompt（性格、说话风格、能力边界）
- [ ] 将 System Prompt 注入到每轮对话的 messages[0]
- [ ] 让角色"知道自己是谁"——这是从普通 chatbot 变成角色的关键一步

**关键参考**：`claude-code-from-scratch/python/mini_claude/prompt.py`

### 1.3 加入第一个工具（让代理"能做事"）

- [ ] 实现一个最简单的工具（如 `get_current_time` 或 `read_file`）
- [ ] 实现工具调用的 JSON 解析（从 LLM 回复中提取 function_call）
- [ ] 实现工具执行 → 结果注入回对话 → LLM 继续生成 的循环

**这就是 Agent 的本质**：LLM 不再是"回答完就结束"，而是"调用工具→观察结果→继续思考→再回答"。

**关键参考**：
- `claude-code-from-scratch/python/mini_claude/tools.py` — 工具定义与执行
- `Shinsekai/llm/tools/tool_executor.py` — 工具执行器（含风险评估）

---

## 第二阶段：情感陪伴层

### 2.1 角色记忆系统

Shinsekai 用短期记忆（对话历史压缩）+ 长期记忆（向量检索）来让角色"记住"用户。

- [ ] 短期记忆：对话历史自动压缩（超过 token 阈值时摘要/截断）
- [ ] 长期记忆：用户说过的重要信息存入向量数据库，检索注入上下文
- [ ] 参考 `Shinsekai/llm/compact_manager.py` 和 `Shinsekai/llm/history_manager.py`

### 2.2 情绪 / 表情系统

- [ ] 定义角色的情绪状态机（开心、难过、惊讶、思考中...）
- [ ] 让 LLM 在回复中输出情绪标签，UI 根据标签切换精灵/表情
- [ ] 参考 Shinsekai 的 sprite 系统（`core/sprite/`）

### 2.3 TTS / ASR 语音交互（可选，较复杂）

- [ ] TTS：文字转语音，让角色"说话"
- [ ] ASR：语音转文字，让用户"说话"
- [ ] 参考 `Shinsekai/tts/tts_manager.py` 和 `Shinsekai/asr/asr_manager.py`

---

## 第三阶段：专业代理能力

### 3.1 完善工具系统

- [ ] 按类别组织工具（文件操作、代码执行、网络请求、系统命令）
- [ ] 实现工具搜索/动态激活（类似 Shinsekai 的 `tool_search.py`）
- [ ] 实现权限分级（只读工具自动执行，写入工具需确认，危险工具需二次确认）

### 3.2 子代理（Sub-agent）

- [ ] 实现子代理派发：主代理可以将复杂任务委托给子代理
- [ ] 子代理有独立上下文，执行完毕后返回结果
- [ ] 参考 `claude-code-from-scratch/python/mini_claude/subagent.py`

### 3.3 Plan Mode（规划模式）

- [ ] 复杂任务先出计划，用户确认后再执行
- [ ] 参考 claude-code-from-scratch 的 plan mode 实现

### 3.4 MCP 支持

- [ ] 实现 MCP 客户端，连接外部 MCP 服务器
- [ ] 将 MCP 提供的工具注册到本地工具列表
- [ ] 参考 `claude-code-from-scratch/python/mini_claude/mcp_client.py` 和 `Shinsekai/llm/tools/mcp_bridge.py`

---

## 第四阶段：通用接口与 UI

### 4.1 多 LLM 提供商适配器

- [ ] 抽象 LLM 适配器基类（统一 chat/completion 接口）
- [ ] 实现至少 3 个适配器：OpenAI、DeepSeek、Claude（Anthropic）
- [ ] 参考 `Shinsekai/llm/llm_adapter.py` 的工厂模式

### 4.2 插件系统

- [ ] 定义插件接口（可贡献：LLM 适配器、工具、UI 组件）
- [ ] 实现插件发现与加载
- [ ] 参考 `Shinsekai/core/plugins/plugin_host.py` 和 `Shinsekai/sdk/`

### 4.3 用户界面

- [ ] 先做 CLI（快速验证所有功能）
- [ ] 再做 Web UI（Gradio/Streamlit 快速原型 → 正式 Web 框架）
- [ ] 桌面 GUI 放在最后（PySide6 学习成本高）

---

## 通用开发建议（来自经验教训）

### 架构方面

1. **适配器模式是银弹**：任何和外部系统的交互都用适配器封装。这样换模型、换 TTS 引擎、换数据库都不需要改核心逻辑。

2. **队列解耦**：Shinsekai 的 Worker 管道模式（Queue → Worker → Queue → Worker）非常适合实时交互场景——LLM 生成慢不会阻塞 UI 刷新。

3. **配置即代码**：用 YAML + Pydantic 做配置校验（参考 `Shinsekai/config/schema.py`），避免"配错了一个 key 导致运行时崩溃"。

### Agent 特有陷阱

4. **工具调用的 JSON 解析是坑**：LLM 不一定返回合法的 JSON。需要做容错——正则提取、重试、给 LLM 报错让它自己修复。这是 claude-code-from-scratch 花了很多精力处理的部分。

5. **Token 预算管理是核心**：对话历史会越来越长，必须做压缩。Shinsekai 的 `compact_manager.py` 和 claude-code-from-scratch 的 context compaction 都是关键参考。

6. **工具调用的死循环**：LLM 可能反复调用同一个工具得不到想要的结果。需要设置最大工具调用轮数（建议 10 轮以内）。

7. **流式输出 + 工具调用的冲突**：流式模式下工具调用信号可能在任意位置出现，需要专门的拦截逻辑。参考 `Shinsekai/llm/llm_manager.py` 的 `_chat_with_tools_stream()`。

### 项目管理

8. **测试从第一天写起**：Agent 行为难以手动验证，自动测试是必须的。Shinsekai 的 mock adapter 模式（`test/conftest.py`）让你可以不花 API 费用跑测试。

9. **提交粒度要小**：每完成一个独立功能就提交，方便回退。"能跑的代码 + 一次提交" 好过 "半成品 + 攒了一周"。

10. **先用别人的模型，别自己训**：LLM API 已经很便宜了，把精力放在 Agent 架构上，而不是模型训练/微调上。

---

## 建议阅读顺序

1. `claude-code-from-scratch/docs/01-agent-loop.md` — 理解 Agent 循环的本质
2. `claude-code-from-scratch/docs/02-tools.md` — 理解工具调用机制
3. `claude-code-from-scratch/python/mini_claude/agent.py` — 看一个不到 300 行的 Agent 实现
4. `Shinsekai/CLAUDE.md` — 了解 Shinsekai 的完整架构
5. `Shinsekai/llm/llm_manager.py` — 了解多提供商适配器 + 流式工具拦截

---

## 进度追踪

| 阶段 | 状态 | 开始日期 | 完成日期 |
|------|------|---------|---------|
| 1.1 最简 Agent 循环 | ⬜ 未开始 | - | - |
| 1.2 System Prompt | ✅ 已完成 | 2026-05-20 | 2026-05-20 |
| 1.3 第一个工具 | ⬜ 未开始 | - | - |
| 2.1 角色记忆 | ⬜ 未开始 | - | - |
| 2.2 情绪系统 | ⬜ 未开始 | - | - |
| 2.3 TTS/ASR | ⬜ 未开始 | - | - |
| 3.1 完善工具系统 | ⬜ 未开始 | - | - |
| 3.2 子代理 | ⬜ 未开始 | - | - |
| 3.3 Plan Mode | ⬜ 未开始 | - | - |
| 3.4 MCP 支持 | ⬜ 未开始 | - | - |
| 4.1 多 LLM 适配器 | ⬜ 未开始 | - | - |
| 4.2 插件系统 | ⬜ 未开始 | - | - |
| 4.3 用户界面 | ⬜ 未开始 | - | - |
