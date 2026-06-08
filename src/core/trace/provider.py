from __future__ import annotations

import dataclasses
import time
from datetime import UTC, datetime
from typing import Any

from core.events.bus import EventBus
from core.llm.base import LLMProvider
from core.llm.types import LlmResponse
from core.trace.record import TraceRecord
from core.trace.writer import TraceWriter


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TracingProvider:
    """装饰 LLMProvider，在每次 chat() 调用前后记录完整 API I/O 到 TraceWriter"""

    def __init__(
        self,
        inner: LLMProvider,
        trace: TraceWriter,
        *,
        include_payload: bool = True,
    ) -> None:
        self._inner = inner
        self._trace = trace
        self._include_payload = include_payload

    # 记录 CORE→LLM 请求 → 调用真实 provider → 记录 LLM→CORE 响应（含延迟）
    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        # 请求 trace（可选完整 payload 或仅元信息）
        if self._include_payload:
            call_data: dict[str, Any] = {
                "messages": messages,
                "tool_schemas": tool_schemas,
                "system": system,
            }
        else:
            call_data = {
                "message_count": len(messages),
                "tool_count": len(tool_schemas),
            }

        self._trace.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE→LLM",
                layer="llm",
                kind="api_call",
                run_id=run_id,
                step=step,
                data=call_data,
            )
        )

        t0 = time.monotonic()
        result = await self._inner.chat(
            messages, tool_schemas, bus, run_id, step=step, system=system
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 响应 trace
        if self._include_payload:
            resp_data: dict[str, Any] = {
                "stop_reason": result.stop_reason,
                "text": result.text,
                "tool_calls": [dataclasses.asdict(tc) for tc in result.tool_calls],
                "usage": dataclasses.asdict(result.usage) if result.usage else {},
                "latency_ms": latency_ms,
            }
        else:
            resp_data = {
                "stop_reason": result.stop_reason,
                "latency_ms": latency_ms,
                "usage": dataclasses.asdict(result.usage) if result.usage else {},
            }

        self._trace.emit(
            TraceRecord(
                ts=_now(),
                direction="LLM→CORE",
                layer="llm",
                kind="api_response",
                run_id=run_id,
                step=step,
                data=resp_data,
            )
        )

        return result
