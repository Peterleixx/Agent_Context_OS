import subprocess
import sys
import tempfile
import textwrap
import json
from pathlib import Path
import unittest
from urllib.parse import quote


class PersonaVaultStaticSiteTest(unittest.TestCase):
    def _create_demo_vault(self) -> Path:
        vault_dir = Path(tempfile.mkdtemp(prefix="persona-vault-demo-"))
        (vault_dir / "00 - Profile").mkdir(parents=True)
        (vault_dir / "01 - Capabilities").mkdir(parents=True)
        (vault_dir / "02 - Projects").mkdir(parents=True)

        (vault_dir / "Home.md").write_text("# Home\n", encoding="utf-8")
        (vault_dir / "00 - Profile" / "Current Focus.md").write_text(
            "# Current Focus\n\n## 当前关注主题\n\n- PersonaVault 自动生成与网页导出\n",
            encoding="utf-8",
        )
        (vault_dir / "00 - Profile" / "Values And Preferences.md").write_text(
            "# Values And Preferences\n\n## 稳定偏好与决策风格\n\n- 证据优先\n",
            encoding="utf-8",
        )
        (vault_dir / "00 - Profile" / "Work History.md").write_text(
            textwrap.dedent(
                """
                # Work History

                ## 工作经历

                | 时间 | 角色 | 说明 |
                | --- | --- | --- |
                | 2024-now | Builder | 构建 PersonaVault 工作流 |
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "00 - Profile" / "主要人物画像.md").write_text(
            textwrap.dedent(
                """
                # 主要人物画像

                ## 当前角色定位

                AI 工作流产品与工程设计者。

                ## 当前关注主题

                - PersonaVault 自动生成
                - 本地静态站导出

                ## 稳定偏好与决策风格

                - 证据优先
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

                | 能力 | 当前判断 | 置信度 |
                | --- | --- | --- |
                | 能力-Agent工具化与开发者体验设计 | 已形成稳定能力 | 高 |
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "01 - Capabilities" / "能力-Agent工具化与开发者体验设计.md").write_text(
            textwrap.dedent(
                """
                # 能力-Agent工具化与开发者体验设计

                ## 一句话定义

                能把复杂的 Agent 工作流压缩成可直接操作的本地产品。

                ## 典型表现

                - 设计从输入到输出的完整交互路径
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

                面向 PersonaVault 的本地工作流与展示项目。

                ## 可见内容

                - 交互式生成器
                - 静态站导出

                ## 该项目体现的能力

                - 能力-Agent工具化与开发者体验设计
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return vault_dir

    def test_renderer_creates_html_from_persona_vault(self):
        repo_root = Path(__file__).resolve().parents[1]
        persona_vault_path = self._create_demo_vault()
        output_dir = Path(tempfile.mkdtemp(prefix="persona-site-"))
        script_path = (
            repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "scripts"
            / "render_persona_site.py"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--persona-vault-path",
                str(persona_vault_path),
                "--output-dir",
                str(output_dir),
                "--site-title",
                "PersonaVault Demo",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        html_path = output_dir / "index.html"
        self.assertTrue(html_path.exists())
        html = html_path.read_text(encoding="utf-8")
        self.assertIn("PersonaVault Demo", html)
        self.assertIn("Current Focus", html)
        self.assertIn("能力-Agent工具化与开发者体验设计", html)
        self.assertIn("项目-Context OS Demo", html)
        self.assertIn("能力轮廓图", html)
        self.assertIn("能力置信度", html)
        self.assertIn("项目 x 能力覆盖", html)
        self.assertIn("<svg", html)
        self.assertIn("在 Obsidian 中打开", html)
        expected_link = (
            f'href="obsidian://open?vault={quote(persona_vault_path.name)}&amp;file=Home.md"'
        )
        self.assertIn(expected_link, html)

    def test_renderer_falls_back_to_primary_profile_file(self):
        repo_root = Path(__file__).resolve().parents[1]
        output_dir = Path(tempfile.mkdtemp(prefix="persona-site-fallback-"))
        vault_dir = Path(tempfile.mkdtemp(prefix="persona-vault-"))
        script_path = (
            repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "scripts"
            / "render_persona_site.py"
        )

        (vault_dir / "00 - Profile").mkdir(parents=True)
        (vault_dir / "01 - Capabilities").mkdir(parents=True)
        (vault_dir / "02 - Projects").mkdir(parents=True)
        (vault_dir / "Home.md").write_text("# Home\n", encoding="utf-8")
        (vault_dir / "00 - Profile" / "主要人物画像.md").write_text(
            textwrap.dedent(
                """
                # 主要人物画像

                ## 当前角色定位

                - AI 产品与工程工作流设计者

                ## 当前关注主题

                - PersonaVault 交互式生成器

                ## 稳定偏好与决策风格

                - 证据优先
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

                | 能力 | 当前判断 | 置信度 |
                | --- | --- | --- |
                | 能力-交互式工具设计 | 已形成稳定能力 | 高 |
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "01 - Capabilities" / "能力-交互式工具设计.md").write_text(
            textwrap.dedent(
                """
                # 能力-交互式工具设计

                ## 一句话定义

                能把复杂工作流压缩成可以直接操作的本地界面。

                ## 典型表现

                - 设计面向真实输入的操作界面
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (vault_dir / "02 - Projects" / "项目-生成器.md").write_text(
            textwrap.dedent(
                """
                # 项目-生成器

                ## 项目定义

                面向 PersonaVault 的本地交互式生成器。

                ## 可见内容

                - 交互表单

                ## 该项目体现的能力

                - 能力-交互式工具设计
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--persona-vault-path",
                str(vault_dir),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        html = (output_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("主要人物画像", html)
        self.assertIn("PersonaVault 交互式生成器", html)
        self.assertIn("能力-交互式工具设计", html)

    def test_renderer_prefers_render_profile_json(self):
        repo_root = Path(__file__).resolve().parents[1]
        output_dir = Path(tempfile.mkdtemp(prefix="persona-site-json-"))
        vault_dir = Path(tempfile.mkdtemp(prefix="persona-vault-json-"))
        script_path = (
            repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "scripts"
            / "render_persona_site.py"
        )

        (vault_dir / "00 - Profile").mkdir(parents=True)
        (vault_dir / "01 - Capabilities").mkdir(parents=True)
        (vault_dir / "02 - Projects").mkdir(parents=True)
        (vault_dir / ".persona-system").mkdir(parents=True)
        (vault_dir / "Home.md").write_text("# Home\n", encoding="utf-8")
        (vault_dir / "00 - Profile" / "主要人物画像.md").write_text("# 主要人物画像\n", encoding="utf-8")
        (vault_dir / ".persona-system" / "render-profile.json").write_text(
            json.dumps(
                {
                    "generation_context": {
                        "target_scene": "job_jd",
                        "job_jd_text": "AI Agent 岗位",
                        "focus_presets": ["能力亮点"],
                        "focus_custom": "强调复杂工作流",
                        "redaction_profile": "conservative",
                        "redaction_custom_rules": "不要写真实公司名",
                    },
                    "profile_facets": [
                        {
                            "icon": "briefcase",
                            "title": "岗位叙事重心",
                            "summary": "围绕 Agent 工作流与交付抽象展开。",
                        }
                    ],
                    "keyword_chips": ["Agent 工作流", "证据驱动"],
                    "focus_items": ["Agent 工作流抽象"],
                    "work_style_items": ["先定约束，再落计划"],
                    "value_cards": [
                        {"title": "证据优先", "description": "先验证，再表述。"}
                    ],
                    "capability_metrics": [
                        {
                            "title": "能力-Agent交付封装",
                            "short_title": "Agent交付封装",
                            "icon": "wrench",
                            "judgment": "已形成稳定能力",
                            "confidence": "高",
                            "score": 90,
                        }
                    ],
                    "project_capability_matrix": [
                        {
                            "title": "项目-Context OS Demo",
                            "capabilities": ["能力-Agent交付封装"],
                        }
                    ],
                    "public_summary": [
                        "擅长把复杂工作流转成可交付资产。"
                    ],
                    "external_source_cards": [
                        {
                            "icon": "book",
                            "title": "GitHub 公开资料",
                            "summary": "OpenAI 公开主页与代表仓库摘要。",
                            "meta": ["owner: openai", "languages: Python"],
                            "url": "https://github.com/openai",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--persona-vault-path",
                str(vault_dir),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        html = (output_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("关键人物画像", html)
        self.assertIn("岗位叙事重心", html)
        self.assertIn("Agent 工作流", html)
        self.assertIn("Agent交付封装", html)
        self.assertIn("GitHub 公开资料", html)
        self.assertIn("OpenAI 公开主页与代表仓库摘要", html)
        self.assertNotIn("No capability radar available.", html)

    def test_renderer_accepts_value_cards_with_summary_only(self):
        repo_root = Path(__file__).resolve().parents[1]
        output_dir = Path(tempfile.mkdtemp(prefix="persona-site-summary-"))
        vault_dir = Path(tempfile.mkdtemp(prefix="persona-vault-summary-"))
        script_path = (
            repo_root
            / "skills"
            / "persona-vault-generator-app"
            / "scripts"
            / "render_persona_site.py"
        )

        (vault_dir / "00 - Profile").mkdir(parents=True)
        (vault_dir / "01 - Capabilities").mkdir(parents=True)
        (vault_dir / "02 - Projects").mkdir(parents=True)
        (vault_dir / ".persona-system").mkdir(parents=True)
        (vault_dir / "Home.md").write_text("# Home\n", encoding="utf-8")
        (vault_dir / "00 - Profile" / "主要人物画像.md").write_text("# 主要人物画像\n", encoding="utf-8")
        (vault_dir / ".persona-system" / "render-profile.json").write_text(
            json.dumps(
                {
                    "generation_context": {"target_scene": "job_jd"},
                    "profile_facets": [],
                    "keyword_chips": [],
                    "focus_items": [],
                    "work_style_items": [],
                    "value_cards": [
                        {"title": "证据优先", "summary": "先验证，再表述。"}
                    ],
                    "capability_metrics": [
                        {
                            "title": "能力-Agent交付封装",
                            "short_title": "Agent交付封装",
                            "icon": "wrench",
                            "judgment": "已形成稳定能力",
                            "confidence": "高",
                            "score": 90,
                        }
                    ],
                    "project_capability_matrix": [
                        {
                            "project": "项目-Context OS Demo",
                            "capabilities": ["能力-Agent交付封装"],
                        }
                    ],
                    "public_summary": "擅长把复杂工作流转成可交付资产。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--persona-vault-path",
                str(vault_dir),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        html = (output_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("证据优先", html)
        self.assertIn("先验证，再表述。", html)
        self.assertIn("Context OS Demo", html)


if __name__ == "__main__":
    unittest.main()
