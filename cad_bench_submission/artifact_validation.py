"""Audit a downloaded submission artifact tree against its frozen benchmark."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from cad_bench_submission.validation import load_policies, load_yaml, validate_manifest


SCORE_TOLERANCE = 1e-6
HARBOR_JOB_ID_PATTERN = re.compile(
    r"^https://hub\.harborframework\.com/jobs/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$"
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _first_existing(directory: Path, candidates: list[str]) -> Path | None:
    return next((directory / item for item in candidates if (directory / item).is_file()), None)


def _task_identity(
    result: dict[str, Any], config: dict[str, Any]
) -> tuple[str | None, str | None, str | None]:
    # The trial config is the evidence for what task the agent actually ran.
    # result.json is only a fallback for normalized legacy exports.
    task = config.get("task")
    if not isinstance(task, dict):
        task = result.get("task_id")
    if not isinstance(task, dict):
        embedded_config = result.get("config")
        task = embedded_config.get("task") if isinstance(embedded_config, dict) else None
    if not isinstance(task, dict):
        return None, None, None

    name = task.get("name")
    if isinstance(name, str) and "/" not in name:
        name = f"gnucleus-ai/{name}"
    ref = task.get("ref") or task.get("digest")
    source = task.get("source") or result.get("source")
    return (
        name if isinstance(name, str) else None,
        ref if isinstance(ref, str) else None,
        source if isinstance(source, str) else None,
    )


def _score_from_file(path: Path, field: str) -> tuple[float | None, str | None]:
    try:
        payload = _load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return None, f"{path}: cannot read score: {error}"
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None, f"{path}: {field!r} must be numeric"
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        return None, f"{path}: {field!r} must be finite and in [0, 1]"
    return score, None


def _trial_source_key(result: dict[str, Any]) -> dict[str, Any]:
    """Extract Harbor's leaderboard selection key from one trial result."""
    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict):
        agent_info = {}
    config = result.get("config")
    if not isinstance(config, dict):
        config = {}
    agent_config = config.get("agent")
    if not isinstance(agent_config, dict):
        agent_config = {}
    kwargs = agent_config.get("kwargs")
    if not isinstance(kwargs, dict):
        kwargs = {}

    model_info = agent_info.get("model_info")
    if not isinstance(model_info, dict):
        model_info = {}
    model = agent_config.get("model_name") or model_info.get("name")
    provider = model_info.get("provider")
    if (
        isinstance(model, str)
        and isinstance(provider, str)
        and provider
        and "/" not in model
    ):
        model = f"{provider}/{model}"

    return {
        "agent": agent_info.get("name") or agent_config.get("name"),
        "agent_version": agent_info.get("version"),
        "model": model,
        "reasoning_effort": kwargs.get("reasoning_effort"),
    }


def _harbor_job_id(result: dict[str, Any]) -> str | None:
    config = result.get("config")
    if not isinstance(config, dict):
        return None
    job_id = config.get("job_id")
    return job_id if isinstance(job_id, str) else None


def audit_artifacts(
    manifest: dict[str, Any], artifacts_root: Path, policy: dict[str, Any]
) -> list[str]:
    """Validate coverage, task digests, artifacts, and declared aggregates."""
    issues: list[str] = []
    if policy["tag"] == "v1":
        run_root = artifacts_root / manifest["results"]["runs_prefix"]
    else:
        run_root = artifacts_root
    if not run_root.is_dir():
        return [f"{run_root}: artifact root does not exist"]

    expected_tasks = policy["task_digests"]
    contract = policy["artifact_contract"]
    result_paths: list[Path] = []
    expected_source_filter: dict[str, Any] | None = None
    expected_job_ids: set[str] = set()
    seen_job_ids: set[str] = set()
    if policy["tag"] == "v2":
        expected_source_filter = manifest["results"]["source_filter"]
        for url in manifest["results"]["source_jobs"]:
            match = HARBOR_JOB_ID_PATTERN.fullmatch(url)
            if match:
                expected_job_ids.add(match.group(1))

    for path in sorted(run_root.rglob("result.json")):
        try:
            result = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            result_paths.append(path)
            continue
        if result.get("task_name") is None and result.get("task_id") is None:
            continue
        if expected_source_filter is not None:
            job_id = _harbor_job_id(result)
            if job_id is not None:
                seen_job_ids.add(job_id)
            if job_id not in expected_job_ids:
                continue
            if _trial_source_key(result) != expected_source_filter:
                continue
        result_paths.append(path)

    if expected_source_filter is not None:
        for job_id in sorted(expected_job_ids - seen_job_ids):
            issues.append(f"source Harbor job not found under artifact root: {job_id}")

    declared = manifest["declared"]
    if len(result_paths) != declared["total_trials"]:
        issues.append(
            f"{run_root}: found {len(result_paths)} trial result files; "
            f"manifest declares {declared['total_trials']}"
        )

    task_counts: Counter[str] = Counter()
    composite_scores: list[float] = []
    geometry_scores: list[float] = []
    spec_scores: list[float] = []
    exception_count = 0

    for result_path in result_paths:
        trial_dir = result_path.parent
        label = str(trial_dir.relative_to(run_root))
        config_path = trial_dir / "config.json"
        try:
            result = _load_json(result_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            issues.append(f"{result_path}: invalid JSON object: {error}")
            exception_count += 1
            composite_scores.append(0.0)
            geometry_scores.append(0.0)
            spec_scores.append(0.0)
            continue
        try:
            config = _load_json(config_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            issues.append(f"{config_path}: invalid or missing trial config: {error}")
            config = {}

        task_name, task_ref, source = _task_identity(result, config)
        if task_name is None:
            issues.append(f"{label}: cannot determine task name")
        else:
            task_counts[task_name] += 1
            expected_ref = expected_tasks.get(task_name)
            if expected_ref is None:
                issues.append(f"{label}: task {task_name!r} is not in {policy['tag']}")
            elif task_ref != expected_ref:
                issues.append(
                    f"{label}: task digest mismatch for {task_name}: "
                    f"expected {expected_ref}, got {task_ref}"
                )
        if source != policy["dataset"]:
            issues.append(
                f"{label}: expected task source {policy['dataset']!r}, got {source!r}"
            )

        has_exception = result.get("exception_info") is not None or bool(
            result.get("exception_type")
        )
        reward_path = _first_existing(
            trial_dir,
            [contract["reward_file"], f"verifier/{contract['reward_file']}"]
        )
        if reward_path is None:
            has_exception = True
            score = 0.0
        else:
            score, score_issue = _score_from_file(reward_path, contract["score_field"])
            if score_issue:
                issues.append(score_issue)
                score = 0.0
                has_exception = True

        trajectory = _first_existing(trial_dir, contract["trajectory_one_of"])
        if trajectory is None:
            issues.append(f"{label}: no accepted trajectory artifact found")
        agent_name = manifest["agent"]["name"]
        agent_log = _first_existing(
            trial_dir, ["agent.log", f"agent/{agent_name}.txt"]
        )
        if agent_log is None:
            issues.append(f"{label}: no accepted agent log found")

        if has_exception:
            exception_count += 1
            composite_scores.append(0.0)
            geometry_scores.append(0.0)
            spec_scores.append(0.0)
            continue

        assert score is not None
        details_path = _first_existing(
            trial_dir,
            [contract["details_file"], f"verifier/{contract['details_file']}"]
        )
        if details_path is None:
            issues.append(f"{label}: missing {contract['details_file']}")
            details: dict[str, Any] = {}
        else:
            try:
                details = _load_json(details_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                issues.append(f"{details_path}: invalid details JSON: {error}")
                details = {}

        detail_values: dict[str, float] = {}
        for field in contract["details_fields"]:
            value = details.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                issues.append(f"{label}: details field {field!r} must be numeric")
                detail_values[field] = 0.0
            else:
                numeric_value = float(value)
                if not math.isfinite(numeric_value) or not 0 <= numeric_value <= 1:
                    issues.append(f"{label}: details field {field!r} must be in [0, 1]")
                    numeric_value = 0.0
                detail_values[field] = numeric_value

        combined = detail_values.get("combined", 0.0)
        if abs(score - combined) > SCORE_TOLERANCE:
            issues.append(
                f"{label}: reward score {score:.8f} does not match "
                f"details combined {combined:.8f}"
            )

        answer_fcstd = _first_existing(
            trial_dir, ["answer.FCStd", "artifacts/app/answer.FCStd"]
        )
        answer_py = _first_existing(trial_dir, ["answer.py", "artifacts/app/answer.py"])
        if score > 0 and answer_fcstd is None:
            issues.append(f"{label}: positive-scoring trial is missing answer.FCStd")
        if score > 0 and answer_py is None:
            issues.append(f"{label}: positive-scoring trial is missing answer.py")

        composite_scores.append(score)
        geometry_scores.append(detail_values.get("geometry_similarity", 0.0))
        spec_scores.append(detail_values.get("cad_spec_consistency", 0.0))

    trials_per_task = declared["trials_per_task"]
    missing = sorted(set(expected_tasks) - set(task_counts))
    unknown = sorted(set(task_counts) - set(expected_tasks))
    wrong_counts = sorted(
        (task, count)
        for task, count in task_counts.items()
        if task in expected_tasks and count != trials_per_task
    )
    if missing:
        issues.append(f"missing {len(missing)} official tasks: {', '.join(missing)}")
    if unknown:
        issues.append(f"found {len(unknown)} unknown tasks: {', '.join(unknown)}")
    if wrong_counts:
        rendered = ", ".join(f"{task}={count}" for task, count in wrong_counts)
        issues.append(
            f"expected {trials_per_task} trials per official task; mismatches: {rendered}"
        )

    def compare_mean(field: str, values: list[float]) -> None:
        if field not in declared or not values:
            return
        actual = sum(values) / len(values)
        if abs(actual - float(declared[field])) > SCORE_TOLERANCE:
            issues.append(
                f"$.declared.{field}: declared {declared[field]:.8f}, "
                f"audited {actual:.8f}"
            )

    compare_mean("mean_composite", composite_scores)
    compare_mean("mean_geometry_similarity", geometry_scores)
    compare_mean("mean_cad_spec_consistency", spec_scores)
    if exception_count != declared["exceptions"]:
        issues.append(
            f"$.declared.exceptions: declared {declared['exceptions']}, "
            f"audited {exception_count}"
        )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--artifacts-root",
        "--snapshot-root",
        dest="artifacts_root",
        required=True,
        type=Path,
        help=(
            "v2: directory containing only the downloaded source_jobs; "
            "v1 archive: root of the pinned Hugging Face snapshot"
        ),
    )
    args = parser.parse_args(argv)

    manifest = load_yaml(args.manifest)
    # Artifact audits remain available for the immutable v1 archive, even
    # though new v1 intake is closed.
    issues = validate_manifest(manifest, allow_archived=True)
    if not issues:
        policy = load_policies()[manifest["bench"]["tag"]]
        issues = audit_artifacts(manifest, args.artifacts_root, policy)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print(f"OK {args.manifest}: manifest and artifact tree are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
