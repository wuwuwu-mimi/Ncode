from __future__ import annotations
import asyncio
from datetime import datetime, UTC
import logging
import os
from typing import Any
import anthropic
from core.bus.events import LlmModelSelectedEvent, LlmTokenEvent, LlmUsageEvent
from core.events.bus import EventBus
from core.llm.types import LlmResponse, ToolCallBlock, UsageStats
import httpx

_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-pro": 200_000,
    "deepseek-v4-flash": 200_000,
}

_MAX_STREAM_RETRIES = 3  # 最大重试次数
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)  # 重试间隔

log = logging.getLogger(__name__)


# 返回指定模型的最大 context window token 数
def _context_window(model: str) -> int:
    return _MODEL_CONTEXT_WINDOWS.get(model, 200_000)


_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. "
    "Use the available tools to complete the user's goal. "
    "When the goal is fully achieved, respond with a final answer and do not call any more tools."
)


# 返回当前 UTC 时间的 ISO 8601 字符串
def _now() -> str:
    return datetime.now(UTC).isoformat()


class DeepSeekProvider:
    # 初始化 deepseek客户端 client 可在测试时注入以跳过 API key 检查

    def __init__(self, model: str, client: Any = None) -> None:

        if client is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY")

            if not api_key:
                raise SystemExit("API_KEY IS NOT SET")
            self._client: Any = anthropic.AsyncAnthropic(
                api_key=api_key, base_url="https://api.deepseek.com/anthropic"
            )
        else:
            self._client = client
        self._model = model

    # 流式调用 API 逐 TOKEN 发送事件并返回 LLMResponse

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

        await bus.publish(
            LlmModelSelectedEvent(
                run_id=run_id, model=self._model, strategy="static", ts=_now()
            )
        )

        system_blocks: list[dict[str, object]] = [
            {
                "type": "text",
                "text": system or _SYSTEM_PROMPT,
            },
        ]

        tools: list[dict[str, object]] = list(tool_schemas)
        if tools:
            last = dict(tools[-1])
            log.debug(f"tools-last:{last}")
            tools = tools[:-1] + [last]
            log.debug(f"tools格式:{tools}")

        kwargs: dict[str, object] = {
            "model": self._model,
            "max_tokens": 8192,
            "system": system_blocks,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        text_parts: list[str] = []
        final_message: Any = None

        for attempt in range(1, _MAX_STREAM_RETRIES + 1):
            text_parts = []
            try:
                async with self._client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        # 仅在首次请求时推送 Token 事件，避免 TUI 界面重复刷屏。
                        if attempt == 1:
                            await bus.publish(
                                LlmTokenEvent(run_id=run_id, token=text, ts=_now())
                            )
                        text_parts.append(text)
                    final_message = await stream.get_final_message()
                break

            except (
                httpx.RemoteProtocolError,
                httpx.ReadError,
                httpx.ConnectError,
            ) as exc:
                if attempt == _MAX_STREAM_RETRIES:
                    log.error(
                        "stream failed after %d attempts run_id=%s step=%d: %s",
                        _MAX_STREAM_RETRIES,
                        run_id,
                        step,
                        exc,
                    )
                    raise
                delay = _RETRY_BACKOFF_S[attempt - 1]
                log.warning(
                    "stream dropped (attempt %d/%d) run_id=%s step=%d: %s — retrying in %.0fs",
                    attempt,
                    _MAX_STREAM_RETRIES,
                    run_id,
                    step,
                    exc,
                    delay,
                )

                await asyncio.sleep(delay)

        assert final_message is not None

        usage = final_message.usage
        cache_read: int = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create: int = getattr(usage, "cache_creation_input_tokens", 0) or 0
        context_pct = usage.input_tokens / _context_window(self._model)

        await bus.publish(
            LlmUsageEvent(
                run_id=run_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_create,
                context_pct=context_pct,
                ts=_now(),
            )
        )

        tool_calls: list[ToolCallBlock] = []
        thinking_blocks: list[dict[str, object]] = []
        for block in final_message.content:
            if block.type == "tool_use":
                tool_calls.append(
                    ToolCallBlock(id=block.id, name=block.name, input=dict(block.input))
                )
            elif block.type == "thinking":
                # thinking blocks must be passed back verbatim in subsequent requests
                thinking_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature,
                    }
                )

        return LlmResponse(
            stop_reason=final_message.stop_reason or "end_turn",
            tool_calls=tool_calls,
            text="".join(text_parts),
            thinking_blocks=thinking_blocks,
            usage=UsageStats(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_create,
                context_pct=context_pct,
            ),
        )
