#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_JOB_MESSAGE = "正在调用本机 Codex 执行 PersonaVault 生成任务"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local PersonaVault generator app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--working-directory", default=os.getcwd())
    return parser.parse_args()


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


def resolve_static_site_renderer_path(repo_root: Path) -> Path:
    return repo_root / "skills" / "persona-vault-static-site" / "scripts" / "render_persona_site.py"


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
    return {
        "agents": [str(agent).strip() for agent in payload.get("agents", []) if str(agent).strip()],
        "workspace_dirs": grouped["workspace_dirs"],
        "source_dirs": grouped["source_dirs"],
        "chat_override_paths": grouped["chat_override_paths"],
        "profile_links": links,
        "output_dir": output_dir or str((working_directory / "PersonaVault").resolve()),
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
        "- Generate Home.md, capabilities, projects, evidence, policies, source map, and audit files.\n"
        "- Use the selected agents and local paths as authorized sources.\n"
        "- External links are reference-only; do not fetch network content.\n"
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


class JobState:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.status = "running"
        self.stage = "discovering_sources"
        self.message = "正在整理输入来源。"
        self.vault_path: str | None = None
        self.profile_path: str | None = None
        self.site_path: str | None = None
        self.site_url: str | None = None
        self.can_open_obsidian = False
        self.raw_output: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "vault_path": self.vault_path,
            "profile_path": self.profile_path,
            "site_path": self.site_path,
            "site_url": self.site_url,
            "can_open_obsidian": self.can_open_obsidian,
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

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._jobs.get(job_id)
            return None if state is None else state.to_dict()

    def _update_job(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            state = self._jobs[job_id]
            for key, value in changes.items():
                setattr(state, key, value)

    def _run_job(self, job_id: str, payload: dict[str, Any]) -> None:
        self._update_job(job_id, stage="discovering_sources", message="正在整理输入来源。")
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
                    return

                self._update_job(
                    job_id,
                    status="completed",
                    stage="completed",
                    message=final_message or "PersonaVault 已生成完成。",
                    vault_path=str(vault_path),
                    profile_path=str(profile_path),
                    site_path=str(site_path),
                    site_url=f"/generated/{job_id}",
                    can_open_obsidian=Path("/Applications/Obsidian.app").exists(),
                )
                return

            error_message = final_message or "\n".join(output_lines[-10:]).strip() or "Codex generation failed."
            self._update_job(
                job_id,
                status="failed",
                stage="failed",
                message=error_message,
            )

    def _render_persona_site(self, vault_path: Path, site_dir: Path) -> dict[str, Any]:
        renderer_script_path = resolve_static_site_renderer_path(self.repo_root)
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
        return {"ok": True, "site_path": str(site_path)}


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
        working_directory: Path,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.repo_root = repo_root
        self.runner = runner
        self.obsidian_opener = obsidian_opener
        self.working_directory = working_directory


def create_server(
    host: str,
    port: int,
    repo_root: Path,
    runner: Any,
    obsidian_opener: Any,
    working_directory: Path,
) -> PersonaGeneratorServer:
    return PersonaGeneratorServer(
        (host, port),
        AppHandler,
        repo_root.resolve(),
        runner,
        obsidian_opener,
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
        working_directory,
    )
    url = f"http://{args.host}:{server.server_address[1]}"
    print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
