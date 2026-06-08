import asyncio
from dotenv import load_dotenv
load_dotenv()

from src.core.app import CoreApp
from src.core.transport.socket_client import SocketClient


async def test():
    # 1. 后台启动 daemon
    app = CoreApp()
    daemon_task = asyncio.create_task(app.run())

    # 等 daemon 启动
    await asyncio.sleep(0.3)
    port = app._config.port
    print(f"Daemon 已启动: 127.0.0.1:{port}")

    # 2. 客户端连接
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
        # 3. 订阅事件
        sub = await client.send_command("event.subscribe", {"topics": ["*"]})
        print(f"订阅: {sub}")

        # 4. 发 ping
        pong = await client.send_command("core.ping", {"client": "cli-test"})
        print(f"Ping: {pong}")

        # 5. 发 agent.run
        print("\n🚀 启动 agent run...")
        run_result = await client.send_command("agent.run", {
            "goal": "用一句话介绍你自己"
        })
        print(f"Run: {run_result}")

        # 等 agent 跑完（事件会实时推送）
        await asyncio.sleep(8)

        print(f"\n收到 {len(events)} 个事件: {events}")
    finally:
        loop_task.cancel()
        await client.close()
        daemon_task.cancel()


if __name__ == "__main__":
    asyncio.run(test())
