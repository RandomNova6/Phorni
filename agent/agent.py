import asyncio
import json
import os
from pathlib import Path
from openai import AsyncOpenAI

from .prompts import build_system_prompt
from .tools import (
    tool_definitions,
    execute_tool,
    CONCURRENCY_SAFE_TOOLS,
    check_permission,
    )

class Agent:
    def __init__(self, *, api_key: str, base_url: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self._base_system_prompt = build_system_prompt()
        self.context: list[dict] = [
            {"role": "system", "content": self._base_system_prompt}
        ]
        self.tools=tool_definitions

        #safety
        self._confirmed_paths: set[str] = set()
        self.permission_mode="default"
        self._workspace_root=Path.cwd().resolve()
        self._plan_file_path: str | None = None
        self._pre_plan_mode: str | None = None
        self.confirm_fn = None
        
        #compact conversation
        self.effective_window=1024 * 1024  # DeepSeek V4 1M context window
        self.last_input_token_count=0

    async def _chat_openai(self, user_message: str) -> str:
        self.context.append({"role": "user", "content": user_message})
        await self._check_and_compact()

        while True:
            response = await self._call_openai_stream()
            content = response["content"]
            tool_calls = response["tool_calls"]
            reasoning = response["reasoning_content"]
            self.last_input_token_count = response["usage"].get("prompt_tokens", 0)
            print(f"\n[Prompt tokens this turn: {self.last_input_token_count} | Context limit: {self.effective_window}]\n")

            # 无工具调用、直接返回对话内容
            if not tool_calls:
                msg: dict = {"role": "assistant", "content": content}
                if reasoning:
                    msg["reasoning_content"] = reasoning
                self.context.append(msg)
                return content

            # 有工具调用，返回工具调用信息
            msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            if reasoning:
                msg["reasoning_content"] = reasoning
            self.context.append(msg)

            oai_batches: list[dict] = []
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                inp = json.loads(tc["function"]["arguments"])

                # Plan mode tools: intercepted before permission check (state switch handled in agent)
                if tool_name in ("enter_plan_mode", "exit_plan_mode"):
                    result = await self._execute_plan_mode_tool(tool_name, inp)
                    self.context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                    continue

                # Layer 1: permission rules
                perm = check_permission(tool_name, inp, self.permission_mode, self._plan_file_path)
                if perm["action"] == "deny":
                    print(f"Denied: {perm.get('message', '')}")
                    self.context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": f"Action denied: {perm.get('message', '')}",
                    })
                    continue
                
                if perm["action"] == "confirm" and perm.get("message") and perm["message"] not in self._confirmed_paths:
                    confirmed = await self._confirm_dangerous(perm["message"])
                    if not confirmed:
                        self.context.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "User denied this action.",
                        })
                        continue
                    self._confirmed_paths.add(perm["message"])

                # Layer 2: sandbox path resolution (applies to ALL file operations)
                sandbox_error = None
                if "file_path" in inp:
                    try:
                        inp["file_path"] = str(self._resolve_and_check(inp["file_path"]))
                    except PermissionError as e:
                        sandbox_error = str(e)

                if sandbox_error:
                    self.context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": sandbox_error,
                    })
                    continue

                # Lock shell commands to workspace
                if tool_name == "run_shell":
                    inp["_cwd"] = str(self._workspace_root)

                # Group by concurrency safety
                safe = tool_name in CONCURRENCY_SAFE_TOOLS
                if oai_batches and oai_batches[-1]["concurrent"] and safe:
                    oai_batches[-1]["items"].append((tc, inp))
                else:
                    oai_batches.append({"concurrent": safe, "items": [(tc, inp)]})

            # 按批次异步执行
            for batch in oai_batches:
                if batch["concurrent"]:
                    async def _exec_one(tc, inp):
                        t_name = tc["function"]["name"]
                        result = await execute_tool(t_name, inp)
                        print(f"\n[tool] {t_name}({inp}) → {result[:200]}...")
                        return (tc["id"], result)

                    results = await asyncio.gather(*[_exec_one(tc, inp) for tc, inp in batch["items"]])
                    for tc_id, result in results:
                        self.context.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": result,
                        })
                else:
                    for tc, inp in batch["items"]:
                        t_name = tc["function"]["name"]
                        result = await execute_tool(t_name, inp)
                        print(f"\n[tool] {t_name}({inp}) → {result[:200]}...")
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
            stream_options={"include_usage": True},
        )

        content: list[str] = []
        reasoning: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        first_word = True
        usage: dict[str, int] = {}
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }

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
            "usage": usage,
        }
    
    async def _confirm_dangerous(self, command: str) -> bool:
        print(command)
        if self.confirm_fn:
            return await self.confirm_fn(command)
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False


    def _generate_plan_file_path(self) -> str:
        import time
        d = self._workspace_root / "plans"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / f"plan-{int(time.time())}.md")

    def _build_plan_mode_prompt(self) -> str:
        return f"""

# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), run non-readonly tools, or make any changes to the system.

## Plan File: {self._plan_file_path}
Write your plan incrementally to this file using write_file or edit_file. This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, list_files, grep_search.
2. **Design**: Design your implementation approach.
3. **Write Plan**: Write a structured plan to the plan file including context, steps, and verification.
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode."""

    async def _execute_plan_mode_tool(self, name: str, inp: dict) -> str:
        if name == "enter_plan_mode":
            if self.permission_mode == "plan":
                return "Already in plan mode."
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            # 用户指定了路径则使用，否则自动生成
            user_path = inp.get("plan_file_path")
            self._plan_file_path = str(Path(user_path).resolve()) if user_path else self._generate_plan_file_path()
            self.context[0]["content"] = self._base_system_prompt + self._build_plan_mode_prompt()
            print(f"Entered plan mode. Plan file: {self._plan_file_path}")
            return (
                f"Entered plan mode. You are now in read-only mode.\n\n"
                f"Your plan file: {self._plan_file_path}\n"
                f"Write your plan to this file. This is the only file you can edit.\n\n"
                f"When your plan is complete, call exit_plan_mode."
            )

        if name == "exit_plan_mode":
            if self.permission_mode != "plan":
                return "Not in plan mode."
            plan_content = "(No plan file found)"
            if self._plan_file_path and Path(self._plan_file_path).exists():
                plan_content = Path(self._plan_file_path).read_text(encoding="utf-8")
            self.permission_mode = self._pre_plan_mode or "default"
            self._pre_plan_mode = None
            self._plan_file_path = None
            self.context[0]["content"] = self._base_system_prompt
            print(f"Exited plan mode. Restored to {self.permission_mode}.")
            return (
                f"Exited plan mode. Permission mode restored to: {self.permission_mode}\n\n"
                f"## Your Plan:\n{plan_content}"
            )

        return f"Unknown plan mode tool: {name}"

    def _resolve_and_check(self,file_path: str) -> Path:
        p = Path(file_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        resolved = p.resolve()

        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            raise PermissionError(
                f"Access denied: '{file_path}' is outside workspace '{self._workspace_root}'"
            )
        return resolved
    
    async def _check_and_compact(self) -> None:
        if self.last_input_token_count > self.effective_window * 0.85:
            print("Context window filling up, compacting conversation...")
            await self._compact_openai()

    async def _compact_openai(self) -> None:
        if len(self.context) < 5:
            return

        system_msg = self.context[0]
        last_user_msg = self.context[-1]

        summary_resp = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer. Be concise but preserve important details."},
                *self.context[1:-1],
                {"role": "user", "content": "Summarize the conversation so far..."},
            ],
        )
        summary_text = summary_resp.choices[0].message.content or "No summary available."

        self.context = [
            system_msg,
            {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
            {"role": "assistant", "content": "Understood. I have the context..."},
        ]

        if last_user_msg.get("role") == "user":
            self.context.append(last_user_msg)
        self.last_input_token_count = 0
