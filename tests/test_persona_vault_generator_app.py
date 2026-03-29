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
        self.job = {
            "job_id": "job_test",
            "status": "running",
            "stage": "running_codex",
            "message": "正在调用本机 Codex 执行 PersonaVault 生成任务",
        }

    def start_job(self, payload):
        self.last_payload = payload
        return self.job["job_id"]

    def get_job(self, job_id):
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
        renderer_path = module.resolve_static_site_renderer_path(repo_root)

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
            repo_root / "skills" / "persona-vault-static-site" / "scripts" / "render_persona_site.py",
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

            payload = {
                "agents": ["codex"],
                "path_mappings": [{"type": "workspace_dir", "path": "/tmp/workspace"}],
                "links": [{"kind": "github", "url": "https://github.com/example"}],
                "output_dir": "",
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

            job = json.loads(
                urllib.request.urlopen(f"{base_url}/api/jobs/job_test").read().decode("utf-8")
            )
            self.assertEqual(job["stage"], "running_codex")

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


if __name__ == "__main__":
    unittest.main()
