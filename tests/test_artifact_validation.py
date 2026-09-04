from __future__ import annotations

import copy
import json
from pathlib import Path

from cad_bench_submission.artifact_validation import audit_artifacts


def _policy() -> dict:
    return {
        "dataset": "gnucleus-ai/cad-bench",
        "tag": "v2",
        "task_count": 2,
        "task_digests": {
            "gnucleus-ai/freecad-one": "sha256:" + "1" * 64,
            "gnucleus-ai/freecad-two": "sha256:" + "2" * 64,
        },
        "artifact_contract": {
            "reward_file": "reward.json",
            "score_field": "reward",
            "details_file": "reward_details.json",
            "details_fields": [
                "geometry_similarity",
                "cad_spec_consistency",
                "combined",
            ],
            "trajectory_one_of": ["trajectory.json", "agent/trajectory.json"],
        },
    }


def _manifest() -> dict:
    return {
        "results": {
            "source_jobs": [
                "https://hub.harborframework.com/jobs/"
                "11111111-1111-4111-8111-111111111111"
            ],
            "source_filter": {
                "agent": "codex",
                "agent_version": "1.0.0",
                "model": "openai/model",
                "reasoning_effort": "max",
            },
        },
        "agent": {"name": "codex"},
        "declared": {
            "trials_per_task": 1,
            "total_trials": 2,
            "exceptions": 0,
            "mean_composite": 0.75,
            "mean_geometry_similarity": 0.7,
            "mean_cad_spec_consistency": 0.85,
        },
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_trial(root: Path, task: str, digest: str, score: float, geom: float, spec: float) -> None:
    trial = root / "11111111-1111-4111-8111-111111111111" / task.split("/")[-1]
    task_config = {"name": task, "ref": digest, "source": "gnucleus-ai/cad-bench"}
    _write_json(trial / "config.json", {"task": task_config})
    _write_json(
        trial / "result.json",
        {
            "task_id": task_config,
            "source": "gnucleus-ai/cad-bench",
            "exception_info": None,
            "agent_info": {
                "name": "codex",
                "version": "1.0.0",
                "model_info": {"name": "model", "provider": "openai"},
            },
            "config": {
                "job_id": "11111111-1111-4111-8111-111111111111",
                "agent": {
                    "name": "codex",
                    "model_name": "openai/model",
                    "kwargs": {"reasoning_effort": "max"},
                },
            },
        },
    )
    _write_json(trial / "verifier" / "reward.json", {"reward": score})
    _write_json(
        trial / "verifier" / "reward_details.json",
        {
            "geometry_similarity": geom,
            "cad_spec_consistency": spec,
            "combined": score,
        },
    )
    _write_json(trial / "agent" / "trajectory.json", {"schema_version": "1.0"})
    (trial / "agent" / "codex.txt").write_text("agent log", encoding="utf-8")
    (trial / "artifacts" / "app").mkdir(parents=True)
    (trial / "artifacts" / "app" / "answer.py").write_text("# generated", encoding="utf-8")
    (trial / "artifacts" / "app" / "answer.FCStd").write_bytes(b"FCStd")


def _valid_snapshot(tmp_path: Path) -> None:
    policy = _policy()
    _write_trial(
        tmp_path,
        "gnucleus-ai/freecad-one",
        policy["task_digests"]["gnucleus-ai/freecad-one"],
        0.5,
        0.4,
        0.8,
    )
    _write_trial(
        tmp_path,
        "gnucleus-ai/freecad-two",
        policy["task_digests"]["gnucleus-ai/freecad-two"],
        1.0,
        1.0,
        0.9,
    )


def test_valid_v2_artifact_tree(tmp_path: Path) -> None:
    _valid_snapshot(tmp_path)
    assert audit_artifacts(_manifest(), tmp_path, _policy()) == []


def test_rejects_task_from_wrong_dataset_version(tmp_path: Path) -> None:
    _valid_snapshot(tmp_path)
    config_path = (
        tmp_path
        / "11111111-1111-4111-8111-111111111111"
        / "freecad-one/config.json"
    )
    config = json.loads(config_path.read_text())
    config["task"]["ref"] = "sha256:" + "9" * 64
    _write_json(config_path, config)

    issues = audit_artifacts(_manifest(), tmp_path, _policy())
    assert any("task digest mismatch" in issue for issue in issues)


def test_rejects_partial_cohort(tmp_path: Path) -> None:
    policy = _policy()
    _write_trial(
        tmp_path,
        "gnucleus-ai/freecad-one",
        policy["task_digests"]["gnucleus-ai/freecad-one"],
        0.5,
        0.4,
        0.8,
    )
    issues = audit_artifacts(_manifest(), tmp_path, policy)
    assert any("found 1 trial result files" in issue for issue in issues)
    assert any("missing 1 official tasks" in issue for issue in issues)


def test_failed_trial_counts_as_zero(tmp_path: Path) -> None:
    _valid_snapshot(tmp_path)
    trial = (
        tmp_path
        / "11111111-1111-4111-8111-111111111111"
        / "freecad-two"
    )
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text())
    result["exception_info"] = {"type": "TimeoutError"}
    _write_json(result_path, result)
    (trial / "verifier" / "reward.json").unlink()

    manifest = copy.deepcopy(_manifest())
    manifest["declared"].update(
        {
            "exceptions": 1,
            "mean_composite": 0.25,
            "mean_geometry_similarity": 0.2,
            "mean_cad_spec_consistency": 0.4,
        }
    )
    assert audit_artifacts(manifest, tmp_path, _policy()) == []


def test_failed_trial_still_requires_trajectory(tmp_path: Path) -> None:
    _valid_snapshot(tmp_path)
    trial = (
        tmp_path
        / "11111111-1111-4111-8111-111111111111"
        / "freecad-two"
    )
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text())
    result["exception_info"] = {"type": "TimeoutError"}
    _write_json(result_path, result)
    (trial / "verifier" / "reward.json").unlink()
    (trial / "agent" / "trajectory.json").unlink()

    manifest = copy.deepcopy(_manifest())
    manifest["declared"].update(
        {
            "exceptions": 1,
            "mean_composite": 0.25,
            "mean_geometry_similarity": 0.2,
            "mean_cad_spec_consistency": 0.4,
        }
    )
    issues = audit_artifacts(manifest, tmp_path, _policy())
    assert any("no accepted trajectory artifact" in issue for issue in issues)
