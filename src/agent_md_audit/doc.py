"""Load an agent instruction file and work out what it is talking about."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Iterator, Optional

INSTRUCTION_FILENAMES = (
    "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md",
    "copilot-instructions.md", ".cursorrules", ".windsurfrules", ".clinerules",
)
CONFIG_DIRS = {".github", ".claude", ".gemini", ".cursor", ".codex"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", "target", ".next", ".mypy_cache", ".pytest_cache"}
MAX_TREE_ENTRIES = 50_000

FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+\S")


@dataclass
class Doc:
    path: Path
    """Absolute path to the instruction file."""
    text: str
    lines: list[str]
    in_fence: list[bool]
    """True for lines inside a fenced code block (fence lines included)."""
    root: Path
    """Project root: the nearest folder above the file that holds .git, else the file's folder."""
    _tree: Optional[tuple[set[str], set[str]]] = field(default=None, repr=False)

    @property
    def folder(self) -> Path:
        return self.path.parent

    @property
    def base_dirs(self) -> list[Path]:
        """Folders a relative path in this file may be relative to, most likely first."""
        dirs = [self.folder]
        if self.folder.name in CONFIG_DIRS:
            dirs.append(self.folder.parent)
        if self.root not in dirs:
            dirs.append(self.root)
        return dirs

    # --- text views -----------------------------------------------------------

    def prose_lines(self) -> Iterator[tuple[int, str]]:
        """(lineno, line) outside fenced code, with inline code blanked out."""
        for i, line in enumerate(self.lines):
            if not self.in_fence[i]:
                yield i + 1, INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)

    def lines_all(self) -> Iterator[tuple[int, str]]:
        """(lineno, line) for every line, code included."""
        for i, line in enumerate(self.lines):
            yield i + 1, line

    def text_lines(self) -> Iterator[tuple[int, str]]:
        """(lineno, line) outside fenced code, inline code kept."""
        for i, line in enumerate(self.lines):
            if not self.in_fence[i]:
                yield i + 1, line

    def code_snippets(self) -> Iterator[tuple[int, str]]:
        """(lineno, code) for every fenced line and every inline code span."""
        for i, line in enumerate(self.lines):
            if self.in_fence[i]:
                if not FENCE_RE.match(line):
                    yield i + 1, line
            else:
                for m in INLINE_CODE_RE.finditer(line):
                    yield i + 1, m.group(2)

    def headings(self) -> Iterator[tuple[int, int, str]]:
        """(lineno, level, text) for every ATX heading outside fences."""
        for i, line in enumerate(self.lines):
            if not self.in_fence[i]:
                m = HEADING_RE.match(line)
                if m:
                    yield i + 1, len(m.group(1)), line.strip().lstrip("#").strip()

    # --- the project around the file -----------------------------------------

    def find_project_file(self, *names: str) -> Optional[Path]:
        """The first of `names` found in the file's folder(s), then the project root."""
        for d in self.base_dirs:
            for n in names:
                if (d / n).is_file():
                    return d / n
        return None

    def _walk(self) -> tuple[set[str], set[str]]:
        if self._tree is None:
            rels: set[str] = set()
            names: set[str] = set()
            stack = [self.root]
            while stack and len(rels) < MAX_TREE_ENTRIES:
                d = stack.pop()
                try:
                    entries = list(d.iterdir())
                except OSError:
                    continue
                for e in entries:
                    if e.name in SKIP_DIRS:
                        continue
                    rel = e.relative_to(self.root).as_posix()
                    rels.add(rel)
                    names.add(e.name)
                    if e.is_dir() and not e.is_symlink():
                        stack.append(e)
            self._tree = (rels, names)
        return self._tree

    def path_exists(self, target: str) -> bool:
        """True if `target` exists relative to any base folder, or (for a path
        without ./ or ../) as the tail of some path in the project."""
        clean = target.rstrip("/")
        if not clean:
            return True
        for d in self.base_dirs:
            if (d / clean).exists():
                return True
        if clean.startswith(("./", "../")):
            return False
        rels, names = self._walk()
        if "/" not in clean:
            return clean in names
        return any(r == clean or r.endswith("/" + clean) for r in rels)

    @cached_property
    def ignore_patterns(self) -> list[str]:
        pats = [".env", ".env.*", "*.local", "node_modules", "node_modules/*"]
        gi = self.root / ".gitignore"
        if gi.is_file():
            for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "!")):
                    pats.append(line.lstrip("/"))
        return pats

    def is_ignored(self, target: str) -> bool:
        """True if git would ignore `target`, so it legitimately may not exist in a checkout."""
        clean = target[2:] if target.startswith("./") else target
        parts = clean.rstrip("/").split("/")
        for pat in self.ignore_patterns:
            p = pat.rstrip("/")
            if fnmatch.fnmatch(clean.rstrip("/"), p) or any(fnmatch.fnmatch(part, p) for part in parts):
                return True
            if clean.startswith(p + "/"):
                return True
        return False


def project_root(path: Path) -> Path:
    start = path.parent
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return start.parent if start.name in CONFIG_DIRS else start


def mark_fences(lines: list[str]) -> list[bool]:
    flags: list[bool] = []
    fence: Optional[str] = None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                flags.append(True)
            else:
                flags.append(False)
        else:
            flags.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence = None
    return flags


def load_doc(path: Path, root: Optional[Path] = None) -> Doc:
    path = path.resolve()
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return Doc(path=path, text=text, lines=lines, in_fence=mark_fences(lines), root=(root or project_root(path)).resolve())


def discover(paths: list[Path]) -> list[Path]:
    """Expand files/folders into a sorted list of agent instruction files."""
    found: set[Path] = set()
    for p in paths:
        if p.is_file():
            found.add(p.resolve())
        elif p.is_dir():
            for name in INSTRUCTION_FILENAMES:
                for candidate in p.rglob(name):
                    if any(part in SKIP_DIRS for part in candidate.relative_to(p).parts):
                        continue
                    if candidate.is_file():
                        found.add(candidate.resolve())
    return sorted(found)
