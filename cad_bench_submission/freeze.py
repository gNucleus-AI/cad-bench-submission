"""Check the immutable CAD-Bench v1 archive and reject later PR changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cad_bench_submission.validation import REPOSITORY_ROOT


MARKER_PATH = "submissions/v1/.frozen"
LEADERBOARD_MARKER_PATH = "leaderboards/v1.frozen"
LOCK_PATHS = (
    "frozen/v1-lock.json",
    "frozen/v1-leaderboard-lock.json",
)
PROTECTED_PATHS = (
    "baselines/v1.json",
    "benchmarks/v1.json",
    "frozen/v1-lock.json",
    "submissions/_schema/manifest-v1.schema.json",
    "submissions/v1/",
)
LEADERBOARD_PROTECTED_PATHS = (
    "cad_bench_submission/build_v1_leaderboard.py",
    "frozen/v1-leaderboard-lock.json",
    "leaderboards/v1.frozen",
    "leaderboards/v1.yaml",
    "leaderboards/v1-rows.json",
    "leaderboards/v1-source-metrics.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_tree(root: Path = REPOSITORY_ROOT, lock_path: Path | None = None) -> list[str]:
    """Check every frozen file against the committed v1 lock."""
    issues: list[str] = []
    expected: dict[str, str] = {}
    lock_paths = [lock_path] if lock_path else [root / path for path in LOCK_PATHS]
    for current_lock_path in lock_paths:
        if not current_lock_path.is_file():
            issues.append(
                "frozen lock is missing: "
                f"{current_lock_path.relative_to(root)}"
            )
            continue
        with current_lock_path.open(encoding="utf-8") as stream:
            lock = json.load(stream)

        current_expected = lock.get("files")
        if not isinstance(current_expected, dict):
            issues.append(f"{current_lock_path}: expected a files mapping")
            continue
        expected.update(current_expected)
        for relative_path, expected_digest in sorted(current_expected.items()):
            path = root / relative_path
            if not path.is_file():
                issues.append(f"frozen v1 file is missing: {relative_path}")
            elif _sha256(path) != expected_digest:
                issues.append(f"frozen v1 file changed: {relative_path}")

    frozen_files = {
        str(path.relative_to(root))
        for path in (root / "submissions" / "v1").rglob("*")
        if path.is_file()
    }
    locked_files = {
        path for path in expected if path.startswith("submissions/v1/")
    }
    for relative_path in sorted(frozen_files - locked_files):
        issues.append(f"unlocked file added to frozen v1 archive: {relative_path}")
    return issues


def check_pr_diff(base: str) -> list[str]:
    """Reject protected v1 changes after the freeze marker reaches the base."""
    scopes = (
        (MARKER_PATH, PROTECTED_PATHS, "v1"),
        (
            LEADERBOARD_MARKER_PATH,
            LEADERBOARD_PROTECTED_PATHS,
            "v1 leaderboard publication",
        ),
    )
    active_scopes: list[tuple[tuple[str, ...], str]] = []
    for marker_path, protected_paths, label in scopes:
        marker = subprocess.run(
            ["git", "cat-file", "-e", f"{base}:{marker_path}"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
        )
        if marker.returncode != 0:
            print(
                f"BOOTSTRAP: {label} PR-diff protection is not enforced "
                "because the base has no freeze marker"
            )
            continue
        active_scopes.append((protected_paths, label))

    if not active_scopes:
        return []

    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [line for line in diff.stdout.splitlines() if line]
    issues: list[str] = []
    for protected_paths, label in active_scopes:
        issues.extend(
            f"{label} is frozen; PR changes protected path: {path}"
            for path in changed
            if any(
                path == protected
                or protected.endswith("/") and path.startswith(protected)
                for protected in protected_paths
            )
        )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        help="optional PR base commit; protected changes are rejected after bootstrap",
    )
    args = parser.parse_args(argv)

    issues = check_tree()
    if args.base:
        issues.extend(check_pr_diff(args.base))
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("OK frozen v1 archive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
