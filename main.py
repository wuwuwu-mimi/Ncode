import asyncio
from dotenv import load_dotenv
load_dotenv()

from src.core.app import CoreApp
from src.core.transport.socket_client import SocketClient


async def test():
    # 后台启动 daemon
    app = CoreApp()
    daemon_task = asyncio.create_task(app.run())
    await asyncio.sleep(0.3)
    port = app._config.port
    print(f"Daemon 已启动: 127.0.0.1:{port}")

    # 客户端连接
    client = SocketClient("127.0.0.1", port)

    events: list[str] = []
    async def on_event(ev):
        events.append(ev["type"])
        print(f"  ← 事件: {ev['type']}")

    client.on_event(on_event)
    await client.connect()
    print("客户端已连接")

    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        sub = await client.send_command("event.subscribe", {"topics": ["*"]})
        print(f"订阅: {sub}")

        pong = await client.send_command("core.ping", {"client": "cli-test"})
        print(f"Ping: {pong}")

        print("\n🚀 启动 agent run...")
        run_result = await client.send_command("agent.run", {
            "goal": "用一句话介绍你自己"
        })
        print(f"Run: {run_result}")
        await asyncio.sleep(5)

        print(f"\n收到 {len(events)} 个事件: {events}")
    finally:
        loop_task.cancel()
        await client.close()
        daemon_task.cancel()


if __name__ == "__main__":
    asyncio.run(test())
