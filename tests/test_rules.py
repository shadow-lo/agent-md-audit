from pathlib import Path

from agent_md_audit.doc import discover, load_doc
from agent_md_audit.rules import Options, audit

from conftest import GOOD, GOOD_FILES


def codes(path: Path, **kw) -> list[str]:
    return [f.code for f in audit(load_doc(path), **kw)]


def messages(path: Path) -> list[str]:
    return [f.message for f in audit(load_doc(path))]


def test_good_file_is_clean(project):
    assert codes(project(GOOD, GOOD_FILES)) == []


# --- AM001 paths ---------------------------------------------------------------

def test_missing_backtick_path(project):
    p = project("Config lives in `config/app.yaml`.\n")
    assert codes(p) == ["AM001"]


def test_missing_markdown_link(project):
    p = project("See [the guide](docs/guide.md#setup).\n")
    assert codes(p) == ["AM001"]
    assert "docs/guide.md" in messages(p)[0]


def test_existing_paths_pass(project):
    p = project("See [guide](docs/guide.md), `docs/guide.md:12` and `docs/`.\n", {"docs/guide.md": ""})
    assert codes(p) == []


def test_partial_path_found_deeper_in_tree(project):
    p = project("Buttons are in `components/Button.tsx`; see `Button.tsx`.\n", {"src/components/Button.tsx": ""})
    assert codes(p) == []


def test_non_paths_are_ignored(project):
    text = (
        "Send `application/json`, call `user.save()`, set `--verbose`, run `npm run x y`,\n"
        "use `v1.2.3`, `foo/*.ts`, `https://example.com/a.md` and [site](https://x.dev).\n"
    )
    assert "AM001" not in codes(project(text))


def test_paths_in_code_blocks_are_ignored(project):
    assert codes(project("```\ncat missing/file.md\n```\n")) == []


def test_gitignored_paths_are_skipped(project):
    p = project("Copy `.env.example` to `.env`, output goes to `out/report.json`.\n", {".env.example": "", ".gitignore": "out/\n"})
    assert codes(p) == []


def test_config_dir_file_resolves_from_project_root(project):
    p = project("See `src/main.py`.\n", {"src/main.py": ""}, name=".github/copilot-instructions.md")
    assert codes(p) == []


# --- AM002 / AM107 imports ---------------------------------------------------------

def test_missing_import(project):
    p = project("Read @docs/missing.md and email me at a@b.com, ping @alice.\n")
    assert codes(p) == ["AM002"]


def test_import_in_code_is_ignored(project):
    assert codes(project("Install `@types/node` and run:\n\n```\nnpm i @scope/pkg\n```\n")) == []


def test_home_import_is_skipped(project):
    assert codes(project("@~/.config/agents/prefs.md\n")) == []


def test_circular_import(project):
    p = project("@a.md\n", {"a.md": "@b.md\n", "b.md": "@a.md\n"})
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM107"]
    assert "circular" in found[0].message


def test_import_chain_too_deep(project):
    files = {f"d{i}.md": f"@d{i + 1}.md\n" for i in range(1, 7)}
    files["d7.md"] = "end\n"
    p = project("@d1.md\n", files)
    found = [f for f in audit(load_doc(p)) if f.code == "AM107"]
    assert found and "hops deep" in found[0].message


def test_import_chain_within_limit(project):
    p = project("@d1.md\n", {"d1.md": "@d2.md\n", "d2.md": "end\n"})
    assert codes(p) == []


# --- AM003 scripts ---------------------------------------------------------------

PKG = {"package.json": '{"scripts": {"test": "jest", "build": "tsc"}}'}


def test_missing_npm_run_script(project):
    p = project("Run `npm run lint`.\n", PKG)
    assert codes(p) == ["AM003"]
    assert "'lint'" in messages(p)[0]


def test_pnpm_shorthand_script(project):
    p = project("```sh\npnpm install\npnpm build\npnpm typecheck\n```\n", {**PKG, "pnpm-lock.yaml": ""})
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM003"]
    assert "typecheck" in found[0].message


def test_npm_test_needs_test_script(project):
    p = project("Run `npm test`.\n", {"package.json": '{"scripts": {}}'})
    assert codes(p) == ["AM003"]


def test_no_package_json_means_no_script_check(project):
    assert codes(project("Run `npm run whatever`.\n")) == []


def test_prose_shorthand_is_not_a_command(project):
    assert codes(project("We moved from yarn or npm to pnpm.\n", PKG)) == []


# --- AM004 make ------------------------------------------------------------------

def test_missing_make_target(project):
    p = project("Run `make lint test` then `make deploy ENV=prod`.\n", {"Makefile": "lint:\n\truff .\ntest: lint\n\tpytest\n"})
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM004"]
    assert "deploy" in found[0].message


def test_make_with_includes_is_skipped(project):
    p = project("Run `make deploy`.\n", {"Makefile": "include other.mk\nlint:\n\truff .\n"})
    assert codes(p) == []


# --- AM005 secrets ---------------------------------------------------------------

def test_secret_detected(project):
    p = project("Token: ghp_" + "a" * 36 + "\n")
    assert codes(p) == ["AM005"]
    assert "a" * 36 not in messages(p)[0]


def test_private_key_in_code_block(project):
    assert codes(project("```\n-----BEGIN RSA PRIVATE KEY-----\n```\n")) == ["AM005"]


# --- AM101 length ------------------------------------------------------------------

def test_too_long(project):
    p = project("".join(f"line {i}\n" for i in range(250)))
    assert codes(p) == ["AM101"]
    assert codes(p, options=Options(max_lines=300)) == []


# --- AM102 conflicts --------------------------------------------------------------

def test_always_vs_never(project):
    p = project("- Always use semicolons.\n- Run the tests.\n- **Never** use semicolons.\n")
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM102"]
    assert found[0].line == 3 and "line 1" in found[0].message


def test_imperative_vs_dont(project):
    assert codes(project("Use tabs for indentation.\n\nDon't use tabs for indentation.\n")) == ["AM102"]


def test_avoid_counts_as_negative(project):
    assert codes(project("- Use `any` in TypeScript when needed.\n- Avoid `any` in TypeScript.\n")) == ["AM102"]


def test_different_rules_do_not_conflict(project):
    assert codes(project("- Always use pnpm commands.\n- Never use npm commands.\n")) == []


def test_scoped_exception_is_not_a_conflict(project):
    assert codes(project("- Use semicolons.\n- Don't use semicolons in generated files.\n")) == []


# --- AM103 package managers ---------------------------------------------------------

def test_mixed_package_managers(project):
    assert codes(project("```\nnpm install\nyarn add lodash\n```\n")) == ["AM103"]


def test_package_manager_vs_lockfile(project):
    p = project("Install with `pnpm install`.\n", {"yarn.lock": ""})
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM103"]
    assert "yarn.lock" in found[0].message


def test_npx_alongside_pnpm_is_fine(project):
    assert codes(project("```\npnpm install\nnpx prettier --write .\n```\n", {"pnpm-lock.yaml": ""})) == []


# --- AM104 duplicates ------------------------------------------------------------------

def test_duplicate_rule(project):
    p = project("- Write a test for every fix.\n- Other.\n* write a test for every fix\n")
    found = audit(load_doc(p))
    assert [f.code for f in found] == ["AM104"]
    assert found[0].line == 3


def test_short_repeats_are_fine(project):
    assert codes(project("## Notes\n\n- None yet.\n\n## More\n\n- None yet.\n")) == []


# --- AM105 home paths -------------------------------------------------------------------

def test_home_path(project):
    assert codes(project("Logs: /Users/alice/app/logs\n")) == ["AM105"]
    assert codes(project("Logs: C:\\Users\\bob\\app\n")) == ["AM105"]


def test_placeholder_home_path_ok(project):
    assert codes(project("e.g. /home/user/project or /Users/<you>/x\n")) == []


# --- AM106 empty sections -----------------------------------------------------------------

def test_empty_section(project):
    p = project("# Title\n\n## Empty\n\n## Full\n\ntext\n\n## Trailing\n")
    found = audit(load_doc(p))
    assert [(f.code, f.line) for f in found] == [("AM106", 3), ("AM106", 9)]


def test_parent_with_subsections_is_not_empty(project):
    assert codes(project("# Title\n\n## Sub\n\ntext\n")) == []


def test_hash_in_code_block_is_not_heading(project):
    assert codes(project("## Shell\n\n```\n# comment\n```\n")) == []


# --- ignore / discovery ---------------------------------------------------------------------

def test_ignore(project):
    p = project("Config lives in `config/app.yaml`.\n")
    assert codes(p, ignore=frozenset({"AM001"})) == []


def test_discover_finds_all_memory_files(project, tmp_path):
    project("x\n")
    project("x\n", name="CLAUDE.md")
    project("x\n", name="GEMINI.md")
    project("x\n", name="web/AGENTS.md")
    project("x\n", name=".github/copilot-instructions.md")
    project("x\n", name="notes/README.md")
    project("x\n", name="node_modules/pkg/AGENTS.md")
    found = {p.relative_to(tmp_path.resolve()).as_posix() for p in discover([tmp_path])}
    assert found == {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "web/AGENTS.md", ".github/copilot-instructions.md"}
