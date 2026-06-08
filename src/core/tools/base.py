from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    # "runtime_error" | "timeout" | "schema_error" | "permission_denied"
    error_type: str | None = None


class BaseTool(ABC):
    name: str                               # "bash", "read_file"
    description: str                        # 给 LLM 看的功能描述
    input_schema: dict[str, object]         # Anthropic 格式的 JSON Schema
    params_model: ClassVar[type[BaseModel] | None] = None  # pydantic 参数校验模型

    @abstractmethod
    async def invoke(self, params: dict[str, object]) -> ToolResult: ...
