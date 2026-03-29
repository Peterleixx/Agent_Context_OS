---
name: persona-vault-static-site
description: Use when a local PersonaVault needs to be exported into a minimal local personal profile webpage, especially for one-click static HTML generation that opens directly in a browser without a build step.
---

# Persona Vault Static Site

## 何时使用

- 用户已经有一个本地 `PersonaVault`
- 需要把人物画像导出成一个本地可直接打开的网页
- 希望输出是单文件 `index.html`
- 希望页面简约、可读、适合展示核心画像
- 不想引入 `npm install`、打包器或运行时服务

## 不适合使用

- 用户想部署完整网站，而不是本地静态页
- 用户想把 `03 - Evidence/` 的证据层直接展示到页面里
- 用户还没有整理好的 `PersonaVault`

## 核心目标

把一个现成的 `PersonaVault` 编译成单文件静态网页：

- 浏览器直接打开
- 使用 Tailwind CSS CDN
- 只展示核心画像，不展示证据正文
- 尽量保留 `Markdown-first` 知识库的结构感

## 输入契约

开始前确认以下输入：

- `persona_vault_path`
  - 本地 `PersonaVault` 根目录
- `output_dir`
  - 输出目录
- `site_title`
  - 可选
  - 用作网页标题和页眉标题

如果 `persona_vault_path` 或 `output_dir` 缺失，先返回待补输入项，不要自行猜路径。

## 固定读取范围

默认读取以下内容：

- `Home.md`
- `00 - Profile/主要人物画像.md`
- `00 - Profile/About Me.md`
- `00 - Profile/Current Focus.md`
- `00 - Profile/Values And Preferences.md`
- `00 - Profile/Work History.md`
- `01 - Capabilities/能力-*.md`
- `02 - Projects/项目-*.md`

不要把 `03 - Evidence/` 的正文直接渲染进页面。

## 标准流程

1. 检查输入路径
2. 确认目标是“单文件静态页”
3. 运行脚本：
   - `python3 skills/persona-vault-static-site/scripts/render_persona_site.py --persona-vault-path <PATH> --output-dir <PATH> [--site-title <TITLE>]`
4. 确认 `output_dir/index.html` 已生成
5. 页面应提供一个 `obsidian://` 链接，默认打开该 vault 的 `Home.md`
6. 可选：提示用户直接用浏览器打开该文件

## 输出契约

至少输出：

- `output_dir/index.html`

页面应尽量包含：

- Hero 摘要
- Obsidian 打开入口
- `Current Focus`
- `Values And Preferences`
- `Work History`
- 能力可视化图表
- Capability Cards
- Selected Projects

## 内容规则

1. 只展示核心画像
   - 优先读取 `主要人物画像.md`
   - 若缺失，再回退到 `About Me.md`
   - 读取画像、能力、项目卡片
   - 不直接展开证据卡正文
2. 缺失内容不补写
   - 没有的 section 直接省略
3. 保守表达
   - 只使用卡片中已有内容
4. 本地优先
   - 输出必须可离线打开
5. 风格简约
   - 页面结构清晰
   - 不做复杂交互
6. 图表优先静态实现
   - 优先使用内联 `SVG`、HTML 表格和 Tailwind 样式
   - 不为图表引入额外前端依赖
7. Obsidian 入口优先深链
   - 默认使用 `obsidian://open?vault=<vault>&file=Home.md`
   - 不在页面里暴露本地绝对路径

## 实现说明

脚本与模板位于：

- `scripts/render_persona_site.py`
- `templates/index.template.html`

优先复用脚本，不要每次手写 HTML。

## 完成检查

完成前确认：

- `index.html` 已生成
- 页面可直接打开
- 页面只展示核心画像
- 页面包含能力画像图表
- 页面包含 Obsidian 一键打开入口
- 至少有一个能力卡片和一个项目卡片
- 页面没有直接暴露 `03 - Evidence/` 正文
