# Persona Vault Static Site Design

**Goal:** Add a reusable Codex skill that turns a local `PersonaVault` into a minimal static personal profile page powered by Tailwind CSS CDN and opened directly as a local `index.html`.

## Scope

- Input is an existing local `PersonaVault` directory.
- Output is a single `index.html` file inside a caller-provided output directory.
- The page only shows core profile content:
  - `00 - Profile/*`
  - `01 - Capabilities/*`
  - `02 - Projects/*`
- The page does not expose `03 - Evidence/*` content.
- The generated page must work without `npm install`, bundlers, or a local web server.

## User Flow

1. User points Codex to a local `PersonaVault`.
2. Skill validates required inputs.
3. Skill runs a bundled renderer script.
4. Script reads the approved Markdown cards.
5. Script writes `output_dir/index.html`.
6. User opens the file directly in a browser.

## Technical Approach

- Create a new skill folder: `skills/persona-vault-static-site/`
- Put operational guidance in `SKILL.md`.
- Put deterministic export logic in `scripts/render_persona_site.py`.
- Keep HTML structure in `templates/index.template.html`.
- Use Python standard library only.
- Use Tailwind CSS via CDN in the generated page.

## Content Model

The renderer should extract:

- Site title:
  - `site_title` input if provided
  - else profile title from `About Me`
  - else fallback to `Persona Profile`
- Hero summary:
  - `About Me -> 保守摘要`
- Current focus:
  - `Current Focus -> 近期焦点`
- Work style / preferences:
  - `Current Focus -> 当前可见任务风格`
  - `Values And Preferences`
- Work history:
  - `Work History`
- Capability cards:
  - title
  - `一句话定义`
  - `典型表现`
  - optional `可对外表述`
- Project cards:
  - title
  - `项目定义`
  - `可见内容`
  - optional `该项目体现的能力`

## Rendering Rules

- Missing files should not crash the whole render if enough profile content exists.
- Missing sections should be omitted, not invented.
- Internal wiki links such as `[[项目-Context OS Demo]]` should be rendered as plain text.
- Frontmatter must be ignored.
- Raw Markdown should be converted conservatively:
  - headings become section labels only where explicitly parsed
  - bullet lists become HTML lists
  - short paragraphs remain paragraphs
- The page should stay visually minimal and readable on desktop and mobile.

## Validation

- Add a regression test that runs the renderer against the sample `PersonaVault` in the parent workspace.
- Verify `index.html` is created.
- Verify generated HTML contains:
  - page title
  - `Current Focus`
  - at least one capability title
  - at least one project title

