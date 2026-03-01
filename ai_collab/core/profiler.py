"""
Project profiling module.
Detects repository category so collaboration can auto-trigger by project type.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field

PRUNE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
}


class ProjectProfile(BaseModel):
    """Detected project profile."""

    root: str
    categories: List[str] = Field(default_factory=list)
    signals: Dict[str, List[str]] = Field(default_factory=dict)


class ProjectProfiler:
    """Infers project categories from workspace files."""

    def __init__(self, root: Path | None = None, *, max_scan_seconds: float = 1.5, max_walk_entries: int = 12000):
        self.root = Path(root or Path.cwd()).resolve()
        self.max_scan_seconds = max(0.2, float(max_scan_seconds))
        self.max_walk_entries = max(200, int(max_walk_entries))
        self._scan_deadline = 0.0
        self._candidate_cache: List[str] | None = None
        self._fast_mode = False

    def detect(self) -> ProjectProfile:
        self._scan_deadline = time.monotonic() + self.max_scan_seconds
        self._candidate_cache = None
        self._fast_mode = self._use_fast_mode()

        signals: Dict[str, List[str]] = {}
        categories: List[str] = []

        def add_signal(key: str, values: List[str]) -> None:
            if values:
                signals[key] = values

        def add_category(name: str) -> None:
            if name not in categories:
                categories.append(name)

        # 1) Text/blog/docs-heavy projects
        docs_dirs = self._existing_dirs(["docs", "blog", "posts", "content"])
        docs_files = self._find_any([
            "docs/**/*.md",
            "blog/**/*.md",
            "posts/**/*.md",
            "content/**/*.md",
            "README*",
        ])
        if docs_dirs or any(
            s.startswith(("docs/", "blog/", "posts/", "content/"))
            for s in docs_files
        ):
            add_signal("docs_text", docs_dirs + docs_files[:8])
            add_category("docs-text")

        # 2) Superapp/full-stack style projects (like PP)
        fullstack_dirs = self._existing_dirs(["admin", "backend", "frontend", "client", "web"])
        if len(fullstack_dirs) >= 2:
            add_signal("fullstack_dirs", fullstack_dirs)
            add_category("superapp-fullstack")

        miniapp_signals = self._find_any(["miniprogram", "uniapp", "wechat", "miniapp", "apps"])
        if miniapp_signals and "superapp-fullstack" not in categories:
            add_signal("miniapp", miniapp_signals)
            add_category("superapp-fullstack")

        # 3) macOS Swift native
        macos_swift = self._find_any(["*.xcodeproj", "Package.swift", "*.swift", "*.xcworkspace"])
        if macos_swift:
            add_signal("swift_native", macos_swift)
            # if it's clearly mobile only we'll classify mobile below; otherwise include macOS
            if any("macos" in s.lower() or "moonlight" in s.lower() for s in macos_swift):
                add_category("macos-swift")

        # 4) Mobile native (iOS/Android)
        mobile_signals = self._find_any([
            "AndroidManifest.xml",
            "build.gradle",
            "build.gradle.kts",
            "Podfile",
            "*.xcodeproj",
            "*.xcworkspace",
            "app/src/main",
            "ios",
            "android",
        ])
        if mobile_signals:
            add_signal("mobile_native", mobile_signals)
            add_category("mobile-native")
            if "macos-swift" not in categories and any(s.endswith(".swift") or "xcode" in s.lower() for s in mobile_signals):
                add_category("macos-swift")

        # 5) Systems/tooling projects
        systems_signals = self._find_any([
            "Cargo.toml",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Makefile",
            "scripts",
            "scripts/*.sh",
            "*.sh",
        ])
        has_strong_marker = any(
            marker in systems_signals
            for marker in ["Cargo.toml", "Makefile", "scripts", "requirements.txt"]
        )
        if systems_signals and (has_strong_marker or len(systems_signals) >= 2):
            add_signal("systems_tooling", systems_signals)
            add_category("systems-tooling")

        # 6) Game projects: Unity / Unreal / Ren'Py
        unity_signals = self._find_any([
            "Assets",
            "ProjectSettings",
            "Packages/manifest.json",
            "ProjectSettings/ProjectVersion.txt",
        ])
        unreal_signals = self._find_any([
            "*.uproject",
            "Source/*.Build.cs",
            "Config/DefaultEngine.ini",
        ])
        renpy_signals = self._find_any([
            "*.rpy",
            "game/script.rpy",
            "renpy.sh",
        ])

        unity_detected = (
            ("Assets" in unity_signals and "ProjectSettings" in unity_signals)
            or any("Packages/manifest.json" in s for s in unity_signals)
            or any("ProjectSettings/ProjectVersion.txt" in s for s in unity_signals)
        )
        unreal_detected = any(s.endswith(".uproject") for s in unreal_signals) or any(
            "DefaultEngine.ini" in s or ".Build.cs" in s for s in unreal_signals
        )
        renpy_detected = any(s.endswith(".rpy") for s in renpy_signals) or any(
            "game/script.rpy" in s for s in renpy_signals
        )

        if unity_detected or unreal_detected or renpy_detected:
            game_hits: List[str] = []
            game_hits.extend(unity_signals)
            game_hits.extend(unreal_signals)
            game_hits.extend(renpy_signals)
            add_signal("game_dev", game_hits[:8])
            add_category("game-dev")

        return ProjectProfile(
            root=str(self.root),
            categories=categories,
            signals=signals,
        )

    def _existing_dirs(self, names: List[str]) -> List[str]:
        hits: List[str] = []
        for name in names:
            path = self.root / name
            if path.exists() and path.is_dir():
                hits.append(name)
        return hits

    def _find_any(self, patterns: List[str], limit: int = 8) -> List[str]:
        hits: List[str] = []

        # First check exact top-level paths to avoid expensive recursion.
        for pattern in patterns:
            top = self.root / pattern
            if top.exists():
                hits.append(pattern)
                if len(hits) >= limit:
                    return hits

        # Then bounded filesystem scan with cached candidates.
        candidates = self._candidate_paths()
        for rel in candidates:
            if self._deadline_reached():
                break
            if any(self._match_pattern(rel, pattern) for pattern in patterns):
                if rel not in hits:
                    hits.append(rel)
                if len(hits) >= limit:
                    return hits

        return hits

    def _deadline_reached(self) -> bool:
        return time.monotonic() >= self._scan_deadline

    def _use_fast_mode(self) -> bool:
        home = Path.home().resolve()
        if self.root == home:
            return True
        if not self.root.exists() or not self.root.is_dir():
            return True
        if (self.root / ".git").exists():
            return False

        # If many top-level entries and no VCS marker, keep scan shallow.
        count = 0
        try:
            for _ in self.root.iterdir():
                count += 1
                if count >= 100:
                    return True
        except Exception:
            return True
        return False

    def _candidate_paths(self) -> List[str]:
        if self._candidate_cache is not None:
            return self._candidate_cache

        results: List[str] = []
        if not self.root.exists() or not self.root.is_dir():
            self._candidate_cache = results
            return results

        entry_count = 0
        max_depth = 2 if self._fast_mode else 6

        def _on_error(_exc: OSError) -> None:
            return

        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True, onerror=_on_error, followlinks=False):
            if self._deadline_reached() or entry_count >= self.max_walk_entries:
                break

            rel_dir = os.path.relpath(dirpath, self.root)
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

            # Prune expensive/irrelevant directories early.
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            if depth >= max_depth:
                dirnames[:] = []

            for name in dirnames:
                if self._deadline_reached() or entry_count >= self.max_walk_entries:
                    break
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                results.append(rel.replace(os.sep, "/"))
                entry_count += 1

            for name in filenames:
                if self._deadline_reached() or entry_count >= self.max_walk_entries:
                    break
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                results.append(rel.replace(os.sep, "/"))
                entry_count += 1

        self._candidate_cache = results
        return results

    def _match_pattern(self, rel: str, pattern: str) -> bool:
        rel_path = Path(rel)

        if any(ch in pattern for ch in "*?[]"):
            if rel_path.match(pattern):
                return True
            if "**/" in pattern and rel_path.match(pattern.replace("**/", "", 1)):
                return True
            return False

        # Non-wildcard patterns should match by segment as if using **/pattern.
        if rel == pattern:
            return True
        return rel.endswith(f"/{pattern}")
