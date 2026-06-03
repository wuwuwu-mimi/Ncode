import asyncio

from src.core.transport.socket_server import SocketServer, get_connection_writer
from src.core.transport.socket_client import SocketClient
from src.core.transport.ipc_broadcaster import IpcEventBroadcaster
from src.core.events.bus import EventBus
from src.core.bus.commands import PingCommand, PongResult
from src.core.bus.events import CoreStartedEvent


# ── 事件推送流程测试 ──
# 链路: ping_handler → EventBus.publish → IpcEventBroadcaster.handle → TCP → 客户端 on_event

async def test():
    # 1. 创建事件总线 + 广播器，串联
    bus = EventBus()
    broadcaster = IpcEventBroadcaster()
    bus.subscribe(broadcaster.handle)  # EventBus 上的事件 → 推送给 TCP 客户端

    # 2. 启动服务端（带 broadcaster，用于客户端断开时清理订阅）
    server = SocketServer("127.0.0.1", 7437, broadcaster=broadcaster)

    # 注册 core.ping：校验参数，发布事件，返回 pong
    async def ping_handler(params: dict) -> dict:
        cmd = PingCommand.model_validate(params)
        # ★ 发布事件 — 这会触发 EventBus → Broadcaster → 所有订阅的客户端
        await bus.publish(CoreStartedEvent(
            listen_addr="127.0.0.1:7437",
            version="0.1.0",
        ))
        return PongResult(
            server_version="0.1.0",
            uptime_ms=1234,
            received_at="2025-01-01T00:00:00Z",
        ).model_dump()

    # 注册 event.subscribe：客户端订阅事件流
    async def subscribe_handler(params: dict) -> dict:
        writer = get_connection_writer()  # 获取当前客户端 TCP 连接
        topics = params.get("topics", ["*"])
        scope = params.get("scope", "global")
        sub_id = broadcaster.subscribe(writer, topics, scope)
        return {"subscription_id": sub_id, "replayed_count": 0}

    server.register("core.ping", ping_handler)
    server.register("event.subscribe", subscribe_handler)
    addr = await server.start()
    print(f"服务端启动: {addr}")

    # 3. 客户端连接
    client = SocketClient("127.0.0.1", 7437)
    await client.connect()
    print("客户端已连接")

    # 注册接收事件的回调
    received_events: list[dict] = []

    async def on_event(event_data: dict) -> None:
        received_events.append(event_data)
        print(f"  ← 客户端收到事件: type={event_data['type']}")

    client.on_event(on_event)

    # 4. 后台 task 跑读循环
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        # 5. 订阅事件（topic="*" 匹配所有事件）
        sub_result = await client.send_command("event.subscribe", {
            "topics": ["*"],
            "scope": "global",
        })
        print(f"订阅事件成功: {sub_result}")

        # 6. 发送 ping（服务端在 ping_handler 里发布 CoreStartedEvent）
        ping_result = await client.send_command("core.ping", {"client": "test"})
        print(f"ping 响应: {ping_result}")

        # 等待事件推送到达
        await asyncio.sleep(0.1)

        # 7. 验证
        print(f"\n共收到 {len(received_events)} 个事件")
        for ev in received_events:
            print(f"  - {ev['type']}: {ev}")
    finally:
        loop_task.cancel()
        await client.close()
        await server.stop()
        print("已关闭")


if __name__ == "__main__":
    asyncio.run(test())
