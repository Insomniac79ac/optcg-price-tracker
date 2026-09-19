from pathlib import Path

from tests._repo_root import find_repo_root


def test_find_repo_root_walks_up_for_repo_markers(tmp_path):
    repo_root = tmp_path / "checkout"
    (repo_root / "services" / "worker" / "tests").mkdir(parents=True)
    (repo_root / "docker-compose.yml").write_text("")

    start = repo_root / "services" / "worker" / "tests" / "test_module.py"

    assert find_repo_root(start) == repo_root


def test_find_repo_root_returns_none_for_standalone_service_layout(tmp_path):
    start = tmp_path / "app" / "tests" / "test_module.py"
    start.parent.mkdir(parents=True)

    assert find_repo_root(start) is None


def test_find_repo_root_does_not_depend_on_cwd(monkeypatch, tmp_path):
    repo_root = tmp_path / "checkout"
    start = repo_root / "services" / "worker" / "tests" / "test_module.py"
    start.parent.mkdir(parents=True)
    (repo_root / "docker-compose.yml").write_text("")

    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    assert find_repo_root(start) == repo_root
    assert isinstance(find_repo_root(start), Path)
