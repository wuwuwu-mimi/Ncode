from __future__ import annotations

import asyncio
import logging
import signal
import time

from pathlib import Path

from core.bus.commands import AgentRunCommand, AgentRunResult, PongResult
from core.bus.events import CoreStartedEvent
from core.config import CodeConfig, get_config
from core.events.bus import EventBus
from core.permissions.manager import PermissionManager
from core.runner import AgentRunner
from core.transport.ipc_broadcaster import IpcEventBroadcaster
from core.transport.socket_server import SocketServer, get_connection_writer

logger = logging.getLogger(__name__)


class CoreApp:
    """守护进程入口：加载配置、组装所有模块、启动 TCP 服务器"""

    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self._bus = EventBus()
        self._broadcaster: IpcEventBroadcaster | None = None
        self._config: CodeConfig | None = None
        self._runner: AgentRunner | None = None

    # 处理 core.ping 请求
    async def _ping_handler(self, params: dict) -> PongResult:
        return PongResult(
            server_version="0.1.0",
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at="",  # 简化
        )

    # 处理 agent.run 请求：异步启动 agent run，立即返回 run_id
    async def _agent_run_handler(self, params: dict) -> AgentRunResult:
        assert self._runner is not None
        cmd = AgentRunCommand.model_validate(params)
        run_task = asyncio.create_task(
            self._runner.run_and_capture(cmd.goal)
        )
        return AgentRunResult(run_id="run-pending")  # 简化：后续改进

    # 处理 event.subscribe 请求：注册客户端事件订阅
    async def _subscribe_handler(self, params: dict) -> dict:
        assert self._broadcaster is not None
        writer = get_connection_writer()
        topics = params.get("topics", ["*"])
        scope = params.get("scope", "global")
        sub_id = self._broadcaster.subscribe(writer, topics, scope)
        return {"subscription_id": sub_id, "replayed_count": 0}

    # 启动守护进程
    async def run(self) -> None:
        self._start_time = time.monotonic()
        self._config = get_config()

        # 事件总线 + 广播器（事件 → TCP 推送）
        self._broadcaster = IpcEventBroadcaster()
        self._bus.subscribe(self._broadcaster.handle)

        # 权限管理器（读取 ~/.kama/policy.toml）
        policy_file = Path("~/.kama/policy.toml").expanduser()
        permission_manager = PermissionManager(policy_file=policy_file)

        # AgentRunner
        self._runner = AgentRunner(
            self._config, bus=self._bus,
            permission_manager=permission_manager,
        )

        # TCP 服务器
        server = SocketServer(
            self._config.host,
            self._config.port,
            broadcaster=self._broadcaster,
        )
        server.register("core.ping", self._ping_handler)
        server.register("agent.run", self._agent_run_handler)
        server.register("event.subscribe", self._subscribe_handler)

        addr = await server.start()
        logger.info("kama-core listening on %s", addr)
        logger.info("config: host=%s port=%s model=%s",
                     self._config.host, self._config.port, self._config.llm.default_model)

        # 发布启动事件
        await self._bus.publish(CoreStartedEvent(
            listen_addr=addr,
            version="0.1.0",
        ))

        # 等待退出信号
        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, shutdown.set)
        loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()

        logger.info("shutting down")
        await server.stop()


# 同步入口
def run() -> None:
    asyncio.run(CoreApp().run())
