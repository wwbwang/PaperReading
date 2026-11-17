"""Build from current sources without taking other delivered years offline."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_library as build
from scripts import build_iclr_web as iclr


class LibraryBuildTests(unittest.TestCase):
    def test_prepare_only_preserves_existing_export_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / "web"
            (web / "src").mkdir(parents=True)
            preferences = {"selected": "markdown", "destinations": ["local"]}
            (web / "src/data.json").write_text(json.dumps({"exportPreferences": preferences}))
            with patch.object(iclr, "ROOT", root), patch.object(iclr, "WEB", web), \
                    patch.object(iclr, "snapshot", return_value={}), \
                    patch.object(iclr.sys, "argv", ["build_iclr_web.py", "--prepare-only", "--year", "2027"]):
                iclr.main()
            self.assertEqual(json.loads((web / "src/data.json").read_text())["exportPreferences"], preferences)

    def exercise_build(self, fail=False, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / "web"
            (root / ".runtime").mkdir()
            (web / "src/content").mkdir(parents=True)
            (web / "src/data.json").write_text('{"original":true}')
            source = root / "iclr2027"
            source.mkdir()
            (source / "papers.jsonl").write_text("current source")
            manifest = {"output_sha256": {"papers.jsonl": hashlib.sha256(b"current source").hexdigest()}}
            (source / "manifest.json").write_text(json.dumps(manifest))
            if corrupt:
                (source / "papers.jsonl").write_text("damaged source")
            old = web / "dist/iclr/2027/index.html"
            other = web / "dist/cvpr/2025/index.html"
            for file in (old, other):
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("old site")
            revision = "a" * 64

            def snapshot(year, assets):
                self.assertEqual(year, 2027)
                assets.mkdir()
                (assets / "00.json").write_text('{"current":"details"}')
                return {"iclr": {"revision": revision}, "fresh": True}

            def compile_site(command, **kwargs):
                # The old site must stay served throughout compilation.
                self.assertEqual(other.read_text(), "old site")
                self.assertEqual(old.read_text(), "old site")
                self.assertEqual((web / "src/data.json").read_text(), '{"original":true}')
                project = Path(command[command.index("--project-dir") + 1])
                self.assertTrue(json.loads((project / "src/data.json").read_text())["fresh"])
                if fail:
                    raise subprocess.CalledProcessError(1, command)
                (project / "dist").mkdir()
                (project / "dist/index.html").write_text("current site")

            with patch.object(build, "ROOT", root), patch.object(build, "WEB", web), \
                    patch.object(build, "__file__", str(root / "scripts/build_library.py")), \
                    patch.object(build, "iclr_snapshot", side_effect=snapshot) as read_snapshot, \
                    patch.object(build.subprocess, "run", side_effect=compile_site) as compiler:
                if fail or corrupt:
                    with self.assertRaises(ValueError if corrupt else subprocess.CalledProcessError):
                        build.build_one("iclr", 2027)
                else:
                    build.build_one("iclr", 2027)
                self.assertEqual(read_snapshot.call_count, 0 if corrupt else 1)
                self.assertEqual(compiler.call_count, 0 if corrupt else 1)
            self.assertEqual(old.read_text(), "old site" if fail or corrupt else "current site")
            self.assertEqual(other.read_text(), "old site")
            self.assertEqual((web / "src/data.json").read_text(), '{"original":true}')

    def test_build_reads_fresh_source_without_reusing_deployed_snapshot(self):
        self.exercise_build()

    def test_compiler_failure_preserves_all_delivered_pages_and_source(self):
        self.exercise_build(fail=True)

    def test_modified_source_is_rejected_before_compilation(self):
        self.exercise_build(corrupt=True)


if __name__ == "__main__":
    unittest.main()
