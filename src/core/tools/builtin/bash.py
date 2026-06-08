from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict

from core.tools.base import BaseTool, ToolResult


class BashParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    command: str


class BashTool(BaseTool):
    params_model = BashParams
    name = "bash"
    description = "Execute a bash command. Returns stdout and stderr."

    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            }
        },
        "required": ["command"],
    }

    # 异步执行 shell 命令，捕获 stdout/stderr
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        p = BashParams.model_validate(params)
        proc = await asyncio.create_subprocess_shell(
            p.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        return ToolResult(content=output, is_error=proc.returncode != 0)
