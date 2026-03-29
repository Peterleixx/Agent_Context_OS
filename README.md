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
skills/
  build-persona-vault/
    SKILL.md
    references/
    templates/
  compile-match-response/
    SKILL.md
    templates/
  persona-vault-generator-app/
    SKILL.md
    scripts/
    templates/
```

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
