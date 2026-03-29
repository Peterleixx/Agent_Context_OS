# Persona Vault Static Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable skill that exports a local `PersonaVault` into a minimal single-file `index.html` profile page using Tailwind CSS CDN.

**Architecture:** The skill will combine a deterministic Python renderer with a static HTML template. `SKILL.md` will define when to use it and the input/output contract, while the renderer will read selected Markdown cards from `PersonaVault`, normalize them into structured sections, and inject them into the template.

**Tech Stack:** Markdown files, Python 3 standard library, `unittest`, Tailwind CSS CDN

---

### Task 1: Add the failing regression test

**Files:**
- Create: `tests/test_persona_vault_static_site.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


class PersonaVaultStaticSiteTest(unittest.TestCase):
    def test_renderer_creates_html_from_persona_vault(self):
        repo_root = Path(__file__).resolve().parents[1]
        persona_vault_path = repo_root.parent / "PersonaVault"
        output_dir = Path(tempfile.mkdtemp(prefix="persona-site-"))
        script_path = (
            repo_root
            / "skills"
            / "persona-vault-static-site"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_persona_vault_static_site -v`
Expected: FAIL because `skills/persona-vault-static-site/scripts/render_persona_site.py` does not exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/test_persona_vault_static_site.py
git commit -m "test: add persona vault static site regression"
```

### Task 2: Implement the skill and renderer

**Files:**
- Create: `skills/persona-vault-static-site/SKILL.md`
- Create: `skills/persona-vault-static-site/scripts/render_persona_site.py`
- Create: `skills/persona-vault-static-site/templates/index.template.html`
- Modify: `README.md`

- [ ] **Step 1: Write minimal implementation**

```text
Create the skill contract in SKILL.md.
Implement a standard-library renderer script that:
- parses arguments
- reads approved PersonaVault markdown files
- extracts profile, capability, and project sections
- renders HTML via the template
- writes output_dir/index.html
Update README.md to list the new skill.
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m unittest tests.test_persona_vault_static_site -v`
Expected: PASS

- [ ] **Step 3: Manually render the sample site**

Run: `python3 skills/persona-vault-static-site/scripts/render_persona_site.py --persona-vault-path ../PersonaVault --output-dir /tmp/persona-site-check --site-title "PersonaVault Demo"`
Expected: `/tmp/persona-site-check/index.html` exists and contains profile, capability, and project sections.

- [ ] **Step 4: Commit**

```bash
git add README.md skills/persona-vault-static-site
git commit -m "feat: add persona vault static site skill"
```

### Task 3: Strengthen the regression assertions

**Files:**
- Modify: `tests/test_persona_vault_static_site.py`

- [ ] **Step 1: Extend the test expectations**

```python
        html = html_path.read_text(encoding="utf-8")
        self.assertIn("PersonaVault Demo", html)
        self.assertIn("Current Focus", html)
        self.assertIn("能力-Agent工具化与开发者体验设计", html)
        self.assertIn("项目-Context OS Demo", html)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m unittest tests.test_persona_vault_static_site -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_persona_vault_static_site.py
git commit -m "test: verify persona site content"
```

