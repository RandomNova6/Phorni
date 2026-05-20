# 手写 Agent 异步指南

以你当前的 `agent.py` 为起点，逐层讲清楚每一步"为什么这么写"。

---

## 第 0 层：先搞清楚 `async` / `await` 是什么

### 一句话

`async def` 定义一个"可以暂停"的函数。`await` 在某个慢操作（网络请求）前说"我先去干别的，你好了叫我"。

### 三个关键规则

```python
# 规则 1：async 函数不能直接调用，必须 await 或 asyncio.run()
async def foo():
    return 1

foo()         # 错——返回 coroutine 对象，不会执行
await foo()   # 对——但只能在另一个 async 函数里用 await
asyncio.run(foo())  # 对——在普通代码里启动 async 函数
```

```python
# 规则 2：await 只能出现在 async def 内部
def normal():
    await something()  # SyntaxError

async def coroutine():
    await something()  # OK
```

```python
# 规则 3：async 会传染——一旦一个函数是 async，
# 调用它的函数也必须是 async（除非用 asyncio.run）
async def call_api():
    ...

async def chat():
    await call_api()  # 必须 await

def main():
    asyncio.run(chat())  # 最外层用 asyncio.run 启动
```

### 为什么 Agent 必须用 async

你的 Agent 需要同时做多件事：

- 等 LLM 回复（网络 IO，慢）
- 流式打印输出（用户体验）
- 执行工具调用（可能并行多个）
- 响应用户取消（按 Esc 停止）

同步代码下这些都是"一件事做完才做下一件"——用户要等很久。async 让这些事可以交错进行。

---

## 第 1 层：最简同步调用（别急着异步）

先把"能对话"跑通，用最简单的同步方式：

```python
from openai import OpenAI

class Agent:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.context = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

    def chat(self, user_message: str) -> str:
        # 1. 把用户消息加入上下文
        self.context.append({"role": "user", "content": user_message})

        # 2. 调用 API（同步，阻塞等待）
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.context,
        )

        # 3. 取出回复
        content = response.choices[0].message.content

        # 4. 把助手回复也加入上下文（维持多轮对话）
        self.context.append({"role": "assistant", "content": content})

        return content
```

**关键点说明**：

| 行 | 说明 |
|---|------|
| `self.context = [{...}]` | `messages` 参数需要一个**列表**，不是裸字符串。每条消息是 `{"role": ..., "content": ...}` |
| `self.context.append(user_msg)` | 多轮对话的核心——每次把新消息追加进去，LLM 才能"记住"之前说过什么 |
| `self.context.append(assistant_msg)` | 这步很关键。如果不加，LLM 下次会"忘记自己刚才说过什么" |
| `stream=False`（默认） | 完整回复一次返回，简单直接 |

### `__main__.py` 启动

```python
from agent.agent import Agent

agent = Agent(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
)

# 同步调用，不需要 asyncio.run
response = agent.chat("你好！")
print(response)

response = agent.chat("刚才我说了什么？")  # 多轮对话
print(response)
```

---

## 第 2 层：升级到异步（只改 3 个地方）

当 Agent 需要同时处理多个用户、或者你想在等回复时做其他事，再升级：

```python
from openai import AsyncOpenAI  # ← 改动 1：用 AsyncOpenAI

class Agent:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)  # ← AsyncOpenAI
        self.model = model
        self.context = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

    async def chat(self, user_message: str) -> str:  # ← 改动 2：async def
        self.context.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(  # ← 改动 3：await
            model=self.model,
            messages=self.context,
        )

        content = response.choices[0].message.content
        self.context.append({"role": "assistant", "content": content})
        return content
```

**三处改动**：
1. `from openai import AsyncOpenAI`
2. `async def chat(self, ...)`
3. `await self.client.chat.completions.create(...)`

其他逻辑完全不变。

### 对应的 `__main__.py`

```python
import asyncio
from agent.agent import Agent

async def main():
    agent = Agent(api_key="sk-xxx", base_url="...", model="...")
    response = await agent.chat("你好！")
    print(response)

asyncio.run(main())
```

---

## 第 3 层：流式输出（真正的 streaming）

流式的核心思想：**不等模型生成完，收到一个字就打印一个字**。

### 异步迭代器

```python
# stream=True 返回的是一个 async iterator
stream = await self.client.chat.completions.create(
    model=self.model,
    messages=self.context,
    stream=True,  # ← 开启流式
)

# 用 async for 逐块消费
async for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

**注意**：`stream=True` 时不能用 `response.choices[0].message.content` 取完整内容——因为此时还没有"完整内容"。你必须自己拼接：

```python
async def chat(self, user_message: str) -> str:
    self.context.append({"role": "user", "content": user_message})

    stream = await self.client.chat.completions.create(
        model=self.model,
        messages=self.context,
        stream=True,
    )

    full_content = ""  # 手动拼接
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            full_content += delta.content

    print()  # 换行
    self.context.append({"role": "assistant", "content": full_content})
    return full_content
```

### 流式中处理 tool_calls（预告）

当 LLM 决定调用工具时，流式中 `delta.tool_calls` 会分片到达：

```python
tool_calls_buffer: dict[int, dict] = {}

async for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.tool_calls:
        for tc in delta.tool_calls:
            idx = tc.index
            if idx not in tool_calls_buffer:
                tool_calls_buffer[idx] = {
                    "id": tc.id or "",
                    "function": {"name": tc.function.name if tc.function else "", "arguments": ""}
                }
            if tc.function and tc.function.arguments:
                tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments
```

这个先了解即可，到实现工具调用时再深究。

---

## 第 4 层：Agent 循环（真正让 Agent "做事"）

前面只是"一问一答"。Agent 循环是：

```
用户输入 → LLM 回复（可能调用工具）→ 执行工具 → 把结果告诉 LLM → LLM 再回复 → ...
                                                        ↑_____________________________↓
                                                        （循环，直到 LLM 不再调用工具）
```

### 核心代码

```python
async def chat(self, user_message: str) -> str:
    self.context.append({"role": "user", "content": user_message})

    while True:  # ← Agent 循环
        # 1. 收集流式回复（可能是文本，也可能是 tool_calls）
        content, tool_calls = await self._call_llm_stream()

        # 2. 把助手消息加入上下文
        assistant_msg = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        self.context.append(assistant_msg)

        # 3. 如果没有工具调用，对话结束
        if not tool_calls:
            return content or ""

        # 4. 执行每个工具，收集结果
        for tc in tool_calls:
            tool_name = tc["function"]["name"]
            tool_args = json.loads(tc["function"]["arguments"])
            tool_result = await self._execute_tool(tool_name, tool_args)

            self.context.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

        # 5. 循环继续——LLM 看到工具结果后可能：
        #    - 调用更多工具 → 回到步骤 1
        #    - 给出最终回复 → 步骤 3 中 tool_calls 为空，return
```

**这个 `while True` 就是 Agent 的本质**——LLM 不再是"回答完就结束"，而是"调用工具→观察结果→继续思考→……"。

### 防止死循环

```python
MAX_TURNS = 10
turn_count = 0

while True:
    turn_count += 1
    if turn_count > MAX_TURNS:
        return "达到最大轮次限制，停止。"
    ...
```

---

## 你当前代码的具体问题和修复对照

| 你的代码 | 问题 | 修复 |
|---------|------|------|
| `self.context: list[dict] = build_system_prompt()` | `build_system_prompt()` 返回 `str`，不是 `list[dict]` | `[{"role": "system", "content": build_system_prompt()}]` |
| `async def chat(self)` 无参数 | 收不到用户输入 | `async def chat(self, user_message: str)` |
| `stream=True` 但 `return response` | 返回 Stream 对象而非文本 | 要么关掉 `stream=True`，要么用 `async for` 消费 |
| `reasoning_effort="high"` | DeepSeek 不支持这个参数 | 删掉 |
| `extra_body={"thinking": ...}` | 这是 Anthropic 的格式 | 删掉（或查 DeepSeek 文档确认格式） |
| `agent.chat()` 无 `await` | 返回 coroutine 对象 | `await agent.chat(...)` 在 async 上下文中调用 |
| `__main__.py` 不是 async | 顶层不能直接 await | `def main(): asyncio.run(amain())` |
| `prompts.py:load_claude_md()` 128-129 行缩进 | `return` 写在 `while` 循环里面 | `return` 缩进到与 `while` 平级 |

---

## 建议的开发顺序

```
第 1 层：同步一问一答（30 行）     ← 先跑通这个
第 2 层：改成异步（改 3 处）       ← 10 分钟
第 3 层：加上流式输出              ← 30 分钟
第 4 层：加入 Agent 循环 + 工具    ← 项目的核心，花最多时间打磨
```

每层都确认能跑，再进下一层。不要跳步。
