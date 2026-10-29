"""편집 도구 (transpose, shift_octave, quantize …)와 읽기 도구 (get_project_info, analyze_harmony).

모두 Project -> 새 Project 순수 함수 (읽기 도구는 프로젝트를 돌려주지 않음). 원본은 고치지 않는다.
"""

from app.tools.base import Selection, Tool, ToolError, ToolResult
from app.tools.registry import TOOLS, run_tool, tool_specs

__all__ = ["Selection", "Tool", "ToolError", "ToolResult", "TOOLS", "run_tool", "tool_specs"]
