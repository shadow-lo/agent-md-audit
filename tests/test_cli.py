import json

from agent_md_audit.cli import main

from conftest import GOOD, GOOD_FILES


def test_clean_exit_zero(project, capsys):
    p = project(GOOD, GOOD_FILES)
    assert main([str(p), "--no-color"]) == 0
    assert "1 file(s) checked, 0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_errors_exit_one(project):
    assert main([str(project("See `docs/nope.md`.\n"))]) == 1


def test_warning_only_passes_unless_strict(project):
    p = project("## Empty\n")
    assert main([str(p)]) == 0
    assert main([str(p), "--strict"]) == 1


def test_max_lines_flag(project):
    p = project("".join(f"line {i}\n" for i in range(50)))
    assert main([str(p), "--strict"]) == 0
    assert main([str(p), "--strict", "--max-lines", "20"]) == 1


def test_scans_folders(project, tmp_path, capsys):
    project("ok\n")
    project("ok\n", name="web/AGENTS.md")
    assert main([str(tmp_path), "--no-color"]) == 0
    assert "2 file(s) checked" in capsys.readouterr().out


def test_json_output(project, capsys):
    main([str(project("See `docs/nope.md`.\n")), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["findings"][0]["code"] == "AM001"
    assert data[0]["findings"][0]["severity"] == "error"


def test_github_output(project, capsys):
    main([str(project("See `docs/nope.md`.\n")), "--format", "github"])
    out = capsys.readouterr().out
    assert out.startswith("::error file=")
    assert "title=AM001" in out


def test_no_files_found(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert "no agent instruction files" in capsys.readouterr().err


def test_missing_path(tmp_path):
    assert main([str(tmp_path / "nope")]) == 2


def test_list_rules(capsys):
    assert main(["--list-rules"]) == 0
    out = capsys.readouterr().out
    assert "AM001" in out and "AM107" in out
