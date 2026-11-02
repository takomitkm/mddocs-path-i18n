"""`pathmap apply`: build the translated tree from the vault.

The output tree is a build artifact, always rebuilt from scratch, always
outside the vault.  Nothing is ever renamed in place -- that is the mistake
the scripts this tool replaces made, and it is what turns a translation job
into an unrecoverable one.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

from .links import Options, Report, rewrite_text
from .plan import Plan, ambiguous_basenames, build_plan
from .rules import MapFile, Rules
from .util import SENTINEL, SENTINEL_TEXT, is_markdown, read_text, write_text


@dataclass
class Summary:
    plan: Plan
    written: int = 0
    copied: int = 0
    linked: int = 0
    wiki_links: int = 0
    md_links: int = 0
    reports: list[Report] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ambiguous(self) -> list[tuple[str, str, list[str]]]:
        return [entry for report in self.reports for entry in report.ambiguous]

    @property
    def unresolved(self) -> list[tuple[str, str]]:
        return [entry for report in self.reports for entry in report.unresolved]


class PathmapError(RuntimeError):
    """Refusals: bad output target, or a plan that cannot be built safely."""


def check_output(vault: str, out: str, *, force: bool) -> None:
    vault_abs = os.path.abspath(vault)
    out_abs = os.path.abspath(out)
    if vault_abs == out_abs or out_abs.startswith(vault_abs + os.sep):
        raise PathmapError(f"refusing to write inside the vault: {out_abs}")
    if not os.path.isdir(out_abs):
        return
    if force:
        return
    if not os.listdir(out_abs):
        return
    if not os.path.exists(os.path.join(out_abs, SENTINEL)):
        raise PathmapError(
            f"refusing to wipe {out_abs}: no {SENTINEL} marker there "
            "(use --force if that directory is yours to lose)"
        )


def run_apply(
    vault: str,
    out: str,
    mapfile: MapFile,
    rules: Rules,
    *,
    link: bool = False,
    force: bool = False,
    dry_run: bool = False,
    options: Options | None = None,
) -> Summary:
    options = options or Options()
    check_output(vault, out, force=force)
    plan = build_plan(vault, out, mapfile, rules)
    summary = Summary(plan=plan, dry_run=dry_run)

    if plan.collisions:
        raise PathmapError(_collision_message(plan))

    if dry_run:
        summary.reports = _scan_sources(plan, options)
        summary.wiki_links = sum(report.wiki for report in summary.reports)
        summary.md_links = sum(report.md for report in summary.reports)
        summary.written = sum(1 for item in plan.items if item.is_md)
        summary.copied = sum(1 for item in plan.items if not item.is_md)
        return summary

    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)

    for item in plan.items:
        target = plan.out_abs(item.out)
        source = plan.src_abs(item.src)
        if is_markdown(item.src):
            text = read_text(source)
            new_text, report = rewrite_text(text, item.src, item.out, plan, options)
            write_text(target, new_text)
            summary.reports.append(report)
            summary.wiki_links += report.wiki
            summary.md_links += report.md
            summary.written += 1
        else:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            if link and _try_link(source, target):
                summary.linked += 1
            else:
                shutil.copy2(source, target)
                summary.copied += 1

    sentinel = os.path.join(out, SENTINEL)
    with open(sentinel, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(SENTINEL_TEXT)
    return summary


def _scan_sources(plan: Plan, options: Options) -> list[Report]:
    reports: list[Report] = []
    for item in plan.items:
        if not item.is_md:
            continue
        text = read_text(plan.src_abs(item.src))
        _, report = rewrite_text(text, item.src, item.out, plan, options)
        reports.append(report)
    return reports


def _try_link(source: str, target: str) -> bool:
    try:
        os.link(source, target)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


def _collision_message(plan: Plan) -> str:
    lines = ["two vault paths land on the same output path; fix the map first:"]
    for first, second, target in plan.collisions[:20]:
        lines.append(f"  {target}  <-  {first}  +  {second}")
    return "\n".join(lines)


def duplicate_output_basenames(plan: Plan) -> dict[str, list[str]]:
    return ambiguous_basenames(plan.out_basename)