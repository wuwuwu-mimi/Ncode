from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

from core.tools.base import BaseTool, ToolResult


class GetTimeParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    timezone: str = "+00:00"


class GetTimeTool(BaseTool):
    params_model = GetTimeParams
    name = "get_time"
    description = "获取当前日期和时间，返回 ISO 8601 格式的时间字符串"

    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "时区，如 '+08:00'、'-05:00'，默认为 UTC",
            }
        },
        "required": [],
    }

    # 返回指定时区的当前时间
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        p = GetTimeParams.model_validate(params)

        if p.timezone == "+08:00":
            now = datetime.now(UTC).astimezone(timezone(timedelta(hours=8)))
        elif p.timezone in ("+00:00", "UTC"):
            now = datetime.now(UTC)
        else:
            return ToolResult(
                content=f"不支持的时区: {p.timezone}，目前支持 '+08:00' 和 UTC",
                is_error=True,
            )

        return ToolResult(
            content=f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC{p.timezone})"
        )
