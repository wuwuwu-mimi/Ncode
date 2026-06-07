import asyncio
from ..base import BaseTool,ToolResult


class BashTool(BaseTool):
    name = "bash"
    description = "Execute a bash command. Returns stdout and stderr."

    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            }
        },
        "required": ["command"],
    }

    async def invoke(self, params: dict) -> ToolResult:
        command = params["command"]
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        return ToolResult(content=output, is_error=proc.returncode != 0)
