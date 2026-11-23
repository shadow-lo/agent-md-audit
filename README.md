<div align="center">

# 🩺 agent-md-audit

### Your AI agent believes every word of `AGENTS.md`. Make sure those words are still true.

**An offline linter for AI agent instruction files. It catches dead paths, renamed scripts,<br>contradicting rules, leaked keys and token bloat before your agent acts on them.**

[![CI](https://github.com/shadow-lo/agent-md-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/shadow-lo/agent-md-audit/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![offline](https://img.shields.io/badge/runs-100%25%20offline-blueviolet)
![license](https://img.shields.io/badge/license-MIT-green)

[Quick start](#-quick-start) · [What it checks](#-what-it-checks) · [CI](#-use-it-in-ci) · [How it stays quiet](#-how-it-stays-quiet)

</div>

---

## 🤔 Why

Coding agents read an instruction file at the start of every session and treat it as ground truth about your project.
Those files rot quietly:

- 📁 `src/components/` moved to `app/ui/` six months ago, and the agent keeps looking for it.
- 🏃 `npm run test:unit` was renamed to `npm test`, so the agent runs a command that fails, then "fixes" it.
- ⚔️ Line 13 says *"Always use default exports"*, and line 40 says *"Never use default exports"*.
- 🔑 Someone pasted a real API key "just for staging".
- 🐘 The file grew to 400 lines, and every one of them costs tokens on every request.

The agent can't tell stale from current. **agent-md-audit** checks the file against the real project, so you can.

<br>

```text
$ agent-md-audit examples

✓ examples/good/AGENTS.md
✗ examples/messy/AGENTS.md
     3  AM002  imports '@docs/old-setup.md', but docs/old-setup.md does not exist
     7  AM003  'npm run test:unit' runs script 'test:unit', but package.json has no such script
     8  AM003  'yarn build' runs script 'build', but package.json has no such script
     8  AM103  mixes package managers: npm (line 7), yarn (line 8)
     9  AM004  'make deploy' is not a target in Makefile
    14  AM102  contradicts line 13: one says to 'use default exports', the other says not to
    15  AM001  mentions 'src/components/', which does not exist in the project
    17  AM104  repeats line 16
    21  AM005  looks like an AWS access key (AKIAIOSF…); instruction files are usually committed, so move it to an env var
    22  AM105  '/Users/alice/…' is a path on one person's machine; use a project-relative path or ~
    24  AM106  section 'TODO' is empty

2 file(s) checked, 6 error(s), 5 warning(s)
```

## ✨ Highlights

| | |
|---|---|
| 🔌 **Zero dependencies** | Pure Python standard library. Nothing to audit but the code itself. |
| 📴 **Fully offline** | No API keys, no network calls, no model in the loop. Same input, same output. |
| 🧭 **Project aware** | Reads `package.json`, `Makefile`, lockfiles and `.gitignore` to check claims against reality. |
| 🤫 **Low noise** | Built to skip anything it can't prove. A finding is worth reading. |
| 🤖 **CI native** | Inline pull request annotations, JSON output and a ready-made GitHub Action. |

## 📂 Supported files

It finds every one of these under the folders you point it at, skipping `node_modules`, virtualenvs and build output:

| File | Used by |
|---|---|
| `AGENTS.md`, `AGENTS.override.md` | the open AGENTS.md convention (Codex, Jules, Amp, Cursor, Zed and others) |
| `CLAUDE.md`, `CLAUDE.local.md` | Anthropic's coding agent |
| `GEMINI.md` | Gemini CLI |
| `.github/copilot-instructions.md` | GitHub Copilot |
| `.cursorrules`, `.windsurfrules`, `.clinerules` | Cursor, Windsurf, Cline |

Monorepo with one file per package? Point it at the root and every file is checked against its own folder.

## 🚀 Quick start

```bash
pip install git+https://github.com/shadow-lo/agent-md-audit
agent-md-audit
```

That's it. Run it from your repository root.

```bash
agent-md-audit                       # every instruction file under the current folder
agent-md-audit path/to/AGENTS.md     # one file
agent-md-audit --strict              # fail on warnings too
agent-md-audit --max-lines 150       # tighten the length budget (default 200)
agent-md-audit --ignore AM101,AM104  # skip rules
agent-md-audit --format json         # machine-readable output
agent-md-audit --format github       # pull request annotations
agent-md-audit --list-rules          # every rule, one line each
```

| Exit code | Meaning |
|:---:|---|
| `0` | clean, or warnings only |
| `1` | errors found, or warnings with `--strict` |
| `2` | nothing to check (no files, or a path that doesn't exist) |

## 🔍 What it checks

### Errors: provably wrong

| Code | Rule | Example it catches |
|---|---|---|
| **AM001** | Paths in links and `inline code` exist | ``Handlers live in `src/api/` `` after `src/api/` was deleted |
| **AM002** | `@path` imports point at real files | `See @docs/old-setup.md` |
| **AM003** | `npm run x`, `pnpm x`, `yarn x`, `bun run x` exist in `package.json` | `npm run test:unit` when only `test` exists |
| **AM004** | `make x` is a real Makefile target | `make deploy` with no `deploy:` target |
| **AM005** | No secrets: AWS, GitHub, OpenAI, Anthropic, Slack, Google, Stripe keys and private keys | `AKIA…`, `ghp_…`, `-----BEGIN PRIVATE KEY-----` |

### Warnings: probably a problem

| Code | Rule | Example it catches |
|---|---|---|
| **AM101** | The file stays under 200 lines (`--max-lines`) | a 400-line file loaded into every session |
| **AM102** | No rule contradicts another | *"Always use tabs"* … *"Don't use tabs"* |
| **AM103** | One package manager, and it matches the lockfile | `yarn add` in the docs, `pnpm-lock.yaml` in the repo |
| **AM104** | No rule is written twice | the same bullet pasted into two sections |
| **AM105** | No paths from one person's machine | `/Users/alice/…`, `/home/bob/…`, `C:\Users\carol\…` |
| **AM106** | No empty sections | `## TODO` with nothing under it |
| **AM107** | `@imports` aren't circular and stay within 5 hops | `a.md → b.md → a.md` |

## 🤖 Use it in CI

Findings appear as annotations right on the pull request diff.

```yaml
# .github/workflows/agent-instructions.yml
name: Audit agent instructions
on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: shadow-lo/agent-md-audit@main
        with:
          strict: "true"        # optional: fail on warnings too
          # paths: "AGENTS.md"  # optional: default is the whole repository
          # ignore: "AM101"     # optional: rules to skip
          # max-lines: "300"    # optional: length budget
```

<details>
<summary><b>pre-commit hook</b></summary>

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: agent-md-audit
        name: agent-md-audit
        entry: agent-md-audit
        language: system
        pass_filenames: false
        files: (AGENTS|CLAUDE|GEMINI)(\.local|\.override)?\.md$|copilot-instructions\.md$|\.(cursor|windsurf|cline)rules$
```

</details>

<details>
<summary><b>JSON output</b></summary>

```json
[
  {
    "path": "examples/messy/AGENTS.md",
    "findings": [
      {
        "code": "AM002",
        "severity": "error",
        "line": 3,
        "message": "imports '@docs/old-setup.md', but docs/old-setup.md does not exist"
      }
    ]
  }
]
```

</details>

## 🤫 How it stays quiet

A linter that cries wolf gets turned off, so every rule is biased toward silence:

- **Paths** resolve from the file's own folder and from the project root (the nearest folder with `.git`).
  A partial path like `components/Button.tsx` passes if it exists anywhere in the tree.
- **Things that only look like paths** are skipped: MIME types (`application/json`), method calls (`user.save()`),
  flags, globs, URLs, version numbers and import aliases such as `@/lib/utils`.
- **Ignored files** never count as missing: anything in `.gitignore`, plus `.env` files.
- **Code blocks** aren't checked for paths, but the commands inside them are checked.
- **Scripts and make targets** are only checked when a `package.json` or `Makefile` exists. Makefiles with `include` or pattern rules are skipped, since their targets can't be known statically.
- **`@mentions` and emails** are not imports. `@~/…` imports point at someone's home folder and are left alone.
- **Contradictions** need the same instruction with opposite polarity. *"Use semicolons"* and *"Don't use semicolons in generated files"* is a scoped exception, not a conflict.

## 🛠️ Development

```bash
git clone https://github.com/shadow-lo/agent-md-audit
cd agent-md-audit
pip install -e ".[dev]"
pytest -q
```

Each rule is a small function in [`src/agent_md_audit/rules.py`](src/agent_md_audit/rules.py) with a test that fires and a test that stays quiet.
New rule ideas and false-positive reports are very welcome as issues.

## 📄 License

[MIT](LICENSE)
