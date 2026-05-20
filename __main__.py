import os
import asyncio
from dotenv import load_dotenv
from agent.agent import Agent

load_dotenv()

agent = Agent(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
)


async def main():
    await agent._chat_openai("你好")
    await agent._chat_openai("帮我在当前文件夹下写一个文件，名叫helloworld.py,并带有print('helloworld')的功能")
    await agent._chat_openai("帮我改成打印'hello Phorni',并执行")

asyncio.run(main())
