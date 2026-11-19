#!/usr/bin/env python3
"""Behaviour tests for cli-anything-index. No third-party dependencies."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cli_anything_index as idx  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "sample-root"
CLEAN = ROOT / "tests" / "fixtures" / "clean-root"
BIN = ROOT / "bin" / "cli-anything-index"


def run(*args):
    return subprocess.run([sys.executable, str(BIN), *args],
                          capture_output=True, text=True, timeout=60)


class IndexBuildTests(unittest.TestCase):
    def setUp(self):
        self.index = idx.build_index(SAMPLE)
        self.by_name = {e["software"]: e for e in self.index["entries"]}

    def test_discovers_all_harness_dirs(self):
        self.assertEqual(self.index["totals"]["harnesses"], 3)
        self.assertEqual(sorted(self.by_name), ["3MF", "blender", "broken"])

    def test_click_commands_and_flags(self):
        blender = self.by_name["blender"]
        self.assertEqual(blender["framework"], "click")
        self.assertIn("render", blender["commands"])
        self.assertIn("scene-add", blender["commands"])
        self.assertTrue(blender["json_flag"])
        self.assertIn("--json", blender["flags"])

    def test_argparse_command_discovery(self):
        threemf = self.by_name["3MF"]
        self.assertEqual(threemf["framework"], "argparse")
        self.assertEqual(threemf["commands"], ["inspect", "repair"])
        self.assertTrue(threemf["json_flag"])

    def test_frontmatter_parsed(self):
        self.assertEqual(self.by_name["blender"]["skill"]["name"], "cli-anything-blender")
        self.assertIn("Blender", self.by_name["blender"]["skill"]["description"])

    def test_documented_commands_extracted(self):
        docs = self.by_name["blender"]["documented_commands"]
        self.assertEqual(docs, ["export", "render", "scene"])
        self.assertEqual(self.by_name["3MF"]["documented_commands"], ["inspect", "repair"])

    def test_missing_skill_and_cli_recorded_as_none(self):
        broken = self.by_name["broken"]
        self.assertIsNone(broken["skill_md"])
        self.assertIsNone(broken["cli_source"])

    def test_totals_are_consistent(self):
        totals = self.index["totals"]
        self.assertEqual(totals["with_skill"], 2)
        self.assertEqual(totals["with_cli_source"], 2)
        self.assertEqual(totals["with_json_flag"], 2)


class CheckTests(unittest.TestCase):
    def test_sample_root_reports_errors(self):
        findings = idx.check_index(idx.build_index(SAMPLE))
        rules = {(f["rule"], f["software"]) for f in findings}
        self.assertIn(("no-skill", "broken"), rules)
        self.assertIn(("no-cli-source", "broken"), rules)
        self.assertIn(("documented-not-in-parser", "blender"), rules)
        self.assertTrue(any(f["level"] == "error" for f in findings))

    def test_clean_root_has_no_errors(self):
        findings = idx.check_index(idx.build_index(CLEAN))
        self.assertEqual([f for f in findings if f["level"] == "error"], [])

    def test_check_exit_code_1_on_errors(self):
        result = run("check", "--root", str(SAMPLE), "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreater(payload["summary"]["error"], 0)

    def test_check_exit_code_0_when_clean(self):
        result = run("check", "--root", str(CLEAN), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_json_is_parseable(self):
        result = run("check", "--root", str(SAMPLE), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], idx.SCHEMA_VERSION)
        self.assertIn("findings", payload)


class CliContractTests(unittest.TestCase):
    def test_index_json_parseable_and_sorted(self):
        result = run("index", "--root", str(SAMPLE), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["totals"]["harnesses"], 3)
        names = [e["software"] for e in payload["entries"]]
        self.assertEqual(names, sorted(names))

    def test_query_filters_by_software(self):
        result = run("query", "--root", str(SAMPLE), "--software", "blend", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        matches = json.loads(result.stdout)["matches"]
        self.assertEqual([m["software"] for m in matches], ["blender"])

    def test_query_no_match_exits_1(self):
        result = run("query", "--root", str(SAMPLE), "--software", "nope", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["matches"], [])

    def test_json_only_filter(self):
        result = run("query", "--root", str(SAMPLE), "--json-only", "--json")
        matches = json.loads(result.stdout)["matches"]
        self.assertTrue(matches)
        self.assertTrue(all(m["json_flag"] for m in matches))

    def test_missing_root_exits_2(self):
        result = run("index", "--root", str(ROOT / "does-not-exist"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)

    def test_non_checkout_dir_exits_2(self):
        result = run("index", "--root", str(ROOT))
        self.assertEqual(result.returncode, 2)

    def test_out_file_matches_stdout(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            out = Path(fh.name)
        try:
            result = run("index", "--root", str(SAMPLE), "--json", "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(out.read_text()), json.loads(result.stdout))
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)