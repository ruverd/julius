"""Public CLI paths for explicit, project-scoped symbol retrieval."""

import json

import pytest

from julius.cli import run


def test_cli_symbol_index_search_refresh_and_invalidate(tmp_path, capsys) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def alpha():\n    return 1\n")
    common = ["--project", "p", "--project-root", str(root),
              "--snapshot", "snapshot-1", "--data-dir", str(tmp_path / "data")]

    assert run(["symbols", "index", "module.py", *common]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["symbols"] == 1
    assert indexed["changed"] is True

    assert run(["symbols", "search", "alpha", *common]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["name"] for hit in hits] == ["alpha"]
    assert hits[0]["path"] == "module.py"

    source.write_text("def beta():\n    return 2\n")
    assert run(["symbols", "index", "module.py", *common]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert run(["symbols", "search", "alpha", *common]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert run(["symbols", "search", "beta", *common]) == 0
    assert [hit["name"] for hit in json.loads(capsys.readouterr().out)] == ["beta"]

    assert run(["symbols", "invalidate", "module.py", *common]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 1}
    assert run(["symbols", "search", "beta", *common]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_symbol_project_root_binding_is_enforced(tmp_path, capsys) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "module.py").write_text("def one():\n    pass\n")
    common = ["--project", "p", "--snapshot", "snapshot-1",
              "--data-dir", str(tmp_path / "data")]
    assert run(["symbols", "index", "module.py", "--project-root", str(first), *common]) == 0
    capsys.readouterr()
    with pytest.raises(ValueError, match="bound to another root"):
        run(["symbols", "search", "one", "--project-root", str(second), *common])
