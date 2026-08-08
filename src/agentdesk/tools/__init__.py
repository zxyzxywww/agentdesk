"""工具注册表与各工具实现。"""

from __future__ import annotations

from agentdesk.tools.code_runner import build_code_tools
from agentdesk.tools.data_ops import build_data_tools
from agentdesk.tools.file_ops import build_file_tools
from agentdesk.tools.registry import Tool
from agentdesk.tools.web_research import build_web_tools

__all__ = ["Tool", "build_default_tools"]


def build_default_tools() -> list[Tool]:
    """AgentDesk 全部内置工具：文件/目录、表格数据处理、代码执行、网页调研。"""
    return [
        *build_file_tools(),
        *build_data_tools(),
        *build_code_tools(),
        *build_web_tools(),
    ]
