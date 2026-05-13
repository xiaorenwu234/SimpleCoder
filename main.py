from agent import Agent
import asyncio


async def async_main():
    agent = Agent()
    await agent.initialize()
    await agent.run()
    await agent.close()


if __name__ == "__main__":
    asyncio.run(async_main())
