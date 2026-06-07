import asyncio
from dotenv import load_dotenv
load_dotenv()

from src.core.events.bus import EventBus
from src.core.llm.provider import DeepSeekProvider
from src.core.tools.builtin.get_time import GetTimeTool
from src.core.tools.registry import ToolRegistry
from src.core.context import ExecutionContext
from src.core.loop import AgentLoop


async def test():
    bus = EventBus()

    # 详细打印事件
    async def print_event(event):
        ev = event.model_dump()
        etype = ev["type"]
        if etype == "step.started":
            print(f"\n{'='*50}")
            print(f"📍 Step {ev['step']} 开始")
            print(f"{'='*50}")
        elif etype == "llm.token":
            print(ev["token"], end="", flush=True)
        elif etype == "llm.usage":
            print(f"\n📊 用量: input={ev['input_tokens']} output={ev['output_tokens']}")
        elif etype == "tool.call_started":
            print(f"\n🔧 调用工具: {ev['tool_name']}({ev['params']})")
        elif etype == "tool.call_finished":
            output = ev.get("output", "")
            print(f"✅ 工具结果: {output[:200]}")
        elif etype == "step.finished":
            print(f"\n✅ Step 完成\n")

    bus.subscribe(print_event)

    # 注册工具
    registry = ToolRegistry()
    registry.register(GetTimeTool())

    # LLM provider
    provider = DeepSeekProvider(model="deepseek-v4-flash")

    # 创建执行上下文
    context = ExecutionContext(
        run_id="test-loop-1",
        goal="当前北京时间是几点几分？今天是几月几号？星期几？",
        max_steps=5,
    )

    # 创建 AgentLoop 并运行
    loop = AgentLoop(provider, registry, bus)
    print(f"🚀 目标: {context.goal}")
    await loop.run(context)

    # 结果
    print(f"\n{'='*50}")
    print(f"🏁 运行完成")
    print(f"   状态: {context.status}")
    print(f"   步数: {context.step}")
    print(f"   回答: {context.result}")
    print(f"   消息数: {len(context.messages)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(test())
