from __future__ import annotations

import copy
import json

import pytest

from cad_bench_submission.validation import (
    REPOSITORY_ROOT,
    default_manifest_paths,
    load_policies,
    load_yaml,
    validate_manifest,
    validate_manifest_file,
    validate_repository_layout,
)


@pytest.fixture
def v3_manifest() -> dict:
    return {
        "schema_version": 3,
        "submission": {"version": 1, "submitted_at": "2026-09-03"},
        "contributor": {"handle": "octocat"},
        "bench": {
            "dataset": "gnucleus-ai/cad-bench",
            "tag": "v3",
            "dataset_content_hash": (
                "sha256:8a786725d3648a76282fc5868df06da3"
                "d5e00d603f283573a53430803465d78a"
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


def test_v2_intake_is_closed_even_for_a_valid_historical_manifest(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["schema_version"] = 2
    manifest["bench"].update(tag="v2", dataset_content_hash=load_policies()["v2"]["dataset_content_hash"])
    assert validate_manifest(manifest, allow_archived=True) == []
    assert validate_manifest(manifest) == [
        "$.bench.tag: v2 submissions are closed; submit against gnucleus-ai/cad-bench@v3"
    ]


@pytest.mark.parametrize("tag", ["v1", "v2"])
def test_new_manifest_in_closed_directory_is_rejected(tmp_path, tag: str, v3_manifest: dict) -> None:
    path = tmp_path / "submissions" / tag / "new.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(v3_manifest))
    assert validate_manifest_file(path)
    if tag == "v2":
        assert validate_repository_layout(tmp_path)


def test_v3_is_the_only_active_policy_and_default_directory(tmp_path, monkeypatch) -> None:
    import cad_bench_submission.validation as validation

    assert [tag for tag, policy in load_policies().items() if policy["accepting_submissions"]] == ["v3"]
    for tag in ("v1", "v2", "v3"):
        directory = tmp_path / "submissions" / tag
        directory.mkdir(parents=True)
        (directory / "example.yaml").write_text("{}")
    monkeypatch.setattr(validation, "REPOSITORY_ROOT", tmp_path)
    assert default_manifest_paths() == [tmp_path / "submissions/v3/example.yaml"]


def test_closed_v1_policy_is_reported_before_schema_noise(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["bench"]["tag"] = "v1"
    issues = validate_manifest(manifest)
    assert issues == [
        "$.bench.tag: v1 submissions are closed; submit against "
        "gnucleus-ai/cad-bench@v3"
    ]


def test_v3_template_is_valid() -> None:
    template = REPOSITORY_ROOT / "submissions" / "_template" / "example-v3.yaml"
    assert validate_manifest_file(template) == []


def test_valid_v3_manifest(v3_manifest: dict) -> None:
    assert validate_manifest(v3_manifest) == []


def test_v3_requires_frozen_dataset_digest(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    del manifest["bench"]["dataset_content_hash"]
    issues = validate_manifest(manifest)
    assert any("dataset_content_hash" in issue for issue in issues)


def test_v3_rejects_wrong_dataset_digest(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["bench"]["dataset_content_hash"] = "sha256:" + "0" * 64
    issues = validate_manifest(manifest)
    assert any("frozen v3 digest" in issue for issue in issues)


def test_v3_requires_reasoning_effort(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    del manifest["agent"]["reasoning_effort"]
    issues = validate_manifest(manifest)
    assert any("reasoning_effort" in issue for issue in issues)


def test_v3_requires_mean_reward(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    del manifest["declared"]["mean_reward"]
    issues = validate_manifest(manifest)
    assert any("mean_reward" in issue for issue in issues)


def test_v3_requires_live_display_and_auth_metadata(v3_manifest: dict) -> None:
    for section, field in (
        ("agent", "display_name"),
        ("agent", "display_url"),
        ("agent", "auth_mode"),
        ("model", "display_name"),
        ("model", "display_url"),
    ):
        manifest = copy.deepcopy(v3_manifest)
        del manifest[section][field]
        issues = validate_manifest(manifest)
        assert any(field in issue for issue in issues)


def test_v3_requires_one_complete_cohort(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["declared"]["trials_per_task"] = 2
    manifest["declared"]["total_trials"] = 200
    issues = validate_manifest(manifest)
    assert any("trials_per_task" in issue for issue in issues)
    assert any("total_trials" in issue for issue in issues)


def test_v3_requires_one_source_job(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["results"]["source_jobs"].append(
        "https://hub.harborframework.com/jobs/11111111-1111-4111-8111-111111111111"
    )
    issues = validate_manifest(manifest)
    assert any("source_jobs" in issue for issue in issues)


def test_v3_requires_public_harbor_job_url(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["results"]["source_jobs"] = [
        "https://huggingface.co/datasets/octocat/results"
    ]
    issues = validate_manifest(manifest)
    assert any("does not match" in issue and "source_jobs" in issue for issue in issues)


def test_source_filter_must_match_manifest_metadata(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["results"]["source_filter"]["model"] = "openai/a-different-model"
    issues = validate_manifest(manifest)
    assert any("source_filter.model" in issue for issue in issues)


def test_total_trials_uses_version_task_count(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["declared"]["total_trials"] = 99
    issues = validate_manifest(manifest)
    assert any("expected 1 × 100 = 100" in issue for issue in issues)


def test_unknown_benchmark_version_is_rejected(v3_manifest: dict) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["bench"]["tag"] = "v4"
    issues = validate_manifest(manifest)
    assert any("'v3' was expected" in issue for issue in issues)
    assert any("no benchmark policy" in issue for issue in issues)


def test_example_is_parseable_mapping() -> None:
    template = REPOSITORY_ROOT / "submissions" / "_template" / "example-v3.yaml"
    assert load_yaml(template)["bench"]["tag"] == "v3"


def test_repository_layout_is_versioned() -> None:
    assert validate_repository_layout() == []


def test_top_level_manifest_is_rejected(tmp_path) -> None:
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    (submissions / "old-layout.yaml").write_text("bench: {}\n", encoding="utf-8")
    issues = validate_repository_layout(tmp_path)
    assert any("accepted only as .yaml files" in issue for issue in issues)


def test_manifest_tag_must_match_versioned_directory(
    tmp_path, v3_manifest: dict
) -> None:
    manifest = copy.deepcopy(v3_manifest)
    manifest["bench"]["tag"] = "v1"
    path = tmp_path / "submissions" / "v3" / "wrong-tag.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    issues = validate_manifest_file(path)
    assert issues[0] == (
        "$.bench.tag: manifests under submissions/v3/ must declare 'v3', got 'v1'"
    )
