#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_JOB_MESSAGE = "正在调用本机 Codex 执行 PersonaVault 生成任务"
DEFAULT_EDIT_MESSAGE = "正在应用自然语言修改并同步 PersonaVault 与网页预览。"
GITHUB_FETCH_TIMEOUT_SECONDS = 8.0
FOCUS_PRESET_LABELS = [
    "能力亮点",
    "代表项目",
    "工作经历",
    "领域方向",
    "业务结果",
    "协作风格",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local PersonaVault generator app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--working-directory", default=os.getcwd())
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args(argv)


def open_browser(url: str) -> None:
    webbrowser.open(url)


def split_path_mappings(path_mappings: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped = {
        "workspace_dirs": [],
        "source_dirs": [],
        "chat_override_paths": [],
    }
    mapping_to_key = {
        "workspace_dir": "workspace_dirs",
        "source_dir": "source_dirs",
        "chat_override": "chat_override_paths",
    }
    for item in path_mappings:
        key = mapping_to_key.get(str(item.get("type", "")).strip())
        path = str(item.get("path", "")).strip()
        if not key or not path:
            continue
        grouped[key].append(path)
    return grouped


def normalize_advanced_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    focus_presets = raw.get("focus_presets", [])
    if not isinstance(focus_presets, list):
        focus_presets = []
    return {
        "target_scene": str(raw.get("target_scene", "")).strip() or "job_jd",
        "job_jd_text": str(raw.get("job_jd_text", "")).strip(),
        "focus_presets": [
            item
            for item in [str(entry).strip() for entry in focus_presets]
            if item in FOCUS_PRESET_LABELS
        ],
        "focus_custom": str(raw.get("focus_custom", "")).strip(),
        "redaction_profile": str(raw.get("redaction_profile", "")).strip() or "conservative",
        "redaction_custom_rules": str(raw.get("redaction_custom_rules", "")).strip(),
    }


def parse_codex_output_lines(lines: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def extract_github_owner(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None
    owner = path_parts[0].strip()
    return owner or None


def fetch_json_from_url(
    url: str,
    opener: Any = urlopen,
    timeout: float = GITHUB_FETCH_TIMEOUT_SECONDS,
) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PersonaVaultGeneratorApp/1.0",
        },
    )
    with opener(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def collect_github_public_data(
    profile_links: list[dict[str, Any]],
    fetch_json: Any = fetch_json_from_url,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in profile_links:
        if str(item.get("kind", "")).strip() != "github":
            continue
        url = str(item.get("url", "")).strip()
        owner = extract_github_owner(url)
        if not owner or owner in seen:
            continue
        seen.add(owner)
        try:
            profile = fetch_json(f"https://api.github.com/users/{owner}")
            repositories = fetch_json(
                f"https://api.github.com/users/{owner}/repos?per_page=6&sort=updated"
            )
        except Exception:
            continue
        if not isinstance(profile, dict) or not isinstance(repositories, list):
            continue

        cleaned_repositories: list[dict[str, Any]] = []
        languages: list[str] = []
        for repo in repositories:
            if not isinstance(repo, dict) or repo.get("fork"):
                continue
            language = str(repo.get("language", "")).strip()
            if language and language not in languages:
                languages.append(language)
            cleaned_repositories.append(
                {
                    "name": str(repo.get("name", "")).strip(),
                    "url": str(repo.get("html_url", "")).strip(),
                    "description": str(repo.get("description", "") or "").strip(),
                    "language": language,
                    "stars": int(repo.get("stargazers_count", 0) or 0),
                }
            )

        collected.append(
            {
                "owner": owner,
                "profile_url": f"https://github.com/{owner}",
                "profile": {
                    "login": str(profile.get("login", "")).strip(),
                    "name": str(profile.get("name", "") or "").strip(),
                    "bio": str(profile.get("bio", "") or "").strip(),
                    "blog": str(profile.get("blog", "") or "").strip(),
                    "public_repos": int(profile.get("public_repos", 0) or 0),
                    "followers": int(profile.get("followers", 0) or 0),
                    "following": int(profile.get("following", 0) or 0),
                },
                "repositories": cleaned_repositories[:4],
                "top_languages": languages[:4],
            }
        )
    return collected


def enrich_payload_with_github_data(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    links = payload.get("links", [])
    if not isinstance(links, list):
        links = []
    if enriched.get("github_public_data"):
        return enriched
    enriched["github_public_data"] = collect_github_public_data(links)
    return enriched


def build_codex_command(output_last_message_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--model",
        "gpt-5.4",
        "-c",
        'model_reasoning_effort="medium"',
        "-s",
        "danger-full-access",
        "--skip-git-repo-check",
        "--json",
        "-o",
        str(output_last_message_path),
        "-",
    ]


def resolve_renderer_script_path(repo_root: Path) -> Path:
    return repo_root / "skills" / "persona-vault-generator-app" / "scripts" / "render_persona_site.py"


def resolve_site_output_paths(vault_path: Path) -> tuple[Path, Path]:
    site_dir = vault_path / "_site"
    site_path = site_dir / "index.html"
    return site_dir, site_path


def build_persona_site_command(
    renderer_script_path: Path, vault_path: Path, output_dir: Path, site_title: str
) -> list[str]:
    return [
        sys.executable,
        str(renderer_script_path),
        "--persona-vault-path",
        str(vault_path),
        "--output-dir",
        str(output_dir),
        "--site-title",
        site_title,
    ]


def build_edit_prompt(repo_root: Path, vault_path: Path, instruction: str) -> str:
    skill_path = repo_root / "skills" / "build-persona-vault" / "SKILL.md"
    structure_path = (
        repo_root / "skills" / "build-persona-vault" / "references" / "persona-vault-structure.md"
    )
    render_profile_path = vault_path / ".persona-system" / "render-profile.json"
    return (
        "Read the repository-local PersonaVault skill and use it as the guardrail for this edit.\n\n"
        f"Skill path: {skill_path}\n"
        f"Structure reference: {structure_path}\n\n"
        "Task:\n"
        "- Apply a natural-language edit to the existing PersonaVault.\n"
        f"- PersonaVault root: {vault_path}\n"
        f"- Structured render profile path: {render_profile_path}\n"
        "- You MUST 同时修改 human-readable Markdown cards and `.persona-system/render-profile.json`.\n"
        "- Treat this as a 自然语言修改 / 重写 request against an existing vault, not a fresh rebuild.\n"
        "- Keep `00 - Profile/主要人物画像.md` as the primary profile entry.\n"
        "- Keep `01 - Capabilities/能力地图.md` consistent with render-profile data, especially the `核心能力总览` table.\n"
        "- Preserve the advanced settings context and conservative redaction style unless the instruction explicitly changes emphasis.\n"
        "- Do not delete the vault or unrelated notes. Update only the files needed to satisfy the edit request.\n"
        "- Do not render the website yourself; the local app will regenerate the preview after your edits.\n\n"
        "Natural-language instruction:\n"
        f"{instruction.strip()}\n"
    )


def normalize_payload(payload: dict[str, Any], working_directory: Path) -> dict[str, Any]:
    grouped = split_path_mappings(payload.get("path_mappings", []))
    links = [
        {
            "kind": str(item.get("kind", "")).strip(),
            "url": str(item.get("url", "")).strip(),
        }
        for item in payload.get("links", [])
        if str(item.get("kind", "")).strip() and str(item.get("url", "")).strip()
    ]
    output_dir = str(payload.get("output_dir", "")).strip()
    github_public_data = payload.get("github_public_data", [])
    if not isinstance(github_public_data, list):
        github_public_data = []
    return {
        "agents": [str(agent).strip() for agent in payload.get("agents", []) if str(agent).strip()],
        "workspace_dirs": grouped["workspace_dirs"],
        "source_dirs": grouped["source_dirs"],
        "chat_override_paths": grouped["chat_override_paths"],
        "profile_links": links,
        "github_public_data": github_public_data,
        "output_dir": output_dir or str((working_directory / "PersonaVault").resolve()),
        "advanced_settings": normalize_advanced_settings(payload.get("advanced_settings")),
    }


def build_generation_prompt(repo_root: Path, payload: dict[str, Any], working_directory: Path) -> str:
    skill_path = repo_root / "skills" / "build-persona-vault" / "SKILL.md"
    structure_path = (
        repo_root / "skills" / "build-persona-vault" / "references" / "persona-vault-structure.md"
    )
    normalized = normalize_payload(payload, working_directory)
    return (
        "Read the repository-local PersonaVault skill and follow it as the primary workflow.\n\n"
        f"Skill path: {skill_path}\n"
        f"Structure reference: {structure_path}\n\n"
        "Task:\n"
        "- Build or refresh a complete PersonaVault.\n"
        "- The primary profile file MUST be `00 - Profile/主要人物画像.md`.\n"
        "- Generate Home.md, profile support files, capabilities, projects, evidence, policies, source map, and audit files.\n"
        "- You MUST also write `.persona-system/render-profile.json` with machine-readable rendering data.\n"
        "- You MUST also write `.persona-system/openclaw-agent.json` for one-click OpenClaw deployment.\n"
        "- `01 - Capabilities/能力地图.md` MUST contain a `## 核心能力总览` Markdown table.\n"
        "- The `核心能力总览` table MUST include columns: `能力 | 当前判断 | 置信度 | 图标 | 关键词`.\n"
        "- Create or refresh `00 - Profile/About Me.md`, `00 - Profile/Current Focus.md`, `00 - Profile/Values And Preferences.md`, and `00 - Profile/Work History.md`.\n"
        "- `render-profile.json` MUST include: `generation_context`, `profile_facets`, `keyword_chips`, `focus_items`, `work_style_items`, `value_cards`, `capability_metrics`, `project_capability_matrix`, and `public_summary`.\n"
        "- `openclaw-agent.json` MUST include: `agent_slug`, `display_name`, `soul_summary`, `agent_rules`, `user_model`, `identity_card`, and `source_snapshot`.\n"
        "- Every capability metric in `render-profile.json` MUST have `icon`, `title`, `short_title`, `judgment`, `confidence`, and `score`.\n"
        "- `profile_facets` are for key profile icon cards and every item MUST have `icon`, `title`, and `summary`.\n"
        "- If `github_public_data` is present, use it as authorized external evidence and reflect it in source map, project summaries, and render-profile external source cards.\n"
        "- Use the selected agents and local paths as authorized sources.\n"
        "- The target scene for this run is 岗位/JD unless the structured input says otherwise.\n"
        "- External links are reference-only; do not fetch additional network content beyond the pre-fetched GitHub public data in the structured input.\n"
        "- If the output directory already exists, refresh conservatively instead of deleting cards.\n"
        "- Default to Markdown-first output that Obsidian can open directly.\n\n"
        "Structured input JSON:\n"
        f"{json.dumps(normalized, ensure_ascii=False, indent=2)}\n"
    )


def resolve_output_paths(payload: dict[str, Any], working_directory: Path) -> tuple[Path, Path]:
    normalized = normalize_payload(payload, working_directory)
    vault_path = Path(normalized["output_dir"]).expanduser().resolve()
    profile_path = vault_path / "00 - Profile" / "主要人物画像.md"
    return vault_path, profile_path


def load_renderer_module(repo_root: Path) -> Any:
    script_path = resolve_renderer_script_path(repo_root)
    module_name = "persona_vault_renderer_runtime"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def write_text_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def slugify_agent_id(value: str) -> str:
    raw = value.strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")
    return raw or "persona-vault"


def derive_default_agent_slug(vault_name: str) -> str:
    raw = vault_name.strip().lower()
    while raw.count("-") >= 3:
        prefix, _, suffix = raw.rpartition("-")
        if len(suffix) >= 5 and re.fullmatch(r"[0-9a-z]+", suffix):
            raw = prefix
            continue
        if len(suffix) <= 2 and re.fullmatch(r"[0-9]+", suffix):
            raw = prefix
            continue
        break
    return slugify_agent_id(raw)


def resolve_unique_agent_id(base_slug: str, home_dir: Path | None = None) -> str:
    home_dir = (home_dir or Path.home()).expanduser().resolve()
    state_dir = home_dir / ".openclaw"
    candidate = slugify_agent_id(base_slug)
    suffix = 2
    while (
        (state_dir / f"workspace-{candidate}").exists()
        or (state_dir / "agents" / candidate).exists()
    ):
        candidate = f"{slugify_agent_id(base_slug)}-{suffix}"
        suffix += 1
    return candidate


def build_openclaw_setup_command() -> list[str]:
    return ["openclaw", "setup", "--non-interactive"]


def build_openclaw_add_agent_command(agent_id: str, workspace_path: Path) -> list[str]:
    return [
        "openclaw",
        "agents",
        "add",
        agent_id,
        "--non-interactive",
        "--workspace",
        str(workspace_path),
    ]


def build_openclaw_health_command() -> list[str]:
    return ["openclaw", "health", "--json"]


def build_openclaw_gateway_start_command() -> list[str]:
    return ["openclaw", "gateway", "start", "--json"]


def build_openclaw_gateway_restart_command() -> list[str]:
    return ["openclaw", "gateway", "restart", "--json"]


def build_openclaw_docs_url() -> str:
    return "https://docs.openclaw.ai/start/openclaw"


def build_openclaw_agent_profile(
    vault_path: Path,
    render_profile: dict[str, Any],
    renderer_module: Any,
) -> dict[str, Any]:
    def normalize_string_items(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(item.get("title") or item.get("summary") or "").strip()
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    primary_profile = renderer_module.load_markdown_if_exists(
        vault_path / "00 - Profile" / "主要人物画像.md"
    )
    role_summary = ""
    persona_lines: list[str] = []
    preference_lines: list[str] = []
    if primary_profile:
        role_summary = renderer_module.extract_first_paragraph(
            primary_profile.sections.get("当前角色定位", [])
        )
        persona_lines = renderer_module.extract_bullets(
            primary_profile.sections.get("当前关注主题", [])
        )
        preference_lines = renderer_module.extract_bullets(
            primary_profile.sections.get("稳定偏好与决策风格", [])
        )

    capability_metrics = render_profile.get("capability_metrics", [])
    if not isinstance(capability_metrics, list):
        capability_metrics = []
    top_capabilities = [
        str(item.get("short_title") or item.get("title") or "").strip()
        for item in capability_metrics[:3]
        if isinstance(item, dict)
    ]
    top_capabilities = [item for item in top_capabilities if item]

    keyword_chips = normalize_string_items(render_profile.get("keyword_chips", []))
    focus_items = normalize_string_items(render_profile.get("focus_items", []))
    work_style_items = normalize_string_items(render_profile.get("work_style_items", []))
    public_summary = normalize_string_items(render_profile.get("public_summary", []))

    base_name = derive_default_agent_slug(vault_path.name)
    display_name = role_summary or f"{vault_path.name} 分身"
    soul_parts = [
        role_summary or "继承 PersonaVault 画像的 OpenClaw 分身。",
        "关注重点：" + "；".join(item for item in persona_lines[:3] if item) if persona_lines else "",
        "核心能力：" + "、".join(item for item in top_capabilities[:3] if item) if top_capabilities else "",
        "工作方式：" + "；".join(item for item in (work_style_items or preference_lines)[:3] if item)
        if (work_style_items or preference_lines)
        else "",
    ]
    soul_summary = "\n".join(item for item in soul_parts if item)

    agent_rule_lines = [
        "优先遵循 PersonaVault 已明确的能力边界、判断风格与可公开表达范围。",
        "在信息不足时保守表述，不要补造经历、数据或关系。",
    ]
    if public_summary:
        agent_rule_lines.append(
            "可稳定复述的公开摘要：" + "；".join(str(item).strip() for item in public_summary[:3] if str(item).strip())
        )
    agent_rules = "\n".join(f"- {line}" for line in agent_rule_lines)

    user_model = "\n".join(
        [
            f"- 服务对象画像来自 {vault_path.name} 的 PersonaVault。",
            "- 对外协作时默认保持证据驱动、约束优先、最小可行交付。",
        ]
    )
    identity_bits = [display_name] + [str(item).strip() for item in keyword_chips[:3] if str(item).strip()]
    identity_card = " | ".join(identity_bits)

    return {
        "agent_slug": base_name,
        "display_name": display_name,
        "soul_summary": soul_summary,
        "agent_rules": agent_rules,
        "user_model": user_model,
        "identity_card": identity_card,
        "source_snapshot": {
            "vault_path": str(vault_path),
            "render_profile_path": str(vault_path / ".persona-system" / "render-profile.json"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def open_obsidian_vault(vault_path: str) -> dict[str, Any]:
    target = Path(vault_path).expanduser().resolve()
    if not target.exists():
        return {"ok": False, "message": f"Vault path does not exist: {target}"}
    if not Path("/Applications/Obsidian.app").exists():
        return {"ok": False, "message": "Obsidian.app is not installed in /Applications."}

    result = subprocess.run(
        ["open", "-a", "Obsidian", str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "message": result.stderr.strip() or "Failed to open Obsidian."}
    return {"ok": True, "message": "opened"}


def open_local_path(target_path: str) -> dict[str, Any]:
    target = Path(target_path).expanduser().resolve()
    if not target.exists():
        return {"ok": False, "message": f"Path does not exist: {target}"}
    result = subprocess.run(
        ["open", str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "message": result.stderr.strip() or "Failed to open local path."}
    return {"ok": True, "message": "opened"}


class JobState:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.source_job_id: str | None = None
        self.status = "running"
        self.stage = "discovering_sources"
        self.message = "正在整理输入来源。"
        self.vault_path: str | None = None
        self.profile_path: str | None = None
        self.site_path: str | None = None
        self.site_url: str | None = None
        self.can_open_obsidian = False
        self.openclaw_agent_id: str | None = None
        self.openclaw_workspace_path: str | None = None
        self.openclaw_docs_url: str | None = None
        self.raw_output: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source_job_id": self.source_job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "vault_path": self.vault_path,
            "profile_path": self.profile_path,
            "site_path": self.site_path,
            "site_url": self.site_url,
            "can_open_obsidian": self.can_open_obsidian,
            "openclaw_agent_id": self.openclaw_agent_id,
            "openclaw_workspace_path": self.openclaw_workspace_path,
            "openclaw_docs_url": self.openclaw_docs_url,
        }


class CodexPersonaJobRunner:
    def __init__(self, repo_root: Path, working_directory: Path):
        self.repo_root = repo_root
        self.working_directory = working_directory
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def start_job(self, payload: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        state = JobState(job_id=job_id)
        with self._lock:
            self._jobs[job_id] = state
        thread = threading.Thread(target=self._run_job, args=(job_id, payload), daemon=True)
        thread.start()
        return job_id

    def start_edit_job(self, job_id: str, instruction: str) -> str:
        source_job = self.get_job(job_id)
        if source_job is None:
            raise ValueError("job not found")
        vault_path = str(source_job.get("vault_path", "")).strip()
        if not vault_path:
            raise ValueError("job has no generated PersonaVault")
        edit_job_id = f"job_{uuid.uuid4().hex[:10]}"
        state = JobState(job_id=edit_job_id)
        state.vault_path = vault_path
        state.profile_path = str(source_job.get("profile_path", "")).strip() or None
        state.site_path = str(source_job.get("site_path", "")).strip() or None
        state.site_url = str(source_job.get("site_url", "")).strip() or None
        with self._lock:
            self._jobs[edit_job_id] = state
        thread = threading.Thread(
            target=self._run_edit_job,
            args=(edit_job_id, Path(vault_path), instruction),
            daemon=True,
        )
        thread.start()
        return edit_job_id

    def start_deploy_job(self, job_id: str) -> str:
        source_job = self.get_job(job_id)
        if source_job is None:
            raise ValueError("job not found")
        vault_path = str(source_job.get("vault_path", "")).strip()
        if not vault_path:
            raise ValueError("job has no generated PersonaVault")
        deploy_job_id = f"job_{uuid.uuid4().hex[:10]}"
        state = JobState(job_id=deploy_job_id)
        state.source_job_id = job_id
        state.vault_path = vault_path
        state.profile_path = str(source_job.get("profile_path", "")).strip() or None
        state.site_path = str(source_job.get("site_path", "")).strip() or None
        state.site_url = str(source_job.get("site_url", "")).strip() or None
        with self._lock:
            self._jobs[deploy_job_id] = state
        thread = threading.Thread(
            target=self._run_deploy_job,
            args=(deploy_job_id, Path(vault_path)),
            daemon=True,
        )
        thread.start()
        return deploy_job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._jobs.get(job_id)
            return None if state is None else state.to_dict()

    def _update_job(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            state = self._jobs[job_id]
            for key, value in changes.items():
                setattr(state, key, value)

    def _enhance_persona_vault(self, vault_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        renderer_module = load_renderer_module(self.repo_root)
        normalized = normalize_payload(payload, self.working_directory)
        advanced_settings = normalized["advanced_settings"]
        github_public_data = normalized.get("github_public_data", [])
        fallback_profile = renderer_module.build_render_profile_from_markdown(
            vault_path,
            advanced_settings,
        )
        render_profile = renderer_module.merge_render_profile(
            renderer_module.load_render_profile_if_exists(vault_path),
            fallback_profile,
        )
        if github_public_data:
            render_profile["external_source_cards"] = self._build_external_source_cards(
                github_public_data
            )
        self._ensure_profile_support_files(vault_path, render_profile)
        self._ensure_capability_map_table(vault_path, render_profile)
        self._write_github_source_map(vault_path, github_public_data)
        self._write_render_profile_json(vault_path, render_profile)
        self._write_openclaw_agent_profile_json(vault_path, render_profile, renderer_module)
        return render_profile

    def _build_external_source_cards(
        self,
        github_public_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for item in github_public_data:
            if not isinstance(item, dict):
                continue
            profile = item.get("profile", {})
            if not isinstance(profile, dict):
                profile = {}
            name = str(profile.get("name", "") or item.get("owner", "")).strip()
            bio = str(profile.get("bio", "") or "").strip()
            languages = item.get("top_languages", [])
            if not isinstance(languages, list):
                languages = []
            repos = item.get("repositories", [])
            if not isinstance(repos, list):
                repos = []
            repo_names = [str(repo.get("name", "")).strip() for repo in repos if isinstance(repo, dict)]
            meta = []
            if item.get("owner"):
                meta.append(f"owner: {item['owner']}")
            if languages:
                meta.append(f"languages: {', '.join(str(language) for language in languages[:3])}")
            if repo_names:
                meta.append(f"repos: {', '.join(name for name in repo_names[:3] if name)}")
            cards.append(
                {
                    "icon": "book",
                    "title": "GitHub 公开资料",
                    "summary": bio or f"{name} 的公开主页与代表仓库摘要。",
                    "meta": meta,
                    "url": str(item.get("profile_url", "")).strip(),
                }
            )
        return cards

    def _write_github_source_map(
        self,
        vault_path: Path,
        github_public_data: list[dict[str, Any]],
    ) -> None:
        if not github_public_data:
            return
        source_map_dir = vault_path / "07 - Source Map"
        source_map_dir.mkdir(parents=True, exist_ok=True)
        lines = ["# GitHub公开资料", ""]
        for item in github_public_data:
            if not isinstance(item, dict):
                continue
            owner = str(item.get("owner", "")).strip()
            profile = item.get("profile", {})
            if not isinstance(profile, dict):
                profile = {}
            lines.append(f"## {owner or 'github-profile'}")
            lines.append("")
            if item.get("profile_url"):
                lines.append(f"- 链接: {item['profile_url']}")
            if profile.get("name"):
                lines.append(f"- 名称: {profile['name']}")
            if profile.get("bio"):
                lines.append(f"- 简介: {profile['bio']}")
            languages = item.get("top_languages", [])
            if isinstance(languages, list) and languages:
                lines.append(f"- 主要语言: {', '.join(str(language) for language in languages[:4])}")
            repositories = item.get("repositories", [])
            if isinstance(repositories, list) and repositories:
                lines.append("- 代表仓库:")
                for repo in repositories[:4]:
                    if not isinstance(repo, dict):
                        continue
                    repo_name = str(repo.get("name", "")).strip()
                    repo_desc = str(repo.get("description", "")).strip()
                    repo_lang = str(repo.get("language", "")).strip()
                    repo_stars = int(repo.get("stars", 0) or 0)
                    detail = " / ".join(
                        part for part in [repo_desc, repo_lang, f"stars {repo_stars}" if repo_stars else ""] if part
                    )
                    lines.append(f"  - {repo_name}" + (f": {detail}" if detail else ""))
            lines.append("")
        (source_map_dir / "GitHub公开资料.md").write_text("\n".join(lines), encoding="utf-8")

    def _refresh_persona_outputs(
        self,
        job_id: str,
        vault_path: Path,
        profile_path: Path,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        self._update_job(job_id, stage="writing_vault", message="正在补齐结构化画像数据。")
        try:
            if payload is None:
                payload = {
                    "agents": [],
                    "path_mappings": [],
                    "links": [],
                    "output_dir": str(vault_path),
                    "advanced_settings": (
                        load_renderer_module(self.repo_root)
                        .load_render_profile_if_exists(vault_path)
                        or {}
                    ).get("generation_context", {}),
                }
            self._enhance_persona_vault(vault_path, payload)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message=f"补齐结构化画像数据失败: {exc}",
                vault_path=str(vault_path),
                profile_path=str(profile_path),
            )
            return False

        self._update_job(job_id, stage="writing_vault", message="正在导出静态网页。")
        site_dir, site_path = resolve_site_output_paths(vault_path)
        site_result = self._render_persona_site(vault_path, site_dir)
        if not site_result["ok"]:
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message=site_result["message"],
                vault_path=str(vault_path),
                profile_path=str(profile_path),
            )
            return False

        self._update_job(
            job_id,
            status="completed",
            stage="completed",
            message=site_result.get("message", "PersonaVault 已生成完成。"),
            vault_path=str(vault_path),
            profile_path=str(profile_path),
            site_path=str(site_path),
            site_url=f"/generated/{job_id}",
            can_open_obsidian=Path("/Applications/Obsidian.app").exists(),
        )
        return True

    def _ensure_profile_support_files(self, vault_path: Path, render_profile: dict[str, Any]) -> None:
        profile_dir = vault_path / "00 - Profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        public_summary = [str(item) for item in render_profile.get("public_summary", []) if str(item).strip()]
        keyword_chips = [str(item) for item in render_profile.get("keyword_chips", []) if str(item).strip()]
        focus_items = [str(item) for item in render_profile.get("focus_items", []) if str(item).strip()]
        work_style_items = [str(item) for item in render_profile.get("work_style_items", []) if str(item).strip()]
        value_cards = render_profile.get("value_cards", [])

        about_lines = ["# About Me", "", "## 保守摘要", ""]
        about_lines.extend([f"- {item}" for item in public_summary] or ["- 资料待补"])
        about_lines.extend(["", "## 画像关键词", "", "| 关键词 | 说明 |", "| --- | --- |"])
        about_lines.extend(
            [f"| {item} | 来自本次画像提炼与岗位/JD聚焦 |" for item in keyword_chips]
            or ["| 资料待补 | 待补充关键词 |"]
        )
        write_text_if_missing(profile_dir / "About Me.md", "\n".join(about_lines) + "\n")

        focus_lines = ["# Current Focus", "", "## 近期焦点", ""]
        focus_lines.extend([f"- {item}" for item in focus_items] or ["- 资料待补"])
        focus_lines.extend(["", "## 当前可见任务风格", ""])
        focus_lines.extend([f"- {item}" for item in work_style_items] or ["- 资料待补"])
        write_text_if_missing(profile_dir / "Current Focus.md", "\n".join(focus_lines) + "\n")

        values_lines = ["# Values And Preferences", "", "## 核心偏好", ""]
        if isinstance(value_cards, list) and value_cards:
            for item in value_cards:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                description = str(item.get("description", "")).strip()
                if not title:
                    continue
                values_lines.append(f"- {title}")
                if description:
                    values_lines.append(f"  - {description}")
        else:
            values_lines.append("- 资料待补")
        write_text_if_missing(profile_dir / "Values And Preferences.md", "\n".join(values_lines) + "\n")

        work_history_lines = [
            "# Work History",
            "",
            "## 资料不足",
            "",
            "- 当前授权资料不足以恢复正式时间线",
            "- 如需岗位/JD版本的工作经历，请补充简历或工作区材料后刷新",
        ]
        write_text_if_missing(profile_dir / "Work History.md", "\n".join(work_history_lines) + "\n")

    def _ensure_capability_map_table(self, vault_path: Path, render_profile: dict[str, Any]) -> None:
        capability_dir = vault_path / "01 - Capabilities"
        capability_dir.mkdir(parents=True, exist_ok=True)
        capability_map_path = capability_dir / "能力地图.md"
        existing = capability_map_path.read_text(encoding="utf-8") if capability_map_path.exists() else "# 能力地图\n"
        if "## 核心能力总览" in existing and "| 能力 | 当前判断 | 置信度 | 图标 | 关键词 |" in existing:
            return

        metrics = render_profile.get("capability_metrics", [])
        lines = ["", "## 核心能力总览", "", "| 能力 | 当前判断 | 置信度 | 图标 | 关键词 |", "| --- | --- | --- | --- | --- |"]
        if isinstance(metrics, list) and metrics:
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                keywords = metric.get("keywords", [])
                if not isinstance(keywords, list):
                    keywords = []
                keyword_text = ", ".join(str(item).strip() for item in keywords if str(item).strip())
                lines.append(
                    f"| {str(metric.get('title', '')).strip()} | {str(metric.get('judgment', '')).strip()} | "
                    f"{str(metric.get('confidence', '')).strip()} | {str(metric.get('icon', '')).strip()} | {keyword_text} |"
                )
        else:
            lines.append("| 能力-资料待补 | 待补充 | 中 | sparkles | 待补充 |")
        capability_map_path.write_text(existing.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")

    def _write_render_profile_json(self, vault_path: Path, render_profile: dict[str, Any]) -> None:
        system_dir = vault_path / ".persona-system"
        system_dir.mkdir(parents=True, exist_ok=True)
        path = system_dir / "render-profile.json"
        path.write_text(
            json.dumps(render_profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_openclaw_agent_profile_json(
        self,
        vault_path: Path,
        render_profile: dict[str, Any],
        renderer_module: Any,
    ) -> None:
        system_dir = vault_path / ".persona-system"
        system_dir.mkdir(parents=True, exist_ok=True)
        path = system_dir / "openclaw-agent.json"
        payload = build_openclaw_agent_profile(vault_path, render_profile, renderer_module)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _run_job(self, job_id: str, payload: dict[str, Any]) -> None:
        self._update_job(job_id, stage="discovering_sources", message="正在整理输入来源。")
        payload = enrich_payload_with_github_data(payload)
        if normalize_payload(payload, self.working_directory).get("github_public_data"):
            self._update_job(job_id, stage="discovering_sources", message="正在抓取 GitHub 公开资料。")
        prompt = build_generation_prompt(self.repo_root, payload, self.working_directory)
        self._update_job(job_id, stage="preparing_prompt", message="正在整理 Codex 生成指令。")

        with tempfile.TemporaryDirectory(prefix="persona-vault-job-") as tmp_dir:
            last_message_path = Path(tmp_dir) / "last-message.txt"
            command = build_codex_command(last_message_path)

            self._update_job(job_id, stage="running_codex", message=DEFAULT_JOB_MESSAGE)
            process = subprocess.Popen(
                command,
                cwd=str(self.working_directory),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(prompt)
            process.stdin.close()

            output_lines: list[str] = []
            for line in process.stdout:
                output_lines.append(line.rstrip("\n"))
            return_code = process.wait()

            self._update_job(job_id, stage="writing_vault", message="正在核对 PersonaVault 输出结构。")

            vault_path, profile_path = resolve_output_paths(payload, self.working_directory)
            final_message = ""
            if last_message_path.exists():
                final_message = last_message_path.read_text(encoding="utf-8").strip()
            if return_code == 0 and vault_path.exists():
                self._refresh_persona_outputs(job_id, vault_path, profile_path, payload)
                if final_message and self.get_job(job_id) and self.get_job(job_id)["status"] == "completed":
                    self._update_job(job_id, message=final_message)
                return

            error_message = final_message or "\n".join(output_lines[-10:]).strip() or "Codex generation failed."
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message=error_message,
            )

    def _render_persona_site(self, vault_path: Path, site_dir: Path) -> dict[str, Any]:
        renderer_script_path = resolve_renderer_script_path(self.repo_root)
        if not renderer_script_path.exists():
            return {
                "ok": False,
                "message": f"静态站脚本不存在: {renderer_script_path}",
            }

        site_dir.mkdir(parents=True, exist_ok=True)
        command = build_persona_site_command(
            renderer_script_path,
            vault_path,
            site_dir,
            f"{vault_path.name} Profile",
        )
        result = subprocess.run(
            command,
            cwd=str(self.working_directory),
            capture_output=True,
            text=True,
        )
        _, site_path = resolve_site_output_paths(vault_path)
        if result.returncode != 0 or not site_path.exists():
            message = result.stderr.strip() or result.stdout.strip() or "静态网页导出失败。"
            return {"ok": False, "message": message}
        return {"ok": True, "site_path": str(site_path), "message": "PersonaVault 与网页预览已同步完成。"}

    def _load_openclaw_agent_profile(self, vault_path: Path) -> dict[str, Any]:
        path = vault_path / ".persona-system" / "openclaw-agent.json"
        if not path.exists():
            raise FileNotFoundError(f"缺少 OpenClaw 部署画像: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("OpenClaw 部署画像格式无效。")
        return data

    def _run_checked_command(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "command failed"
            raise RuntimeError(message)
        return result

    def _write_openclaw_workspace_files(
        self,
        workspace_path: Path,
        agent_profile: dict[str, Any],
        vault_path: Path,
    ) -> None:
        workspace_path.mkdir(parents=True, exist_ok=True)
        display_name = str(agent_profile.get("display_name", "")).strip() or "PersonaVault 分身"
        soul_summary = str(agent_profile.get("soul_summary", "")).strip()
        agent_rules = str(agent_profile.get("agent_rules", "")).strip()
        user_model = str(agent_profile.get("user_model", "")).strip()
        identity_card = str(agent_profile.get("identity_card", "")).strip()

        files = {
            "SOUL.md": "\n".join(
                [
                    "# SOUL",
                    "",
                    f"你是 `{display_name}`，这是一个由 PersonaVault 部署出的 OpenClaw 分身。",
                    "",
                    "## Persona Summary",
                    "",
                    soul_summary or "保持保守、证据驱动、可交付导向的画像风格。",
                    "",
                ]
            ),
            "AGENTS.md": "\n".join(
                [
                    "# AGENTS",
                    "",
                    "## Session Startup",
                    "",
                    agent_rules or "- 优先遵循 PersonaVault 的能力边界和保守表达原则。",
                    "",
                    "## Red Lines",
                    "",
                    "- 不要虚构经历、数据、组织关系或未授权事实。",
                    "- 不要绕过当前 PersonaVault 明确写出的可说边界和脱敏要求。",
                    "",
                ]
            ),
            "USER.md": "\n".join(["# USER", "", user_model or "- 当前服务对象来自对应 PersonaVault。"]),
            "IDENTITY.md": "\n".join(["# IDENTITY", "", identity_card or display_name]),
            "PERSONA_VAULT_SOURCE.md": "\n".join(
                [
                    "# PersonaVault Source",
                    "",
                    f"- Source Vault: {vault_path}",
                    f"- Deployment Profile: {vault_path / '.persona-system' / 'openclaw-agent.json'}",
                    f"- Render Profile: {vault_path / '.persona-system' / 'render-profile.json'}",
                    "",
                ]
            ),
        }
        for file_name, content in files.items():
            (workspace_path / file_name).write_text(content + "\n", encoding="utf-8")

    def _run_deploy_job(self, job_id: str, vault_path: Path) -> None:
        self._update_job(job_id, stage="deploy_preparing_profile", message="正在准备 OpenClaw 部署画像。")
        try:
            agent_profile = self._load_openclaw_agent_profile(vault_path)
        except Exception as exc:
            self._update_job(job_id, status="failed", stage="failed", message=str(exc))
            return

        self._update_job(job_id, stage="deploy_validating_openclaw", message="正在校验本机 OpenClaw 环境。")
        if shutil.which("openclaw") is None:
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message="未在 PATH 中找到 openclaw CLI。",
            )
            return

        home_dir = Path.home().expanduser().resolve()
        state_dir = home_dir / ".openclaw"
        config_path = state_dir / "openclaw.json"
        try:
            if not config_path.exists():
                self._run_checked_command(build_openclaw_setup_command(), self.working_directory)
        except Exception as exc:
            self._update_job(job_id, status="failed", stage="failed", message=f"初始化 OpenClaw 失败: {exc}")
            return

        agent_id = resolve_unique_agent_id(str(agent_profile.get("agent_slug", "")), home_dir)
        workspace_path = state_dir / f"workspace-{agent_id}"
        self._update_job(
            job_id,
            stage="deploy_creating_workspace",
            message="正在创建分身 workspace 并注册 agent。",
        )
        try:
            self._run_checked_command(
                build_openclaw_add_agent_command(agent_id, workspace_path),
                self.working_directory,
            )
        except Exception as exc:
            self._update_job(job_id, status="failed", stage="failed", message=f"注册 OpenClaw agent 失败: {exc}")
            return

        self._update_job(job_id, stage="deploy_writing_bootstrap", message="正在写入 persona bootstrap 文件。")
        try:
            self._write_openclaw_workspace_files(workspace_path, agent_profile, vault_path)
        except Exception as exc:
            self._update_job(job_id, status="failed", stage="failed", message=f"写入 workspace 文件失败: {exc}")
            return

        self._update_job(job_id, stage="deploy_starting_gateway", message="正在启动或重启 OpenClaw gateway。")
        try:
            health = subprocess.run(
                build_openclaw_health_command(),
                cwd=str(self.working_directory),
                capture_output=True,
                text=True,
            )
            if health.returncode == 0:
                self._run_checked_command(build_openclaw_gateway_restart_command(), self.working_directory)
            else:
                self._run_checked_command(build_openclaw_gateway_start_command(), self.working_directory)
        except Exception as exc:
            self._update_job(job_id, status="failed", stage="failed", message=f"启动 gateway 失败: {exc}")
            return

        self._update_job(
            job_id,
            status="completed",
            stage="completed",
            message="OpenClaw 分身 Agent 已部署完成。",
            openclaw_agent_id=agent_id,
            openclaw_workspace_path=str(workspace_path),
            openclaw_docs_url=build_openclaw_docs_url(),
        )

    def _run_edit_job(self, job_id: str, vault_path: Path, instruction: str) -> None:
        self._update_job(job_id, stage="preparing_prompt", message="正在整理自然语言修改指令。")
        prompt = build_edit_prompt(self.repo_root, vault_path, instruction)
        with tempfile.TemporaryDirectory(prefix="persona-vault-edit-") as tmp_dir:
            last_message_path = Path(tmp_dir) / "last-message.txt"
            command = build_codex_command(last_message_path)

            self._update_job(job_id, stage="running_codex", message=DEFAULT_EDIT_MESSAGE)
            process = subprocess.Popen(
                command,
                cwd=str(vault_path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(prompt)
            process.stdin.close()

            output_lines: list[str] = []
            for line in process.stdout:
                output_lines.append(line.rstrip("\n"))
            return_code = process.wait()

            profile_path = vault_path / "00 - Profile" / "主要人物画像.md"
            final_message = ""
            if last_message_path.exists():
                final_message = last_message_path.read_text(encoding="utf-8").strip()

            if return_code == 0 and vault_path.exists():
                refreshed = self._refresh_persona_outputs(job_id, vault_path, profile_path, None)
                if refreshed and final_message:
                    self._update_job(job_id, message=final_message)
                return

            error_message = final_message or "\n".join(output_lines[-10:]).strip() or "Codex edit failed."
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message=error_message,
                vault_path=str(vault_path),
                profile_path=str(profile_path),
            )


class AppHandler(BaseHTTPRequestHandler):
    server: "PersonaGeneratorServer"

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/":
            self._serve_index()
            return
        if request_path.startswith("/api/jobs/"):
            job_id = request_path.rsplit("/", 1)[-1]
            job = self.server.runner.get_job(job_id)
            if job is None:
                self._json_response({"message": "job not found"}, HTTPStatus.NOT_FOUND)
                return
            self._json_response(job, HTTPStatus.OK)
            return
        if request_path.startswith("/generated/"):
            job_id = request_path.rsplit("/", 1)[-1]
            job = self.server.runner.get_job(job_id)
            if job is None or not job.get("site_path"):
                self._json_response({"message": "generated site not found"}, HTTPStatus.NOT_FOUND)
                return
            self._serve_generated_site(Path(str(job["site_path"])))
            return
        self._json_response({"message": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/generate":
            payload = self._read_json_body()
            if not payload.get("agents"):
                self._json_response({"message": "至少需要选择一个 agent。"}, HTTPStatus.BAD_REQUEST)
                return
            job_id = self.server.runner.start_job(payload)
            self._json_response({"job_id": job_id}, HTTPStatus.OK)
            return

        if self.path == "/api/open-obsidian":
            payload = self._read_json_body()
            vault_path = str(payload.get("vault_path", "")).strip()
            result = self.server.obsidian_opener(vault_path)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._json_response(result, status)
            return

        if self.path == "/api/open-path":
            payload = self._read_json_body()
            local_path = str(payload.get("path", "")).strip()
            result = self.server.path_opener(local_path)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._json_response(result, status)
            return

        if self.path == "/api/edit":
            payload = self._read_json_body()
            job_id = str(payload.get("job_id", "")).strip()
            instruction = str(payload.get("instruction", "")).strip()
            if not job_id or not instruction:
                self._json_response({"message": "缺少 job_id 或 instruction。"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                edit_job_id = self.server.runner.start_edit_job(job_id, instruction)
            except ValueError as exc:
                self._json_response({"message": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._json_response({"job_id": edit_job_id}, HTTPStatus.OK)
            return

        if self.path == "/api/deploy-openclaw":
            payload = self._read_json_body()
            job_id = str(payload.get("job_id", "")).strip()
            if not job_id:
                self._json_response({"message": "缺少 job_id。"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                deploy_job_id = self.server.runner.start_deploy_job(job_id)
            except ValueError as exc:
                self._json_response({"message": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._json_response({"job_id": deploy_job_id}, HTTPStatus.OK)
            return

        self._json_response({"message": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _serve_index(self) -> None:
        template_path = (
            self.server.repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "templates"
            / "index.html"
        )
        html = template_path.read_text(encoding="utf-8")
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_generated_site(self, site_path: Path) -> None:
        resolved = site_path.expanduser().resolve()
        if not resolved.exists() or resolved.suffix.lower() != ".html":
            self._json_response({"message": "generated site not found"}, HTTPStatus.NOT_FOUND)
            return
        encoded = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _json_response(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class PersonaGeneratorServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        repo_root: Path,
        runner: Any,
        obsidian_opener: Any,
        path_opener: Any,
        working_directory: Path,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.repo_root = repo_root
        self.runner = runner
        self.obsidian_opener = obsidian_opener
        self.path_opener = path_opener
        self.working_directory = working_directory


def create_server(
    host: str,
    port: int,
    repo_root: Path,
    runner: Any,
    obsidian_opener: Any,
    path_opener: Any,
    working_directory: Path,
) -> PersonaGeneratorServer:
    return PersonaGeneratorServer(
        (host, port),
        AppHandler,
        repo_root.resolve(),
        runner,
        obsidian_opener,
        path_opener,
        working_directory.resolve(),
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    working_directory = Path(args.working_directory).expanduser().resolve()
    runner = CodexPersonaJobRunner(repo_root, working_directory)
    server = create_server(
        args.host,
        args.port,
        repo_root,
        runner,
        open_obsidian_vault,
        open_local_path,
        working_directory,
    )
    url = f"http://{args.host}:{server.server_address[1]}"
    print(url, flush=True)
    if args.open_browser:
        threading.Timer(0.2, open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
