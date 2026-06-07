import asyncio
from datetime import datetime, UTC, timedelta, timezone

from src.core.tools.base import BaseTool, ToolResult


class GetTimeTool(BaseTool):
    name = "get_time"
    description = "获取当前日期和时间，返回 ISO 8601 格式的时间字符串"

    input_schema = {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "时区，如 '+08:00'，默认为 UTC",
            }
        },
        "required": [],  # 没有必填参数
    }

    async def invoke(self, params: dict) -> ToolResult:
        tz_str = params.get("timezone", "+00:00")

        if tz_str == "+08:00":
            now = datetime.now(UTC).astimezone(timezone(timedelta(hours=8)))
        elif tz_str == "+00:00" or tz_str == "UTC":
            now = datetime.now(UTC)
        else:
            return ToolResult(
                content=f"不支持的时区: {tz_str}，目前支持 '+08:00' 和 UTC",
                is_error=True,
            )

        return ToolResult(
            content=f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC{tz_str})"
        )