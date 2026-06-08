from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class TraceRecord(BaseModel):
    """一条 trace 记录：记录系统间消息的方向、层次、内容和时间戳"""
    ts: str
    direction: Literal[
        "CLIENT→CORE",   # 客户端发给 daemon
        "CORE→CLIENT",   # daemon 发给客户端
        "CORE",          # daemon 内部事件
        "CORE→LLM",      # daemon 发给 LLM
        "LLM→CORE",      # LLM 返回 daemon
    ]
    layer: Literal["ipc", "event", "llm"]
    kind: str           # command / response / error / push / event / api_call / api_response
    run_id: str | None = None
    step: int | None = None
    client_id: str | None = None
    data: dict[str, Any]
