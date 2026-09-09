from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

import cad_bench_submission.build_v2_leaderboard_row as builder
from cad_bench_submission.validation import REPOSITORY_ROOT


JOB_ID = "11111111-1111-4111-8111-111111111111"
DATASET_DIGEST = (
    "sha256:ab2e040d0adcfd2779b4f1ad554890cd"
    "98b5aa19845e00162933ba165144fe56"
)


def _manifest() -> dict:
    return {
        "schema_version": 2,
        "submission": {"version": 1, "submitted_at": "2026-09-08"},
        "contributor": {"handle": "octocat"},
        "bench": {
            "dataset": "gnucleus-ai/cad-bench",
            "tag": "v2",
            "dataset_content_hash": DATASET_DIGEST,
        },
        "agent": {
            "name": "codex",
            "display_name": "Codex",
            "display_url": "https://openai.com/codex/",
            "version": "1.2.3",
            "reasoning_effort": "max",
            "auth_mode": "api-key",
        },
        "model": {
            "id": "openai/example-model",
            "display_name": "Example Model",
            "display_url": "https://example.com/models/example-model",
        },
        "results": {
            "source_jobs": [f"https://hub.harborframework.com/jobs/{JOB_ID}"],
            "source_filter": {
                "agent": "codex",
                "agent_version": "1.2.3",
                "model": "openai/example-model",
                "reasoning_effort": "max",
            },
        },
        "declared": {
            "mean_reward": 0.75,
            "trials_per_task": 1,
            "total_trials": 100,
            "n_errors": 0,
        },
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _job(tmp_path: Path) -> Path:
    job = tmp_path / "downloaded-job"
    _write_json(
        job / "result.json",
        {
            "id": JOB_ID,
            "n_total_trials": 100,
            "stats": {"n_retries": 0},
            "started_at": "2026-09-08T00:00:00Z",
            "finished_at": "2026-09-08T00:20:00Z",
        },
    )
    _write_json(
        job / "config.json",
        {"datasets": [{"name": "gnucleus-ai/cad-bench", "ref": DATASET_DIGEST}]},
    )
    lock_trials = []
    for index in range(100):
        task_name = f"gnucleus-ai/freecad-{index:010d}"
        lock_trials.append(
            {
                "task": {"name": task_name},
                "agent": {
                    "name": "codex",
                    "model_name": "example-model",
                    "kwargs": {"version": "1.2.3", "reasoning_effort": "max"},
                },
            }
        )
        reward = 1.0 if index < 50 else 0.5
        _write_json(
            job / f"trial-{index:03d}" / "result.json",
            {
                "id": str(uuid.UUID(int=index + 1)),
                "task_name": task_name,
                "exception_info": None,
                "started_at": "2026-09-08T00:00:00Z",
                "finished_at": "2026-09-08T00:00:10Z",
                "verifier_result": {"rewards": {"reward": reward}},
                "agent_result": {
                    "cost_usd": 1.0,
                    "n_input_tokens": 10,
                    "n_output_tokens": 20,
                },
            },
        )
    _write_json(
        job / "lock.json",
        {
            "harbor": {"version": "0.20.0"},
            "retry": {"max_retries": 0},
            "trials": lock_trials,
        },
    )
    return job


def _definition() -> dict:
    return yaml.safe_load(
        (REPOSITORY_ROOT / "leaderboards/v2.yaml").read_text(encoding="utf-8")
    )


def test_v2_definition_matches_live_leaderboard_contract() -> None:
    definition = _definition()
    policy = json.loads(
        (REPOSITORY_ROOT / "benchmarks/v2.json").read_text(encoding="utf-8")
    )
    assert definition["package"] == "gnucleus-ai/cad-bench"
    assert definition["name"] == "v2"
    assert definition["title"] == "Parametric CAD Bench v2"
    assert definition["visibility"] == "public"
    assert definition["dataset_version_refs"] == ["v2"]
    assert policy["leaderboard"] == "v2"
    assert [column["id"] for column in definition["columns"]] == [
        "agent",
        "model",
        "effort",
        "score",
        "scored",
        "perfect",
        "avg_runtime",
        "cost",
        "date",
        "run",
    ]
    assert definition["rank_by"] == [
        {"accessor": "metrics.mean_reward", "direction": "desc", "nulls": "last"},
        {"accessor": "metrics.scored_rate", "direction": "desc", "nulls": "last"},
    ]


def test_builds_hidden_row_matching_live_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(tmp_path)
    monkeypatch.setattr(builder, "audit_artifacts", lambda *_args, **_kwargs: [])

    row = builder.build_row(_manifest(), job)
    definition = _definition()
    checker = FormatChecker()
    Draft202012Validator(
        definition["metadata_schema"], format_checker=checker
    ).validate(row["metadata"])
    Draft202012Validator(
        definition["metrics_schema"], format_checker=checker
    ).validate(row["metrics"])

    assert row["status"] == "hide"
    assert len(row["trial_ids"]) == 100
    assert row["metadata"]["job_display"]["label"] == "11111111"
    assert row["metadata"]["dataset_digest"] == DATASET_DIGEST
    assert row["metrics"]["mean_reward"] == pytest.approx(0.75)
    assert row["metrics"]["scored_rate"] == 1
    assert row["metrics"]["perfect_rate"] == 0.5
    assert row["metrics"]["n_trials"] == 100
    assert row["metrics"]["n_errors"] == 0
    assert row["metrics"]["known_cost_usd"] == 100
    assert row["metrics"]["cost_coverage"] == 1
    assert row["metrics"]["known_total_tokens"] == 3000
    assert row["metrics"]["token_coverage"] == 1


def test_builder_rejects_retry_enabled_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(tmp_path)
    lock_path = job / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["retry"]["max_retries"] = 1
    _write_json(lock_path, lock)
    monkeypatch.setattr(builder, "audit_artifacts", lambda *_args, **_kwargs: [])

    with pytest.raises(ValueError, match="enabled retries"):
        builder.build_row(_manifest(), job)
