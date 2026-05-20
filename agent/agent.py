import json
from openai import AsyncOpenAI
from .prompts import build_system_prompt
from .tools import (
    tool_definitions,
    execute_tool
    )

class Agent:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.context: list[dict] = [
            {"role": "system", "content": build_system_prompt()}
        ]
        self.tools=tool_definitions

    async def _chat_openai(self, user_message: str) -> str:
        self.context.append({"role": "user", "content": user_message})

        while True:
            response = await self._call_openai_stream()
            content = response["content"]
            tool_calls = response["tool_calls"]
            reasoning = response["reasoning_content"]

            if not tool_calls:
                msg: dict = {"role": "assistant", "content": content}
                if reasoning:
                    msg["reasoning_content"] = reasoning
                self.context.append(msg)
                return content

            msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            if reasoning:
                msg["reasoning_content"] = reasoning
            self.context.append(msg)

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"]["arguments"])
                result = await execute_tool(tool_name, tool_args)
                print(f"\n[tool] {tool_name}({tool_args}) → {result[:200]}...")
                self.context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

    async def _call_openai_stream(self) -> dict:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=self.context,
            stream=True,
            tools=self.tools,
        )

        content: list[str] = []
        reasoning: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        first_word = True
        async for chunk in stream:
            delta = chunk.choices[0].delta

            if getattr(delta, "reasoning_content", None):
                reasoning.append(delta.reasoning_content)

            if delta.content:
                text = delta.content
                if first_word:
                    text = text.lstrip("\n")
                    if not text:
                        continue
                    first_word = False
                print(text, end="", flush=True)
                content.append(text)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": tc.id or "",
                            "type": "function",
                            "function": {
                                "name": tc.function.name if tc.function else "",
                                "arguments": "",
                            },
                        }
                    if tc.function and tc.function.arguments:
                        tool_calls_by_index[idx]["function"]["arguments"] += tc.function.arguments

        print()
        return {
            "content": "".join(content),
            "tool_calls": [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)],
            "reasoning_content": "".join(reasoning) if reasoning else "",
        }
