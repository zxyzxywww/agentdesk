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
┌─ 前端（frontend/：Vite + React + TS + Tailwind + shadcn/ui + Motion）──┐
│ 白色现代三栏：会话列表 / 对话区 / 执行·计划·文件·验收·撤销（构建产物托管） │
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

### 工具清单（17）

文件/目录 8：`list_files` `read_file` `write_file` `move_file` `delete_file` `make_dir` `organize_by_type` `count_files` ·
表格 3：`read_table` `merge_tables` `describe_table` · 代码 1：`run_python` ·
网页 3：`web_search` `fetch_page` `research_report` · 知识检索 1：`knowledge_search` ·
规划 1：`update_plan`

## 测试与评估

```bash
uv run pytest          # 108 个离线测试（全 mock，不依赖付费 API）
uv run ruff check .    # 零告警
uv run mypy            # 零告警
uv run python scripts/bench_reflection.py --tasks 5   # 真实 LLM 评测（需 .env 余额）
```

### 评测结果（真实模型实测：4 任务 × 反思开关，`deepseek-chat`）

评测方法：每个任务在独立临时工作目录完整执行两遍（反思关 `max_reflections=0` / 开 `=2`）；
产出只认真实文件（写文件/归档/合并/统计）；危险操作由脚本模拟用户批准并计数（即 HITL 确认次数）。

| 指标 | 反思关 | 反思开 |
|---|---|---|
| 任务完成率（done） | 4/4 | 4/4 |
| 产出达标率（真实产物文件） | 4/4 | 4/4 |
| 平均步数 | 4.0 | 5.0 |
| 平均成本（元/任务） | 0.026 | 0.033 |
| 工具调用成功率 | 100% | 100% |
| 人工确认次数（危险操作被拦截，HITL） | 0 | 2 |

> 解读：反思开让 Agent 在收尾前多做一轮评审与修正——多出的 1.0 步/0.007 元换来"产出经评审后才交付"；
> 反思开时 Agent 会尝试覆盖/重建已有产物来修正，全部被安全层拦截并计数（0→2），HITL 机制真实生效；
> 评测同时暴露并修复了一个真实缺陷：多工具调用中一个触发确认时，其余调用缺少 tool 响应会导致严格
> provider（DeepSeek）报 400 —— 已通过补占位响应解决（回归测试覆盖）。
> 复现：`uv run python scripts/bench_reflection.py --tasks N`（N×2 次完整执行，需账户余额）。

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
│   └── ui/                # FastAPI（API/WS/托管 frontend/dist）
├── frontend/              # Vite + React + TS + Tailwind + shadcn/ui + Motion
│   ├── src/               # 组件与 hooks（App/TopBar/Chat/Panels/…）
│   └── dist/              # 构建产物（.gitignore，由 FastAPI 托管）
├── scripts/smoke.py       # 真实冒烟任务
├── tests/                 # 93 个离线测试
└── docs/                  # 设计文档 / 简历素材 / 面试深挖 / Demo 脚本
```

## 技术栈

后端：Python 3.12 · FastAPI + WebSocket · OpenAI 兼容 API（DeepSeek）·
Tavily / DuckDuckGo 搜索 · pandas · SQLite · Pydantic · pytest / ruff / mypy · uv · Docker
前端：Vite + React + TypeScript + Tailwind CSS + shadcn/ui 风格组件 + Motion 动效
（构建产物由 FastAPI 直接托管，单服务单端口；开发模式 `npm run dev` 代理到 8000）

## 诚实边界（README 如实披露）

- **代码执行是轻量沙箱**：子进程 + 工作目录 + 超时 + 输出截断，**不是强隔离**；
  只建议在本机可信环境使用，文档已写明风险。
- **免 key 搜索（DuckDuckGo/Bing 解析）稳定性较弱**，正式演示建议配 Tavily 免费 key。
- **成本为估算值**：按 DeepSeek 公开定价的价格表计算，精确费用以账单为准。
- **字体走 Google Fonts CDN**（Inter / JetBrains Mono），离线时回退系统字体，功能不受影响。

## 参考

- [docs/设计文档.md](docs/设计文档.md) —— 架构与设计决策
- [docs/简历素材.md](docs/简历素材.md) —— 简历条目 + 面试深挖清单
- [docs/Live-Demo-录屏脚本.md](docs/Live-Demo-录屏脚本.md) —— 演示流程

# 分支练习占位
作者：张潇漾