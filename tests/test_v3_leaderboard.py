from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

import cad_bench_submission.build_v3_leaderboard_row as builder
from cad_bench_submission.validation import REPOSITORY_ROOT, load_policies


JOB_ID = "11111111-1111-4111-8111-111111111111"
DATASET_DIGEST = (
    "sha256:8a786725d3648a76282fc5868df06da3"
    "d5e00d603f283573a53430803465d78a"
)


def _manifest() -> dict:
    return {
        "schema_version": 3,
        "submission": {"version": 1, "submitted_at": "2026-09-08"},
        "contributor": {"handle": "octocat"},
        "bench": {
            "dataset": "gnucleus-ai/cad-bench",
            "tag": "v3",
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
    policy = load_policies()["v3"]
    for index, (task_name, digest) in enumerate(policy["task_digests"].items()):
        task_config = {"name": task_name, "ref": digest, "source": policy["dataset"]}
        lock_trials.append(
            {
                "task": task_config,
                "agent": {
                    "name": "codex",
                    "model_name": "example-model",
                    "kwargs": {"version": "1.2.3", "reasoning_effort": "max"},
                },
            }
        )
        reward = 1.0 if index < 50 else 0.5
        trial_dir = job / f"trial-{index:03d}"
        _write_json(trial_dir / "config.json", {"task": task_config})
        _write_json(trial_dir / "verifier/reward.json", {"reward": reward})
        details = {"geometry_similarity": reward, "cad_spec_consistency": reward, "combined": reward}
        mode = policy["task_modes"][task_name]
        if mode == "create_edit":
            details = {"combined": reward, "score": reward, "base": details, "target": details}
        _write_json(trial_dir / "verifier/reward_details.json", details)
        _write_json(trial_dir / "agent/trajectory.json", {"steps": []})
        (trial_dir / "agent/codex.txt").write_text("recorded agent log")
        for filename in policy["artifact_contract"]["mode_contracts"][mode]["answer_files"]:
            output = trial_dir / "artifacts/app" / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("fixture artifact; CAD validity is checked during manual re-grade")
        _write_json(
            job / f"trial-{index:03d}" / "result.json",
            {
                "id": str(uuid.UUID(int=index + 1)),
                "task_name": task_name,
                "agent_info": {"name": "codex", "version": "1.2.3"},
                "config": {
                    "job_id": JOB_ID, "task": task_config,
                    "agent": {"name": "codex", "model_name": "openai/example-model", "kwargs": {"reasoning_effort": "max"}},
                },
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
            "harbor": {"version": "0.23.0"},
            "retry": {"max_retries": 0},
            "trials": lock_trials,
        },
    )
    return job


def _definition() -> dict:
    return yaml.safe_load(
        (REPOSITORY_ROOT / "leaderboards/v3.yaml").read_text(encoding="utf-8")
    )


def test_v3_definition_matches_live_leaderboard_contract() -> None:
    definition = _definition()
    policy = json.loads(
        (REPOSITORY_ROOT / "benchmarks/v3.json").read_text(encoding="utf-8")
    )
    assert definition["package"] == "gnucleus-ai/cad-bench"
    assert definition["name"] == "v3"
    assert definition["title"] == "Parametric CAD Bench v3"
    assert definition["visibility"] == "public"
    assert definition["dataset_version_refs"] == ["v3"]
    assert policy["leaderboard"] == "v3"
    assert [column["id"] for column in definition["columns"]] == [
        "agent",
        "model",
        "effort",
        "score",
        "create",
        "create_edit",
        "image_to_cad",
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
    assert row["metadata"]["benchmark_tag"] == "v3"
    policy = load_policies()["v3"]
    for mode, count in policy["mode_counts"].items():
        expected = sum(
            1.0 if index < 50 else 0.5
            for index, name in enumerate(policy["task_digests"])
            if policy["task_modes"][name] == mode
        ) / count
        assert row["metrics"][f"{mode}_mean_reward"] == pytest.approx(expected)
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

    with pytest.raises(ValueError, match="enabled retries"):
        builder.build_row(_manifest(), job)


def _trial_for_mode(job: Path, mode: str) -> Path:
    policy = load_policies()["v3"]
    return next(
        path.parent for path in sorted(job.glob("*/result.json"))
        if policy["task_modes"][json.loads(path.read_text())["task_name"]] == mode
    )


@pytest.mark.parametrize("mode,filename", [
    ("create", "answer.FCStd"),
    ("image_to_cad", "answer.FCStd"),
    ("create_edit", "answer_base.FCStd"),
    ("create_edit", "answer_edit.FCStd"),
    ("create_edit", "answer.py"),
])
def test_positive_scores_require_mode_specific_outputs(tmp_path, mode, filename):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, mode)
    (trial / "artifacts/app" / filename).unlink()
    with pytest.raises(ValueError, match=f"missing {filename}"):
        builder.build_row(_manifest(), job)


def test_create_edit_nested_scores_are_validated(tmp_path):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, "create_edit")
    details = json.loads((trial / "verifier/reward_details.json").read_text())
    details["target"]["combined"] = 0
    _write_json(trial / "verifier/reward_details.json", details)
    with pytest.raises(ValueError, match="base/target harmonic mean"):
        builder.build_row(_manifest(), job)


@pytest.mark.parametrize("mode", ["create", "create_edit", "image_to_cad"])
def test_published_zero_envelope_is_scored_and_keeps_mode_denominator(tmp_path, mode):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, mode)
    result = json.loads((trial / "result.json").read_text())
    previous = result["verifier_result"]["rewards"]["reward"]
    result["verifier_result"]["rewards"]["reward"] = 0
    _write_json(trial / "result.json", result)
    _write_json(trial / "verifier/reward.json", {"reward": 0})
    _write_json(trial / "verifier/reward_details.json", {"score": 0, "reason": "candidate did not produce output"})
    for path in (trial / "artifacts/app").iterdir():
        path.unlink()
    manifest = _manifest()
    manifest["declared"]["mean_reward"] -= previous / 100
    row = builder.build_row(manifest, job)
    assert row["metrics"]["n_errors"] == 0
    assert row["metrics"]["mean_reward"] == pytest.approx(manifest["declared"]["mean_reward"])
    assert sum(row["metrics"][f"{m}_mean_reward"] * n for m, n in load_policies()["v3"]["mode_counts"].items()) / 100 == pytest.approx(row["metrics"]["mean_reward"])


def test_wrong_task_digest_is_rejected_before_publication(tmp_path):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, "create_edit")
    config = json.loads((trial / "config.json").read_text())
    config["task"]["ref"] = "sha256:" + "0" * 64
    _write_json(trial / "config.json", config)
    with pytest.raises(ValueError, match="task digest mismatch"):
        builder.build_row(_manifest(), job)


def test_result_reward_cannot_disagree_with_verifier(tmp_path):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, "create")
    result = json.loads((trial / "result.json").read_text())
    result["verifier_result"]["rewards"]["reward"] = 0.123
    _write_json(trial / "result.json", result)
    with pytest.raises(ValueError, match="result.json reward does not match"):
        builder.build_row(_manifest(), job)


def test_verifier_retained_answers_are_accepted(tmp_path):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, "create_edit")
    (trial / "artifacts/app").rename(trial / "agent/answer")
    assert builder.build_row(_manifest(), job)["metrics"]["n_trials"] == 100


@pytest.mark.parametrize("tag", ["v1", "v2"])
def test_builder_rejects_old_versions(tmp_path, tag):
    manifest = _manifest()
    manifest["bench"]["tag"] = tag
    with pytest.raises(ValueError, match="only v3 submissions"):
        builder.build_row(manifest, tmp_path)


def test_old_harbor_runtime_is_rejected(tmp_path):
    job = _job(tmp_path)
    lock = json.loads((job / "lock.json").read_text())
    lock["harbor"]["version"] = "0.20.0"
    _write_json(job / "lock.json", lock)
    with pytest.raises(ValueError, match="Harbor 0.23.0"):
        builder.build_row(_manifest(), job)


def test_duplicate_trial_ids_are_rejected(tmp_path):
    job = _job(tmp_path)
    paths = sorted(job.glob('*/result.json'))
    first = json.loads(paths[0].read_text())
    second = json.loads(paths[1].read_text())
    second['id'] = first['id']
    _write_json(paths[1], second)
    with pytest.raises(ValueError, match='trial IDs must be unique'):
        builder.build_row(_manifest(), job)


def _hosted_job(tmp_path):
    """Construct the layout observed in published hosted job eefb6a64."""
    job = _job(tmp_path)
    config = json.loads((job / 'config.json').read_text())
    config['datasets'][0]['overwrite'] = False
    _write_json(job / 'config.json', config)
    lock = json.loads((job / 'lock.json').read_text())
    for path, entry in zip(sorted(job.glob('*/result.json')), lock['trials'], strict=True):
        task = entry['task']
        extracted = f'/tmp/hosted-harbor-task-{path.parent.name}/task'
        task.update(name='task', type='local', path=extracted, digest=task.pop('ref'))
        _write_json(path.parent / 'lock.json', entry)
        trial_config = {
            'task': {'path': extracted, 'source': 'gnucleus-ai/cad-bench'},
            'environment': {'type': 'modal', 'import_path': 'hosted_harbor.isolation.environment:SupervisorEnvironment'},
        }
        _write_json(path.parent / 'config.json', trial_config)
        result = json.loads(path.read_text())
        result['task_id'] = {'path': extracted}
        result['config'].update(trial_config)
        _write_json(path, result)
    _write_json(job / 'lock.json', lock)
    return job


def test_hosted_complete_cohort_is_accepted(tmp_path):
    job = _hosted_job(tmp_path)
    # Root lock ordering is not an identity signal.
    lock = json.loads((job / 'lock.json').read_text())
    lock['trials'].reverse()
    _write_json(job / 'lock.json', lock)
    row = builder.build_row(_manifest(), job)
    assert row['metrics']['mean_reward'] == pytest.approx(0.75)
    assert row['metrics']['n_trials'] == 100


@pytest.mark.parametrize('change', ['missing', 'digest', 'path', 'source'])
def test_hosted_trial_lock_is_required_and_bound_to_the_trial(tmp_path, change):
    job = _hosted_job(tmp_path)
    path = next(job.glob('*/lock.json'))
    if change == 'missing':
        path.unlink()
    else:
        lock = json.loads(path.read_text())
        lock['task'][change] = {'digest': 'sha256:' + '0' * 64, 'path': '/tmp/other/task', 'source': 'other/dataset'}[change]
        _write_json(path, lock)
    with pytest.raises(ValueError, match='artifact audit failed'):
        builder.build_row(_manifest(), job)


def test_hosted_root_lock_cannot_substitute_other_tasks(tmp_path):
    job = _hosted_job(tmp_path)
    lock = json.loads((job / 'lock.json').read_text())
    lock['trials'][0]['task']['digest'] = lock['trials'][1]['task']['digest']
    _write_json(job / 'lock.json', lock)
    with pytest.raises(ValueError, match='100 unique tasks'):
        builder.build_row(_manifest(), job)


def test_antigravity_native_logs_and_observed_version_are_accepted(tmp_path):
    """Construct the log/version contract observed in job 57efd748."""
    job = _job(tmp_path)
    manifest = _manifest()
    manifest['agent']['name'] = 'antigravity-cli'
    manifest['results']['source_filter']['agent'] = 'antigravity-cli'
    lock = json.loads((job / 'lock.json').read_text())
    for entry in lock['trials']:
        entry['agent']['name'] = 'antigravity-cli'
        del entry['agent']['kwargs']['version']
    _write_json(job / 'lock.json', lock)
    for path in job.glob('*/result.json'):
        result = json.loads(path.read_text())
        result['agent_info']['name'] = 'antigravity-cli'
        result['config']['agent']['name'] = 'antigravity-cli'
        _write_json(path, result)
        agent_dir = path.parent / 'agent'
        (agent_dir / 'codex.txt').unlink()
        (agent_dir / 'antigravity-cli.err').write_text('')
        (agent_dir / 'antigravity-stream.jsonl').write_text('{}\n')
    assert builder.build_row(manifest, job)['metrics']['n_trials'] == 100
    next(job.glob('*/agent/antigravity-stream.jsonl')).unlink()
    with pytest.raises(ValueError, match='no accepted agent log'):
        builder.build_row(manifest, job)


def test_scorer_crash_with_finite_zero_is_scored(tmp_path):
    job = _job(tmp_path)
    trial = _trial_for_mode(job, 'create')
    result = json.loads((trial / 'result.json').read_text())
    previous = result['verifier_result']['rewards']['reward']
    result['verifier_result']['rewards']['reward'] = 0
    _write_json(trial / 'result.json', result)
    _write_json(trial / 'verifier/reward.json', {'reward': 0})
    _write_json(trial / 'verifier/reward_details.json', {'score': 0, 'reason': 'scorer crashed'})
    manifest = _manifest()
    manifest['declared']['mean_reward'] -= previous / 100
    row = builder.build_row(manifest, job)
    assert row['metrics']['n_errors'] == 0
    assert row['metrics']['scored_rate'] == 1


def test_hosted_job_without_root_lock_requires_original_evidence(tmp_path):
    job = _hosted_job(tmp_path)
    (job / 'lock.json').unlink()
    with pytest.raises(ValueError, match='job lock.json is required'):
        builder.build_row(_manifest(), job)
