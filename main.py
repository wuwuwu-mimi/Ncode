import asyncio

from dotenv import load_dotenv

load_dotenv()

from src.core.events.bus import EventBus
from src.core.llm.provider import DeepSeekProvider


async def test():
    bus = EventBus()

    # 收集事件，验证 provider 是否正确发布了事件
    events: list[str] = []
    tests: list[str] = []

    async def collect(event):
        events.append(event.model_dump()["type"])

    async def test(event):
        tests.append("test")

    bus.subscribe(collect)
    bus.subscribe(test)

    # 创建 DeepSeek provider
    provider = DeepSeekProvider(model="deepseek-v4-flash")

    # 最简单的对话测试：不传 tools，让 LLM 直接回答
    response = await provider.chat(
        messages=[{"role": "user", "content": "用一句话介绍你自己"}],
        tool_schemas=[],
        bus=bus,
        run_id="test-run-1",
    )

    print(f"stop_reason: {response.stop_reason}")
    print(f"text: {response.text}")
    print(f"tool_calls: {response.tool_calls}")
    print(f"usage: {response.usage}")
    print(f"发布的事件: {events}")

    print(f"测试的事件{tests}")


if __name__ == "__main__":
    asyncio.run(test())
