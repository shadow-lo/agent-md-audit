"""The audit rules. Each rule takes a Doc and yields Findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Optional
from urllib.parse import unquote

from .doc import Doc

DEFAULT_MAX_LINES = 200
MAX_IMPORT_DEPTH = 5  # agents that support @imports stop after 5 hops

KNOWN_EXTS = {
    "md", "mdx", "txt", "rst", "json", "jsonc", "yaml", "yml", "toml", "ini", "cfg", "conf", "env", "lock",
    "py", "pyi", "ipynb", "js", "mjs", "cjs", "jsx", "ts", "tsx", "mts", "cts", "vue", "svelte", "astro",
    "go", "rs", "java", "kt", "kts", "swift", "rb", "php", "cs", "fs", "c", "h", "cc", "cpp", "hpp", "m", "mm",
    "scala", "clj", "ex", "exs", "erl", "hs", "lua", "dart", "r", "jl", "zig", "nim", "sol",
    "sh", "bash", "zsh", "fish", "ps1", "bat", "sql", "prisma", "graphql", "gql", "proto",
    "html", "htm", "css", "scss", "sass", "less", "xml", "csv", "tsv", "svg", "png", "jpg", "jpeg", "gif", "webp",
    "dockerfile", "tf", "tfvars", "hcl", "nix", "gradle", "sbt", "csproj", "sln",
}
WELL_KNOWN_FILES = {"Makefile", "Dockerfile", "Justfile", "Procfile", "Gemfile", "Rakefile", "Brewfile", "Pipfile", "Vagrantfile", "Caddyfile"}

MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
LINE_SUFFIX_RE = re.compile(r":\d+(?::\d+)?$|#L\d+(?:-L?\d+)?$")
PATH_BAD_CHARS = set(" \t*?{}[]<>$|=(),;'\"\\!^&%")
IMPORT_RE = re.compile(r"(?:^|(?<=[\s(]))@([^\s`)]+)")

RUN_SCRIPT_RE = re.compile(r"\b(npm|pnpm|yarn|bun)\s+run\s+([A-Za-z0-9][\w:.\-]*)")
SHORT_SCRIPT_RE = re.compile(r"(?:^|[\s;&|(])(npm|pnpm|yarn)\s+([A-Za-z0-9][\w:.\-]*)")
NPM_SHORTHANDS = {"test", "t", "tst", "start", "stop", "restart"}
PM_BUILTINS = {
    "add", "install", "i", "ci", "update", "up", "upgrade", "remove", "rm", "uninstall", "un", "link", "ln", "unlink",
    "import", "rebuild", "rb", "prune", "fetch", "patch", "patch-commit", "exec", "dlx", "create", "init", "publish",
    "pack", "store", "list", "ls", "ll", "la", "outdated", "why", "audit", "env", "setup", "config", "c", "get", "set",
    "dedupe", "licenses", "server", "deploy", "recursive", "help", "root", "bin", "cache", "self-update", "info",
    "view", "version", "versions", "workspace", "workspaces", "global", "login", "logout", "whoami", "owner", "tag",
    "dist-tag", "run", "node", "plugin", "constraints", "explain", "npm", "dedup", "approve-builds", "catalog",
    "doctor", "search", "s", "docs", "home", "bugs", "repo", "fund", "query", "sbom", "shrinkwrap", "star", "token",
    "access", "adduser", "team", "hook", "profile", "org", "completion", "edit", "explore", "pkg", "x", "check",
}
MAKE_RE = re.compile(r"(?:^|[\s;&|(])make\s+([^;&|)\n]+)")
PM_USE_RE = re.compile(r"(?:^|[\s;&|(])(npm|pnpm|pnpx|yarn|bun|bunx)\s+[A-Za-z@\-]")
LOCKFILES = {"package-lock.json": "npm", "npm-shrinkwrap.json": "npm", "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lockb": "bun", "bun.lock": "bun"}

SECRET_PATTERNS = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe secret key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]
HOME_PATH_RE = re.compile(r"(?<![\w.])(?:/Users/|/home/)(?!user/|username/|you/|me/|<)[A-Za-z0-9._-]+/|\b[A-Za-z]:\\Users\\(?!<)[^\\\s]+\\", re.I)

BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
NEGATIVE_RE = re.compile(r"^(?:you\s+)?(?:must\s+not|mustn't|should\s+not|shouldn't|never|do\s+not|don't|dont|avoid|stop)\s+(.+)$")
POSITIVE_PREFIX_RE = re.compile(r"^(?:you\s+)?(?:always|must|should|please|make\s+sure\s+(?:to|you)|be\s+sure\s+to|remember\s+to)\s+")
LABEL_RE = re.compile(r"^(?:important|note|rule|tip|warning|nb)\s*:\s*")
CLAUSE_SPLIT_RE = re.compile(r"\s+(?:because|since|so that|unless|except|when|if)\s+|\s+[-–—]\s+|[,;:(]")
ARTICLE_RE = re.compile(r"\b(?:a|an|the)\b")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Options:
    max_lines: int = DEFAULT_MAX_LINES


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    path: Path
    line: int = 1


@dataclass(frozen=True)
class Rule:
    code: str
    severity: Severity
    summary: str
    check: Callable[[Doc, "Rule", Options], Iterator[Finding]]

    def finding(self, doc: Doc, message: str, line: int = 1) -> Finding:
        return Finding(self.code, self.severity, message, doc.path, line)


# --- referenced paths ------------------------------------------------------------

def _looks_like_path(s: str, doc: Doc) -> bool:
    if not s or len(s) > 200 or any(c in PATH_BAD_CHARS for c in s):
        return False
    if s.startswith(("-", "@", "~", "/", "#")):
        return False
    if s.startswith(".") and not s.startswith(("./", "../")) and not s[1:2].isalnum():
        return False
    if "://" in s or s.startswith(("mailto:", "www.")):
        return False
    if re.fullmatch(r"v?\d+(\.\d+)+\w*", s):  # version numbers
        return False
    name = s.rstrip("/").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name[1:] else ""
    has_ext = ext in KNOWN_EXTS or name in WELL_KNOWN_FILES
    if s.startswith(("./", "../")):
        return True
    if "/" in s:
        first = s.split("/", 1)[0]
        return has_ext or s.endswith("/") or any((d / first).exists() for d in doc.base_dirs)
    return has_ext


def _path_candidates(doc: Doc) -> Iterator[tuple[int, str]]:
    for lineno, line in doc.text_lines():
        for m in MD_LINK_RE.finditer(line):
            target = m.group(1)
            if "://" in target or target.startswith(("mailto:", "#", "/", "tel:")):
                continue
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if target:
                yield lineno, target
        for m in INLINE_CODE_RE.finditer(line):
            raw = m.group(2).strip()
            raw = LINE_SUFFIX_RE.sub("", raw)
            if _looks_like_path(raw, doc):
                yield lineno, raw


def check_paths(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    seen: set[str] = set()
    for lineno, target in _path_candidates(doc):
        if target in seen or doc.is_ignored(target):
            continue
        seen.add(target)
        if not doc.path_exists(target):
            yield rule.finding(doc, f"mentions '{target}', which does not exist in the project", lineno)


# --- @imports --------------------------------------------------------------------

def _imports_in(lines: list[tuple[int, str]]) -> Iterator[tuple[int, str]]:
    for lineno, line in lines:
        for m in IMPORT_RE.finditer(line):
            target = m.group(1).rstrip(".,;:!?'\"")
            if "/" not in target and "." not in target:
                continue  # an @mention, not an import
            if target.startswith("@") or "@" in target:
                continue
            yield lineno, target


def _resolve_import(base: Path, target: str) -> Optional[Path]:
    if target.startswith("~"):
        return None  # machine-specific; AM105 covers home paths
    return (base / target).resolve()


def check_imports(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    for lineno, target in _imports_in(list(doc.prose_lines())):
        resolved = _resolve_import(doc.folder, target)
        if resolved is not None and not resolved.exists():
            yield rule.finding(doc, f"imports '@{target}', but {target} does not exist", lineno)


def _file_imports(path: Path) -> list[Path]:
    from .doc import load_doc

    try:
        d = load_doc(path)
    except (OSError, UnicodeError):
        return []
    out = []
    for _, target in _imports_in(list(d.prose_lines())):
        r = _resolve_import(d.folder, target)
        if r is not None and r.is_file():
            out.append(r)
    return out


def check_import_chain(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    reported_cycle = False
    deepest: list[Path] = []

    def walk(path: Path, chain: list[Path]) -> None:
        nonlocal reported_cycle, deepest
        if len(chain) > MAX_IMPORT_DEPTH + 1:
            if len(chain) > len(deepest):
                deepest = list(chain)
            return
        if len(chain) > len(deepest):
            deepest = list(chain)
        for child in _file_imports(path):
            if child in chain:
                if not reported_cycle:
                    reported_cycle = True
                    cycle = " -> ".join(p.name for p in chain[chain.index(child):] + [child])
                    findings.append(rule.finding(doc, f"circular @import: {cycle}"))
                continue
            walk(child, chain + [child])

    findings: list[Finding] = []
    walk(doc.path, [doc.path])
    yield from findings
    hops = len(deepest) - 1
    if hops > MAX_IMPORT_DEPTH:
        chain = " -> ".join(p.name for p in deepest[: MAX_IMPORT_DEPTH + 2])
        yield rule.finding(doc, f"@import chain is more than {MAX_IMPORT_DEPTH} hops deep, so agents stop following it: {chain}")


# --- commands that must exist ------------------------------------------------------

def _package_scripts(doc: Doc) -> Optional[set[str]]:
    pkg = doc.find_project_file("package.json")
    if pkg is None:
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return set(scripts) if isinstance(scripts, dict) else set()


def check_scripts(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    scripts = _package_scripts(doc)
    if scripts is None:
        return
    seen: set[str] = set()

    def report(lineno: int, cmd: str, name: str) -> Iterator[Finding]:
        if name in scripts or name in seen:
            return
        seen.add(name)
        yield rule.finding(doc, f"'{cmd}' runs script '{name}', but package.json has no such script", lineno)

    for lineno, line in doc.lines_all():
        for m in RUN_SCRIPT_RE.finditer(line):
            yield from report(lineno, m.group(0), m.group(2))
    for lineno, code in doc.code_snippets():
        for m in SHORT_SCRIPT_RE.finditer(code):
            pm, name = m.group(1), m.group(2)
            if pm == "npm":
                if name in NPM_SHORTHANDS:
                    canonical = {"t": "test", "tst": "test"}.get(name, name)
                    if canonical in ("stop", "restart") or canonical in scripts:
                        continue
                    yield from report(lineno, f"npm {name}", canonical)
                continue
            if name in PM_BUILTINS or name.startswith("@"):
                continue
            yield from report(lineno, f"{pm} {name}", name)


def _make_targets(makefile: Path) -> tuple[set[str], bool]:
    """Targets defined in the Makefile, and whether it has includes or pattern rules
    (which make the target list impossible to know statically)."""
    targets: set[str] = set()
    opaque = False
    for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
        if re.match(r"^-?s?include\s", line):
            opaque = True
        m = re.match(r"^([^\s:#=][^:=]*?)\s*::?(?!=)", line)
        if m:
            for t in m.group(1).split():
                if "%" in t:
                    opaque = True
                targets.add(t)
    return targets, opaque


def check_make_targets(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    mk = doc.find_project_file("GNUmakefile", "makefile", "Makefile")
    if mk is None:
        return
    targets, opaque = _make_targets(mk)
    if opaque:
        return
    seen: set[str] = set()
    for lineno, code in doc.code_snippets():
        for m in MAKE_RE.finditer(code):
            for word in m.group(1).split():
                if word.startswith("-") or "=" in word or word.startswith(("#", "$", "<")):
                    if word.startswith("#"):
                        break
                    continue
                word = word.strip("`'\"")
                if not re.fullmatch(r"[\w./-]+", word) or word in targets or word in seen:
                    continue
                seen.add(word)
                yield rule.finding(doc, f"'make {word}' is not a target in {mk.name}", lineno)


# --- secrets -------------------------------------------------------------------------

def check_secrets(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    for lineno, line in doc.lines_all():
        for label, regex in SECRET_PATTERNS:
            m = regex.search(line)
            if m:
                token = m.group(0)
                shown = token[:8] + "…" if len(token) > 12 else token
                yield rule.finding(doc, f"looks like {'an' if label[0] in 'AEIOU' else 'a'} {label} ({shown}); instruction files are usually committed, so move it to an env var", lineno)
                break


# --- size and structure --------------------------------------------------------------

def check_length(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    n = len(doc.lines)
    if n > opts.max_lines:
        tokens = len(doc.text) // 4
        yield rule.finding(
            doc,
            f"{n} lines (~{tokens:,} tokens) are loaded into every session; keep it under {opts.max_lines} and move detail into @imported or linked files",
            opts.max_lines + 1,
        )


def check_empty_sections(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    heads = list(doc.headings())
    for idx, (lineno, level, title) in enumerate(heads):
        end = len(doc.lines) + 1
        for next_line, next_level, _ in heads[idx + 1 :]:
            end = next_line
            break
        body = [doc.lines[i] for i in range(lineno, end - 1)]
        has_child = idx + 1 < len(heads) and heads[idx + 1][1] > level
        if not any(line.strip() for line in body) and not has_child:
            yield rule.finding(doc, f"section '{title}' is empty", lineno)


def check_home_paths(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    for lineno, line in doc.lines_all():
        m = HOME_PATH_RE.search(line)
        if m:
            yield rule.finding(doc, f"'{m.group(0)}…' is a path on one person's machine; use a project-relative path or ~", lineno)


# --- rules that contradict or repeat each other ----------------------------------------

def _normalize(sentence: str) -> str:
    s = sentence.lower().replace("\u2019", "'").replace("`", "").replace("*", "").replace("_", " ")
    s = LABEL_RE.sub("", s.strip())
    s = re.sub(r"[^\w\s./+'-]", " ", s)
    s = ARTICLE_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def _directives(doc: Doc) -> Iterator[tuple[int, str, bool]]:
    """(lineno, key, negative) for each instruction-like sentence outside code."""
    for lineno, line in doc.text_lines():
        if not line.strip() or line.lstrip().startswith(("#", ">", "|", "<!--")):
            continue
        text = BULLET_RE.sub("", line)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            s = _normalize(sentence)
            if not s:
                continue
            neg = NEGATIVE_RE.match(s)
            if neg:
                body, negative = neg.group(1), True
                if s.startswith("avoid"):
                    body = "use " + body
            else:
                body, negative = POSITIVE_PREFIX_RE.sub("", s), False
            key = CLAUSE_SPLIT_RE.split(body, 1)[0].strip(" .")
            if len(key.split()) >= 2:
                yield lineno, key, negative


def check_conflicts(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    first: dict[tuple[str, bool], int] = {}
    reported: set[str] = set()
    for lineno, key, negative in _directives(doc):
        other = first.get((key, not negative))
        if other is not None and key not in reported:
            reported.add(key)
            yield rule.finding(doc, f"contradicts line {other}: one says to '{key}', the other says not to", lineno)
        first.setdefault((key, negative), lineno)


def check_duplicates(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    first: dict[str, int] = {}
    for lineno, line in doc.text_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "<!--")):
            continue
        key = _normalize(BULLET_RE.sub("", line))
        if len(key.split()) < 4:
            continue
        if key in first:
            yield rule.finding(doc, f"repeats line {first[key]}", lineno)
        else:
            first[key] = lineno


def check_package_manager(doc: Doc, rule: Rule, opts: Options) -> Iterator[Finding]:
    used: dict[str, int] = {}
    for lineno, code in doc.code_snippets():
        for m in PM_USE_RE.finditer(code):
            pm = {"pnpx": "pnpm", "bunx": "bun"}.get(m.group(1), m.group(1))
            used.setdefault(pm, lineno)
    if not used:
        return
    if len(used) > 1:
        where = ", ".join(f"{pm} (line {ln})" for pm, ln in sorted(used.items(), key=lambda kv: kv[1]))
        yield rule.finding(doc, f"mixes package managers: {where}", sorted(used.values())[1])
        return
    (pm, lineno), = used.items()
    lock = doc.find_project_file(*LOCKFILES)
    if lock is not None and LOCKFILES[lock.name] != pm:
        yield rule.finding(doc, f"says to use {pm}, but the project has {lock.name} ({LOCKFILES[lock.name]})", lineno)


RULES: list[Rule] = [
    Rule("AM001", Severity.ERROR, "file and folder paths it mentions exist", check_paths),
    Rule("AM002", Severity.ERROR, "@imports point at files that exist", check_imports),
    Rule("AM003", Severity.ERROR, "npm/pnpm/yarn/bun scripts it runs exist in package.json", check_scripts),
    Rule("AM004", Severity.ERROR, "make targets it runs exist in the Makefile", check_make_targets),
    Rule("AM005", Severity.ERROR, "no API keys, tokens or private keys", check_secrets),
    Rule("AM101", Severity.WARNING, f"under {DEFAULT_MAX_LINES} lines (configurable with --max-lines)", check_length),
    Rule("AM102", Severity.WARNING, "no rules that contradict each other", check_conflicts),
    Rule("AM103", Severity.WARNING, "one package manager, matching the lockfile", check_package_manager),
    Rule("AM104", Severity.WARNING, "no repeated rules", check_duplicates),
    Rule("AM105", Severity.WARNING, "no paths from one person's machine (/Users/name, /home/name, C:\\Users\\name)", check_home_paths),
    Rule("AM106", Severity.WARNING, "no empty sections", check_empty_sections),
    Rule("AM107", Severity.WARNING, f"@imports are not circular and at most {MAX_IMPORT_DEPTH} hops deep", check_import_chain),
]


def audit(doc: Doc, ignore: frozenset[str] = frozenset(), options: Options = Options()) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        if rule.code in ignore:
            continue
        findings.extend(rule.check(doc, rule, options))
    return sorted(findings, key=lambda f: (f.line, f.code))
