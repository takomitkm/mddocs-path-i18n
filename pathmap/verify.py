"""`pathmap verify`: check the product, not the intention.

`apply` already knows what it wanted to write.  This module deliberately
throws that away and re-reads the generated tree, resolving every link
against the tree itself -- because the only claim worth making is "no page in
the output points at something that is not there".
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field

from .links import iter_refs
from .plan import build_plan, walk_vault
from .rules import MapFile, Rules
from .util import SENTINEL, is_markdown, key, posix, read_text, resolve_rel


@dataclass
class VerifyResult:
    out: str
    pages: int = 0
    assets: int = 0
    dead_links: list[tuple[str, str]] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)
    collisions: list[tuple[str, str, str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    unused_rules: list[tuple[str, str]] = field(default_factory=list)
    sentinel_missing: bool = False
    missing_out: bool = False

    @property
    def errors(self) -> int:
        return (
            len(self.dead_links)
            + len(self.ambiguous)
            + len(self.collisions)
            + (1 if self.sentinel_missing else 0)
            + (1 if self.missing_out else 0)
        )

    @property
    def ok(self) -> bool:
        return self.errors == 0


def run_verify(vault: str, out: str, mapfile: MapFile, rules: Rules) -> VerifyResult:
    result = VerifyResult(out=out)
    if not os.path.isdir(out):
        result.missing_out = True
        return result
    if not os.path.exists(os.path.join(out, SENTINEL)):
        result.sentinel_missing = True

    plan = build_plan(vault, out, mapfile, rules)
    result.collisions = list(plan.collisions)
    result.unmapped = list(plan.unmapped)
    result.orphans = sorted(e.rel for e in mapfile.entries if plan.known.get(key(e.rel)) is None)

    tree = _walk(out)
    result.pages = sum(1 for rel in tree if is_markdown(rel))
    result.assets = len(tree) - result.pages

    by_basename: dict[str, list[str]] = {}
    by_path: dict[str, str] = {}
    for rel in tree:
        by_path[key(rel)] = rel
        by_basename.setdefault(rel.rsplit("/", 1)[-1].casefold(), []).append(rel)
    result.ambiguous = {name: paths for name, paths in by_basename.items() if len(paths) > 1}

    for rel in tree:
        if not is_markdown(rel):
            continue
        text = read_text(os.path.join(out, rel.replace("/", os.sep)))
        for kind, target in iter_refs(text):
            if kind == "wiki":
                if not _wiki_hits(target, posix(posixpath.dirname(rel)), by_basename, by_path):
                    result.dead_links.append((rel, target))
            else:
                guess = resolve_rel(posix(posixpath.dirname(rel)), target)
                if key(guess) not in by_path:
                    result.dead_links.append((rel, target))

    result.unused_rules = rules.unused_patterns(walk_vault(vault, Rules(keep=rules.keep, skip=[])))
    return result


def _wiki_hits(
    target: str,
    page_dir: str,
    by_basename: dict[str, list[str]],
    by_path: dict[str, str],
) -> bool:
    raw = posix(target.strip())
    if "/" in raw:
        guess = resolve_rel(page_dir, raw)
        if key(guess) in by_path or key(raw) in by_path:
            return True
    base = raw.rsplit("/", 1)[-1].casefold()
    if base in by_basename:
        return True
    return f"{base}.md" in by_basename


def _walk(root: str) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        prefix = "" if rel_dir == "." else posix(rel_dir)
        for name in sorted(filenames):
            if name == SENTINEL:
                continue
            found.append(f"{prefix}/{name}" if prefix else name)
    return found


def describe(result: VerifyResult) -> str:
    lines = [
        f"pages: {result.pages}  assets: {result.assets}",
        f"dead links: {len(result.dead_links)}",
    ]
    for page, target in result.dead_links[:20]:
        lines.append(f"  DEAD  {page}  ->  {target}")
    if result.ambiguous:
        lines.append(f"ambiguous output basenames: {len(result.ambiguous)}")
        for name, paths in list(result.ambiguous.items())[:10]:
            lines.append(f"  DUP   {name}  {paths}")
    if result.collisions:
        lines.append(f"output collisions: {len(result.collisions)}")
        for first, second, target in result.collisions[:10]:
            lines.append(f"  CLASH {target}  <-  {first} + {second}")
    if result.orphans:
        lines.append(f"map keys with no vault file: {len(result.orphans)}")
        for rel in result.orphans[:10]:
            lines.append(f"  ORPHAN {rel}")
    if result.unmapped:
        lines.append(f"vault files with no map entry (kept as-is): {len(result.unmapped)}")
        for rel in result.unmapped[:10]:
            lines.append(f"  RAW   {rel}")
    if result.unused_rules:
        lines.append(f"keep/skip patterns that matched nothing: {len(result.unused_rules)}")
        for kind, pattern in result.unused_rules[:10]:
            lines.append(f"  NOOP  {kind}: {pattern}")
    if result.sentinel_missing:
        lines.append(f"WARNING: {SENTINEL} missing -- this tree was probably not built by pathmap")
    if result.missing_out:
        lines.append("WARNING: output directory does not exist")
    lines.append("OK" if result.ok else "FAILED")
    return "\n".join(lines)