from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.tool_router import ToolRouter


class BaseAgent:
    """Minimal agent base class.

    Agents are pure functions over (dataset, context) with side effects restricted to context updates.
    """

    name: str

    def __init__(self, context: Dict[str, Any], name: Optional[str] = None, tool_router: Optional['ToolRouter'] = None):
        self.context = context
        self.name = name or self.__class__.__name__
        self.tool_router = tool_router

    def warn(self, msg: str) -> None:
        self.context.setdefault("warnings", []).append({"agent": self.name, "msg": msg})

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            self.context[k] = v

    def run(self, dataset: Any) -> Any:
        raise NotImplementedError
