"""冒烟测试：验证包可导入、版本可读取。"""

import agentdesk


def test_package_importable() -> None:
    assert agentdesk.__version__ == "0.1.0"


def test_core_packages_available() -> None:
    """核心依赖应可导入（fastapi/pandas/httpx/bs4/openai）。"""
    import fastapi  # noqa: F401
    import httpx  # noqa: F401
    import openai  # noqa: F401
    import pandas  # noqa: F401
    from bs4 import BeautifulSoup  # noqa: F401

    assert True
