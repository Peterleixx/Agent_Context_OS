import importlib.util
import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
import unittest


def load_generator_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = (
        repo_root
        / "skills"
        / "persona-vault-generator-app"
        / "scripts"
        / "run_persona_vault_generator_app.py"
    )
    spec = importlib.util.spec_from_file_location("persona_vault_generator_app", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    def __init__(self):
        self.last_payload = None
        self.last_edit = None
        self.job = {
            "job_id": "job_test",
            "status": "running",
            "stage": "running_codex",
            "message": "正在调用本机 Codex 执行 PersonaVault 生成任务",
        }

    def start_job(self, payload):
        self.last_payload = payload
        return self.job["job_id"]

    def start_edit_job(self, job_id, instruction):
        self.last_edit = {"job_id": job_id, "instruction": instruction}
        return "job_edit"

    def get_job(self, job_id):
        if job_id == "job_edit":
            return {
                "job_id": "job_edit",
                "status": "running",
                "stage": "running_codex",
                "message": "正在应用自然语言修改。",
            }
        if job_id != self.job["job_id"]:
            return None
        return self.job


class FakeOpener:
    def __init__(self):
        self.last_path = None

    def __call__(self, vault_path):
        self.last_path = vault_path
        return {"ok": True, "message": "opened"}


class PersonaVaultGeneratorAppTest(unittest.TestCase):
    def test_extract_github_owner_from_supported_urls(self):
        module = load_generator_module()

        self.assertEqual(module.extract_github_owner("https://github.com/openai"), "openai")
        self.assertEqual(module.extract_github_owner("https://github.com/openai/codex"), "openai")
        self.assertEqual(module.extract_github_owner("https://github.com/openai/"), "openai")
        self.assertIsNone(module.extract_github_owner("https://example.com/openai"))

    def test_collect_github_public_data_summarizes_profile_and_repos(self):
        module = load_generator_module()

        responses = {
            "https://api.github.com/users/openai": {
                "login": "openai",
                "name": "OpenAI",
                "bio": "AI research and deployment company.",
                "blog": "https://openai.com",
                "public_repos": 12,
                "followers": 999,
                "following": 1,
            },
            "https://api.github.com/users/openai/repos?per_page=6&sort=updated": [
                {
                    "name": "codex",
                    "html_url": "https://github.com/openai/codex",
                    "description": "Codex CLI and app.",
                    "language": "Python",
                    "stargazers_count": 4200,
                    "fork": False,
                },
                {
                    "name": "evals",
                    "html_url": "https://github.com/openai/evals",
                    "description": "Evaluation framework.",
                    "language": "Python",
                    "stargazers_count": 3800,
                    "fork": False,
                },
            ],
        }

        def fake_fetch_json(url):
            return responses[url]

        data = module.collect_github_public_data(
            [{"kind": "github", "url": "https://github.com/openai"}],
            fetch_json=fake_fetch_json,
        )

        self.assertEqual(len(data), 1)
        profile = data[0]
        self.assertEqual(profile["owner"], "openai")
        self.assertEqual(profile["profile"]["name"], "OpenAI")
        self.assertEqual(profile["top_languages"], ["Python"])
        self.assertEqual(profile["repositories"][0]["name"], "codex")

    def test_parse_args_supports_open_browser_flag(self):
        module = load_generator_module()

        args = module.parse_args(["--open-browser", "--port", "9999"])

        self.assertTrue(args.open_browser)
        self.assertEqual(args.port, 9999)

    def test_build_codex_command_uses_local_codex_exec(self):
        module = load_generator_module()

        command = module.build_codex_command(Path("/tmp/last-message.txt"))

        self.assertEqual(command[:4], ["codex", "exec", "--model", "gpt-5.4"])
        self.assertIn('-c', command)
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--json", command)
        self.assertIn("-", command)

    def test_build_persona_site_command_uses_external_renderer_skill(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        renderer_path = module.resolve_renderer_script_path(repo_root)

        command = module.build_persona_site_command(
            renderer_path,
            Path("/tmp/PersonaVault"),
            Path("/tmp/PersonaVault/_site"),
            "PersonaVault Preview",
        )

        self.assertEqual(command[0], module.sys.executable)
        self.assertEqual(command[1], str(renderer_path))
        self.assertEqual(
            renderer_path,
            repo_root / "skills" / "persona-vault-generator-app" / "scripts" / "render_persona_site.py",
        )
        self.assertIn("--persona-vault-path", command)
        self.assertIn("/tmp/PersonaVault", command)
        self.assertIn("--output-dir", command)
        self.assertIn("/tmp/PersonaVault/_site", command)
        self.assertIn("--site-title", command)
        self.assertIn("PersonaVault Preview", command)

    def test_split_path_mappings_groups_by_type(self):
        module = load_generator_module()

        grouped = module.split_path_mappings(
            [
                {"type": "workspace_dir", "path": "/tmp/workspace"},
                {"type": "source_dir", "path": "/tmp/docs"},
                {"type": "chat_override", "path": "/tmp/chat"},
            ]
        )

        self.assertEqual(grouped["workspace_dirs"], ["/tmp/workspace"])
        self.assertEqual(grouped["source_dirs"], ["/tmp/docs"])
        self.assertEqual(grouped["chat_override_paths"], ["/tmp/chat"])

    def test_normalize_payload_includes_advanced_settings(self):
        module = load_generator_module()

        normalized = module.normalize_payload(
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [],
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "AI Agent 产品经理",
                    "focus_presets": ["能力亮点", "代表项目"],
                    "focus_custom": "强调复杂工作流抽象能力",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "不要写真实公司名",
                },
            },
            Path("/tmp/workdir"),
        )

        self.assertEqual(normalized["advanced_settings"]["target_scene"], "job_jd")
        self.assertEqual(normalized["advanced_settings"]["focus_presets"], ["能力亮点", "代表项目"])
        self.assertEqual(normalized["advanced_settings"]["redaction_custom_rules"], "不要写真实公司名")

    def test_generation_prompt_mentions_render_profile_json_and_advanced_settings(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]

        prompt = module.build_generation_prompt(
            repo_root,
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [],
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "AI Agent 岗位 JD",
                    "focus_presets": ["能力亮点"],
                    "focus_custom": "",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "",
                },
            },
            Path("/tmp/workdir"),
        )

        self.assertIn(".persona-system/render-profile.json", prompt)
        self.assertIn("核心能力总览", prompt)
        self.assertIn('"target_scene": "job_jd"', prompt)
        self.assertIn("岗位/JD", prompt)

    def test_generation_prompt_mentions_github_public_data_when_present(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]

        prompt = module.build_generation_prompt(
            repo_root,
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [{"kind": "github", "url": "https://github.com/openai"}],
                "github_public_data": [
                    {
                        "owner": "openai",
                        "profile_url": "https://github.com/openai",
                        "profile": {"name": "OpenAI", "bio": "AI company"},
                        "repositories": [{"name": "codex", "url": "https://github.com/openai/codex"}],
                        "top_languages": ["Python"],
                    }
                ],
            },
            Path("/tmp/workdir"),
        )

        self.assertIn("github_public_data", prompt)
        self.assertIn("OpenAI", prompt)
        self.assertIn("codex", prompt)

    def test_build_edit_prompt_mentions_vault_and_render_profile_sync(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]

        prompt = module.build_edit_prompt(
            repo_root,
            Path("/tmp/PersonaVault"),
            "把人物画像改得更适合 AI Agent 岗位，强调代表项目，删掉过于投资化表述。",
        )

        self.assertIn("/tmp/PersonaVault", prompt)
        self.assertIn(".persona-system/render-profile.json", prompt)
        self.assertIn("同时修改", prompt)
        self.assertIn("自然语言修改", prompt)

    def test_parse_codex_output_skips_non_json_lines(self):
        module = load_generator_module()

        events = module.parse_codex_output_lines(
            [
                "WARN plugin warmup failed",
                '{"type":"thread.started","id":"1"}',
                "",
                '{"type":"message.delta","delta":"ok"}',
            ]
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "thread.started")
        self.assertEqual(events[1]["type"], "message.delta")

    def test_http_server_exposes_form_and_job_endpoints(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = FakeRunner()
        opener = FakeOpener()
        httpd = module.create_server("127.0.0.1", 0, repo_root, runner, opener, repo_root)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

        try:
            html = urllib.request.urlopen(f"{base_url}/").read().decode("utf-8")
            self.assertIn("Codex", html)
            self.assertIn("Claude Code", html)
            self.assertIn("workspace_dir", html)
            self.assertIn("linkedin", html)
            self.assertIn("output_dir", html)
            self.assertIn("岗位/JD", html)
            self.assertIn("job_jd_text", html)
            self.assertIn("redaction_custom_rules", html)
            self.assertIn("自然语言修改 / 重写", html)

            payload = {
                "agents": ["codex"],
                "path_mappings": [{"type": "workspace_dir", "path": "/tmp/workspace"}],
                "links": [{"kind": "github", "url": "https://github.com/example"}],
                "output_dir": "",
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "JD content",
                    "focus_presets": ["能力亮点", "代表项目"],
                    "focus_custom": "强调证据驱动",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "不要写真实公司名",
                },
            }
            request = urllib.request.Request(
                f"{base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = json.loads(urllib.request.urlopen(request).read().decode("utf-8"))
            self.assertEqual(response["job_id"], "job_test")
            self.assertEqual(runner.last_payload["agents"], ["codex"])
            self.assertEqual(runner.last_payload["advanced_settings"]["target_scene"], "job_jd")
            self.assertEqual(runner.last_payload["advanced_settings"]["focus_presets"], ["能力亮点", "代表项目"])

            job = json.loads(
                urllib.request.urlopen(f"{base_url}/api/jobs/job_test").read().decode("utf-8")
            )
            self.assertEqual(job["stage"], "running_codex")

            edit_request = urllib.request.Request(
                f"{base_url}/api/edit",
                data=json.dumps(
                    {
                        "job_id": "job_test",
                        "instruction": "强化代表项目，弱化投资内容",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            edit_response = json.loads(
                urllib.request.urlopen(edit_request).read().decode("utf-8")
            )
            self.assertEqual(edit_response["job_id"], "job_edit")
            self.assertEqual(runner.last_edit["job_id"], "job_test")
            self.assertEqual(runner.last_edit["instruction"], "强化代表项目，弱化投资内容")

            open_request = urllib.request.Request(
                f"{base_url}/api/open-obsidian",
                data=json.dumps({"vault_path": "/tmp/PersonaVault"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            open_response = json.loads(
                urllib.request.urlopen(open_request).read().decode("utf-8")
            )
            self.assertTrue(open_response["ok"])
            self.assertEqual(opener.last_path, "/tmp/PersonaVault")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_generated_site_endpoint_serves_rendered_html(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = FakeRunner()
        opener = FakeOpener()

        with tempfile.TemporaryDirectory() as temp_dir:
            site_path = Path(temp_dir) / "index.html"
            site_path.write_text("<html><body>Persona Site</body></html>", encoding="utf-8")
            runner.job = {
                "job_id": "job_test",
                "status": "completed",
                "stage": "completed",
                "message": "ok",
                "site_path": str(site_path),
                "site_url": "/generated/job_test",
            }

            httpd = module.create_server("127.0.0.1", 0, repo_root, runner, opener, repo_root)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

            try:
                html = urllib.request.urlopen(f"{base_url}/generated/job_test").read().decode("utf-8")
                self.assertIn("Persona Site", html)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_index_template_keeps_success_on_first_page(self):
        repo_root = Path(__file__).resolve().parents[1]
        template_path = (
            repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "templates"
            / "index.html"
        )
        html = template_path.read_text(encoding="utf-8")

        self.assertIn("打开网页预览", html)
        self.assertIn("自然语言修改 / 重写", html)
        self.assertIn("/api/edit", html)
        self.assertNotIn("即将跳转到网页预览", html)
        self.assertNotIn("pendingRedirect = setTimeout", html)


if __name__ == "__main__":
    unittest.main()
