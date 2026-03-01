"""Tests for project profiler behavior and performance safety."""

from __future__ import annotations

from ai_collab.core.profiler import ProjectProfiler


def test_profiler_avoids_recursive_glob_patterns(monkeypatch, tmp_path) -> None:
    """Profiler should not rely on recursive '**' glob calls that can hang on large trees."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("# docs\n", encoding="utf-8")

    path_cls = type(tmp_path)
    original_glob = path_cls.glob
    seen_patterns: list[str] = []

    def guarded_glob(self, pattern):  # type: ignore[override]
        seen_patterns.append(str(pattern))
        return original_glob(self, pattern)

    monkeypatch.setattr(path_cls, "glob", guarded_glob, raising=True)

    profile = ProjectProfiler(root=tmp_path).detect()

    assert isinstance(profile.categories, list)
    assert all("**" not in pattern for pattern in seen_patterns)


def test_profiler_still_detects_categories(tmp_path) -> None:
    """Profiler should keep core category detection after safety changes."""
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

    profile = ProjectProfiler(root=tmp_path).detect()

    assert "superapp-fullstack" in profile.categories
    assert "systems-tooling" in profile.categories
