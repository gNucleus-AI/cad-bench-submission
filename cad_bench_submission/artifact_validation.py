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
    result: dict[str, Any], config: dict[str, Any], lock: dict[str, Any] | None = None
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
    # Hosted Harbor extracts the package to a temporary local directory. The
    # result retains its public name; the trial lock retains its content hash.
    if name is None and task.get("path") and lock is not None:
        locked = lock.get("task", {})
        environment = config.get("environment") or {}
        if (
            environment.get("import_path") == "hosted_harbor.isolation.environment:SupervisorEnvironment"
            and locked.get("type") == "local"
            and locked.get("name") == "task"
            and locked.get("path") == task["path"]
            and locked.get("source") == task.get("source")
        ):
            name = result.get("task_name")
            task = {"name": name, "digest": locked.get("digest"), "source": locked.get("source")}
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


def _detail_value(details: dict[str, Any], field: str) -> Any:
    value: Any = details
    for key in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


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
    if policy["tag"] in {"v2", "v3"}:
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
    reward_scores: list[float] = []
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
            reward_scores.append(0.0)
            continue
        try:
            config = _load_json(config_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            issues.append(f"{config_path}: invalid or missing trial config: {error}")
            config = {}

        trial_lock = None
        if policy["tag"] == "v3" and (config.get("task") or {}).get("path"):
            try:
                trial_lock = _load_json(trial_dir / "lock.json")
            except (OSError, ValueError) as error:
                issues.append(f"{label}: missing or invalid hosted trial lock: {error}")
        task_name, task_ref, source = _task_identity(result, config, trial_lock)
        mode = policy.get("task_modes", {}).get(task_name)
        task_contract = contract.get("mode_contracts", {}).get(mode, contract)
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

        if policy["tag"] == "v3":
            recorded = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            if not isinstance(recorded, (int, float)) or isinstance(recorded, bool) or not math.isfinite(recorded):
                has_exception = True
            elif not has_exception and score is not None and abs(recorded - score) > SCORE_TOLERANCE:
                issues.append(f"{label}: result.json reward does not match reward.json")

        trajectory = _first_existing(trial_dir, contract["trajectory_one_of"])
        if trajectory is None:
            issues.append(f"{label}: no accepted trajectory artifact found")
        agent_name = manifest["agent"]["name"]
        agent_log = _first_existing(
            trial_dir, ["agent.log", f"agent/{agent_name}.txt"]
        )
        if agent_log is None:
            antigravity_logs = (
                agent_name == "antigravity-cli"
                and (trial_dir / "agent/antigravity-cli.err").is_file()
                and (trial_dir / "agent/antigravity-stream.jsonl").is_file()
            )
            if not antigravity_logs:
                issues.append(f"{label}: no accepted agent log found")

        if has_exception:
            exception_count += 1
            reward_scores.append(0.0)
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

        # All three published v3 verifiers emit this envelope for a scored zero
        # such as missing candidate output or a scorer crash. This matches the
        # published rows: a finite zero reward is scored, not an unscored error.
        if (
            policy["tag"] == "v3" and score == 0
            and type(details.get("score")) in (int, float)
            and details["score"] == 0
            and isinstance(details.get("reason"), str) and details["reason"].strip()
            and "combined" not in details
        ):
            reward_scores.append(0.0)
            continue

        detail_values: dict[str, float] = {}
        for field in task_contract.get("details_fields", ["combined"]):
            value = _detail_value(details, field)
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

        if mode == "create_edit":
            base = detail_values.get("base.combined", 0.0)
            target = detail_values.get("target.combined", 0.0)
            expected = 2 * base * target / (base + target) if base + target else 0.0
            if abs(combined - expected) > SCORE_TOLERANCE:
                issues.append(f"{label}: combined does not match base/target harmonic mean")

        for filename in task_contract.get("answer_files", ["answer.FCStd", "answer.py"]):
            candidates = [filename, f"artifacts/app/{filename}"]
            if policy["tag"] == "v3":
                candidates.append(f"agent/answer/{filename}")
            if score > 0 and _first_existing(trial_dir, candidates) is None:
                issues.append(f"{label}: positive-scoring trial is missing {filename}")

        reward_scores.append(score)

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

    mean_field = "mean_composite" if policy["tag"] == "v1" else "mean_reward"
    compare_mean(mean_field, reward_scores)
    error_field = "exceptions" if policy["tag"] == "v1" else "n_errors"
    if exception_count != declared[error_field]:
        issues.append(
            f"$.declared.{error_field}: declared {declared[error_field]}, "
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
            "v3: directory containing only the downloaded source_jobs; "
            "v1 archive: root of the pinned Hugging Face snapshot"
        ),
    )
    parser.add_argument(
        "--allow-archived", action="store_true",
        help="Historical v1/v2 audit only; does not enable submission intake.",
    )
    args = parser.parse_args(argv)

    manifest = load_yaml(args.manifest)
    # Artifact audits remain available for the immutable v1 archive, even
    # though new v1 intake is closed.
    issues = validate_manifest(manifest, allow_archived=args.allow_archived)
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
