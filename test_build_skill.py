import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

from scripts.build_skill import SKILL, build_skill

ROOT = Path(__file__).resolve().parent


class SkillBuildTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(
            prefix="epacket skill ", dir=os.environ.get("EPACKET_TEST_TMPDIR")
        )
        self.addCleanup(directory.cleanup)
        self.scratch = Path(directory.name)
        self.output = self.scratch / "portable skill.zip"

    def test_archive_contents_and_installed_script(self):
        subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "scripts" / "build_skill.py"), str(self.output)],
            cwd=self.scratch,
            check=True,
            timeout=10,
        )
        files = {
            "SKILL.md": ROOT / "skills" / SKILL / "SKILL.md",
            "scripts/preflight.py": ROOT / "preflight.py",
            "assets/batch.json": ROOT / "examples" / "batch.json",
            "LICENSE": ROOT / "LICENSE",
        }
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertCountEqual(archive.namelist(), [f"{SKILL}/{name}" for name in files])
            for name, source in files.items():
                self.assertEqual(archive.read(f"{SKILL}/{name}"), source.read_bytes())
            manifest_lines = archive.read(f"{SKILL}/SKILL.md").decode("utf-8").splitlines()
            self.assertIn(f"name: {SKILL}", manifest_lines)
            for host in (".agents", ".claude"):
                archive.extractall(self.scratch / host / "skills")

        invalid = self.scratch / "invalid batch & sample.json"
        invalid.write_text('{"parcels":[]}', encoding="utf-8")
        malformed = self.scratch / "malformed batch.json"
        malformed.write_text("{", encoding="utf-8")
        (self.scratch / "json.py").write_text('raise RuntimeError("shadowed stdlib")', encoding="utf-8")
        runner_env = {**os.environ, "PYTHONPATH": str(self.scratch)}
        for host in (".agents", ".claude"):
            install = self.scratch / host / "skills" / SKILL
            runner = [sys.executable, "-I", "-B", str(install / "scripts" / "preflight.py")]
            with self.subTest(host=host):
                sample = subprocess.run(
                    runner + [str(install / "assets" / "batch.json")],
                    cwd=self.scratch, env=runner_env, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(sample.returncode, 0, sample.stderr)
                report = json.loads(sample.stdout)
                self.assertEqual(report["status"], "warn")
                self.assertEqual(report["issues"][0]["code"], "CCC_MISSING")
                bad = subprocess.run(
                    runner + [str(invalid)], cwd=self.scratch, env=runner_env,
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(bad.returncode, 1, bad.stderr)
                self.assertEqual(json.loads(bad.stdout)["status"], "fail")
                broken = subprocess.run(
                    runner + [str(malformed)], cwd=self.scratch, env=runner_env,
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(broken.returncode, 2)
                self.assertEqual(broken.stdout, "")
                self.assertEqual(
                    broken.stderr.strip(),
                    "Input could not be processed. Provide one readable UTF-8 JSON file up to 1 MiB.",
                )

    def test_preserves_an_existing_output(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            build_skill(self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_removes_new_partial_output_on_write_failure(self):
        open_file = Path.open

        @contextmanager
        def failing_file():
            with open_file(self.output, "xb") as file:
                file.write(b"partial")
                writer = Mock()
                writer.write.side_effect = OSError("synthetic disk failure")
                yield writer

        def open_with_failure(path, mode, *args, **kwargs):
            if path == self.output and mode == "xb":
                return failing_file()
            return open_file(path, mode, *args, **kwargs)

        with patch.object(Path, "open", open_with_failure):
            with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                build_skill(self.output)
        self.assertFalse(self.output.exists())
