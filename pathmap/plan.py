"""Work out where every vault file lands, and index the result.

The output path of a file is decided one segment at a time, which is the
one design decision worth keeping from the scripts this tool replaces:
a directory gets one name, and everything below it inherits that prefix
without repeating the parent's translation in every key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .rules import MapFile, Rules
from .util import adjust_extension, is_markdown, key, posix, resolve_rel


@dataclass
class Item:
    src: str        # vault-relative, forward slashes
    out: str        # output-relative, forward slashes
    is_md: bool


@dataclass
class Plan:
    vault: str
    out: str
    items: list[Item] = field(default_factory=list)
    collisions: list[tuple[str, str, str]] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)

    # indexes, all keyed case-insensitively
    vault_paths: dict[str, str] = field(default_factory=dict, repr=False)
    vault_basename: dict[str, list[str]] = field(default_factory=dict, repr=False)
    out_of: dict[str, str] = field(default_factory=dict, repr=False)
    out_paths: dict[str, str] = field(default_factory=dict, repr=False)
    out_src: dict[str, str] = field(default_factory=dict, repr=False)
    known: dict[str, str] = field(default_factory=dict, repr=False)
    out_basename: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def src_abs(self, rel: str) -> str:
        return os.path.join(self.vault, posix(rel).replace("/", os.sep))

    def out_abs(self, rel: str) -> str:
        return os.path.join(self.out, posix(rel).replace("/", os.sep))

    def resolve_from(self, source_rel: str, target: str) -> str | None:
        """Vault path a relative link in ``source_rel`` points at, if any."""
        guess = resolve_rel(posix(os.path.dirname(posix(source_rel))), target)
        return self.vault_paths.get(key(guess))

    def translate_for(self, source_rel: str, vault_rel: str) -> str:
        return self.out_of[key(vault_rel)]


def walk_vault(vault: str, rules: Rules) -> list[str]:
    """Every non-skipped file under the vault, vault-relative, sorted."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(vault):
        rel_dir = os.path.relpath(dirpath, vault)
        prefix = "" if rel_dir == "." else posix(rel_dir)
        keep_dirs = []
        for name in sorted(dirnames):
            rel = f"{prefix}/{name}" if prefix else name
            if not rules.skipped(rel):
                keep_dirs.append(name)
        dirnames[:] = keep_dirs
        for name in sorted(filenames):
            rel = f"{prefix}/{name}" if prefix else name
            if rules.skipped(rel):
                continue
            found.append(rel)
    return sorted(found)


def translate_path(rel: str, mapfile: MapFile, rules: Rules) -> str:
    """Where one vault-relative path lands in the output tree."""
    parts = posix(rel).split("/")
    out: list[str] = []
    for depth in range(len(parts)):
        segment = parts[depth]
        prefix = "/".join(parts[: depth + 1])
        is_last = depth == len(parts) - 1
        entry = mapfile.get(prefix)
        name = segment
        if entry is not None and entry.translates:
            name = entry.name.strip()
        elif rules.kept(prefix):
            name = segment
        if is_last:
            name = adjust_extension(segment, name)
        out.append(name)
    return "/".join(out)


def build_plan(vault: str, out: str, mapfile: MapFile, rules: Rules) -> Plan:
    plan = Plan(vault=vault, out=out)
    files = walk_vault(vault, rules)

    for rel in files:
        target = translate_path(rel, mapfile, rules)
        item = Item(src=rel, out=target, is_md=is_markdown(rel))
        plan.items.append(item)

        parts = rel.split("/")
        for depth in range(len(parts)):
            prefix = "/".join(parts[: depth + 1])
            plan.known.setdefault(key(prefix), prefix)

        if mapfile.get(rel) is None and not rules.kept(rel):
            plan.unmapped.append(rel)

        plan.vault_paths[key(rel)] = rel
        plan.vault_basename.setdefault(posix(rel).rsplit("/", 1)[-1].casefold(), []).append(rel)
        plan.out_of[key(rel)] = target

        clash = plan.out_paths.get(key(target))
        if clash is not None:
            plan.collisions.append((plan.out_src[key(target)], rel, target))
        else:
            plan.out_paths[key(target)] = target
            plan.out_src[key(target)] = rel
            plan.out_basename.setdefault(target.rsplit("/", 1)[-1].casefold(), []).append(target)
    return plan


def ambiguous_basenames(index: dict[str, list[str]]) -> dict[str, list[str]]:
    return {name: paths for name, paths in index.items() if len(paths) > 1}