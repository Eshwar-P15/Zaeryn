"""Pre-commit safety net for the staged diff.

Scans `git diff --cached` for the classic "oops, committed something sensitive"
patterns: real .env files, SQLite databases, credential filenames, secret-shaped
strings, absolute local paths, large binary blobs, and debugging artifacts.

Designed to run as a `pre-commit` local hook before `ruff`. Stdlib only, fast
enough (< 1 s typical) that it doesn't slow the commit loop.

Usage:
    python scripts/check_staged_safety.py     # checks current staged set
    pytest tests/test_safety_check.py         # unit-tests the rules
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# -- Issue + Warning data shape -----------------------------------------------


class Issue(NamedTuple):
    category: str
    location: str  # filepath or "filepath:line"
    detail: str


# -- Filename rules ------------------------------------------------------------

# .env.example / .env.sample / .env.template are conventional checked-in templates.
_ENV_ALLOWLIST = frozenset({".env.example", ".env.sample", ".env.template"})

_SQLITE_RE = re.compile(r"\.(db|sqlite|sqlite3)$", re.IGNORECASE)
_ENV_RE = re.compile(r"(^|/)\.env(\..+)?$")
_CREDENTIAL_FILENAME_RE = re.compile(
    r"(^|/)(credentials|secrets|token|tokens)\.(json|txt|yaml|yml)$", re.IGNORECASE
)
_PRIVATE_KEY_EXT_RE = re.compile(r"\.(pem|key|p12|pfx)$", re.IGNORECASE)
_SSH_PRIVATE_RE = re.compile(r"(^|/)id_(rsa|ed25519|dsa|ecdsa)(\.|$)")
_AWS_CREDS_RE = re.compile(r"(^|/)\.aws/credentials$")
_SSH_DIR_RE = re.compile(r"(^|/)\.ssh/")


def check_filenames(files: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for f in files:
        basename = f.rsplit("/", 1)[-1]
        if basename in _ENV_ALLOWLIST:
            continue
        if _ENV_RE.search(f):
            issues.append(Issue("filename", f, "looks like a real .env file"))
            continue
        if _SQLITE_RE.search(f):
            issues.append(Issue("filename", f, "SQLite database staged"))
            continue
        if _CREDENTIAL_FILENAME_RE.search(f):
            issues.append(Issue("filename", f, "credential-shaped filename"))
            continue
        if _PRIVATE_KEY_EXT_RE.search(f) and "public" not in basename.lower():
            issues.append(Issue("filename", f, "private-key file extension"))
            continue
        if _SSH_PRIVATE_RE.search(f):
            issues.append(Issue("filename", f, "SSH private key"))
            continue
        if _AWS_CREDS_RE.search(f) or _SSH_DIR_RE.search(f):
            issues.append(Issue("filename", f, "AWS/SSH credentials path"))
    return issues


# -- File size rule ------------------------------------------------------------


def check_file_sizes(files: list[str], max_bytes: int = 1_000_000) -> list[Issue]:
    issues: list[Issue] = []
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        size = p.stat().st_size
        if size > max_bytes:
            issues.append(Issue("size", f, f"{size:,} bytes exceeds {max_bytes:,}-byte limit"))
    return issues


# -- Secret detection ----------------------------------------------------------

# Self-exclusion: this file and its test will *contain* the patterns by design.
_SELF_FILES = frozenset(
    {
        "scripts/check_staged_safety.py",
        "tests/test_safety_check.py",
    }
)

# Concrete-value patterns. Match on the actual value shape, not just the variable name.
_LITERAL_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub PAT", re.compile(r"\b(ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}\b")),
    ("OpenAI key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9]{32,}\b")),
]

# Assignment pattern. Look for: name [:=]= "real-looking-value".
# Names: generic + project-specific. Case-insensitive.
_SECRET_NAME_RE = (
    r"(?P<name>API_KEY|SECRET(?:_KEY)?|TOKEN|PASSWORD|PASSWD|"
    r"BIRDEYE_API_KEY|HELIUS_API_KEY|NEWSAPI_API_KEY|"
    r"AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID)"
)
# Note `==` is matched as one of [:=] then optional `=` — we just need to detect "name = value".
_ASSIGN_RE = re.compile(
    rf"(?i)\b{_SECRET_NAME_RE}\b\s*[:=]+\s*[\"']?(?P<value>[^\"'\s,)(]{{20,}})",
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "your_key_here",
        "your-key-here",
        "yourkeyhere",
        "replace_me",
        "replaceme",
        "placeholder",
        "xxx",
        "xxxxxx",
        "todo",
        "tbd",
        "...",
        "changeme",
        "change_me",
    }
)


def _is_placeholder_value(value: str) -> bool:
    v = value.strip().strip("\"'").lower()
    if v in _PLACEHOLDER_VALUES:
        return True
    if v.startswith("your") or v.endswith("here") or v.endswith("_here"):
        return True
    # Angle-bracket / curly-brace placeholders: <SOMETHING>, {something}
    if v.startswith(("<", "{", "[")) and v.endswith((">", "}", "]")):
        return True
    # All same char (e.g. "xxxxxxxx", "0000000000")
    return len(set(v)) <= 2


def check_secrets(added_lines: list[tuple[str | None, int, str]]) -> list[Issue]:
    issues: list[Issue] = []
    for filepath, line_no, content in added_lines:
        if filepath in _SELF_FILES:
            continue
        loc = f"{filepath or '?'}:{line_no}"

        for label, pattern in _LITERAL_SECRET_PATTERNS:
            if pattern.search(content):
                issues.append(Issue("secret", loc, f"{label} value detected"))

        m = _ASSIGN_RE.search(content)
        if m:
            value = m.group("value")
            if not _is_placeholder_value(value) and len(value.strip()) >= 20:
                issues.append(
                    Issue(
                        "secret", loc, f"assignment to {m.group('name')} with non-placeholder value"
                    )
                )
    return issues


# -- Local-path detection ------------------------------------------------------

_LOCAL_PATH_PATTERNS = [
    re.compile(r"/home/epala(?:/|\b)"),
    re.compile(r"/mnt/c/"),
    re.compile(r"[A-Z]:\\\\"),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
]

_EXAMPLE_HINTS_RE = re.compile(
    r"\b(example|fake|sample|fixture|placeholder|tmp_path|tmpdir|TODO|TBD|docstring)\b",
    re.IGNORECASE,
)

# Files where absolute local paths are expected by design (and don't represent
# secrets or portability hazards). Scoped to the path check only — these files
# are still subject to secrets, size, and other rules.
_LOCAL_PATH_ALLOWLIST_RE = re.compile(r"^\.claude/.*\.json$")


def check_local_paths(added_lines: list[tuple[str | None, int, str]]) -> list[Issue]:
    issues: list[Issue] = []
    for filepath, line_no, content in added_lines:
        if filepath in _SELF_FILES:
            continue
        if filepath and _LOCAL_PATH_ALLOWLIST_RE.match(filepath):
            continue
        for pattern in _LOCAL_PATH_PATTERNS:
            if pattern.search(content):
                if _EXAMPLE_HINTS_RE.search(content):
                    continue
                loc = f"{filepath or '?'}:{line_no}"
                issues.append(Issue("path", loc, f"local absolute path: {pattern.pattern}"))
                break
    return issues


# -- Debug-artifact warnings ---------------------------------------------------

_PRODUCTION_PRINT_RE = re.compile(r"(?:^|[^.\w])print\s*\(")
_PRODUCTION_EXCLUDED_PREFIXES = ("tests/", "scripts/", "dashboard/")
_FIXME_RE = re.compile(r"#\s*(FIXME|XXX)\b")


def check_debug_artifacts(
    added_lines: list[tuple[str | None, int, str]],
) -> list[Issue]:
    """Returns warnings (presented but non-failing)."""
    warnings: list[Issue] = []
    for filepath, line_no, content in added_lines:
        if not filepath:
            continue
        loc = f"{filepath}:{line_no}"

        is_production = not filepath.startswith(_PRODUCTION_EXCLUDED_PREFIXES)
        if is_production and _PRODUCTION_PRINT_RE.search(content):
            warnings.append(Issue("debug", loc, "print() call in production code"))

        for marker, label in (
            ("breakpoint()", "breakpoint() call"),
            ("import pdb", "import pdb"),
            ("pdb.set_trace()", "pdb.set_trace() call"),
            ("console.log", "console.log call"),
        ):
            if marker in content:
                warnings.append(Issue("debug", loc, label))

        if _FIXME_RE.search(content):
            warnings.append(Issue("debug", loc, "FIXME/XXX comment"))
    return warnings


# -- Diff parsing --------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")
_FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")


def parse_added_lines(diff: str) -> list[tuple[str | None, int, str]]:
    """Yields (filepath, line_no, content) for each added (+) line in a unified diff."""
    out: list[tuple[str | None, int, str]] = []
    current_file: str | None = None
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            m = _FILE_HEADER_RE.match(raw)
            current_file = m.group("path") if m else None
            line_no = 0
            continue
        m = _HUNK_RE.match(raw)
        if m:
            line_no = int(m.group("start"))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            out.append((current_file, line_no, raw[1:]))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
        # "-" lines: don't advance the +file line counter.
    return out


# -- git plumbing --------------------------------------------------------------


def _git(args: list[str]) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def get_staged_files() -> list[str]:
    out = _git(["diff", "--cached", "--name-only", "--diff-filter=AM"])
    return [line for line in out.splitlines() if line]


def get_staged_diff() -> str:
    return _git(["diff", "--cached", "--no-color", "-U0"])


# -- main entrypoint -----------------------------------------------------------


def run_checks(
    files: list[str], added_lines: list[tuple[str | None, int, str]]
) -> tuple[list[Issue], list[Issue]]:
    """Pure function: takes already-parsed inputs, returns (failures, warnings).

    Kept separate from main() so tests can drive it without subprocess mocks.
    """
    issues: list[Issue] = []
    issues += check_filenames(files)
    issues += check_file_sizes(files)
    issues += check_secrets(added_lines)
    issues += check_local_paths(added_lines)
    warnings = check_debug_artifacts(added_lines)
    return issues, warnings


def main() -> int:
    try:
        files = get_staged_files()
        diff = get_staged_diff()
    except subprocess.CalledProcessError as e:
        print(f"git failed: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("git not found on PATH", file=sys.stderr)
        return 1

    added_lines = parse_added_lines(diff)
    issues, warnings = run_checks(files, added_lines)

    if issues:
        print("Staged diff safety check FAILED:\n", file=sys.stderr)
        for issue in issues:
            print(f"  [{issue.category}] {issue.location} — {issue.detail}", file=sys.stderr)
        print(
            "\nIf this is a false positive, address the pattern (or scope an allowlist).",
            file=sys.stderr,
        )
        return 1

    if warnings:
        print("Staged diff safety check passed with warnings:")
        for w in warnings:
            print(f"  [{w.category}] {w.location} — {w.detail}")

    print(f"Staged diff safety check passed ({len(files)} files, {len(added_lines)} additions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
