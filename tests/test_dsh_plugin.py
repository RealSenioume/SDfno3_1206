"""Static checks for the DSH bundle skeleton in ``plugin/lolping-intents``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "lolping-intents"


class TestPluginPackage(unittest.TestCase):
    def test_manifest_shape(self) -> None:
        manifest = json.loads((PLUGIN / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["type"], "module")
        self.assertEqual(manifest["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertIn(".", manifest["exports"])
        self.assertIn("./locale/*.json", manifest["exports"])
        self.assertIn("./icon", manifest["exports"])
        for entry in ("index.js", "cordis.patch.yml", "icon.svg"):
            self.assertIn(entry, manifest["files"])

    def test_patch_inserts_a_row(self) -> None:
        patch = (PLUGIN / "cordis.patch.yml").read_text(encoding="utf-8")
        self.assertIn("- insert:", patch)
        self.assertIn("id: lolping-intents", patch)
        self.assertIn("name: lolping-intents", patch)

    def test_locales_carry_metadata(self) -> None:
        for name in ("en", "zh"):
            meta = json.loads((PLUGIN / "locale" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["meta"]["title"])
            self.assertTrue(meta["meta"]["description"])

    def test_icon_and_readme_exist(self) -> None:
        self.assertTrue((PLUGIN / "icon.svg").read_text(encoding="utf-8").startswith("<svg"))
        self.assertIn("install", (PLUGIN / "README.md").read_text(encoding="utf-8").lower())

    def test_javascript_syntax(self) -> None:
        node = os.environ.get("DSH_NODE") or shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH")
        for script in (PLUGIN / "index.js", PLUGIN / "lib" / "intents.js"):
            result = subprocess.run(
                [node, "--check", str(script)], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
