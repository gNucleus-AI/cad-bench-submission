"""Build one audited Parametric CAD Bench v2 Harbor leaderboard row."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from cad_bench_submission.artifact_validation import (
    HARBOR_JOB_ID_PATTERN,
    SCORE_TOLERANCE,
    audit_artifacts,
)
from cad_bench_submission.validation import (
    REPOSITORY_ROOT,
    load_policies,
    load_yaml,
    validate_manifest,
)


EXPECTED_TASKS = 100
EXPECTED_HARBOR_VERSION = "0.20.0"
LEADERBOARD_DEFINITION = REPOSITORY_ROOT / "leaderboards" / "v2.yaml"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _source_job_id(manifest: dict[str, Any]) -> str:
    source_jobs = manifest["results"]["source_jobs"]
    _require(len(source_jobs) == 1, "v2 rows require exactly one source job")
    match = HARBOR_JOB_ID_PATTERN.fullmatch(source_jobs[0])
    _require(match is not None, "source job is not a canonical Harbor Hub job URL")
    return match.group(1)


def _find_job_dir(artifacts_root: Path, job_id: str) -> Path:
    candidates: list[Path] = []
    for path in [artifacts_root / "result.json", *artifacts_root.rglob("result.json")]:
        try:
            payload = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if payload.get("id") == job_id and "n_total_trials" in payload:
            candidates.append(path.parent)
    unique = sorted(set(candidates))
    _require(unique, f"downloaded Harbor job {job_id} was not found under {artifacts_root}")
    _require(
        len(unique) == 1,
        f"found multiple downloaded roots for Harbor job {job_id}: {unique}",
    )
    return unique[0]


def _live_definition() -> dict[str, Any]:
    with LEADERBOARD_DEFINITION.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{LEADERBOARD_DEFINITION}: expected a YAML mapping")
    return value


def _validate_row_schema(row: dict[str, Any]) -> None:
    definition = _live_definition()
    checker = FormatChecker()
    metadata_issues = sorted(
        Draft202012Validator(
            definition["metadata_schema"], format_checker=checker
        ).iter_errors(row["metadata"]),
        key=lambda error: list(error.absolute_path),
    )
    metric_issues = sorted(
        Draft202012Validator(
            definition["metrics_schema"], format_checker=checker
        ).iter_errors(row["metrics"]),
        key=lambda error: list(error.absolute_path),
    )
    issues = [*metadata_issues, *metric_issues]
    if issues:
        rendered = "; ".join(error.message for error in issues)
        raise ValueError(f"generated row does not match live v2 schema: {rendered}")


def build_row(
    manifest: dict[str, Any],
    artifacts_root: Path,
    *,
    cost_audit_path: Path | None = None,
) -> dict[str, Any]:
    """Audit one complete Harbor job and return an import-ready hidden row."""
    policy = load_policies()["v2"]
    _require(policy["leaderboard"] == "v2", "v2 policy is not routed to v2")
    _require(policy["task_count"] == EXPECTED_TASKS, "v2 policy must contain 100 tasks")

    manifest_issues = validate_manifest(manifest)
    if manifest_issues:
        raise ValueError("invalid v2 manifest: " + "; ".join(manifest_issues))

    job_id = _source_job_id(manifest)
    job_dir = _find_job_dir(artifacts_root.resolve(), job_id)
    artifact_issues = audit_artifacts(manifest, job_dir, policy)
    if artifact_issues:
        raise ValueError("artifact audit failed: " + "; ".join(artifact_issues))

    root = _load_json(job_dir / "result.json")
    config_path = job_dir / "config.json"
    config = _load_json(config_path)
    lock = _load_json(job_dir / "lock.json")
    trials = [_load_json(path) for path in sorted(job_dir.glob("*/result.json"))]

    _require(root.get("id") == job_id, "source job URL does not match result.json")
    _require(root.get("n_total_trials") == EXPECTED_TASKS, "job must contain 100 trials")
    _require(len(trials) == EXPECTED_TASKS, "job directory must contain 100 trials")
    _require(root.get("stats", {}).get("n_retries") == 0, "job contains retries")
    _require(lock.get("retry", {}).get("max_retries") == 0, "job enabled retries")
    _require(
        lock.get("harbor", {}).get("version") == EXPECTED_HARBOR_VERSION,
        f"job must use Harbor {EXPECTED_HARBOR_VERSION}",
    )
    _require(
        config.get("datasets")
        == [{"name": policy["dataset"], "ref": policy["dataset_content_hash"]}],
        "job config does not pin the frozen v2 dataset digest",
    )

    expected_names = sorted(item["task"]["name"] for item in lock["trials"])
    actual_names = sorted(item["task_name"] for item in trials)
    _require(len(set(expected_names)) == EXPECTED_TASKS, "lock does not contain 100 unique tasks")
    _require(actual_names == expected_names, "trial cohort does not match the job lock")

    source_filter = manifest["results"]["source_filter"]
    lock_agents = {item["agent"]["name"] for item in lock["trials"]}
    lock_models = {item["agent"].get("model_name") for item in lock["trials"]}
    lock_efforts = {
        (item["agent"].get("kwargs") or {}).get("reasoning_effort")
        for item in lock["trials"]
    }
    lock_versions = {
        (item["agent"].get("kwargs") or {}).get("version")
        for item in lock["trials"]
    }
    _require(lock_agents == {source_filter["agent"]}, "agent does not match job lock")
    short_model = source_filter["model"].rsplit("/", 1)[-1]
    _require(
        all(model and model.rsplit("/", 1)[-1] == short_model for model in lock_models),
        "model does not match job lock",
    )
    _require(
        lock_efforts == {source_filter["reasoning_effort"]},
        "reasoning effort does not match job lock",
    )
    _require(
        lock_versions == {source_filter["agent_version"]},
        "agent version does not match job lock",
    )

    rewards: list[float] = []
    durations: list[float] = []
    known_costs: list[float] = []
    known_tokens: list[int] = []
    trial_ids: list[str] = []
    scored = 0
    perfect = 0
    for trial in trials:
        trial_ids.append(str(uuid.UUID(trial["id"])))
        value = ((trial.get("verifier_result") or {}).get("rewards") or {}).get(
            "reward"
        )
        if (
            trial.get("exception_info") is None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            reward = float(value)
            _require(0 <= reward <= 1, "trial reward is outside [0, 1]")
            scored += 1
            perfect += math.isclose(reward, 1.0, abs_tol=1e-12)
        else:
            reward = 0.0
        rewards.append(reward)

        duration = (
            _instant(trial["finished_at"]) - _instant(trial["started_at"])
        ).total_seconds()
        _require(duration >= 0, "trial has a negative duration")
        durations.append(duration)

        agent_result = trial.get("agent_result") or {}
        cost = agent_result.get("cost_usd")
        if (
            isinstance(cost, (int, float))
            and not isinstance(cost, bool)
            and math.isfinite(cost)
            and cost >= 0
        ):
            known_costs.append(float(cost))
        input_tokens = agent_result.get("n_input_tokens")
        output_tokens = agent_result.get("n_output_tokens")
        if (
            isinstance(input_tokens, int)
            and not isinstance(input_tokens, bool)
            and input_tokens >= 0
            and isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and output_tokens >= 0
        ):
            known_tokens.append(input_tokens + output_tokens)

    mean_reward = statistics.fmean(rewards)
    _require(
        abs(mean_reward - float(manifest["declared"]["mean_reward"]))
        <= SCORE_TOLERANCE,
        "result.json rewards do not match the declared and audited mean reward",
    )
    n_errors = EXPECTED_TASKS - scored
    _require(
        n_errors == manifest["declared"]["n_errors"],
        "result.json scored count does not match declared n_errors",
    )

    ci95 = 1.96 * statistics.stdev(rewards) / math.sqrt(EXPECTED_TASKS)
    cost_coverage = len(known_costs) / EXPECTED_TASKS
    token_coverage = len(known_tokens) / EXPECTED_TASKS
    known_cost = sum(known_costs)
    known_total_tokens = sum(known_tokens)
    if cost_audit_path is not None:
        audit = _load_json(cost_audit_path)
        short_model = source_filter["model"].rsplit("/", 1)[-1]
        expected_audit = {
            "job_id": job_id,
            "dataset_digest": policy["dataset_content_hash"],
            "agent": source_filter["agent"],
            "model": short_model,
            "reasoning_effort": source_filter["reasoning_effort"],
            "agent_version": source_filter["agent_version"],
        }
        for field, expected in expected_audit.items():
            _require(audit.get(field) == expected, f"cost audit {field} mismatch")
        _require(
            audit.get("priced_trajectory_coverage") == 1.0,
            "cost audit must cover every trajectory",
        )
        known_cost = float(audit["recomputed_standard_api_cost_usd"])
        _require(math.isfinite(known_cost) and known_cost >= 0, "invalid audited cost")
        cost_coverage = 1.0

    started = _instant(root["started_at"])
    finished = _instant(root["finished_at"])
    job_wall_time = (finished - started).total_seconds()
    _require(job_wall_time >= 0, "job has a negative wall time")
    agent = manifest["agent"]
    model = manifest["model"]
    row = {
        "metadata": {
            "agent_display": {
                "label": agent["display_name"],
                "url": agent["display_url"],
            },
            "model_display": {
                "label": model["display_name"],
                "url": model["display_url"],
            },
            "agent_name": agent["name"],
            "model_name": model["id"],
            "reasoning_effort": agent["reasoning_effort"],
            "agent_version": agent["version"],
            "harbor_version": lock["harbor"]["version"],
            "auth_mode": agent["auth_mode"],
            "run_date": started.date().isoformat(),
            "dataset_digest": policy["dataset_content_hash"],
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "job_display": {
                "label": job_id[:8],
                "url": manifest["results"]["source_jobs"][0],
            },
        },
        "metrics": {
            "mean_reward": mean_reward,
            "ci95_half_width": ci95,
            "display_score": f"{100 * mean_reward:.2f}% +/- {100 * ci95:.2f}",
            "scored_rate": scored / EXPECTED_TASKS,
            "display_scored_rate": f"{scored}/{EXPECTED_TASKS}",
            "perfect_rate": perfect / EXPECTED_TASKS,
            "display_perfect_rate": f"{perfect}/{EXPECTED_TASKS}",
            "n_trials": EXPECTED_TASKS,
            "n_errors": n_errors,
            "avg_trial_duration_sec": statistics.fmean(durations),
            "job_wall_time_sec": job_wall_time,
            "known_cost_usd": known_cost,
            "cost_coverage": cost_coverage,
            "display_cost": f"${known_cost:,.2f}" if cost_coverage == 1 else "N/A",
            "known_total_tokens": known_total_tokens,
            "token_coverage": token_coverage,
            "display_tokens": (
                f"{known_total_tokens:,}" if token_coverage == 1 else "N/A"
            ),
        },
        "status": "hide",
        "trial_ids": trial_ids,
    }
    _validate_row_schema(row)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--artifacts-root",
        required=True,
        type=Path,
        help="Downloaded Harbor job directory or a parent containing it.",
    )
    parser.add_argument(
        "--cost-audit",
        type=Path,
        help="Independent cost audit that overrides agent-reported API cost.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    manifest = load_yaml(args.manifest)
    row = build_row(
        manifest,
        args.artifacts_root,
        cost_audit_path=args.cost_audit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"rows": [row]}, indent=2) + "\n")
    print(f"Wrote hidden v2 leaderboard row to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
