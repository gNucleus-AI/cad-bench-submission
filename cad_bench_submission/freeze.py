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
PROTECTED_PATHS = (
    "baselines/v1.json",
    "benchmarks/v1.json",
    "frozen/v1-lock.json",
    "submissions/_schema/manifest-v1.schema.json",
    "submissions/v1/",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_tree(root: Path = REPOSITORY_ROOT, lock_path: Path | None = None) -> list[str]:
    """Check every frozen file against the committed v1 lock."""
    lock_path = lock_path or root / "frozen" / "v1-lock.json"
    with lock_path.open(encoding="utf-8") as stream:
        lock = json.load(stream)

    expected = lock.get("files")
    if not isinstance(expected, dict):
        return [f"{lock_path}: expected a files mapping"]

    issues: list[str] = []
    for relative_path, expected_digest in sorted(expected.items()):
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
    marker = subprocess.run(
        ["git", "cat-file", "-e", f"{base}:{MARKER_PATH}"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    if marker.returncode != 0:
        # This is the one-time bootstrap PR that establishes the archive.
        print(
            "BOOTSTRAP: v1 PR-diff protection is not enforced because the "
            "base has no freeze marker"
        )
        return []

    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [line for line in diff.stdout.splitlines() if line]
    return [
        f"v1 is frozen; PR changes protected path: {path}"
        for path in changed
        if any(
            path == protected or protected.endswith("/") and path.startswith(protected)
            for protected in PROTECTED_PATHS
        )
    ]


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
