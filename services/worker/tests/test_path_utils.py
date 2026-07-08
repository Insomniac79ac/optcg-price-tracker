from pathlib import Path

import worker.jobs.discover_snkrdunk as discover_snkrdunk_module
from worker.path_utils import find_project_root


def test_importing_discover_snkrdunk_does_not_touch_the_filesystem():
    # Regression test: this module used to compute
    # Path(__file__).resolve().parents[4] at import time, which raised
    # IndexError as soon as the package was deployed shallower than the dev
    # checkout (e.g. Docker, where only services/worker is copied to /app).
    assert callable(discover_snkrdunk_module.discover_snkrdunk)
    assert callable(discover_snkrdunk_module._default_seed_file)


def test_find_project_root_prefers_project_root_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    assert find_project_root() == tmp_path


def test_find_project_root_walks_up_for_repo_markers(monkeypatch, tmp_path):
    monkeypatch.delenv("PROJECT_ROOT", raising=False)

    repo_root = tmp_path / "repo"
    (repo_root / "data").mkdir(parents=True)
    (repo_root / "services").mkdir()
    (repo_root / "docker-compose.yml").write_text("")

    nested_cwd = repo_root / "services" / "worker"
    nested_cwd.mkdir(parents=True)
    monkeypatch.chdir(nested_cwd)

    assert find_project_root() == repo_root


def test_find_project_root_falls_back_to_cwd_when_no_markers_found(monkeypatch, tmp_path):
    monkeypatch.delenv("PROJECT_ROOT", raising=False)

    isolated_cwd = tmp_path / "no_markers_here"
    isolated_cwd.mkdir()
    monkeypatch.chdir(isolated_cwd)

    assert find_project_root() == isolated_cwd.resolve()


def test_default_seed_file_uses_project_root_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(discover_snkrdunk_module.settings, "SNKRDUNK_SEED_FILE", None)
    monkeypatch.setattr(discover_snkrdunk_module, "find_project_root", lambda: tmp_path)

    result = discover_snkrdunk_module._default_seed_file()

    assert result == tmp_path / "data" / "source_seeds" / "snkrdunk_one_piece_urls.txt"


def test_default_seed_file_absolute_env_override_is_used_directly(monkeypatch, tmp_path):
    absolute_seed_file = tmp_path / "custom_seeds.txt"
    monkeypatch.setattr(discover_snkrdunk_module.settings, "SNKRDUNK_SEED_FILE", str(absolute_seed_file))
    monkeypatch.setattr(
        discover_snkrdunk_module, "find_project_root", lambda: Path("/should/not/be/used")
    )

    result = discover_snkrdunk_module._default_seed_file()

    assert result == absolute_seed_file


def test_default_seed_file_relative_env_override_resolves_against_project_root(monkeypatch, tmp_path):
    monkeypatch.setattr(discover_snkrdunk_module.settings, "SNKRDUNK_SEED_FILE", "custom/seeds.txt")
    monkeypatch.setattr(discover_snkrdunk_module, "find_project_root", lambda: tmp_path)

    result = discover_snkrdunk_module._default_seed_file()

    assert result == tmp_path / "custom" / "seeds.txt"
