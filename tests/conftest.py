from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture
def project(tmp_path: Path) -> Callable[..., Path]:
    """Build a throwaway project and return the path of its AGENTS.md."""

    def _make(content: str, files: dict[str, str] | None = None, name: str = "AGENTS.md") -> Path:
        (tmp_path / ".git").mkdir(exist_ok=True)
        for rel, text in (files or {}).items():
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("/"):
                f.mkdir(parents=True, exist_ok=True)
            else:
                f.write_text(text, encoding="utf-8")
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    return _make


GOOD = """# Project

Read @docs/arch.md first.

## Commands

- `npm install`
- `npm test`
- `npm run lint`

## Style

- Always use named exports.
- Handlers live in `src/api/` and `src/api/users.ts`.
"""

GOOD_FILES = {
    "docs/arch.md": "# Arch\n",
    "src/api/users.ts": "",
    "package.json": '{"scripts": {"test": "jest", "lint": "eslint ."}}',
    "package-lock.json": "{}",
}
