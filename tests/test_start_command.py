from pathlib import Path
import unittest


class StartCommandTest(unittest.TestCase):
    def test_start_command_exists_and_bootstraps_repo_scripts(self):
        repo_root = Path(__file__).resolve().parents[1]
        start_script = repo_root / "start.command"

        self.assertTrue(start_script.exists())
        content = start_script.read_text(encoding="utf-8")
        self.assertIn("./scripts/setup.sh", content)
        self.assertIn("PERSONA_VAULT_OPEN_BROWSER=1 ./scripts/run.sh", content)


if __name__ == "__main__":
    unittest.main()
