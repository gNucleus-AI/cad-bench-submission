"""Validate submission manifests against their version-specific policy."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATHS = {
    "v1": REPOSITORY_ROOT / "submissions" / "_schema" / "manifest-v1.schema.json",
    "v2": REPOSITORY_ROOT / "submissions" / "_schema" / "manifest-v2.schema.json",
}
BENCHMARKS_DIR = REPOSITORY_ROOT / "benchmarks"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping."""
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError("manifest must contain a YAML mapping at its root")
    return value


def load_schema(tag: str) -> dict[str, Any]:
    try:
        path = SCHEMA_PATHS[tag]
    except KeyError as error:
        raise ValueError(f"no manifest schema exists for {tag!r}") from error
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_policies() -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    for path in sorted(BENCHMARKS_DIR.glob("v*.json")):
        with path.open(encoding="utf-8") as stream:
            policy = json.load(stream)
        tag = policy.get("tag")
        if not isinstance(tag, str):
            raise ValueError(f"{path}: policy is missing a string tag")
        if tag in policies:
            raise ValueError(f"duplicate benchmark policy for {tag}")
        task_digests = policy.get("task_digests")
        task_count = policy.get("task_count")
        if not isinstance(task_digests, dict) or len(task_digests) != task_count:
            raise ValueError(
                f"{path}: task_count={task_count!r} does not match the "
                f"task-digest map"
            )
        policies[tag] = policy
    return policies


def _json_path(parts: Iterable[Any]) -> str:
    rendered = "$"
    for part in parts:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def validate_manifest(
    manifest: dict[str, Any],
    *,
    schema: dict[str, Any] | None = None,
    policies: dict[str, dict[str, Any]] | None = None,
    allow_archived: bool = False,
) -> list[str]:
    """Return all structural and version-policy violations."""
    policies = policies or load_policies()
    bench = manifest.get("bench")
    tag = bench.get("tag") if isinstance(bench, dict) else None
    policy = policies.get(tag) if isinstance(tag, str) else None
    if policy is not None and not policy.get("accepting_submissions", False):
        if not allow_archived:
            return [
                f"$.bench.tag: {tag} submissions are closed; submit against "
                "gnucleus-ai/cad-bench@v2"
            ]

    if schema is None:
        # Use the active schema as a structural fallback so malformed or unknown
        # tags still receive useful schema errors.
        schema = load_schema(tag if tag in SCHEMA_PATHS else "v2")
    issues = [
        f"{_json_path(error.absolute_path)}: {error.message}"
        for error in sorted(
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(manifest),
            key=lambda error: list(error.absolute_path),
        )
    ]

    declared = manifest.get("declared")
    if not isinstance(bench, dict) or not isinstance(declared, dict):
        return issues

    if policy is None:
        if isinstance(tag, str):
            issues.append(f"$.bench.tag: no benchmark policy exists for {tag!r}")
        return issues

    if bench.get("dataset") != policy["dataset"]:
        issues.append(
            "$.bench.dataset: expected "
            f"{policy['dataset']!r} for {tag}, got {bench.get('dataset')!r}"
        )

    submitted_hash = bench.get("dataset_content_hash")
    expected_hash = policy["dataset_content_hash"]
    if tag == "v2" and submitted_hash != expected_hash:
        issues.append(
            "$.bench.dataset_content_hash: expected the frozen "
            f"{tag} digest {expected_hash!r}, got {submitted_hash!r}"
        )
    elif submitted_hash is not None and submitted_hash != expected_hash:
        issues.append(
            "$.bench.dataset_content_hash: expected "
            f"{expected_hash!r}, got {submitted_hash!r}"
        )

    if tag == "v2":
        agent = manifest.get("agent")
        model = manifest.get("model")
        results = manifest.get("results")
        source_filter = (
            results.get("source_filter") if isinstance(results, dict) else None
        )
        if (
            isinstance(agent, dict)
            and isinstance(model, dict)
            and isinstance(source_filter, dict)
        ):
            expected_filter = {
                "agent": agent.get("name"),
                "agent_version": agent.get("version"),
                "model": model.get("id"),
                "reasoning_effort": agent.get("reasoning_effort"),
            }
            for field, expected in expected_filter.items():
                actual = source_filter.get(field)
                if actual != expected:
                    issues.append(
                        f"$.results.source_filter.{field}: expected {expected!r} "
                        f"to match manifest metadata, got {actual!r}"
                    )

    trials_per_task = declared.get("trials_per_task")
    total_trials = declared.get("total_trials")
    if isinstance(trials_per_task, int) and isinstance(total_trials, int):
        expected_total = trials_per_task * policy["task_count"]
        if total_trials != expected_total:
            issues.append(
                "$.declared.total_trials: expected "
                f"{trials_per_task} × {policy['task_count']} = {expected_total}, "
                f"got {total_trials}"
            )

    exceptions = declared.get("exceptions")
    if (
        isinstance(exceptions, int)
        and isinstance(total_trials, int)
        and exceptions > total_trials
    ):
        issues.append(
            "$.declared.exceptions: cannot exceed "
            f"total_trials ({total_trials}), got {exceptions}"
        )

    return issues


def validate_manifest_file(path: Path, *, allow_archived: bool = False) -> list[str]:
    try:
        manifest = load_yaml(path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        return [str(error)]
    issues: list[str] = []
    if path.parent.parent.name == "submissions" and path.parent.name in SCHEMA_PATHS:
        expected_tag = path.parent.name
        bench = manifest.get("bench")
        actual_tag = bench.get("tag") if isinstance(bench, dict) else None
        if actual_tag != expected_tag:
            issues.append(
                f"$.bench.tag: manifests under submissions/{expected_tag}/ must "
                f"declare {expected_tag!r}, got {actual_tag!r}"
            )
    issues.extend(validate_manifest(manifest, allow_archived=allow_archived))
    return issues


def default_manifest_paths() -> list[Path]:
    return sorted((REPOSITORY_ROOT / "submissions" / "v2").glob("*.yaml"))


def validate_repository_layout(root: Path = REPOSITORY_ROOT) -> list[str]:
    """Reject manifests outside the versioned intake/archive directories."""
    submissions = root / "submissions"
    issues: list[str] = []
    manifest_paths = sorted(
        path
        for path in submissions.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )
    for path in manifest_paths:
        is_archive = path.parent == submissions / "v1" and path.suffix == ".yaml"
        is_active = path.parent == submissions / "v2" and path.suffix == ".yaml"
        is_template = path == submissions / "_template" / "example-v2.yaml"
        if not (is_archive or is_active or is_template):
            issues.append(
                f"{path}: manifests are accepted only as .yaml files directly "
                "under submissions/v2/"
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help="manifest YAML files (defaults to active v2 submissions)",
    )
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="also validate the frozen v1 archive using its historical schema",
    )
    args = parser.parse_args(argv)
    layout_issues = validate_repository_layout()
    paths = args.manifests or default_manifest_paths()
    if args.include_archive and not args.manifests:
        paths = sorted((REPOSITORY_ROOT / "submissions" / "v1").glob("*.yaml")) + paths
    if not paths:
        if layout_issues:
            for issue in layout_issues:
                print(issue, file=sys.stderr)
            return 1
        print("OK no active v2 submission manifests")
        return 0

    failed = bool(layout_issues)
    for issue in layout_issues:
        print(issue, file=sys.stderr)
    for path in paths:
        is_archive = path.parent.name == "v1"
        issues = validate_manifest_file(
            path, allow_archived=args.include_archive and is_archive
        )
        if issues:
            failed = True
            for issue in issues:
                print(f"{path}: {issue}", file=sys.stderr)
        else:
            print(f"OK {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
