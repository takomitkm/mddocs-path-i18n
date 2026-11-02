"""End-to-end tests against a small fixture vault.

Run with:  python -X utf8 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pathmap import (  # noqa: E402
    Entry,
    MapFile,
    Options,
    PathmapError,
    Rules,
    run_apply,
    run_scan,
    run_verify,
    translate_path,
)
from pathmap.cli import main  # noqa: E402
from pathmap.util import SENTINEL, read_text  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

EXPECTED_TREE = {
    "素材/logo.svg",
    "素材/示意图.png",
    "指南/进阶/输入输出.md",
    "指南/示例代码.md",
    "指南/入门.md",
    "参考/术语表.md",
    "参考/重复甲/同名甲.md",
    "参考/重复乙/同名乙.md",
    "misc/notes.md",
}


class Workspace:
    """A throwaway copy of the fixture vault plus its map and rules."""

    def __init__(self, variant: str = "vault") -> None:
        self.tmp = tempfile.mkdtemp(prefix="pathmap-")
        self.vault = os.path.join(self.tmp, "vault")
        shutil.copytree(FIXTURES / variant, self.vault)
        self.map = os.path.join(self.tmp, "pathmap.map.tsv")
        shutil.copy2(FIXTURES / "pathmap.map.tsv", self.map)
        self.keep = os.path.join(self.tmp, "keep.txt")
        self.skip = os.path.join(self.tmp, "skip.txt")
        shutil.copy2(FIXTURES / "keep.txt", self.keep)
        shutil.copy2(FIXTURES / "skip.txt", self.skip)
        self.out = os.path.join(self.tmp, "build", "zh")

    def rules(self) -> Rules:
        return Rules.load(self.keep, self.skip)

    def mapfile(self, path: str | None = None) -> MapFile:
        return MapFile.load(path or self.map)

    def apply(self, **kwargs):
        return run_apply(self.vault, self.out, self.mapfile(), self.rules(), **kwargs)

    def verify(self):
        return run_verify(self.vault, self.out, self.mapfile(), self.rules())

    def out_files(self) -> set[str]:
        found = set()
        for dirpath, _dirnames, filenames in os.walk(self.out):
            rel_dir = os.path.relpath(dirpath, self.out).replace(os.sep, "/")
            for name in filenames:
                if name == SENTINEL:
                    continue
                found.add(name if rel_dir == "." else f"{rel_dir}/{name}")
        return found

    def read_out(self, rel: str) -> str:
        return read_text(os.path.join(self.out, rel.replace("/", os.sep)))

    def dispose(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class PathTranslationTests(unittest.TestCase):
    def test_segments_extensions_and_keep(self) -> None:
        mapfile = MapFile(
            [
                Entry("docs", "文档"),
                Entry("docs/bitproc.md", "位流生产"),
                Entry("docs/kept.md", ""),
                Entry("docs/pic.png", "示意图"),
            ]
        )
        rules = Rules(keep=["vendor/*"], skip=[])
        self.assertEqual(translate_path("docs/bitproc.md", mapfile, rules), "文档/位流生产.md")
        self.assertEqual(translate_path("docs/bitproc.md", mapfile, rules).count("/"), 1)
        self.assertEqual(translate_path("docs/kept.md", mapfile, rules), "文档/kept.md")
        self.assertEqual(translate_path("docs/pic.png", mapfile, rules), "文档/示意图.png")
        self.assertEqual(translate_path("vendor/lib/x.md", mapfile, rules), "vendor/lib/x.md")

    def test_extension_not_doubled_when_name_has_it(self) -> None:
        mapfile = MapFile([Entry("a.md", "甲.md")])
        self.assertEqual(translate_path("a.md", mapfile, Rules()), "甲.md")

    def test_glob_and_hidden_rules(self) -> None:
        rules = Rules(keep=["man/**"], skip=["vendor/**"])
        self.assertTrue(rules.kept("man"))
        self.assertTrue(rules.kept("man/deep/x.md"))
        self.assertFalse(rules.kept("manship/x.md"))
        self.assertTrue(rules.skipped("vendor/a/b.md"))
        self.assertTrue(rules.skipped(".obsidian/app.json"))
        self.assertFalse(rules.skipped("guides/intro.md"))


class MapFileTests(unittest.TestCase):
    def test_roundtrip_keeps_tabs_and_note(self) -> None:
        ws = Workspace()
        try:
            path = os.path.join(ws.tmp, "roundtrip.tsv")
            mapfile = MapFile([Entry("a/b.md", "乙", "为什么这么翻")])
            mapfile.save(path)
            again = MapFile.load(path)
            entry = again.get("A/B.md")          # lookup is case-insensitive
            self.assertIsNotNone(entry)
            self.assertEqual(entry.name, "乙")
            self.assertEqual(entry.note, "为什么这么翻")
            raw = Path(path).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
        finally:
            ws.dispose()


class ScanTests(unittest.TestCase):
    def test_adds_missing_keys_and_respects_keep(self) -> None:
        ws = Workspace()
        try:
            mapfile = ws.mapfile()
            result = run_scan(ws.vault, mapfile, ws.rules())
            self.assertIn("misc", result["added"])
            self.assertIn("misc/notes.md", result["added"])
            self.assertNotIn("assets/logo.svg", result["added"])   # keep.txt covers it
            self.assertNotIn("guides/intro.md", result["added"])   # already mapped
        finally:
            ws.dispose()

    def test_prune_drops_orphans(self) -> None:
        ws = Workspace()
        try:
            mapfile = ws.mapfile()
            mapfile.add("gone/away.md", "不存在")
            result = run_scan(ws.vault, mapfile, ws.rules(), prune=True)
            self.assertIn("gone/away.md", result["pruned"])
            self.assertIsNone(mapfile.get("gone/away.md"))
        finally:
            ws.dispose()


class ApplyTests(unittest.TestCase):
    def test_tree_matches_expected_layout(self) -> None:
        ws = Workspace()
        try:
            summary = ws.apply()
            self.assertEqual(ws.out_files(), EXPECTED_TREE)
            self.assertEqual(summary.written, 7)
            self.assertEqual(summary.copied, 2)
            self.assertTrue(os.path.exists(os.path.join(ws.out, SENTINEL)))
            self.assertEqual(summary.plan.collisions, [])
            self.assertEqual(summary.plan.unmapped, ["misc/notes.md"])
        finally:
            ws.dispose()

    def test_assets_copy_byte_identical(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            source = os.path.join(ws.vault, "assets", "pic one.png")
            target = os.path.join(ws.out, "素材", "示意图.png")
            self.assertEqual(Path(source).read_bytes(), Path(target).read_bytes())
        finally:
            ws.dispose()

    def test_links_are_rewritten(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            text = ws.read_out("指南/入门.md")
            self.assertIn("[[术语表]]", text)
            self.assertIn("[[输入输出|进阶IO]]", text)
            self.assertIn("[[输入输出#接口]]", text)
            self.assertIn("![[示意图.png]]", text)
            self.assertIn("[输入输出](进阶/输入输出.md#接口)", text)
            self.assertIn("[术语表](../参考/术语表.md)", text)
            self.assertIn("(https://example.com/a.md)", text)

            # code must survive untouched
            self.assertIn("[[dict]] 与 [x](../ref/dict.md)", text)
            self.assertIn("`[[dict]]`", text)

            dictionary = ws.read_out("参考/术语表.md")
            self.assertIn("[[同名甲.md|甲]]", dictionary)

            io_page = ws.read_out("指南/进阶/输入输出.md")
            self.assertIn("[[入门]]", io_page)
            self.assertIn("[[术语表]]", io_page)
        finally:
            ws.dispose()

    def test_ambiguous_and_missing_links_are_reported_not_guessed(self) -> None:
        ws = Workspace(variant="vault-broken")
        try:
            summary = ws.apply()
            targets = {target for _src, target in summary.unresolved}
            self.assertIn("不存在的页", targets)
            self.assertIn("missing.md", targets)
            ambiguous = [target for _src, target, _hits in summary.ambiguous]
            self.assertIn("same", ambiguous)
            page = ws.read_out("参考/ambig.md")
            self.assertIn("[[same]]", page)          # left alone, not guessed
            self.assertIn("[[不存在的页]]", page)
        finally:
            ws.dispose()

    def test_refuses_output_inside_vault(self) -> None:
        ws = Workspace()
        try:
            with self.assertRaises(PathmapError):
                run_apply(ws.vault, os.path.join(ws.vault, "build"), ws.mapfile(), ws.rules())
        finally:
            ws.dispose()

    def test_refuses_to_wipe_foreign_directory(self) -> None:
        ws = Workspace()
        try:
            os.makedirs(ws.out, exist_ok=True)
            Path(os.path.join(ws.out, "someone-elses-file.txt")).write_text("keep me", encoding="utf-8")
            with self.assertRaises(PathmapError):
                ws.apply()
            self.assertTrue(os.path.exists(os.path.join(ws.out, "someone-elses-file.txt")))
            ws.apply(force=True)                     # explicit override works
            self.assertFalse(os.path.exists(os.path.join(ws.out, "someone-elses-file.txt")))
        finally:
            ws.dispose()

    def test_collision_is_refused(self) -> None:
        ws = Workspace()
        try:
            mapfile = ws.mapfile()
            mapfile.get("ref/dup-a").name = "重复"
            mapfile.get("ref/dup-b").name = "重复"
            mapfile.get("ref/dup-a/same.md").name = "同名"
            mapfile.get("ref/dup-b/same.md").name = "同名"
            with self.assertRaises(PathmapError):
                run_apply(ws.vault, ws.out, mapfile, ws.rules())
            self.assertFalse(os.path.exists(ws.out))
        finally:
            ws.dispose()

    def test_dry_run_writes_nothing(self) -> None:
        ws = Workspace()
        try:
            summary = ws.apply(dry_run=True)
            self.assertTrue(summary.dry_run)
            self.assertFalse(os.path.exists(ws.out))
            self.assertGreater(summary.wiki_links, 0)
        finally:
            ws.dispose()

    def test_md_link_titles_angle_brackets_and_percent_encoding(self) -> None:
        ws = Workspace()
        try:
            page = Path(ws.vault) / "guides" / "title.md"
            page.write_text(
                "# title\n\n"
                '[示意图](<../assets/pic one.png> "标题保留")\n\n'
                "[编码过的](../assets/pic%20one.png)\n\n"
                "[纯锚点](#本页)\n",
                encoding="utf-8",
                newline="\n",
            )
            ws.apply()
            text = ws.read_out("指南/title.md")
            self.assertIn('[示意图](<../素材/示意图.png> "标题保留")', text)
            self.assertIn("[编码过的](../素材/示意图.png)", text)
            self.assertIn("[纯锚点](#本页)", text)
        finally:
            ws.dispose()

    def test_link_mode_uses_hard_links_when_available(self) -> None:
        ws = Workspace()
        try:
            summary = ws.apply(link=True)
            self.assertEqual(summary.linked + summary.copied, 2)
            if summary.linked:
                source = os.path.join(ws.vault, "assets", "logo.svg")
                target = os.path.join(ws.out, "素材", "logo.svg")
                self.assertEqual(os.stat(source).st_ino, os.stat(target).st_ino)
        finally:
            ws.dispose()


class VerifyTests(unittest.TestCase):
    def test_clean_tree_verifies(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            result = ws.verify()
            self.assertEqual(result.dead_links, [])
            self.assertEqual(result.ambiguous, {})
            self.assertTrue(result.ok, result.__dict__)
        finally:
            ws.dispose()

    def test_dead_link_is_caught_in_the_product(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            os.remove(os.path.join(ws.out, "参考", "术语表.md"))
            result = ws.verify()
            self.assertFalse(result.ok)
            targets = {target for _page, target in result.dead_links}
            self.assertIn("术语表", targets)
        finally:
            ws.dispose()

    def test_missing_sentinel_is_reported(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            os.remove(os.path.join(ws.out, SENTINEL))
            self.assertTrue(ws.verify().sentinel_missing)
        finally:
            ws.dispose()

    def test_orphan_key_is_reported(self) -> None:
        ws = Workspace()
        try:
            ws.apply()
            mapfile = ws.mapfile()
            mapfile.add("nope/gone.md", "无")
            result = run_verify(ws.vault, ws.out, mapfile, ws.rules())
            self.assertIn("nope/gone.md", result.orphans)
        finally:
            ws.dispose()


class CliTests(unittest.TestCase):
    def test_scan_apply_verify_roundtrip(self) -> None:
        ws = Workspace()
        try:
            common = ["--vault", ws.vault, "--map", ws.map, "--keep", ws.keep, "--skip", ws.skip]
            self.assertEqual(main(["scan"] + common), 0)
            self.assertIn("misc/notes.md", Path(ws.map).read_text(encoding="utf-8"))
            self.assertEqual(main(["apply"] + common + ["--out", ws.out]), 0)
            self.assertEqual(main(["verify"] + common + ["--out", ws.out, "--require-map"]), 0)
        finally:
            ws.dispose()

    def test_cli_reports_refusal_with_exit_2(self) -> None:
        ws = Workspace()
        try:
            common = ["--vault", ws.vault, "--map", ws.map, "--keep", ws.keep, "--skip", ws.skip]
            code = main(["apply"] + common + ["--out", os.path.join(ws.vault, "inner")])
            self.assertEqual(code, 2)
        finally:
            ws.dispose()

    def test_verify_fails_on_broken_tree(self) -> None:
        ws = Workspace(variant="vault-broken")
        try:
            common = ["--vault", ws.vault, "--map", ws.map, "--keep", ws.keep, "--skip", ws.skip]
            main(["apply"] + common + ["--out", ws.out])
            self.assertEqual(main(["verify"] + common + ["--out", ws.out]), 1)
        finally:
            ws.dispose()


if __name__ == "__main__":
    unittest.main()