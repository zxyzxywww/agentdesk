"""配置加载：config.yaml + .env 环境变量 → Pydantic 模型。

密钥不在 config.yaml 中，而是通过环境变量注入（.env 文件由 python-dotenv 加载）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 项目根目录（本文件位于 src/agentdesk/ → 上三级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelConfig(BaseModel):
    base_url: str = (
        "https://api.deepseek.com"  # DeepSeek 官方（切换方式见 config.yaml 注释）
    )
    chat_model: str = "deepseek-flash"
    temperature: float = 0.2
    max_tokens: int = 4096
    api_key_env: str = "DEEPSEEK_API_KEY"  # 从环境变量读取 API key


class AgentConfig(BaseModel):
    max_steps: int = 40
    max_cost_yuan: float = 2.0
    max_repeated_actions: int = 3
    max_tool_output_chars: int = 4000
    max_reflections: int = 2


class WorkspaceConfig(BaseModel):
    root: str = "data/workspace"


class CodeRunnerConfig(BaseModel):
    timeout_seconds: int = 60
    max_output_chars: int = 8000


class WebResearchConfig(BaseModel):
    request_timeout_seconds: int = 15
    max_pages_per_task: int = 10
    max_chars_per_page: int = 6000


class ToolsConfig(BaseModel):
    code_runner: CodeRunnerConfig = Field(default_factory=CodeRunnerConfig)
    web_research: WebResearchConfig = Field(default_factory=WebResearchConfig)


class TavilyConfig(BaseModel):
    max_results: int = 8
    api_key_env: str = "TAVILY_API_KEY"


class FallbackSearchConfig(BaseModel):
    engine: Literal["duckduckgo", "bing"] = "duckduckgo"
    max_results: int = 8


class SearchConfig(BaseModel):
    provider: Literal["tavily", "fallback"] = "tavily"
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    fallback: FallbackSearchConfig = Field(default_factory=FallbackSearchConfig)


class StorageConfig(BaseModel):
    db_path: str = "data/db/agentdesk.db"
    backups_dir: str = "data/backups"  # 覆盖/删除前的自动备份区


class UIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class Settings(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @property
    def workspace_root(self) -> Path:
        """工作目录绝对路径（相对项目根解析）。"""
        p = Path(self.workspace.root)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def db_file(self) -> Path:
        """SQLite 数据库文件绝对路径。"""
        p = Path(self.storage.db_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def backups_dir_abs(self) -> Path:
        """备份区绝对路径。"""
        p = Path(self.storage.backups_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


def load_settings(path: str | Path | None = None) -> Settings:
    """从 config.yaml 加载配置；path=None 时使用项目根下的 config.yaml。"""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    data: dict = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            data = raw
    return Settings.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级缓存配置：首次调用时加载 .env 并读取 config.yaml。"""
    load_dotenv(PROJECT_ROOT / ".env")
    return load_settings()
