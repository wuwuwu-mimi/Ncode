from __future__ import annotations

import asyncio
import datetime
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from core.permissions.policy import (
    DEFAULT_POLICIES,
    PermissionDecision,
    ToolPolicy,
    evaluate,
    matches_outside_cwd,
    param_preview,
)
from core.permissions.storage import load_policy_file, save_policy_file

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.datetime.now(UTC).isoformat()


@dataclass
class _PendingRequest:
    future: asyncio.Future[str]
    session_id: str
    tool_name: str


class PermissionManager:
    """管理工具调用权限：策略评估、用户审批挂起、缓存、持久化"""

    def __init__(
        self,
        policies: dict[str, ToolPolicy] | None = None,
        *,
        policy_file: Path | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._policies: dict[str, ToolPolicy] = policies or dict(DEFAULT_POLICIES)
        self._pending: dict[str, _PendingRequest] = {}
        self._session_always: dict[tuple[str, str], str] = {}
        self._policy_file = policy_file
        self._persistent_always: dict[str, str] = (
            load_policy_file(policy_file) if policy_file is not None else {}
        )
        self._timeout_s = timeout_s

    # 检查权限；如需 ASK 则挂起等待客户端响应
    async def check_and_wait(
        self,
        tool_use_id: str,
        tool_name: str,
        params: dict[str, Any],
        session_id: str,
        event_emitter: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> tuple[bool, str]:
        command = str(params.get("command", "")) if tool_name == "bash" else ""
        policy = self._policies.get(tool_name)

        # Tier 1: deny_patterns
        if command and policy:
            for pat in policy.deny_patterns:
                if re.search(pat, command):
                    logger.debug("permission: deny_pattern hit tool=%s", tool_name)
                    return False, "auto_deny"

        # Tier 2: OUTSIDE_CWD → forced ASK
        outside_cwd = bool(command and matches_outside_cwd(command))

        if not outside_cwd:
            # Tier 3: session always 缓存
            session_key = (session_id, tool_name)
            if session_key in self._session_always:
                cached = self._session_always[session_key]
                return cached == "allow", f"auto_{cached}"

            # Tier 4: persistent always
            if tool_name in self._persistent_always:
                cached = self._persistent_always[tool_name]
                return cached == "allow", f"auto_{cached}"

            # Tier 5: allow_patterns
            if command and policy:
                for pat in policy.allow_patterns:
                    if re.search(pat, command):
                        return True, "auto_allow"

            # Tier 6: tool default
            if policy is not None:
                if policy.default == PermissionDecision.ALLOW:
                    return True, "auto_allow"
                if policy.default == PermissionDecision.DENY:
                    return False, "auto_deny"

        # ASK 路径
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[tool_use_id] = _PendingRequest(
            future=future, session_id=session_id, tool_name=tool_name,
        )

        await event_emitter({
            "type": "permission.requested",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "params": params,
            "param_preview": param_preview(tool_name, params),
            "session_id": session_id,
            "ts": _now(),
        })

        try:
            raw = await asyncio.wait_for(future, timeout=self._timeout_s) if self._timeout_s > 0 else await future
        except asyncio.TimeoutError:
            self._pending.pop(tool_use_id, None)
            logger.info("permission: timeout tool_use_id=%s", tool_use_id)
            return False, "timeout"

        allowed = self._apply_response(raw, session_id, tool_name)
        return allowed, raw

    # 客户端返回审批决策
    def respond(self, tool_use_id: str, decision: str) -> None:
        req = self._pending.pop(tool_use_id, None)
        if req is None:
            logger.warning("permission.respond: unknown tool_use_id=%s", tool_use_id)
            return
        if not req.future.done():
            req.future.set_result(decision)

    # 应用决策，更新缓存
    def _apply_response(self, decision: str, session_id: str, tool_name: str) -> bool:
        allow = decision in ("allow_once", "always_allow")
        if decision == "always_allow":
            self._session_always[(session_id, tool_name)] = "allow"
            self._persistent_always[tool_name] = "allow"
            if self._policy_file is not None:
                try:
                    save_policy_file(self._persistent_always, self._policy_file)
                except Exception:
                    logger.exception("permission: failed to write policy.toml")
        elif decision == "always_deny":
            self._session_always[(session_id, tool_name)] = "deny"
            self._persistent_always[tool_name] = "deny"
            if self._policy_file is not None:
                try:
                    save_policy_file(self._persistent_always, self._policy_file)
                except Exception:
                    logger.exception("permission: failed to write policy.toml")
        return allow

    # 客户端断连时取消该 session 所有待审批请求
    def cancel_session(self, session_id: str, reason: str = "client_disconnected") -> None:
        to_cancel = [
            uid for uid, req in self._pending.items()
            if req.session_id == session_id
        ]
        for uid in to_cancel:
            req = self._pending.pop(uid)
            if not req.future.done():
                req.future.set_result("deny_once")
