# AgentDesk 容器化部署（基于 uv 官方镜像，无本地构建环境也可按此交付）
# 构建：docker build -t agentdesk .
# 运行：docker run --rm -p 8000:8000 -e DEEPSEEK_API_KEY=sk-xxx -e TAVILY_API_KEY=tvly-xxx agentdesk

FROM python:3.12-slim

# 安装 uv（官方安装方式）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先复制依赖清单 + 构建项目本体所需的 README/源码，利用构建缓存
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# 复制其余源码与配置（.dockerignore 排除 data/tests/docs/.env 等）
COPY . .

EXPOSE 8000

# 密钥通过环境变量注入；数据目录 data/ 可挂载 volume 持久化
CMD ["uv", "run", "uvicorn", "agentdesk.ui.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
