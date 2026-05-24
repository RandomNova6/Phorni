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

async def helloworld_test():
    await agent._chat_openai("帮我在当前文件夹下写一个文件，名叫helloworld.py,并带有print('helloworld')的功能")
    await agent._chat_openai("帮我改成打印'hello Phorni',并执行")

async def chat_test():
    await agent._chat_openai("我是Nova")
    await agent._chat_openai("有没有什么新鲜事呀")

async def planmode_test():
    await agent._chat_openai("我是Nova")
    await agent._chat_openai("在计划模式中策划一个简单的写诗教程")

async def main():
    await agent._chat_openai("你好")
    await chat_test()

asyncio.run(main())