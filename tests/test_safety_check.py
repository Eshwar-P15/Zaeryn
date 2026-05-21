"""Tests for scripts/check_staged_safety.py.

The script lives outside the importable package set (scripts/ has no __init__.py
by design — see CLAUDE.md), so we load it by path.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_staged_safety.py"
_spec = importlib.util.spec_from_file_location("check_staged_safety", _SCRIPT_PATH)
safety = importlib.util.module_from_spec(_spec)
sys.modules["check_staged_safety"] = safety
_spec.loader.exec_module(safety)


# -- filename rules ------------------------------------------------------------


def test_filenames_env_fails():
    issues = safety.check_filenames([".env"])
    assert len(issues) == 1
    assert issues[0].category == "filename"


def test_filenames_env_local_fails():
    issues = safety.check_filenames([".env.local", "config/.env.production"])
    assert len(issues) == 2


def test_filenames_env_example_passes():
    # .env.example / .env.sample are conventional checked-in templates
    assert safety.check_filenames([".env.example", ".env.sample"]) == []


def test_filenames_sqlite_db_fails():
    assert safety.check_filenames(["zaeryn.db"]) != []
    assert safety.check_filenames(["data/store.sqlite3"]) != []


def test_filenames_credentials_json_fails():
    assert safety.check_filenames(["credentials.json", "config/secrets.yaml"]) != []


def test_filenames_pem_private_fails():
    assert safety.check_filenames(["server.pem", "id_rsa"]) != []


def test_filenames_public_key_passes():
    # "public" in name shouldn't trip the private-key rule
    assert safety.check_filenames(["public.pem", "my_public.key"]) == []


def test_filenames_normal_code_passes():
    assert safety.check_filenames(["data/storage.py", "tests/test_data.py", "README.md"]) == []


# -- file size -----------------------------------------------------------------


def test_file_size_under_limit_passes(tmp_path, monkeypatch):
    f = tmp_path / "small.bin"
    f.write_bytes(b"x" * 500)
    monkeypatch.chdir(tmp_path)
    assert safety.check_file_sizes(["small.bin"], max_bytes=1_000_000) == []


def test_file_size_over_limit_fails(tmp_path, monkeypatch):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 2_000_000)
    monkeypatch.chdir(tmp_path)
    issues = safety.check_file_sizes(["big.bin"], max_bytes=1_000_000)
    assert len(issues) == 1
    assert issues[0].category == "size"


# -- secret detection ----------------------------------------------------------


def test_secrets_aws_access_key_fails():
    lines = [("config/aws.py", 1, 'aws = "AKIAIOSFODNN7EXAMPLE"')]
    issues = safety.check_secrets(lines)
    assert any("AWS access key" in i.detail for i in issues)


def test_secrets_github_pat_fails():
    # 36-char alphanumeric after ghp_
    lines = [("ci.yml", 4, "token: ghp_" + "a" * 40)]
    issues = safety.check_secrets(lines)
    assert any("GitHub PAT" in i.detail for i in issues)


def test_secrets_anthropic_key_fails():
    lines = [("notebook.py", 12, 'client = Anthropic(api_key="sk-ant-' + "X" * 40 + '")')]
    issues = safety.check_secrets(lines)
    assert any("Anthropic" in i.detail for i in issues)


def test_secrets_assignment_with_real_value_fails():
    lines = [("config/local.py", 7, 'BIRDEYE_API_KEY = "abc123def456ghi789jkl012mno345pqr"')]
    issues = safety.check_secrets(lines)
    assert any("BIRDEYE_API_KEY" in i.detail for i in issues)


def test_secrets_assignment_with_empty_passes():
    lines = [("config/settings.py", 1, 'BIRDEYE_API_KEY = ""')]
    assert safety.check_secrets(lines) == []


def test_secrets_assignment_with_placeholder_passes():
    lines = [
        (".env.example", 1, "BIRDEYE_API_KEY=your_key_here"),
        (".env.example", 2, "HELIUS_API_KEY=<your-key-here>"),
        (".env.example", 3, "NEWSAPI_API_KEY=REPLACE_ME"),
    ]
    assert safety.check_secrets(lines) == []


def test_secrets_env_var_reference_passes():
    # os.getenv("BIRDEYE_API_KEY") is a name reference, not a value assignment
    lines = [
        ("sentiment/onchain.py", 1, 'api_key = os.getenv("BIRDEYE_API_KEY", "")'),
        (
            "config/_models.py",
            2,
            'api_key: str = Field(default="", validation_alias="BIRDEYE_API_KEY")',
        ),
        ("README.md", 3, "Set `BIRDEYE_API_KEY` in your .env file"),
    ]
    assert safety.check_secrets(lines) == []


def test_secrets_self_file_skipped():
    # The safety script and its test contain the patterns by design — never self-flag.
    lines = [("scripts/check_staged_safety.py", 1, 'pattern = r"AKIA[0-9A-Z]{16}"')]
    assert safety.check_secrets(lines) == []


# -- local path detection ------------------------------------------------------


def test_local_paths_home_epala_fails():
    lines = [("data/storage.py", 5, 'DB_PATH = "/home/epala/dev/Zaeryn/zaeryn.db"')]
    issues = safety.check_local_paths(lines)
    assert len(issues) == 1
    assert issues[0].category == "path"


def test_local_paths_in_example_context_passes():
    # Same path but the line carries an "example" hint → allowed
    lines = [
        ("docs/setup.md", 1, "# Example output: /home/epala/fake/example.py"),
        ("tests/test_x.py", 2, "tmp_path = /home/epala/fixtures/data"),
    ]
    assert safety.check_local_paths(lines) == []


def test_local_paths_windows_drive_fails():
    lines = [("script.bat", 1, r"set DB=C:\\Users\\epala\\zaeryn.db")]
    assert safety.check_local_paths(lines) != []


def test_local_paths_claude_settings_allowlisted():
    # .claude/settings.local.json legitimately stores per-project tool allowlist
    # entries containing absolute paths — they aren't secrets.
    lines = [
        (".claude/settings.local.json", 33, '      "Bash(ls /home/epala/dev/Zaeryn/*)"'),
        (".claude/settings.json", 5, '      "Read(/home/epala/dev/Zaeryn/**)"'),
    ]
    assert safety.check_local_paths(lines) == []


def test_local_paths_claude_allowlist_does_not_leak_to_other_files():
    # The same content in a non-.claude file must still be flagged.
    lines = [("models/trend.py", 10, 'allowed = "/home/epala/dev/Zaeryn/data.csv"')]
    issues = safety.check_local_paths(lines)
    assert len(issues) == 1
    assert issues[0].category == "path"


# -- debug artifacts (warnings only) ------------------------------------------


def test_debug_print_in_production_warns():
    lines = [("models/trainer.py", 10, '    print(f"training {asset}")')]
    warnings = safety.check_debug_artifacts(lines)
    assert any("print()" in w.detail for w in warnings)


def test_debug_print_in_scripts_does_not_warn():
    lines = [("scripts/train_models.py", 10, '    print(f"training {asset}")')]
    warnings = safety.check_debug_artifacts(lines)
    assert not any("print()" in w.detail for w in warnings)


def test_debug_breakpoint_warns():
    lines = [("models/trainer.py", 10, "    breakpoint()")]
    warnings = safety.check_debug_artifacts(lines)
    assert any("breakpoint()" in w.detail for w in warnings)


def test_debug_pdb_set_trace_warns():
    lines = [("tests/test_models.py", 10, "    import pdb; pdb.set_trace()")]
    warnings = safety.check_debug_artifacts(lines)
    assert any("pdb" in w.detail.lower() for w in warnings)


def test_debug_fixme_warns():
    lines = [("models/trainer.py", 10, "    # FIXME: bad")]
    warnings = safety.check_debug_artifacts(lines)
    assert any("FIXME" in w.detail for w in warnings)


# -- diff parsing --------------------------------------------------------------


def test_parse_added_lines_basic():
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "index 1234..5678 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n"
        " unchanged_first_line\n"
        "+added_second_line\n"
        " unchanged_third_line\n"
    )
    parsed = safety.parse_added_lines(diff)
    assert parsed == [("foo.py", 2, "added_second_line")]


def test_parse_added_lines_multiple_hunks():
    diff = "+++ b/a.py\n@@ -0,0 +1,2 @@\n+first\n+second\n+++ b/b.py\n@@ -10,0 +11,1 @@\n+third\n"
    parsed = safety.parse_added_lines(diff)
    assert parsed == [
        ("a.py", 1, "first"),
        ("a.py", 2, "second"),
        ("b.py", 11, "third"),
    ]


# -- orchestration -------------------------------------------------------------


def test_run_checks_clean_returns_empty():
    files = ["data/storage.py", "tests/test_data.py"]
    added_lines = [
        ("data/storage.py", 1, "def foo(): return 1"),
    ]
    issues, warnings = safety.run_checks(files, added_lines)
    assert issues == []
    assert warnings == []


def test_run_checks_finds_secret_assignment():
    files = ["config/local.py"]
    added_lines = [("config/local.py", 1, 'BIRDEYE_API_KEY = "real-looking-secret-value-here-xyz"')]
    issues, _ = safety.run_checks(files, added_lines)
    assert any(i.category == "secret" for i in issues)


def test_run_checks_finds_filename_violation():
    files = [".env", "data/storage.py"]
    issues, _ = safety.run_checks(files, [])
    assert any(i.category == "filename" and ".env" in i.location for i in issues)
