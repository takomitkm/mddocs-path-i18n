"""Command line entry point.

    pathmap scan   --vault <dir> [--map <file>]
    pathmap apply  --vault <dir> --out <dir> [--map <file>]
    pathmap verify --vault <dir> --out <dir> [--map <file>] [--require-map]

All three are non-interactive: no editor is launched, nothing is asked on
stdin.  That is what lets `verify` run as a build gate.
"""

from __future__ import annotations

import argparse
import os
import sys

from .apply import PathmapError, run_apply
from .links import Options
from .rules import MapFile, Rules
from .scan import run_scan
from .verify import describe, run_verify

DEFAULT_MAP = "pathmap.map.tsv"
DEFAULT_KEEP = "keep.txt"
DEFAULT_SKIP = "skip.txt"


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _rules_for(args: argparse.Namespace) -> Rules:
    map_dir = os.path.dirname(os.path.abspath(args.map))
    keep = args.keep or os.path.join(map_dir, DEFAULT_KEEP)
    skip = args.skip or os.path.join(map_dir, DEFAULT_SKIP)
    return Rules.load(
        keep if os.path.isfile(keep) else None,
        skip if os.path.isfile(skip) else None,
    )


def _load(args: argparse.Namespace) -> tuple[MapFile, Rules]:
    if not os.path.isdir(args.vault):
        raise PathmapError(f"vault is not a directory: {args.vault}")
    return MapFile.load(args.map), _rules_for(args)


def cmd_scan(args: argparse.Namespace) -> int:
    mapfile, rules = _load(args)
    result = run_scan(args.vault, mapfile, rules, prune=args.prune)
    print(f"files in vault: {result['files']}")
    print(f"keys added: {len(result['added'])}")
    for rel in result["added"][:20]:
        print(f"  + {rel}")
    if result["pruned"]:
        print(f"keys pruned: {len(result['pruned'])}")
        for rel in result["pruned"][:20]:
            print(f"  - {rel}")
    if result["orphans"]:
        print(f"keys with no vault file (kept; use --prune to drop): {len(result['orphans'])}")
    if args.dry_run:
        print("dry run: map not written")
        return 0
    mapfile.save(args.map)
    print(f"map written: {args.map}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    mapfile, rules = _load(args)
    summary = run_apply(
        args.vault,
        args.out,
        mapfile,
        rules,
        link=args.link,
        force=args.force,
        dry_run=args.dry_run,
        options=Options(root_links=args.root_links),
    )
    verb = "would write" if summary.dry_run else "wrote"
    print(f"{verb} {summary.written} pages, copied {summary.copied}, linked {summary.linked}")
    print(f"rewrote {summary.wiki_links} wiki links, {summary.md_links} markdown links")
    if summary.plan.unmapped:
        print(f"paths with no map entry (kept as-is): {len(summary.plan.unmapped)}")
    if summary.ambiguous:
        print(f"ambiguous wiki links (left untouched): {len(summary.ambiguous)}")
        for src, target, hits in summary.ambiguous[:10]:
            print(f"  AMBIGUOUS {src} -> {target} {hits}")
    if summary.unresolved:
        print(f"references that resolve to nothing (left untouched): {len(summary.unresolved)}")
        for src, target in summary.unresolved[:10]:
            print(f"  DEAD {src} -> {target}")
    if summary.dry_run:
        return 0
    print(f"output tree: {args.out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    mapfile, rules = _load(args)
    result = run_verify(args.vault, args.out, mapfile, rules)
    print(describe(result))
    if args.require_map and result.unmapped:
        print(f"FAILED: {len(result.unmapped)} paths still have no translation")
        return 1
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pathmap",
        description="Translate a Markdown tree's file and directory names, and fix every link.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(ap: argparse.ArgumentParser) -> None:
        ap.add_argument("--vault", required=True, help="source tree to read")
        ap.add_argument("--map", default=DEFAULT_MAP, help=f"translation list (default {DEFAULT_MAP})")
        ap.add_argument("--keep", default=None, help=f"globs that keep their name (default {DEFAULT_KEEP} next to the map)")
        ap.add_argument("--skip", default=None, help=f"globs left out of the tree (default {DEFAULT_SKIP} next to the map)")

    scan = sub.add_parser("scan", help="add missing keys to the translation list")
    common(scan)
    scan.add_argument("--prune", action="store_true", help="drop keys whose vault path no longer exists")
    scan.add_argument("--dry-run", action="store_true", help="report, do not write the map")
    scan.set_defaults(func=cmd_scan)

    apply_cmd = sub.add_parser("apply", help="build the translated tree")
    common(apply_cmd)
    apply_cmd.add_argument("--out", required=True, help="output tree (must be outside the vault)")
    apply_cmd.add_argument("--link", action="store_true", help="hard-link assets instead of copying them")
    apply_cmd.add_argument("--force", action="store_true", help="overwrite an output tree without the sentinel")
    apply_cmd.add_argument("--dry-run", action="store_true", help="plan only, write nothing")
    apply_cmd.add_argument("--root-links", action="store_true", help="also rewrite site-absolute /path links")
    apply_cmd.set_defaults(func=cmd_apply)

    verify_cmd = sub.add_parser("verify", help="check the generated tree")
    common(verify_cmd)
    verify_cmd.add_argument("--out", required=True, help="output tree to check")
    verify_cmd.add_argument("--require-map", action="store_true", help="fail when a path has no translation")
    verify_cmd.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PathmapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())