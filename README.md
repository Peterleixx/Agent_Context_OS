# Agent Context OS 技能仓库

这是一个可直接 clone 到任意目录、本地两行命令启动的 PersonaVault 工具仓库。仓库已经内置：

- `build-persona-vault`
- `persona-vault-generator-app`
- 对应测试、启动脚本和环境配置示例

## 快速启动

前提：

- 已安装 `python3`
- 已安装并登录 `codex` CLI
- `Obsidian` 可选，仅在需要一键打开 vault 时使用

clone 后进入仓库目录，只需要两行：

```bash
./scripts/setup.sh
./scripts/run.sh
```

启动后终端会打印本地地址，例如 `http://127.0.0.1:8765`。

如果你在 macOS 上希望双击直接启动，也可以用仓库根目录的：

```bash
./start.command
```

## 可选环境配置

如果需要改端口、host、默认输出工作目录，或切换 Codex 运行档位，可以复制 `.env.example` 为 `.env.local` 并填写：

```bash
cp .env.example .env.local
```

支持的变量：

- `PERSONA_VAULT_HOST`
- `PERSONA_VAULT_PORT`
- `PERSONA_VAULT_WORKDIR`
- `PERSONA_VAULT_CODEX_MODEL`
- `PERSONA_VAULT_CODEX_REASONING_EFFORT`
- `PERSONA_VAULT_CODEX_TIMEOUT_SECONDS`

推荐的 demo 默认档位：

- `PERSONA_VAULT_CODEX_MODEL=gpt-5.4-mini`
- `PERSONA_VAULT_CODEX_REASONING_EFFORT=low`
- 需要更稳的质量时，再切回 `gpt-5.4` 与更高推理强度

这个仓库当前提供两套面向 Codex 的技能，用于构建 `Markdown-first` 的 `PersonaVault` 工作流：

- `build-persona-vault`
  - 从已授权的本地资料中构建或刷新一个本地 `PersonaVault`
  - 现在要求在构建人物画像时，必须把“用户与 Agent 的聊天记录”作为重要参考来源之一纳入证据链
- `compile-match-response`
  - 读取单个 Markdown 任务请求，并输出一份保守、可追溯、证据驱动的 Markdown 匹配结果
- `persona-vault-generator-app`
  - 启动一个本地交互式服务
  - 通过浏览器收集 agent、多路径映射、外部链接和输出目录
  - 默认由本机 `codex exec --model gpt-5.4-mini -c model_reasoning_effort="low"` 执行完整 PersonaVault 生成
  - 生成完成后会在同一流程里直接导出网页预览链接
  - 对 `github` 类型链接，会先抓取公开主页与代表仓库摘要，再并入 PersonaVault 和网页预览
  - 成功态保留在首页，支持打开网页、打开 Obsidian，以及自然语言修改 / 重写

## 仓库结构

```text
Agent_Context_OS/
├── scripts/
│   ├── setup.sh                         # 初始化虚拟环境、运行测试
│   └── run.sh                           # 启动本地 Web 服务
├── skills/
│   ├── build-persona-vault/
│   │   ├── SKILL.md                     # Codex 技能定义（构建 / 刷新 PersonaVault）
│   │   ├── references/
│   │   │   └── persona-vault-structure.md   # PersonaVault 目录规范参考
│   │   └── templates/
│   │       ├── 能力卡片模板.md
│   │       └── 证据卡片模板.md
│   ├── compile-match-response/
│   │   ├── SKILL.md                     # Codex 技能定义（生成匹配结果）
│   │   └── templates/
│   │       ├── 任务请求模板.md
│   │       └── 匹配结果模板.md
│   └── persona-vault-generator-app/
│       ├── SKILL.md                     # Codex 技能定义（App 专属扩展提示）
│       ├── scripts/
│       │   ├── run_persona_vault_generator_app.py   # HTTP 服务主程序
│       │   └── render_persona_site.py               # Markdown → HTML 静态站渲染器
│       └── templates/
│           ├── index.html               # 浏览器交互 UI
│           └── persona-site.template.html   # 静态预览站 HTML 模板
├── tests/
│   ├── test_persona_vault_generator_app.py
│   ├── test_persona_vault_static_site.py
│   └── test_start_command.py
├── .env.example                         # 环境变量配置示例
└── start.command                        # macOS 双击启动入口
```

## 架构文档

### 整体架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│                         用户 / 浏览器                                 │
│   输入：agent 信息、路径映射、外部链接、高级设置                        │
└──────────────────────┬───────────────────────────────────────────────┘
                       │ HTTP（本地 127.0.0.1:8765）
┌──────────────────────▼───────────────────────────────────────────────┐
│           persona-vault-generator-app  （HTTP 服务）                  │
│  run_persona_vault_generator_app.py                                  │
│                                                                      │
│  ┌─────────────────┐   ┌──────────────────┐   ┌──────────────────┐  │
│  │  请求解析 &      │   │  GitHub 公开数据  │   │  后台 Job 线程   │  │
│  │  参数归一化      │──▶│  抓取与富化       │──▶│  管理（JobRunner）│  │
│  └─────────────────┘   └──────────────────┘   └────────┬─────────┘  │
└───────────────────────────────────────────────────────┼─────────────┘
                                                        │ subprocess
┌───────────────────────────────────────────────────────▼─────────────┐
│                        Codex CLI                                      │
│  codex exec --model gpt-5.4-mini -c model_reasoning_effort="low"     │
│  （model 可选 gpt-5.4；effort 可选 low / medium / high / xhigh）     │
│   读取技能提示词（SKILL.md）+ 用户输入 → 执行 PersonaVault 构建任务   │
└───────────────────────────────────────────────────────┬─────────────┘
                                                        │ 写入文件系统
┌───────────────────────────────────────────────────────▼─────────────┐
│                     PersonaVault（本地 Markdown 目录）                │
│  00-Profile / 01-Capabilities / 02-Projects / 03-Evidence / ...      │
└───────────────────────────────────────────────────────┬─────────────┘
                                                        │
┌───────────────────────────────────────────────────────▼─────────────┐
│              render_persona_site.py（静态站渲染器）                   │
│  读取 PersonaVault Markdown → 生成 HTML 预览站                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 核心模块说明

#### 1. `run_persona_vault_generator_app.py` — HTTP 服务主程序

基于 Python 标准库 `http.server.ThreadingHTTPServer` 实现的轻量级本地 Web 服务，无第三方框架依赖。

| 职责 | 说明 |
|------|------|
| 请求处理 | 解析浏览器提交的 JSON 表单（agent 信息、路径映射、高级设置） |
| GitHub 数据富化 | 对 `github` 类型外部链接，自动抓取用户公开主页和代表仓库摘要，注入生成提示词 |
| Prompt 构建 | 读取 `build-persona-vault/SKILL.md` 和用户输入，拼装 Codex 执行提示词 |
| Job 管理 | 每次生成任务在独立线程中执行，维护 `status / stage / message` 状态供前端轮询 |
| 静态站触发 | Codex 执行完成后调用 `render_persona_site.py` 生成 HTML 预览 |
| 自然语言改写 | 接收用户的自然语言修改指令，构建编辑提示词并再次调用 Codex |

**主要 API 端点：**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/start` | POST | 提交新的 PersonaVault 生成任务 |
| `/api/job/{job_id}` | GET | 轮询任务状态 |
| `/api/edit` | POST | 对已生成的 Vault 发起自然语言修改 |
| `/api/deploy` | POST | 触发 OpenClaw 部署（可选） |
| `/api/retry` | POST | 从断点续跑上一次任务 |
| `/api/open-obsidian` | POST | 用 Obsidian 打开生成的 Vault |
| `/api/open-local` | POST | 打开本地文件路径 |

#### 2. `render_persona_site.py` — 静态站渲染器

将 PersonaVault 中的 Markdown 文件解析为结构化数据，并填充到 `persona-site.template.html` 模板，生成可直接在浏览器中浏览的静态 HTML 网页。

- 解析 Markdown frontmatter 与各章节内容
- 渲染能力卡片、项目卡片、工作经历表格、价值观卡片等组件
- 支持 `focus_presets`（能力亮点 / 代表项目 / 工作经历等）定制展示重点

#### 3. Codex 技能（`skills/*/SKILL.md`）

每个 `SKILL.md` 是一份完整的 Codex 任务提示词规范，描述：

- 技能名称与触发条件
- 输入 / 输出约定
- 执行步骤与约束
- 引用的模板文件路径

| 技能 | 用途 |
|------|------|
| `build-persona-vault` | 从本地资料（文档、聊天记录）构建或刷新一个 PersonaVault |
| `compile-match-response` | 读取单个 Markdown 任务请求，输出保守的、证据驱动的匹配结果 |
| `persona-vault-generator-app` | 为 App 模式提供扩展提示词，支持 GitHub 数据富化与网页预览 |

### 核心数据流

```text
用户在浏览器填写表单
        │
        ▼
POST /api/start
        │
        ├─ 参数归一化（normalize_payload）
        ├─ GitHub 链接 → 抓取公开数据（collect_github_public_data）
        ├─ 构建 Codex 提示词（build_generation_prompt）
        │       └─ 读取 build-persona-vault/SKILL.md
        │
        ▼
后台线程调用 Codex CLI（run_codex_command）
        │
        ├─ Codex 读取提示词，在本机执行文件读写
        ├─ 写入 PersonaVault Markdown 目录
        │
        ▼
render_persona_site.py
        │
        ├─ 解析 PersonaVault Markdown 文件
        ├─ 渲染 persona-site.template.html
        └─ 输出静态 HTML 预览站

前端轮询 GET /api/job/{job_id}
        │
        └─ 完成后展示预览链接 / 打开 Obsidian / 自然语言改写入口
```

### PersonaVault 输出目录结构

```text
PersonaVault/
  Home.md                         # 人类入口页
  00 - Profile/                   # 稳定的人物画像
  01 - Capabilities/              # 能力卡片（按主题组织）
  02 - Projects/                  # 代表项目卡片
  03 - Evidence/                  # 证据明细与证据索引
  04 - Policies/                  # 披露规则 / 脱敏规则
  05 - Requests/                  # 单文件任务请求
  06 - Responses/                 # 单文件匹配结果
  07 - Source Map/                # 来源路径与授权映射
  08 - Audit/                     # 处理过程与异常日志
  .persona-system/                # 机器专用数据（SQLite、Embeddings、缓存）
```

### 技术栈

| 层次 | 技术 |
|------|------|
| 运行时 | Python 3（无第三方依赖，仅标准库） |
| AI 推理 | OpenAI Codex CLI（`codex exec`） |
| Web 服务 | `http.server.ThreadingHTTPServer`（标准库） |
| 知识库格式 | Markdown-first（frontmatter + wikilink + Markdown 表格） |
| 预览站 | 纯静态 HTML（Python 模板渲染，无构建工具） |
| 本地存储 | 文件系统（Markdown 文件） + SQLite（`.persona-system/`） |
| 可选集成 | Obsidian（本地 vault 查看）、OpenClaw（Agent 部署） |

## 当前 MVP 范围

- `Markdown-first` 的 PersonaVault 构建
- 单文件请求 / 单文件输出
- 保守的、证据驱动的岗位或任务匹配
- 适合在 `Obsidian` 中直接阅读和维护的知识组织方式
- 轻量的本地人物画像网页导出与自然语言改写

## 当前约束重点

- `build-persona-vault` 在生成人物画像、`About Me`、`Profile` 类内容时，不能只依赖静态文档
- 已授权的聊天记录应作为一等来源进入来源清单、证据卡片和能力判断
- 聊天记录中的自述可以作为重要线索，但不能在缺少旁证时被提升为完全确定事实
