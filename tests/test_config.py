"""配置加载器测试。"""

from __future__ import annotations

from pathlib import Path

from agentdesk.config import PROJECT_ROOT, load_settings


def test_load_defaults_from_project_config() -> None:
    settings = load_settings()
    assert settings.model.base_url == "https://api.deepseek.com"
    assert settings.model.chat_model == "deepseek-chat"
    assert settings.agent.max_steps == 20
    assert settings.agent.max_repeated_actions == 3
    assert settings.search.provider in ("tavily", "fallback")
    assert settings.ui.port == 8000


def test_yaml_overrides_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "agent:\n  max_steps: 5\nmodel:\n  chat_model: deepseek-reasoner\n",
        encoding="utf-8",
    )
    settings = load_settings(cfg)
    assert settings.agent.max_steps == 5
    assert settings.model.chat_model == "deepseek-reasoner"
    # 未覆盖字段保持默认
    assert settings.agent.max_cost_yuan == 2.0


def test_workspace_root_is_absolute(tmp_path: Path) -> None:
    settings = load_settings()
    root = settings.workspace_root
    assert root.is_absolute()
    assert PROJECT_ROOT in root.parents or root == PROJECT_ROOT


def test_missing_config_file_uses_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "nonexistent.yaml")
    assert settings.agent.max_steps == 20
    assert settings.model.temperature == 0.2


def test_env_example_lists_both_keys() -> None:
    """.env.example 必须包含两个密钥占位，供用户复制填写。"""
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" in content
    assert "TAVILY_API_KEY" in content
