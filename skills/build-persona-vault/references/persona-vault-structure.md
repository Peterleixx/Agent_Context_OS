# PersonaVault 参考目录结构

`PersonaVault` 的目标不是做数据库导出目录，而是做一个人和 Agent 都能使用的 `Markdown-first` 知识库。

如果用户没有指定输出目录，默认就在当前工作目录下创建这套结构。

## 推荐目录

```text
PersonaVault/
  Home.md
  00 - Profile/
    主要人物画像.md
    About Me.md
    Work History.md
    Current Focus.md
    Values And Preferences.md
  01 - Capabilities/
    能力地图.md
    能力-产品定义.md
    能力-技术理解.md
    能力-跨团队协作.md
    能力-0到1推进.md
  02 - Projects/
    项目-项目A.md
    项目-项目B.md
  03 - Evidence/
    证据总表.md
    证据-产品定义-001.md
    证据-跨团队协作-001.md
    证据-0到1推进-001.md
  04 - Policies/
    可说边界.md
    不可说清单.md
    脱敏规则.md
    场景规则-岗位匹配.md
  05 - Requests/
    请求-req_001.md
  06 - Responses/
    返回-req_001.md
  07 - Source Map/
    来源映射总表.md
    来源目录授权.md
  08 - Audit/
    处理日志.md
  .persona-system/
    index.sqlite
    embeddings/
    cache/
    sync-state.json
    render-profile.json
```

## 目录职责

- `Home.md`
  - 人类入口页，说明当前知识库概况、更新时间、待补资料
- `00 - Profile/`
  - 稳定的人物画像；`主要人物画像.md` 应作为默认主入口
- `01 - Capabilities/`
  - 按能力主题组织的核心卡片
- `02 - Projects/`
  - 能证明能力的项目卡片
- `03 - Evidence/`
  - 证据明细与证据索引
- `04 - Policies/`
  - 披露规则和脱敏规则
- `05 - Requests/` / `06 - Responses/`
  - 单文件请求/返回 Demo 的落盘位置
- `07 - Source Map/`
  - 来源路径、来源 ID、授权范围映射
- `08 - Audit/`
  - 处理过程和异常日志
- `.persona-system/`
  - 只给机器使用，不给人做主界面
  - `render-profile.json` 用于静态站和前端直接消费的结构化画像数据

## 写作约束

- 对人可见层尽量只使用 Markdown
- 用 `frontmatter + wikilink + Markdown 表格` 表达结构关系
- 文件名要让人一眼读懂用途
- 不要把 JSON、CSV、YAML 当成主视图

## 最小可用版本

如果资料有限，也至少保留：

- `Home.md`
- `00 - Profile/主要人物画像.md`
- `01 - Capabilities/能力地图.md`
- `03 - Evidence/证据总表.md`
- `04 - Policies/场景规则-岗位匹配.md`
- `07 - Source Map/来源映射总表.md`
- `08 - Audit/处理日志.md`
