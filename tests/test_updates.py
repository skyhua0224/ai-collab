from __future__ import annotations

from urllib.error import HTTPError, URLError

from ai_collab.core.updates import check_pypi_update, compare_versions


def test_compare_versions_handles_dev_version_ahead_of_older_release() -> None:
    assert compare_versions("0.1.5.dev0", "0.1.4") == 1


def test_compare_versions_handles_same_release_dev_lower_than_final() -> None:
    assert compare_versions("0.1.5.dev0", "0.1.5") == -1


def test_check_pypi_update_reports_remote_update() -> None:
    result = check_pypi_update(local_version="0.1.4", fetcher=lambda **_: "0.1.5")

    assert result.status == "behind"
    assert result.remote_version == "0.1.5"


def test_check_pypi_update_reports_local_ahead() -> None:
    result = check_pypi_update(local_version="0.1.5.dev0", fetcher=lambda **_: "0.1.4")

    assert result.status == "ahead"
    assert result.remote_version == "0.1.4"


def test_check_pypi_update_reports_unpublished_package() -> None:
    def _missing(**_):
        raise HTTPError(url="https://pypi.org/pypi/ai-collab/json", code=404, msg="Not Found", hdrs=None, fp=None)

    result = check_pypi_update(local_version="0.1.5.dev0", fetcher=_missing)

    assert result.status == "unpublished"
    assert result.remote_version is None


def test_check_pypi_update_reports_unavailable_on_network_error() -> None:
    def _offline(**_):
        raise URLError("offline")

    result = check_pypi_update(local_version="0.1.5.dev0", fetcher=_offline)

    assert result.status == "unavailable"
    assert result.remote_version is None


def test_package_dunder_version_matches_pyproject_version() -> None:
    from pathlib import Path
    from ai_collab import __version__

    pyproject = Path("pyproject.toml").read_text()
    assert f'version = "{__version__}"' in pyproject
