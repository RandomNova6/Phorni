# 工具调用实现指南

当前状态：`agent.py` 能对话，`tools.py` 有 6 个工具定义和执行函数。下一步是把两者接起来——让 LLM 能"看到"工具，能"决定"调用工具，Agent 能"执行"工具并把结果传回去。

---

## 1. 工具调用的完整生命周期

```
① 把工具定义发给 API    →  LLM 决定调用 read_file("CLAUDE.md")
② 从响应中提取 tool_calls →  {"name": "read_file", "arguments": {"file_path": "CLAUDE.md"}}
③ 执行工具                →  _read_file({"file_path": "CLAUDE.md"}) → "1| # CLAUDE.md\n2| ..."
④ 把结果作为 tool 消息追加 →  {"role": "tool", "tool_call_id": "xxx", "content": "1| ..."}
⑤ 继续对话                →  LLM 看到结果后直接回复或调用更多工具
```

---

## 2. 步骤①：把工具定义发给 API

在调用 `chat.completions.create` 时加 `tools` 参数：

```python
stream = await self.client.chat.completions.create(
    model=self.model,
    messages=self.context,
    tools=tool_definitions,    # ← 来自 tools.py 的 6 个工具 Schema
    stream=True,
)
```

你的 `tool_definitions` 已经是 OpenAI 格式（`{"type": "function", "function": {...}}`），可以直接传。

---

## 3. 步骤②：从流式响应中提取 tool_calls

这是最关键的部分。工具调用在流式响应中是**分片到达**的——一个 tool_call 的 id、name、arguments 可能分布在多个 chunk 中。

### 数据结构

每个 chunk 的 `delta.tool_calls` 长这样：

```python
# Chunk 1: 工具开始
delta.tool_calls = [
    {"index": 0, "id": "call_abc123", "function": {"name": "read_file", "arguments": ""}}
]

# Chunk 2: arguments 片段
delta.tool_calls = [
    {"index": 0, "function": {"arguments": '{"file_'}}
]

# Chunk 3: 更多 arguments
delta.tool_calls = [
    {"index": 0, "function": {"arguments": 'path":'}}
]

# Chunk N: 最后一段 arguments
delta.tool_calls = [
    {"index": 0, "function": {"arguments": ' "CLAUDE.md"}'}}
]
```

### 累积逻辑

用一个 dict 按 `index` 累积每个工具调用的碎片：

```python
tool_calls_by_index: dict[int, dict] = {}

async for chunk in stream:
    delta = chunk.choices[0].delta

    if delta.content:
        # 文本部分照常打印
        ...

    if delta.tool_calls:
        for tc in delta.tool_calls:
            idx = tc.index
            if idx not in tool_calls_by_index:
                # 第一次出现：记录 id 和 name
                tool_calls_by_index[idx] = {
                    "id": tc.id or "",
                    "function": {
                        "name": tc.function.name if tc.function else "",
                        "arguments": "",
                    },
                }
            # 每次都要追加 arguments 片段
            if tc.function and tc.function.arguments:
                tool_calls_by_index[idx]["function"]["arguments"] += tc.function.arguments
```

---

## 4. 步骤③：执行工具

从累积的 tool_calls 中提取完整参数，逐个执行：

```python
from agent.tools import execute_tool

for tc in sorted(tool_calls_by_index.values(), key=lambda x: int(x.get("index", 0))):
    tool_name = tc["function"]["name"]
    tool_args = json.loads(tc["function"]["arguments"])  # arguments 是 JSON 字符串
    result = await execute_tool(tool_name, tool_args)
```

---

## 5. 步骤④：把结果注入消息历史

OpenAI 的上下文格式要求工具结果以 `role: "tool"` 的消息追加：

```python
self.context.append({
    "role": "tool",
    "tool_call_id": tc["id"],
    "content": result,
})
```

---

## 6. 步骤⑤：Agent 循环（把上面串起来）

修改 `agent.py` 的 `chat` 方法，把"一问一答"升级为"循环直到 LLM 不再调工具"：

```python
async def chat(self, user_message: str) -> str:
    self.context.append({"role": "user", "content": user_message})

    while True:
        # 调用 API（带工具定义）
        content, tool_calls = await self._call_openai_with_tools()

        if not tool_calls:
            # LLM 给出了最终文本回复，结束
            self.context.append({"role": "assistant", "content": content})
            return content

        # 有工具调用：把 assistant 消息（含 tool_calls）加入上下文
        assistant_msg = {"role": "assistant", "content": content or None}
        assistant_msg["tool_calls"] = tool_calls
        self.context.append(assistant_msg)

        # 执行每个工具，结果加入上下文
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_args = json.loads(tc["function"]["arguments"])
            result = await execute_tool(tool_name, tool_args)
            self.context.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

        # 循环回到顶部——LLM 看到工具结果后决定下一步
```

### 循环示意图

```
用户问："读取 CLAUDE.md 的内容"
  ↓
LLM: tool_calls=[read_file("CLAUDE.md")]
  ↓
Agent 执行 read_file → 得到文件内容
  ↓
Agent 追加 tool 消息到上下文
  ↓
LLM: "该文件有 19 行，内容是..."  (没有更多工具调用)
  ↓
返回最终回复
```

### 死循环保护

LLM 可能反复调用同一个工具。加个上限：

```python
MAX_TOOL_TURNS = 10
turn = 0

while True:
    turn += 1
    if turn > MAX_TOOL_TURNS:
        return "达到最大工具调用轮次"
    ...
```

---

## 7. 具体修改清单（agent.py）

需要改的内容，按顺序：

### 7.1 导入 tools 模块

```python
from .tools import tool_definitions, execute_tool
```

### 7.2 chat 方法改为循环

`chat()` 不再是直接调 `_call_openai_stream()` 然后 return，而是包在 `while True` 里。

### 7.3 _call_openai_stream 改为返回 (content, tool_calls)

原来返回 `str`，现在需要同时返回工具调用信息。流式循环中需要加 `delta.tool_calls` 的累积逻辑（见第 3 节）。

### 7.4 处理"只有文本"和"只有工具调用"两种情况

LLM 的回复可能是：
- **纯文本**：`content` 有值，`tool_calls` 为空 → 对话结束
- **纯工具调用**：`content` 为空，`tool_calls` 有值 → 执行工具，继续循环
- **文本 + 工具调用**：两者都有 → 先保存文本，执行工具，继续循环

---

## 8. 建议的实现顺序

```
1. 先改 _call_openai_stream → _call_openai_with_tools
   加 tool_calls 累积逻辑，返回 (content, tool_calls)

2. 用 print 验证能正确提取 tool_calls
   先不执行工具，只打印 "LLM 想调用 xxx(params)"

3. 加上 execute_tool + tool 消息注入

4. 加上 while True 循环

5. 加上 MAX_TOOL_TURNS 保护
```

每步都跑一遍确认正确再进下一步。
