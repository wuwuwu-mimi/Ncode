import asyncio
from src.core.transport.socket_server import SocketServer
from src.core.transport.socket_client import SocketClient


# ping 请求处理函数，返回服务信息
async def ping_handler(params: dict) -> dict:
    return {"server_version": "0.1.0", "uptime_ms": 1234}


async def test():
    # 1. 启动服务端
    server = SocketServer("127.0.0.1", 7437)
    server.register("core.ping", ping_handler)
    addr = await server.start()
    print(f"服务端启动: {addr}")

    # 2. 启动客户端
    client = SocketClient("127.0.0.1", 7437)
    await client.connect()
    print("客户端已连接")

    # 3. 后台 task 跑读循环（必需！否则没人消费响应）
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        # 4. 发 ping 请求
        result = await client.send_command("core.ping", {"client": "test"})
        print(f"收到响应: {result}")
    finally:
        # 5. 清理
        loop_task.cancel()
        await client.close()
        await server.stop()
        print("已关闭")


if __name__ == "__main__":
    asyncio.run(test())
