from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

import cad_bench_submission.freeze as freeze
from cad_bench_submission.validation import REPOSITORY_ROOT


def test_frozen_v1_tree_matches_lock() -> None:
    assert freeze.check_tree() == []


def test_bootstrap_pr_can_create_freeze(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        freeze.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )
    assert freeze.check_pr_diff("base-without-marker") == []
    assert "BOOTSTRAP: v1 PR-diff protection is not enforced" in capsys.readouterr().out


def test_non_yaml_file_cannot_bypass_freeze_lock(tmp_path) -> None:
    archive = tmp_path / "submissions" / "v1"
    archive.mkdir(parents=True)
    manifest = archive / "entry.yaml"
    manifest.write_text("bench: v1\n", encoding="utf-8")
    (archive / "notes.md").write_text("not locked\n", encoding="utf-8")

    lock_dir = tmp_path / "frozen"
    lock_dir.mkdir()
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (lock_dir / "v1-lock.json").write_text(
        json.dumps(
            {
                "files": {
                    "submissions/v1/entry.yaml": digest,
                }
            }
        ),
        encoding="utf-8",
    )

    issues = freeze.check_tree(
        root=tmp_path,
        lock_path=lock_dir / "v1-lock.json",
    )
    assert issues == [
        "unlocked file added to frozen v1 archive: submissions/v1/notes.md"
    ]


def test_first_party_v1_baselines_are_complete() -> None:
    path = REPOSITORY_ROOT / "baselines" / "v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["bench"]["tag"] == "v1"
    assert data["source"]["hf_commit_oid"] == (
        "9bfc0b77fca5863ad573f41544f2033bde0a1862"
    )
    assert len(data["rows"]) == 10
    assert sum(row["trials"] for row in data["rows"]) == 1000
    assert len({row["cell"] for row in data["rows"]}) == 10
    assert all(row["trials"] == 100 for row in data["rows"])

    codex = next(row for row in data["rows"] if row["cell"] == "codex-gpt5.5")
    assert codex["metrics"]["combined"] == pytest.approx(0.8323714354000648)

    gemini_cli = next(
        row for row in data["rows"] if row["cell"] == "gemini-cli-pro"
    )
    assert gemini_cli["missing_subscores"] == 7
    assert 100 * gemini_cli["metrics"]["geometry"] == pytest.approx(68.8763133359867)
