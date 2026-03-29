---
name: persona-vault-generator-app
description: Use when a local browser-based UI is needed to collect PersonaVault inputs and launch a complete PersonaVault build through the local Codex CLI.
---

# Persona Vault Generator App

## 何时使用

- 需要一个本地服务而不是命令行来组织 `PersonaVault` 生成输入
- 需要多选 `Codex` / `Claude Code` 聊天记录来源
- 需要让用户动态添加本地路径映射、外部链接和输出目录
- 需要在浏览器中查看生成中状态，并在完成后自动进入网页预览，再打开 `Obsidian`

## 核心目标

提供一个本地浏览器界面，把输入整理成结构化请求，再交给本机 `codex exec` 执行完整 `PersonaVault` 生成任务，并串联静态站导出。

## 启动方式

```bash
python3 skills/persona-vault-generator-app/scripts/run_persona_vault_generator_app.py
```

默认会启动本地 HTTP 服务，并输出可访问 URL。

## 固定行为

- 页面使用 Tailwind CSS CDN
- 后端固定通过本机 `codex exec --model gpt-5.4 -c model_reasoning_effort="medium"` 执行任务
- 外部链接默认只记录为来源，不抓取正文
- 生成完成后自动调用 `persona-vault-static-site` 导出网页预览
- 前端优先跳转到导出的本地网页界面
- 页面内仍保留一键调用本机 `Obsidian`
