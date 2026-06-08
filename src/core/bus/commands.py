from __future__ import annotations
from pydantic import BaseModel, Discriminator
from typing import Annotated, Any, Literal


class PingCommand(BaseModel):
    type: Literal["core.ping"] = "core.ping"
    client: str


class PongResult(BaseModel):
    server_version: str
    uptime_ms: int
    received_at: str


class AgentRunCommand(BaseModel):
    type: Literal["agent.run"] = "agent.run"
    goal: str


class AgentRunResult(BaseModel):
    run_id: str


class EventSubscribeCommand(BaseModel):
    type: Literal["event.subscribe"] = "event.subscribe"
    topics: list[str]
    scope: str = "global"
    replay_from_run: str | None = None


class EventSubscribeResult(BaseModel):
    subscription_id: str
    replayed_count: int = 0


Command = Annotated[
    PingCommand | AgentRunCommand | EventSubscribeCommand,
    Discriminator("type"),
]