from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from cad_bench_submission.build_v1_leaderboard import DATASET_HASH
from cad_bench_submission.validation import REPOSITORY_ROOT


LEADERBOARD_DIR = REPOSITORY_ROOT / "leaderboards"


def _definition() -> dict:
    return yaml.safe_load((LEADERBOARD_DIR / "v1.yaml").read_text(encoding="utf-8"))


def _payload() -> dict:
    return json.loads((LEADERBOARD_DIR / "v1-rows.json").read_text(encoding="utf-8"))


def _source_metrics() -> dict:
    return json.loads(
        (LEADERBOARD_DIR / "v1-source-metrics.json").read_text(encoding="utf-8")
    )


def test_v1_leaderboard_definition_is_private_first() -> None:
    definition = _definition()
    assert definition["package"] == "gnucleus-ai/cad-bench"
    assert definition["name"] == "v1"
    assert definition["visibility"] == "private"
    assert definition["metadata_schema"]["properties"]["dataset_content_hash"][
        "const"
    ] == DATASET_HASH
    assert definition["rank_by"] == [
        {"accessor": "metrics.combined", "direction": "desc", "nulls": "last"}
    ]
    assert [column["id"] for column in definition["columns"]] == [
        "model",
        "agent",
        "geometry",
        "spec",
        "combined",
        "cost",
    ]


def test_v1_rows_match_schemas_and_are_complete() -> None:
    definition = _definition()
    rows = _payload()["rows"]
    metadata_validator = Draft202012Validator(definition["metadata_schema"])
    metrics_validator = Draft202012Validator(definition["metrics_schema"])

    assert len(rows) == 28
    assert sum(row["metadata"]["submission_type"] == "baseline" for row in rows) == 10
    assert sum(
        row["metadata"]["submission_type"] == "contributor" for row in rows
    ) == 18
    assert all(not row["trial_ids"] for row in rows)
    assert all(row["status"] == "display" for row in rows)

    identities = set()
    for row in rows:
        metadata_validator.validate(row["metadata"])
        metrics_validator.validate(row["metrics"])
        assert row["metadata"]["dataset_content_hash"] == DATASET_HASH
        assert row["metadata"]["source"]["url"].startswith(
            "https://huggingface.co/datasets/"
        )
        identity = (
            row["metadata"]["contributor"],
            row["metadata"]["agent"],
            row["metadata"]["model"],
            row["metadata"].get("reasoning_effort"),
        )
        assert identity not in identities
        identities.add(identity)

    scores = [row["metrics"]["combined"] for row in rows]
    assert scores == sorted(scores, reverse=True)


def test_source_metrics_match_frozen_manifests() -> None:
    snapshot = _source_metrics()
    assert snapshot["dataset_content_hash"] == DATASET_HASH
    assert len(snapshot["rows"]) == 18

    for manifest_path in sorted((REPOSITORY_ROOT / "submissions/v1").glob("*.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        recovered = snapshot["rows"][manifest_path.name]
        assert recovered["source"] == manifest["results"]
        assert recovered["task_count"] == 100
        assert recovered["reward_count"] + len(recovered["missing_reward_tasks"]) == 100
        assert recovered["declared_exceptions"] == manifest["declared"]["exceptions"]
        assert recovered["metrics"]["combined"] == pytest.approx(
            manifest["declared"]["mean_composite"], abs=5e-7
        )


def test_rows_preserve_frozen_declared_values() -> None:
    rows = _payload()["rows"]
    baselines = json.loads(
        (REPOSITORY_ROOT / "baselines/v1.json").read_text(encoding="utf-8")
    )
    baseline_rows = [
        row for row in rows if row["metadata"]["submission_type"] == "baseline"
    ]
    contributor_rows = [
        row for row in rows if row["metadata"]["submission_type"] == "contributor"
    ]

    for baseline in baselines["rows"]:
        row = next(
            row
            for row in baseline_rows
            if row["metadata"]["agent"] == baseline["agent"]["name"]
            and row["metadata"]["model"] == baseline["model"]["id"]
        )
        assert row["metrics"]["combined"] == baseline["metrics"]["combined"]
        assert row["metrics"]["cost_usd"] == baseline["metrics"]["cost_usd"]
        assert row["metrics"]["total_trials"] == baseline["trials"]

    for manifest_path in sorted((REPOSITORY_ROOT / "submissions/v1").glob("*.yaml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        candidates = [
            row
            for row in contributor_rows
            if row["metadata"]["contributor"] == manifest["contributor"]["handle"]
            and row["metadata"]["agent"] == manifest["agent"]["name"]
            and row["metadata"]["model"] == manifest["model"]["id"]
        ]
        if len(candidates) > 1:
            effort = "xhigh" if "xhigh" in manifest_path.stem else "high"
            candidates = [
                row
                for row in candidates
                if row["metadata"].get("reasoning_effort") == effort
            ]
        assert len(candidates) == 1
        row = candidates[0]
        assert row["metrics"]["combined"] == pytest.approx(
            manifest["declared"]["mean_composite"], abs=5e-7
        )
        assert row["metrics"]["cost_usd"] == manifest["declared"]["cost_usd"]
        assert row["metrics"]["total_trials"] == manifest["declared"]["total_trials"]
