from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.bus.events import RunFinishedEvent, RunStartedEvent
from core.config import CodeConfig
from core.context import ExecutionContext
from core.events.bus import EventBus
from core.events.writer import EventWriter
from core.llm.base import LLMProvider
from core.llm.provider import DeepSeekProvider
from core.loop import AgentLoop
from core.memory.loader import load_context_file
from core.permissions.manager import PermissionManager
from core.runs import RUNS_DIR, new_run_id
from core.tools.builtin.bash import BashTool
from core.tools.builtin.get_time import GetTimeTool
from core.tools.builtin.list_dir import ListDirTool
from core.tools.builtin.read_file import ReadFileTool
from core.tools.builtin.write_file import WriteFileTool
from core.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RunOutcome:
    """一次 run 的最终结果"""
    status: str          # "success" | "failed"
    result: str          # 最终文字结果
    reason: str | None   # 失败原因


class AgentRunner:
    """编排一次完整的 agent run：创建目录、加载上下文、运行 AgentLoop、持久化结果"""

    def __init__(
        self,
        config: CodeConfig,
        *,
        bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        runs_dir: Path | None = None,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        self._config = config
        self._bus = bus or EventBus()
        self._provider = provider
        self._runs_dir = runs_dir or RUNS_DIR
        self._permission_manager = permission_manager

    # 构建工具注册表，注册所有可用工具
    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(BashTool())
        registry.register(GetTimeTool())
        registry.register(ReadFileTool())
        registry.register(WriteFileTool())
        registry.register(ListDirTool())
        return registry

    # 执行 agent run 并返回 RunOutcome（含最终文字结果）
    async def run_and_capture(
        self,
        goal: str,
        *,
        run_id: str | None = None,
    ) -> RunOutcome:
        run_id = run_id or new_run_id()
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        # 加载上下文文件
        global_ctx = load_context_file(Path("~/.kama/context.md").expanduser())
        project_ctx = load_context_file(Path(".kama/context.md"))

        # 创建执行上下文
        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent.max_steps,
            global_context=global_ctx,
            project_context=project_ctx,
        )

        # EventWriter: 将本次 run 的所有事件写入 events.jsonl
        async with EventWriter(run_path / "events.jsonl") as writer:
            writer.subscribe(self._bus)
            await self._bus.publish(RunStartedEvent(run_id=run_id, goal=goal, ts=_now()))

            cancelled = False
            try:
                # 如果没注入 provider，用默认模型创建
                provider = self._provider or DeepSeekProvider(
                    self._config.llm.default_model
                )
                registry = self._build_registry()
                loop = AgentLoop(
                    provider, registry, self._bus,
                    permission_manager=self._permission_manager,
                )
                await loop.run(context)
            except asyncio.CancelledError:
                cancelled = True
                if not context.is_done():
                    context.mark_failed("cancelled")
            except Exception:
                logger.exception(
                    "agent run failed run_id=%s step=%d", run_id, context.step
                )
                if not context.is_done():
                    context.mark_failed("llm_error")

            # 发布 RunFinishedEvent（无论成功失败都发）
            await self._bus.publish(
                RunFinishedEvent(
                    run_id=run_id,
                    status=context.status,
                    reason=context.reason,
                    steps=context.step,
                    ts=_now(),
                )
            )

        if cancelled:
            raise asyncio.CancelledError()

        return RunOutcome(
            status=context.status,
            result=context.result,
            reason=context.reason,
        )
