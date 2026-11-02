"""`pathmap scan`: keep the translation list in step with the vault."""

from __future__ import annotations

from .plan import build_plan
from .rules import MapFile, Rules


def run_scan(vault: str, mapfile: MapFile, rules: Rules, *, prune: bool = False) -> dict:
    """Add a key for every path that has none; optionally drop orphaned keys.

    A newly added key carries an empty name, which means "keep the original
    spelling" -- so a half-finished list still produces a complete, working
    tree instead of a tree with missing files.
    """
    plan = build_plan(vault, out=vault, mapfile=mapfile, rules=rules)
    added: list[str] = []
    seen: set[str] = set()

    for item in plan.items:
        parts = item.src.split("/")
        for depth in range(len(parts)):
            prefix = "/".join(parts[: depth + 1])
            if prefix in seen:
                continue
            seen.add(prefix)
            if mapfile.get(prefix) is not None:
                continue
            if rules.kept(prefix):
                # keep.txt already says this name stays; a key with an empty
                # name would only add noise to the list a translator reads.
                continue
            mapfile.add(prefix, "", "")
            added.append(prefix)

    pruned: list[str] = []
    if prune:
        for entry in list(mapfile.entries):
            if entry.rel not in seen:
                mapfile.remove(entry.rel)
                pruned.append(entry.rel)

    orphans = [e.rel for e in mapfile.entries if e.rel not in seen]
    return {
        "added": sorted(added),
        "pruned": sorted(pruned),
        "orphans": sorted(orphans),
        "files": len(plan.items),
    }