"""The two data files that drive every translation.

``pathmap.map.tsv``
    ``<vault-relative path> \\t <localised name> [\\t <note>]``
    One entry per segment you want translated: a directory gets its own
    entry, a file gets its own entry.  A key whose name column is empty
    means "leave this name alone" (same effect as a ``keep`` glob, but
    explicit and local).

``keep.txt`` / ``skip.txt``
    One glob per line.
    * keep:  matching paths (or paths under a matching directory) keep their
             original name, and need no map entry.
    * skip:  matching paths are not part of the output tree at all.

    ``*`` stays inside one path segment, ``**`` crosses segments.  Hidden
    files and directories (any segment starting with ".") are skipped
    automatically and do not need a rule.

Why plain text instead of YAML/JSON: a translation list is edited by a
translator, not by a program.  A TSV file opens in Excel/LibreOffice,
a diff of it is one line per change, and parsing it needs no dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .util import glob_to_regex, has_hidden_segment, key, posix, read_text, write_text


@dataclass
class Entry:
    rel: str          # original spelling of the key, forward slashes
    name: str         # "" means: keep the original name for this segment
    note: str = ""
    line: int = 0

    @property
    def translates(self) -> bool:
        return bool(self.name.strip())


class MapFile:
    """The translation list, keyed case-insensitively by vault-relative path."""

    def __init__(self, entries: list[Entry] | None = None, path: str | None = None) -> None:
        self.entries: list[Entry] = entries or []
        self.path = path
        self._index = {key(e.rel): e for e in self.entries if e.rel}

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: str) -> "MapFile":
        text = read_text(path) if os.path.isfile(path) else ""
        return cls(parse_map(text), path=path)

    @classmethod
    def empty(cls, path: str | None = None) -> "MapFile":
        return cls([], path=path)

    # -- lookup ------------------------------------------------------------

    def get(self, rel: str) -> Entry | None:
        return self._index.get(key(rel))

    def __len__(self) -> int:
        return len(self._index)

    def add(self, rel: str, name: str = "", note: str = "") -> Entry:
        entry = Entry(rel=posix(rel), name=name, note=note)
        self.entries.append(entry)
        self._index[key(rel)] = entry
        return entry

    def remove(self, rel: str) -> bool:
        hit = self._index.pop(key(rel), None)
        if hit is None:
            return False
        self.entries = [e for e in self.entries if e is not hit]
        return True

    # -- persistence -------------------------------------------------------

    def render(self) -> str:
        lines = [
            "# pathmap translation list: <vault path> \\t <localised name> \\t <note>",
            "# empty name = keep the original spelling of that one segment",
        ]
        for entry in sorted(self.entries, key=lambda e: key(e.rel)):
            row = [entry.rel, entry.name]
            if entry.note:
                row.append(entry.note)
            lines.append("\t".join(row))
        return "\n".join(lines) + "\n"

    def save(self, path: str | None = None) -> str:
        target = path or self.path
        if not target:
            raise ValueError("no path for the translation list")
        write_text(target, self.render())
        self.path = target
        return target


def parse_map(text: str) -> list[Entry]:
    entries: list[Entry] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) == 1:
            # A map written by hand may use spaces; only tabs are official,
            # but a single-column line is still a usable "keep this" key.
            rel, name, note = fields[0].strip(), "", ""
        else:
            rel = fields[0].strip()
            name = fields[1].strip()
            note = fields[2].strip() if len(fields) > 2 else ""
        if not rel:
            continue
        entries.append(Entry(rel=posix(rel).strip("/"), name=name, note=note, line=line_no))
    return entries


@dataclass
class Rules:
    """Name-preserving and excluded paths, from keep.txt / skip.txt."""

    keep: list[str] = field(default_factory=list)
    skip: list[str] = field(default_factory=list)

    _keep: list = field(default_factory=list, init=False, repr=False)
    _skip: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._keep = [(p, compile_pattern(p)) for p in self.keep]
        self._skip = [(p, compile_pattern(p)) for p in self.skip]

    @classmethod
    def load(cls, keep_path: str | None, skip_path: str | None) -> "Rules":
        return cls(read_patterns(keep_path), read_patterns(skip_path))

    def skipped(self, rel: str) -> bool:
        if has_hidden_segment(rel):
            return True
        return _matches(self._skip, rel)

    def kept(self, rel: str) -> bool:
        """True when this path (or a directory above it) must keep its name."""
        candidates = [posix(rel)]
        parts = posix(rel).split("/")
        candidates += ["/".join(parts[:i]) for i in range(1, len(parts))]
        return any(_matches(self._keep, c) for c in candidates)

    def unused_patterns(self, seen: list[str]) -> list[tuple[str, str]]:
        """(kind, pattern) pairs that matched nothing -- usually a typo."""
        out: list[tuple[str, str]] = []
        for kind, groups in (("keep", self._keep), ("skip", self._skip)):
            for pattern, regexes in groups:
                if not any(rx.match(posix(s)) for rx in regexes for s in seen):
                    out.append((kind, pattern))
        return out


def compile_pattern(pattern: str) -> list:
    """A pattern plus the directory it names, so ``man/**`` also keeps ``man``.

    Without this, ``man/**`` would translate the directory ``man`` while its
    contents kept their names -- which nobody means when they write it.
    """
    compiled = [glob_to_regex(pattern)]
    stripped = posix(pattern).strip().rstrip("/")
    if stripped.endswith("/**"):
        compiled.append(glob_to_regex(stripped[: -len("/**")]))
    return compiled


def _matches(groups: list, rel: str) -> bool:
    target = posix(rel)
    return any(rx.match(target) for _pattern, regexes in groups for rx in regexes)


def read_patterns(path: str | None) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    patterns: list[str] = []
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns