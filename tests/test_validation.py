from __future__ import annotations

import copy
import json

import pytest

from cad_bench_submission.validation import (
    REPOSITORY_ROOT,
    load_yaml,
    validate_manifest,
    validate_manifest_file,
    validate_repository_layout,
)


@pytest.fixture
def v2_manifest() -> dict:
    return {
        "schema_version": 2,
        "submission": {"version": 1, "submitted_at": "2026-09-03"},
        "contributor": {"handle": "octocat"},
        "bench": {
            "dataset": "gnucleus-ai/cad-bench",
            "tag": "v2",
            "dataset_content_hash": (
                "sha256:ab2e040d0adcfd2779b4f1ad554890cd"
                "98b5aa19845e00162933ba165144fe56"
            ),
        },
        "agent": {
            "name": "codex",
            "display_name": "Codex",
            "display_url": "https://openai.com/codex/",
            "version": "1.0.0",
            "reasoning_effort": "max",
            "auth_mode": "api-key",
        },
        "model": {
            "id": "openai/gpt-5.6-sol",
            "display_name": "GPT-5.6-Sol",
            "display_url": "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        },
        "results": {
            "source_jobs": [
                "https://hub.harborframework.com/jobs/"
                "01234567-89ab-cdef-0123-456789abcdef"
            ],
            "source_filter": {
                "agent": "codex",
                "agent_version": "1.0.0",
                "model": "openai/gpt-5.6-sol",
                "reasoning_effort": "max",
            },
        },
        "declared": {
            "mean_reward": 0.8,
            "trials_per_task": 1,
            "total_trials": 100,
            "n_errors": 0,
        },
    }


def test_every_accepted_v1_manifest_remains_valid() -> None:
    manifests = sorted((REPOSITORY_ROOT / "submissions" / "v1").glob("*.yaml"))
    assert manifests
    for path in manifests:
        assert validate_manifest_file(path, allow_archived=True) == [], path


def test_v1_intake_is_closed() -> None:
    path = next((REPOSITORY_ROOT / "submissions" / "v1").glob("*.yaml"))
    issues = validate_manifest_file(path)
    assert any("v1 submissions are closed" in issue for issue in issues)


def test_closed_v1_policy_is_reported_before_schema_noise(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["bench"]["tag"] = "v1"
    issues = validate_manifest(manifest)
    assert issues == [
        "$.bench.tag: v1 submissions are closed; submit against "
        "gnucleus-ai/cad-bench@v2"
    ]


def test_v2_template_is_valid() -> None:
    template = REPOSITORY_ROOT / "submissions" / "_template" / "example-v2.yaml"
    assert validate_manifest_file(template) == []


def test_valid_v2_manifest(v2_manifest: dict) -> None:
    assert validate_manifest(v2_manifest) == []


def test_v2_requires_frozen_dataset_digest(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    del manifest["bench"]["dataset_content_hash"]
    issues = validate_manifest(manifest)
    assert any("dataset_content_hash" in issue for issue in issues)


def test_v2_rejects_wrong_dataset_digest(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["bench"]["dataset_content_hash"] = "sha256:" + "0" * 64
    issues = validate_manifest(manifest)
    assert any("frozen v2 digest" in issue for issue in issues)


def test_v2_requires_reasoning_effort(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    del manifest["agent"]["reasoning_effort"]
    issues = validate_manifest(manifest)
    assert any("reasoning_effort" in issue for issue in issues)


def test_v2_requires_mean_reward(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    del manifest["declared"]["mean_reward"]
    issues = validate_manifest(manifest)
    assert any("mean_reward" in issue for issue in issues)


def test_v2_requires_live_display_and_auth_metadata(v2_manifest: dict) -> None:
    for section, field in (
        ("agent", "display_name"),
        ("agent", "display_url"),
        ("agent", "auth_mode"),
        ("model", "display_name"),
        ("model", "display_url"),
    ):
        manifest = copy.deepcopy(v2_manifest)
        del manifest[section][field]
        issues = validate_manifest(manifest)
        assert any(field in issue for issue in issues)


def test_v2_requires_one_complete_cohort(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["declared"]["trials_per_task"] = 2
    manifest["declared"]["total_trials"] = 200
    issues = validate_manifest(manifest)
    assert any("trials_per_task" in issue for issue in issues)
    assert any("total_trials" in issue for issue in issues)


def test_v2_requires_one_source_job(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["results"]["source_jobs"].append(
        "https://hub.harborframework.com/jobs/11111111-1111-4111-8111-111111111111"
    )
    issues = validate_manifest(manifest)
    assert any("source_jobs" in issue for issue in issues)


def test_v2_requires_public_harbor_job_url(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["results"]["source_jobs"] = [
        "https://huggingface.co/datasets/octocat/results"
    ]
    issues = validate_manifest(manifest)
    assert any("does not match" in issue and "source_jobs" in issue for issue in issues)


def test_source_filter_must_match_manifest_metadata(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["results"]["source_filter"]["model"] = "openai/a-different-model"
    issues = validate_manifest(manifest)
    assert any("source_filter.model" in issue for issue in issues)


def test_total_trials_uses_version_task_count(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["declared"]["total_trials"] = 99
    issues = validate_manifest(manifest)
    assert any("expected 1 × 100 = 100" in issue for issue in issues)


def test_unknown_benchmark_version_is_rejected(v2_manifest: dict) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["bench"]["tag"] = "v3"
    issues = validate_manifest(manifest)
    assert any("'v2' was expected" in issue for issue in issues)
    assert any("no benchmark policy" in issue for issue in issues)


def test_example_is_parseable_mapping() -> None:
    template = REPOSITORY_ROOT / "submissions" / "_template" / "example-v2.yaml"
    assert load_yaml(template)["bench"]["tag"] == "v2"


def test_repository_layout_is_versioned() -> None:
    assert validate_repository_layout() == []


def test_top_level_manifest_is_rejected(tmp_path) -> None:
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "old-layout.yaml").write_text("bench: {}\n", encoding="utf-8")
    issues = validate_repository_layout(tmp_path)
    assert any("accepted only as .yaml files" in issue for issue in issues)


def test_manifest_tag_must_match_versioned_directory(
    tmp_path, v2_manifest: dict
) -> None:
    manifest = copy.deepcopy(v2_manifest)
    manifest["bench"]["tag"] = "v1"
    path = tmp_path / "submissions" / "v2" / "wrong-tag.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    issues = validate_manifest_file(path)
    assert issues[0] == (
        "$.bench.tag: manifests under submissions/v2/ must declare 'v2', got 'v1'"
    )
