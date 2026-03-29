import importlib.util
import json
import socket
import tempfile
import threading
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
import unittest
from unittest import mock


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
        self.last_deploy = None
        self.last_retry = None
        self.job = {
            "job_id": "job_test",
            "status": "running",
            "stage": "running_codex",
            "message": "正在调用本机 Codex 执行 PersonaVault 生成任务",
            "retry_available": False,
            "retry_label": None,
        }

    def start_job(self, payload):
        self.last_payload = payload
        return self.job["job_id"]

    def start_edit_job(self, job_id, instruction):
        self.last_edit = {"job_id": job_id, "instruction": instruction}
        return "job_edit"

    def start_deploy_job(self, job_id):
        self.last_deploy = {"job_id": job_id}
        return "job_deploy"

    def retry_job(self, job_id):
        self.last_retry = {"job_id": job_id}
        return "job_retry"

    def get_job(self, job_id):
        if job_id == "job_retry":
            return {
                "job_id": "job_retry",
                "status": "running",
                "stage": "writing_vault",
                "message": "正在从断点继续。",
                "retry_available": False,
                "retry_label": None,
            }
        if job_id == "job_deploy":
            return {
                "job_id": "job_deploy",
                "status": "running",
                "stage": "deploy_preparing_profile",
                "message": "正在准备 OpenClaw 部署画像。",
                "retry_available": False,
                "retry_label": None,
            }
        if job_id == "job_edit":
            return {
                "job_id": "job_edit",
                "status": "running",
                "stage": "running_codex",
                "message": "正在应用自然语言修改。",
                "retry_available": False,
                "retry_label": None,
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

    def test_fetch_json_from_url_uses_timeout(self):
        module = load_generator_module()
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            captured["url"] = request.full_url
            return FakeResponse()

        data = module.fetch_json_from_url("https://api.github.com/users/openai", opener=fake_urlopen)

        self.assertEqual(data, {"ok": True})
        self.assertEqual(captured["url"], "https://api.github.com/users/openai")
        self.assertEqual(captured["timeout"], module.GITHUB_FETCH_TIMEOUT_SECONDS)

    def test_build_codex_timeout_message_mentions_rate_limit_reset(self):
        module = load_generator_module()

        message = module.build_codex_timeout_message(
            [
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "rate_limits": {
                                "primary": {
                                    "used_percent": 100.0,
                                    "resets_at": 1774769054,
                                }
                            },
                        },
                    }
                )
            ],
            timeout_seconds=30,
        )

        self.assertIn("Codex 调用超时", message)
        self.assertIn("2026-03-29 15:24:14", message)

    def test_run_job_marks_failed_when_codex_exec_times_out(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        runner._jobs["job_timeout"] = module.JobState("job_timeout")

        timeout_error = RuntimeError("Codex 调用超时，当前账户已触发限流。")

        with mock.patch.object(module, "run_codex_command", side_effect=timeout_error):
            runner._run_job(
                "job_timeout",
                {
                    "agents": ["codex"],
                    "path_mappings": [],
                    "links": [],
                    "output_dir": str(repo_root / "PersonaVault"),
                    "advanced_settings": {
                        "target_scene": "job_jd",
                        "job_jd_text": "",
                        "focus_presets": [],
                        "focus_custom": "",
                        "redaction_profile": "conservative",
                        "redaction_custom_rules": "",
                    },
                },
            )

        job = runner.get_job("job_timeout")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["stage"], "failed")
        self.assertIn("Codex 调用超时", job["message"])

    def test_retry_job_reuses_generation_payload_before_checkpoint(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        failed_job = module.JobState("job_failed")
        failed_job.status = "failed"
        failed_job.job_kind = "generate"
        failed_job.retry_mode = "rerun_generate"
        failed_job.retry_available = True
        failed_job.request_payload = {"agents": ["codex"], "path_mappings": [], "links": []}
        runner._jobs["job_failed"] = failed_job

        with mock.patch.object(runner, "start_job", return_value="job_retry") as mocked_start:
            retry_job_id = runner.retry_job("job_failed")

        self.assertEqual(retry_job_id, "job_retry")
        mocked_start.assert_called_once_with({"agents": ["codex"], "path_mappings": [], "links": []}, "job_failed")

    def test_retry_job_resumes_outputs_when_checkpoint_available(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        failed_job = module.JobState("job_failed")
        failed_job.status = "failed"
        failed_job.job_kind = "generate"
        failed_job.retry_mode = "resume_outputs"
        failed_job.retry_available = True
        failed_job.request_payload = {"agents": ["codex"], "path_mappings": [], "links": []}
        failed_job.vault_path = "/tmp/PersonaVault"
        failed_job.profile_path = "/tmp/PersonaVault/00 - Profile/主要人物画像.md"
        runner._jobs["job_failed"] = failed_job

        with mock.patch.object(runner, "start_resume_outputs_job", return_value="job_resume") as mocked_resume:
            retry_job_id = runner.retry_job("job_failed")

        self.assertEqual(retry_job_id, "job_resume")
        mocked_resume.assert_called_once_with(
            Path("/tmp/PersonaVault"),
            Path("/tmp/PersonaVault/00 - Profile/主要人物画像.md"),
            {"agents": ["codex"], "path_mappings": [], "links": []},
            "job_failed",
        )

    def test_run_resume_outputs_job_reuses_refresh_pipeline(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        runner._jobs["job_resume"] = module.JobState("job_resume")

        payload = {"agents": ["codex"], "path_mappings": [], "links": []}
        vault_path = Path("/tmp/PersonaVault")
        profile_path = Path("/tmp/PersonaVault/00 - Profile/主要人物画像.md")

        with mock.patch.object(runner, "_refresh_persona_outputs", return_value=True) as mocked_refresh:
            runner._run_resume_outputs_job("job_resume", vault_path, profile_path, payload)

        job = runner.get_job("job_resume")
        self.assertEqual(job["stage"], "writing_vault")
        self.assertEqual(job["message"], "正在从断点继续同步结构化画像与网页预览。")
        mocked_refresh.assert_called_once_with("job_resume", vault_path, profile_path, payload)

    def test_resolve_codex_runtime_config_uses_defaults_and_sanitizes_reasoning(self):
        module = load_generator_module()

        with mock.patch.dict(
            module.os.environ,
            {
                "PERSONA_VAULT_CODEX_MODEL": "custom-demo-model",
                "PERSONA_VAULT_CODEX_REASONING_EFFORT": "invalid",
            },
            clear=False,
        ):
            config = module.resolve_codex_runtime_config()

        self.assertEqual(config["model"], "custom-demo-model")
        self.assertEqual(config["reasoning_effort"], "low")

    def _create_demo_vault(self) -> Path:
        vault_dir = Path(tempfile.mkdtemp(prefix="persona-vault-deploy-"))
        (vault_dir / "00 - Profile").mkdir(parents=True)
        (vault_dir / "01 - Capabilities").mkdir(parents=True)
        (vault_dir / "02 - Projects").mkdir(parents=True)
        (vault_dir / ".persona-system").mkdir(parents=True)
        (vault_dir / "Home.md").write_text("# Home\n", encoding="utf-8")
        (vault_dir / "00 - Profile" / "主要人物画像.md").write_text(
            textwrap.dedent(
                """
                # 主要人物画像

                ## 当前角色定位

                AI Agent 工作流产品与工程设计者。

                ## 当前关注主题

                - PersonaVault 到 OpenClaw 的画像落地
                - 复杂工作流压缩与交付

                ## 稳定偏好与决策风格

                - 先校验约束，再推进执行
                - 偏好证据驱动与最小可行落地
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "01 - Capabilities" / "能力地图.md").write_text(
            textwrap.dedent(
                """
                # 能力地图

                ## 核心能力总览

                | 能力 | 当前判断 | 置信度 | 图标 | 关键词 |
                | --- | --- | --- | --- | --- |
                | 能力-Agent交付封装 | 已形成稳定能力 | 高 | wrench | Agent 工作流, 交付 |
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "02 - Projects" / "项目-Context OS Demo.md").write_text(
            textwrap.dedent(
                """
                # 项目-Context OS Demo

                ## 项目定义

                基于 PersonaVault 的本地工作流与 OpenClaw 分身部署演示。

                ## 可见内容

                - 一键部署 OpenClaw 分身

                ## 该项目体现的能力

                - 能力-Agent交付封装
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return vault_dir

    def test_parse_args_supports_open_browser_flag(self):
        module = load_generator_module()

        args = module.parse_args(["--open-browser", "--port", "9999"])

        self.assertTrue(args.open_browser)
        self.assertEqual(args.port, 9999)

    def test_build_codex_command_uses_local_codex_exec(self):
        module = load_generator_module()

        command = module.build_codex_command(Path("/tmp/last-message.txt"))

        self.assertEqual(command[:4], ["codex", "exec", "--model", "gpt-5.4-mini"])
        self.assertIn('-c', command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--json", command)
        self.assertIn("-", command)

    def test_build_codex_command_honors_env_override(self):
        module = load_generator_module()

        with mock.patch.dict(
            module.os.environ,
            {
                "PERSONA_VAULT_CODEX_MODEL": "gpt-5.4",
                "PERSONA_VAULT_CODEX_REASONING_EFFORT": "medium",
            },
            clear=False,
        ):
            command = module.build_codex_command(Path("/tmp/last-message.txt"))

        self.assertEqual(command[:4], ["codex", "exec", "--model", "gpt-5.4"])
        self.assertIn('model_reasoning_effort="medium"', command)

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
        self.assertIn(".persona-system/openclaw-agent.json", prompt)
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

    def test_enhance_persona_vault_writes_openclaw_agent_profile(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        vault_dir = self._create_demo_vault()

        render_profile = runner._enhance_persona_vault(
            vault_dir,
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [],
                "output_dir": str(vault_dir),
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "AI Agent 岗位",
                    "focus_presets": ["能力亮点"],
                    "focus_custom": "",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "",
                },
            },
        )

        self.assertTrue(render_profile)
        profile_path = vault_dir / ".persona-system" / "openclaw-agent.json"
        self.assertTrue(profile_path.exists())
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["agent_slug"].startswith("persona-vault-deploy"))
        self.assertIn("AI Agent 工作流产品与工程设计者", payload["soul_summary"])
        self.assertIn("Agent 工作流", payload["identity_card"])
        self.assertEqual(payload["source_snapshot"]["vault_path"], str(vault_dir))

    def test_resolve_unique_agent_id_appends_suffix_when_workspace_exists(self):
        module = load_generator_module()

        with tempfile.TemporaryDirectory(prefix="openclaw-home-") as temp_dir:
            home_dir = Path(temp_dir)
            (home_dir / ".openclaw" / "workspace-persona-vault-deploy").mkdir(parents=True)

            resolved = module.resolve_unique_agent_id("persona-vault-deploy", home_dir)

        self.assertEqual(resolved, "persona-vault-deploy-2")

    def test_build_openclaw_command_helpers_match_expected_cli(self):
        module = load_generator_module()

        self.assertEqual(module.build_openclaw_setup_command(), ["openclaw", "setup", "--non-interactive"])
        self.assertEqual(
            module.build_openclaw_add_agent_command("lobster-twin", Path("/tmp/workspace")),
            [
                "openclaw",
                "agents",
                "add",
                "lobster-twin",
                "--non-interactive",
                "--workspace",
                "/tmp/workspace",
            ],
        )
        self.assertEqual(module.build_openclaw_health_command(), ["openclaw", "health", "--json"])
        self.assertEqual(module.build_openclaw_gateway_start_command(), ["openclaw", "gateway", "start", "--json"])
        self.assertEqual(
            module.build_openclaw_gateway_restart_command(),
            ["openclaw", "gateway", "restart", "--json"],
        )

    def test_build_openclaw_agent_profile_normalizes_non_string_work_style_items(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        renderer = module.load_renderer_module(repo_root)
        vault_dir = self._create_demo_vault()

        payload = module.build_openclaw_agent_profile(
            vault_dir,
            {
                "capability_metrics": [],
                "keyword_chips": ["Agent 工作流"],
                "focus_items": ["PersonaVault 到 OpenClaw 的画像落地"],
                "work_style_items": [{"title": "先校验约束"}, 42, None],
                "public_summary": ["擅长把复杂工作流压缩成可交付资产。"],
            },
            renderer,
        )

        self.assertIn("先校验约束；42", payload["soul_summary"])
        self.assertNotIn("None", payload["soul_summary"])

    def test_run_deploy_job_uses_setup_then_add_agent_then_start_gateway(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        vault_dir = self._create_demo_vault()
        runner._enhance_persona_vault(
            vault_dir,
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [],
                "output_dir": str(vault_dir),
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "AI Agent 岗位",
                    "focus_presets": [],
                    "focus_custom": "",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "",
                },
            },
        )

        runner._jobs["job_deploy"] = module.JobState("job_deploy")
        commands = []

        def fake_checked(command, cwd):
            commands.append(command)
            return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")

        fake_home = Path(tempfile.mkdtemp(prefix="fake-openclaw-home-"))

        with (
            mock.patch.object(module.Path, "home", return_value=fake_home),
            mock.patch.object(module.shutil, "which", return_value="/usr/local/bin/openclaw"),
            mock.patch.object(runner, "_run_checked_command", side_effect=fake_checked),
            mock.patch.object(
                module.subprocess,
                "run",
                return_value=mock.Mock(returncode=1, stdout="", stderr="gateway down"),
            ),
        ):
            runner._run_deploy_job("job_deploy", vault_dir)

        job = runner.get_job("job_deploy")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(commands[0], ["openclaw", "setup", "--non-interactive"])
        self.assertEqual(commands[1][:3], ["openclaw", "agents", "add"])
        self.assertTrue(commands[1][3].startswith("persona-vault-deploy"))
        self.assertEqual(commands[1][4], "--non-interactive")
        self.assertEqual(commands[2], ["openclaw", "gateway", "start", "--json"])
        workspace = fake_home / ".openclaw" / f"workspace-{job['openclaw_agent_id']}"
        self.assertTrue((workspace / "SOUL.md").exists())
        self.assertTrue((workspace / "AGENTS.md").exists())
        self.assertTrue((workspace / "USER.md").exists())
        self.assertTrue((workspace / "IDENTITY.md").exists())
        self.assertTrue((workspace / "PERSONA_VAULT_SOURCE.md").exists())

    def test_run_deploy_job_fails_when_openclaw_missing(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = module.CodexPersonaJobRunner(repo_root, repo_root)
        vault_dir = self._create_demo_vault()
        runner._enhance_persona_vault(
            vault_dir,
            {
                "agents": ["codex"],
                "path_mappings": [],
                "links": [],
                "output_dir": str(vault_dir),
                "advanced_settings": {
                    "target_scene": "job_jd",
                    "job_jd_text": "",
                    "focus_presets": [],
                    "focus_custom": "",
                    "redaction_profile": "conservative",
                    "redaction_custom_rules": "",
                },
            },
        )
        runner._jobs["job_fail"] = module.JobState("job_fail")

        with mock.patch.object(module.shutil, "which", return_value=None):
            runner._run_deploy_job("job_fail", vault_dir)

        job = runner.get_job("job_fail")
        self.assertEqual(job["status"], "failed")
        self.assertIn("openclaw CLI", job["message"])

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

    def test_resolve_server_port_keeps_requested_port_when_available(self):
        module = load_generator_module()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            available_port = probe.getsockname()[1]

        resolved_port = module.resolve_server_port("127.0.0.1", available_port)

        self.assertEqual(resolved_port, available_port)

    def test_resolve_server_port_falls_forward_when_requested_port_is_busy(self):
        module = load_generator_module()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy_port = occupied.getsockname()[1]

            resolved_port = module.resolve_server_port("127.0.0.1", busy_port)

        self.assertGreater(resolved_port, busy_port)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", resolved_port))

    def test_http_server_exposes_form_and_job_endpoints(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = FakeRunner()
        opener = FakeOpener()
        httpd = module.create_server("127.0.0.1", 0, repo_root, runner, opener, opener, repo_root)
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
            self.assertIn("retry-job", html)

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

            deploy_request = urllib.request.Request(
                f"{base_url}/api/deploy-openclaw",
                data=json.dumps({"job_id": "job_test"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            deploy_response = json.loads(
                urllib.request.urlopen(deploy_request).read().decode("utf-8")
            )
            self.assertEqual(deploy_response["job_id"], "job_deploy")
            self.assertEqual(runner.last_deploy["job_id"], "job_test")

            retry_request = urllib.request.Request(
                f"{base_url}/api/retry",
                data=json.dumps({"job_id": "job_test"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            retry_response = json.loads(
                urllib.request.urlopen(retry_request).read().decode("utf-8")
            )
            self.assertEqual(retry_response["job_id"], "job_retry")
            self.assertEqual(runner.last_retry["job_id"], "job_test")

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

            httpd = module.create_server("127.0.0.1", 0, repo_root, runner, opener, opener, repo_root)
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

    def test_index_endpoint_renders_effective_codex_runtime_config(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]
        runner = FakeRunner()
        opener = FakeOpener()

        with mock.patch.dict(
            module.os.environ,
            {
                "PERSONA_VAULT_CODEX_MODEL": "demo-model-fast",
                "PERSONA_VAULT_CODEX_REASONING_EFFORT": "medium",
            },
            clear=False,
        ):
            httpd = module.create_server("127.0.0.1", 0, repo_root, runner, opener, opener, repo_root)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

            try:
                html = urllib.request.urlopen(base_url).read().decode("utf-8")
                self.assertIn("demo-model-fast", html)
                self.assertIn("reasoning: medium", html)
                self.assertNotIn("gpt-5.4</span>", html)
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
        self.assertIn("部署分身 Agent", html)
        self.assertIn("/api/edit", html)
        self.assertIn("/api/deploy-openclaw", html)
        self.assertNotIn("即将跳转到网页预览", html)
        self.assertNotIn("pendingRedirect = setTimeout", html)

    def test_enhance_persona_vault_preserves_external_source_cards_without_new_github_data(self):
        module = load_generator_module()
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp_dir:
            vault_dir = Path(temp_dir) / "PersonaVault"
            (vault_dir / "00 - Profile").mkdir(parents=True)
            (vault_dir / "01 - Capabilities").mkdir(parents=True)
            (vault_dir / ".persona-system").mkdir(parents=True)
            (vault_dir / "00 - Profile" / "主要人物画像.md").write_text(
                textwrap.dedent(
                    """
                    # 主要人物画像

                    ## 当前角色定位

                    AI Agent 工作流构建者。
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (vault_dir / "01 - Capabilities" / "能力地图.md").write_text(
                textwrap.dedent(
                    """
                    # 能力地图

                    ## 核心能力总览

                    | 能力 | 当前判断 | 置信度 | 图标 | 关键词 |
                    | --- | --- | --- | --- | --- |
                    | 能力-Agent交付封装 | 已形成稳定能力 | 高 | wrench | Agent |
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (vault_dir / ".persona-system" / "render-profile.json").write_text(
                json.dumps(
                    {
                        "generation_context": {"target_scene": "job_jd"},
                        "external_source_cards": [
                            {
                                "icon": "book",
                                "title": "GitHub 公开资料",
                                "summary": "OpenAI 公开主页与代表仓库摘要。",
                                "meta": ["owner: openai"],
                                "url": "https://github.com/openai",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            runner = module.CodexPersonaJobRunner(repo_root, repo_root)
            render_profile = runner._enhance_persona_vault(
                vault_dir,
                {"agents": ["codex"], "links": [], "path_mappings": []},
            )

            self.assertEqual(len(render_profile["external_source_cards"]), 1)
            self.assertEqual(render_profile["external_source_cards"][0]["title"], "GitHub 公开资料")


if __name__ == "__main__":
    unittest.main()
