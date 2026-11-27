from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_release_assets():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "release_assets.py"
    spec = importlib.util.spec_from_file_location("release_assets", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        encoding="utf-8",
    ).strip()


def _init_repo(tmp_path: Path, *, tag_initial: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test Release")
    _git(repo, "config", "user.email", "release@example.com")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Initial release commit")
    if tag_initial:
        _git(repo, "tag", "-a", "v2.0.0", "-m", "Release Siderfolio v2.0.0")
    return repo


def test_release_notes_prefers_dedicated_release_doc(tmp_path: Path) -> None:
    mod = _load_release_assets()
    repo = _init_repo(tmp_path)

    doc = repo / "docs" / "releases" / "v2.1.0.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "\ufeffV2.1.0 交付内置技能系统与受控外部 MCP。\n\n- 新增 3 套内置技能\n",
        encoding="utf-8",
    )
    _git(repo, "add", "docs/releases/v2.1.0.md")
    _git(repo, "commit", "-m", "Add v2.1.0 release notes")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v2.1.0", "-m", "Release Siderfolio v2.1.0\n\nIgnored tag body")

    notes = mod.build_release_notes(
        "v2.1.0", sha, "lct808846/siderfolio", git=("git", "-C", str(repo))
    )
    compare_url = "https://github.com/lct808846/siderfolio/compare/v2.0.0...v2.1.0"
    assert notes.startswith("V2.1.0 交付内置技能系统与受控外部 MCP。")
    assert "- 新增 3 套内置技能" in notes
    assert "Ignored tag body" not in notes
    assert f"**Full Changelog**: {compare_url}" in notes


def test_release_notes_uses_annotated_tag_body_and_strips_signature(tmp_path: Path) -> None:
    mod = _load_release_assets()
    repo = _init_repo(tmp_path)

    (repo / "feature.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "Add feature")
    sha = _git(repo, "rev-parse", "HEAD")
    tag_msg = (
        "Release Siderfolio v2.0.1\n\n"
        "- 修复移动端滚动裁切\n"
        "- 补充线上冒烟验证\n"
        "-----BEGIN SSH SIGNATURE-----\n"
        "U1NIU0lHfake\n"
        "-----END SSH SIGNATURE-----\n"
    )
    _git(repo, "tag", "-a", "v2.0.1", "-m", tag_msg)

    notes = mod.build_release_notes(
        "v2.0.1", sha, "lct808846/siderfolio", git=("git", "-C", str(repo))
    )
    compare_url = "https://github.com/lct808846/siderfolio/compare/v2.0.0...v2.0.1"
    assert "Release Siderfolio v2.0.1" not in notes
    assert "- 修复移动端滚动裁切" in notes
    assert "- 补充线上冒烟验证" in notes
    assert "BEGIN SSH SIGNATURE" not in notes
    assert f"**Full Changelog**: {compare_url}" in notes


def test_release_notes_falls_back_to_commit_log_for_boilerplate_tag(tmp_path: Path) -> None:
    mod = _load_release_assets()
    repo = _init_repo(tmp_path)

    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(
        repo,
        "commit",
        "-m",
        "Add automatic changelog generation",
        "-m",
        "- Support docs/releases notes\nSigned-off-by: Dev <dev@example.com>",
    )
    first_sha = _git(repo, "rev-parse", "--short=7", "HEAD")

    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "Refine UI styles")
    sha = _git(repo, "rev-parse", "HEAD")
    second_sha = sha[:7]
    _git(repo, "tag", "-a", "v2.0.1", "-m", "Release Siderfolio v2.0.1")

    notes = mod.build_release_notes(
        "v2.0.1", sha, "lct808846/siderfolio", git=("git", "-C", str(repo))
    )
    compare_url = "https://github.com/lct808846/siderfolio/compare/v2.0.0...v2.0.1"
    assert notes.startswith("## 更新内容\n\n")
    assert f"- Refine UI styles (`{second_sha}`)" in notes
    assert f"- Add automatic changelog generation (`{first_sha}`)" in notes
    assert "  - Support docs/releases notes" in notes
    assert "Signed-off-by" not in notes
    assert f"**Full Changelog**: {compare_url}" in notes


def test_release_notes_handles_first_release_without_previous_tag(tmp_path: Path) -> None:
    mod = _load_release_assets()
    repo = _init_repo(tmp_path, tag_initial=False)
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release Siderfolio v1.0.0")

    notes = mod.build_release_notes(
        "v1.0.0", sha, "lct808846/siderfolio", git=("git", "-C", str(repo))
    )
    assert f"- Initial release commit (`{sha[:7]}`)" in notes
    assert "Full Changelog" not in notes


def test_release_notes_does_not_duplicate_existing_compare_link(tmp_path: Path) -> None:
    mod = _load_release_assets()
    repo = _init_repo(tmp_path)

    doc = repo / "docs" / "releases" / "v2.0.1.md"
    doc.parent.mkdir(parents=True)
    compare_url = "https://github.com/lct808846/siderfolio/compare/v2.0.0...v2.0.1"
    doc.write_text(f"已含链接。\n\n**Full Changelog**: {compare_url}\n", encoding="utf-8")
    _git(repo, "add", "docs/releases/v2.0.1.md")
    _git(repo, "commit", "-m", "Release v2.0.1")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "v2.0.1", "-m", "Release Siderfolio v2.0.1")

    notes = mod.build_release_notes(
        "v2.0.1", sha, "lct808846/siderfolio", git=("git", "-C", str(repo))
    )
    assert notes.count("https://github.com/lct808846/siderfolio/compare/") == 1


def test_release_notes_validates_inputs() -> None:
    mod = _load_release_assets()
    with pytest.raises(ValueError):
        mod.build_release_notes("2.1.0", "a" * 40, "lct808846/siderfolio")
    with pytest.raises(ValueError):
        mod.build_release_notes("v2.1.0", "not-a-sha", "lct808846/siderfolio")
    with pytest.raises(ValueError):
        mod.build_release_notes("v2.1.0", "a" * 40, "UPPER/Repo")
