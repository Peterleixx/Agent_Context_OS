# Agent Context OS Skills

This repository currently contains two Codex-oriented skills for a Markdown-first `PersonaVault` workflow:

- `build-persona-vault`
  - Build or refresh a local PersonaVault from authorized source files
- `compile-match-response`
  - Read a single Markdown request and compile a conservative evidence-backed Markdown response

## Structure

```text
skills/
  build-persona-vault/
    SKILL.md
    references/
    templates/
  compile-match-response/
    SKILL.md
    templates/
```

## Current MVP scope

- Markdown-first PersonaVault
- Single-file request / single-file response
- Conservative evidence-backed role matching
- Obsidian-friendly knowledge organization
