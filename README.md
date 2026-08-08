# AgentDesk —— 通用任务型 Agent 工作台

> 用自然语言下达任务，Agent 自主规划、调用工具完成**文件/数据处理**与**网页调研**，
> 全程可视化监督：实时工具状态、危险操作确认、一键撤销、任务验收。


---

## 它能做什么（使用场景）

| 场景 | 示例指令 | 涉及能力 |
|---|---|---|
| 科研/日常数据杂活 | 「把工作目录下所有 csv 合并为 all.csv 并汇报总行数」 | 表格读取/合并（pandas） |
| 文件整理 | 「把文件按类型归档到子文件夹」 | 移动/建目录/列表 |
| 一次性脚本 | 「写个脚本把所有 xlsx 转成 csv」 | Python 沙箱执行 |
| 网页调研 | 「调研 LLM agent 框架现状，写带引用的笔记」 | 搜索（Tavily/免 key）+ 抓取 + 多轮调研 |
| 兜底安全 | 覆盖/删除/执行代码前**自动请求确认**，执行前**自动备份**，可一键撤销 | 确认机制 + 备份回滚 |

## 快速开始

```bash
# 1. 安装依赖（需要 uv：https://docs.astral.sh/uv/）
uv sync

# 2. 配置密钥：复制 .env.example 为 .env 并填写
#    - DEEPSEEK_API_KEY（必填，https://platform.deepseek.com）
#    - TAVILY_API_KEY（选填，https://app.tavily.com 免费额度；不填自动回退免 key 搜索）
Copy-Item .env.example .env   # Windows PowerShell

# 3. 启动工作台
uv run uvicorn agentdesk.ui.main:create_app --factory --host 127.0.0.1 --port 8000

# 4. 浏览器打开 http://127.0.0.1:8000
```

> 没有 TAVILY_API_KEY 也能跑：`config.yaml` 里 `search.provider` 设为 `fallback`
> 或留空 key 自动回退到 DuckDuckGo/Bing 网页解析（稳定性较弱）。

## 架构概览

```
┌─ 前端（Tabler 深色工作台，三栏）──────────────────────────┐
│ 左：会话列表  中：对话区  右：执行 / 计划 / 文件 / 验收 / 撤销 │
└───────────────┬───────────────────────────────────────┘
                │ REST + WebSocket（实时工具状态流）
┌─ FastAPI 后端（agentdesk/ui/main.py）─────────────────────┐
│ 会话/任务/确认/拒绝/取消/上传/导出/备份  |  WS 事件推送        │
└───────────────┬───────────────────────────────────────┘
┌─ Agent 引擎（agentdesk/core）─────────────────────────────┐
│ Planner（任务→步骤计划）→ ReAct 执行循环 → 护栏 → 任务验收     │
│ 事件：plan / tool_start / tool_end / needs_confirm / done │
└───────────────┬───────────────────────────────────────┘
┌─ 工具层（agentdesk/tools，13 个工具，Pydantic 参数校验）─────┐
│ 文件操作 6 · 表格处理 3 · 代码执行 1 · 网页调研 3              │
└───────────────┬───────────────────────────────────────┘
┌─ 存储（agentdesk/storage）───────────────────────────────┐
│ SQLite：会话/消息/任务/工具调用/备份记录  |  文件自动备份区      │
└──────────────────────────────────────────────────────┘
```

### 护栏（安全设计，面试重点）

| 护栏 | 实现 |
|---|---|
| 危险操作确认 | 覆盖/删除/执行代码抛 `NeedsConfirmation`，任务挂起，用户确认/拒绝后继续 |
| 自动备份回滚 | 修改/删除前自动备份到 `data/backups/`，界面一键恢复 |
| 路径穿越防护 | 所有文件操作经 `resolve_in_workspace` 锁定在工作目录内 |
| 步数上限 | 单任务最大工具调用步数（默认 20） |
| 成本上限 | 单任务最大成本（默认 ¥2），按模型价格表估算 |
| 重复动作 | 连续相同调用达阈值即终止 |
| 长任务中断 | UI 停止按钮 → `cancel()` |
| 代码沙箱 | 子进程 + 工作目录限制 + 超时 + 输出截断（轻量，非强隔离，见边界） |

### 工具清单（13）

`list_files` `read_file` `write_file` `move_file` `delete_file` `make_dir` ·
`read_table` `merge_tables` `describe_table` · `run_python` ·
`web_search` `fetch_page` `research_report`

## 测试与评估

```bash
uv run pytest          # 93 个离线测试（全 mock，不依赖付费 API）
uv run ruff check .    # 零告警
uv run mypy            # 零告警
uv run python scripts/smoke.py   # 真实 LLM 冒烟任务（需 .env 配置）
```

评估指标（`src/agentdesk/core/eval.py`）：任务成功率、平均步数、平均成本——
冒烟脚本执行后输出汇总，为简历量化成果提供真实数据。

## 目录结构

```
agentdesk/
├── config.yaml            # 集中配置（模型/护栏/工具/搜索/存储）
├── .env.example           # 密钥模板（DeepSeek + Tavily）
├── src/agentdesk/
│   ├── config.py          # 配置加载（Pydantic + yaml + dotenv）
│   ├── core/              # planner / executor / summary / export / eval
│   ├── tools/             # registry + file_ops/data_ops/code_runner/web_research
│   ├── llm/               # OpenAI 兼容客户端（token/成本统计）
│   ├── storage/           # SQLite + 备份回滚
│   └── ui/                # FastAPI + static（Tabler 前端）
├── scripts/smoke.py       # 真实冒烟任务
├── tests/                 # 93 个离线测试
└── docs/                  # 设计文档 / 简历素材 / 面试深挖 / Demo 脚本
```

## 技术栈

Python 3.12 · FastAPI + WebSocket · Tabler（Bootstrap 5）· OpenAI 兼容 API（DeepSeek）·
Tavily / DuckDuckGo 搜索 · pandas · SQLite · Pydantic · pytest / ruff / mypy · uv · Docker

## 诚实边界（README 如实披露）

- **代码执行是轻量沙箱**：子进程 + 工作目录 + 超时 + 输出截断，**不是强隔离**；
  只建议在本机可信环境使用，文档已写明风险。
- **免 key 搜索（DuckDuckGo/Bing 解析）稳定性较弱**，正式演示建议配 Tavily 免费 key。
- **成本为估算值**：按 DeepSeek 公开定价的价格表计算，精确费用以账单为准。
- **前端依赖 CDN**（Tabler），离线时样式退化但功能不受影响。

## 参考

- [docs/设计文档.md](docs/设计文档.md) —— 架构与设计决策
- [docs/简历素材.md](docs/简历素材.md) —— 简历条目 + 面试深挖清单
- [docs/Live-Demo-录屏脚本.md](docs/Live-Demo-录屏脚本.md) —— 演示流程
