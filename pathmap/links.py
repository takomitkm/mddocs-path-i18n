"""Rewrite every internal reference so the translated tree is self-consistent.

This is the part the original scripts were missing entirely: they renamed
files and left every ``[[link]]`` pointing at the old English name, which is
what makes a renamed tree unusable in Obsidian and dead on the web.

Two dialects, resolved the way their consumers resolve them:

* ``[[page]]`` / ``[[page|text]]`` / ``[[page#heading]]`` / ``[[page#^block]]``
  and ``![[asset.png]]`` -- Obsidian resolves these **by file name**, not by
  path, so the index is by basename.  Two files with the same basename make a
  bare link ambiguous: that is reported, never guessed.
* ``[text](relative/path.md#anchor)`` and ``![alt](img.png)`` -- resolved
  relative to the file that contains them, then re-relativised against the
  file's new location.

Fenced code blocks and inline code spans are masked first, so a link that is
being *shown* as example text is never rewritten.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from .plan import Plan
from .util import key, posix, resolve_rel

WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
MDLINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\n]*)\)")
INLINE_CODE = re.compile(r"`[^`\n]+`")
PLACEHOLDER = "\x00PM{}\x00"
PLACEHOLDER_RE = re.compile("\x00PM(\\d+)\x00")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
TITLE_AT_END = re.compile(r"\s+(?:\"[^\"]*\"|'[^']*')\s*$")


@dataclass
class Report:
    wiki: int = 0
    md: int = 0
    ambiguous: list[tuple[str, str, list[str]]] = field(default_factory=list)
    unresolved: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Options:
    root_links: bool = False     # also rewrite site-absolute "/path" links


def mask_code(text: str) -> tuple[str, list[str]]:
    """Replace fenced blocks and inline code spans with inert placeholders."""
    lines = text.splitlines(keepends=True)
    masks: list[str] = []
    out: list[str] = []
    fence: tuple[str, int] | None = None
    buffer: list[str] = []

    for line in lines:
        marker = _fence_marker(line)
        if fence is None and marker is not None:
            fence = marker
            buffer = [line]
            continue
        if fence is not None:
            buffer.append(line)
            if marker is not None and marker[0] == fence[0] and marker[1] >= fence[1]:
                masks.append("".join(buffer))
                out.append(PLACEHOLDER.format(len(masks) - 1))
                buffer = []
                fence = None
            continue
        out.append(line)
    if fence is not None:  # unclosed fence: everything after it is code
        masks.append("".join(buffer))
        out.append(PLACEHOLDER.format(len(masks) - 1))

    masked = "".join(out)

    def take(match: "re.Match[str]") -> str:
        masks.append(match.group(0))
        return PLACEHOLDER.format(len(masks) - 1)

    masked = INLINE_CODE.sub(take, masked)
    return masked, masks


def unmask_code(text: str, masks: list[str]) -> str:
    def restore(match: "re.Match[str]") -> str:
        index = int(match.group(1))
        return masks[index] if index < len(masks) else match.group(0)

    return PLACEHOLDER_RE.sub(restore, text)


def _fence_marker(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip()
    if not stripped:
        return None
    char = stripped[0]
    if char not in ("`", "~"):
        return None
    run = len(stripped) - len(stripped.lstrip(char))
    if run < 3:
        return None
    return char, run


def split_target_title(raw: str) -> tuple[str, str]:
    """``path "title"`` -> ("path", ' "title"'); titles are preserved verbatim."""
    match = TITLE_AT_END.search(raw)
    if match:
        return raw[: match.start()].strip(), raw[match.start() :]
    return raw.strip(), ""


def rewrite_text(text: str, src: str, out_rel: str, plan: Plan, options: Options) -> tuple[str, Report]:
    report = Report()
    masked, masks = mask_code(text)
    masked = _rewrite_wikilinks(masked, src, plan, report)
    masked = _rewrite_md_links(masked, src, out_rel, plan, report, options)
    return unmask_code(masked, masks), report


def _rewrite_wikilinks(text: str, src: str, plan: Plan, report: Report) -> str:
    def repl(match: "re.Match[str]") -> str:
        bang, body = match.group(1), match.group(2)
        target, pipe, display = body.partition("|")
        path_part, hashed, anchor = target.partition("#")
        raw = path_part.strip()
        if not raw:
            return match.group(0)          # [[#heading]] links to this page
        hit = _resolve_wikilink(raw, src, plan, report)
        if hit is None:
            return match.group(0)
        new_base = plan.out_of[key(hit)].rsplit("/", 1)[-1]
        if new_base.lower().endswith(".md") and not raw.lower().endswith(".md"):
            new_base = new_base[:-3]
        rebuilt = new_base
        if hashed:
            rebuilt += "#" + anchor
        if pipe:
            rebuilt += "|" + display
        report.wiki += 1
        return f"{bang}[[{rebuilt}]]"

    return WIKILINK.sub(repl, text)


def _resolve_wikilink(raw: str, src: str, plan: Plan, report: Report) -> str | None:
    target = posix(raw.strip())
    if "/" in target:
        guess = resolve_rel(posix(posixpath.dirname(posix(src))), target)
        for candidate in (guess, guess + ".md", target, target + ".md"):
            hit = plan.vault_paths.get(key(candidate))
            if hit:
                return hit
    base = target.rsplit("/", 1)[-1].casefold()
    for candidate in (base, base + ".md"):
        hits = plan.vault_basename.get(candidate, [])
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            report.ambiguous.append((src, raw, hits))
            return None
    report.unresolved.append((src, raw))
    return None


def _rewrite_md_links(
    text: str, src: str, out_rel: str, plan: Plan, report: Report, options: Options
) -> str:
    src_out_dir = posix(posixpath.dirname(posix(out_rel)))

    def repl(match: "re.Match[str]") -> str:
        bang, label, raw = match.group(1), match.group(2), match.group(3)
        if not raw.strip():
            return match.group(0)
        url, title = split_target_title(raw)
        bracketed = url.startswith("<") and url.endswith(">")
        if bracketed:
            url = url[1:-1]
        path_part, hashed, fragment = url.partition("#")
        path_part, queried, query = path_part.partition("?")
        plain = unquote(path_part)
        if not plain or SCHEME.match(plain) or plain.startswith("//"):
            return match.group(0)
        if plain.startswith("/") and not options.root_links:
            return match.group(0)
        hit = plan.resolve_from(src, plain)
        if hit is None:
            report.unresolved.append((src, url))
            return match.group(0)
        new_abs = plan.out_of[key(hit)]
        new_rel = posixpath.relpath(new_abs, src_out_dir or ".")
        rebuilt = _quote_spaces(new_rel)
        if queried:
            rebuilt += "?" + query
        if hashed:
            rebuilt += "#" + fragment
        if bracketed:
            rebuilt = f"<{rebuilt}>"
        rebuilt += title
        report.md += 1
        return f"{bang}[{label}]({rebuilt})"

    return MDLINK.sub(repl, text)


def _quote_spaces(value: str) -> str:
    return value.replace(" ", "%20")


def iter_refs(text: str):
    """Yield ("wiki" | "md", target) for every internal reference in a page.

    Code blocks and spans are masked first, so examples stay out of the check.
    """
    masked, _ = mask_code(text)

    for match in WIKILINK.finditer(masked):
        body = match.group(2)
        target = body.partition("|")[0].partition("#")[0].strip()
        if target:
            yield "wiki", target

    for match in MDLINK.finditer(masked):
        url, _title = split_target_title(match.group(3))
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        path_part = url.partition("#")[0].partition("?")[0]
        plain = unquote(path_part)
        if not plain or SCHEME.match(plain) or plain.startswith("//"):
            continue
        yield "md", plain