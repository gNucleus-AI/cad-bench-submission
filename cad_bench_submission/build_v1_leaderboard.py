"""Build the frozen CAD-Bench v1 Harbor leaderboard from public artifacts."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from cad_bench_submission.validation import REPOSITORY_ROOT


DATASET_HASH = (
    "sha256:22be8aa80fdbf2d9844e73c9d91ee7e01082d70bcf706d347216d0b97bdf862e"
)
TASK_COUNT = 100
USER_AGENT = "cad-bench-submission-v1-publication/1.0"
COMBINED_TOLERANCE = 5e-7

# The frozen public uploads span three historical Harbor artifact layouts.
# Mapping by public dataset ID avoids probing nonexistent URLs and triggering
# public-host rate limits. These layouts affect artifact lookup only.
SOURCE_LAYOUTS = {
    "EricSpencer00/cad-bench-results": ("{task}", "reward.json"),
    "gnucleus-ai/cad-gen-freecad-bench": ("{task}", "reward.json"),
    "rekurin/cad-bench-results": ("{task}", "verifier/reward.json"),
    "SpongeCakeAllDay/cad-bench-freecad-agent-initial-runs": (
        "{task}",
        "reward.json",
    ),
    "xavierpeich/cad-bench-results": ("gnucleus-ai-{task}", "reward.json"),
}


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _read_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / hashlib.sha256(url.encode()).hexdigest()


def _download(url: str, cache_dir: Path) -> bytes:
    cache_path = _cache_path(cache_dir, url)
    if cache_path.exists():
        return cache_path.read_bytes()

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(data)
            return data
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            retry_after = int(error.headers.get("Retry-After", "5"))
            time.sleep(max(retry_after, 2**attempt))
        except (OSError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _reward_url(result: dict[str, Any], task: str) -> str:
    repo = result["hf_repo"]
    try:
        directory_template, reward_path = SOURCE_LAYOUTS[repo]
    except KeyError as error:
        raise ValueError(f"unsupported frozen public artifact layout: {repo}") from error

    directory = directory_template.format(task=task)
    path = f"{result['runs_prefix']}{directory}/{reward_path}"
    encoded_path = urllib.parse.quote(path, safe="/")
    return (
        f"https://huggingface.co/datasets/{repo}/resolve/"
        f"{result['hf_commit_oid']}/{encoded_path}?download=true"
    )


def _fetch_reward(
    result: dict[str, Any], task: str, cache_dir: Path
) -> tuple[str, dict[str, Any] | None]:
    url = _reward_url(result, task)
    missing_path = _cache_path(cache_dir, url).with_suffix(".missing")
    if missing_path.exists():
        return task, None
    try:
        return task, json.loads(_download(url, cache_dir))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        missing_path.parent.mkdir(parents=True, exist_ok=True)
        missing_path.write_text("404\n", encoding="utf-8")
        return task, None


def _aggregate_manifest(
    manifest_path: Path,
    task_names: list[str],
    cache_dir: Path,
    workers: int,
) -> dict[str, Any]:
    manifest = _read_manifest(manifest_path)
    result = manifest["results"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_fetch_reward, result, task, cache_dir)
            for task in task_names
        ]
        fetched = [future.result() for future in futures]

    found = [(task, reward) for task, reward in fetched if reward is not None]
    missing_reward_tasks = sorted(
        task for task, reward in fetched if reward is None
    )
    missing_subscores = sum(
        "geometry_similarity" not in reward
        or "cad_spec_consistency" not in reward
        or "combined" not in reward
        for _, reward in found
    )
    metrics = {
        "geometry_similarity": sum(
            float(reward.get("geometry_similarity", 0.0)) for _, reward in found
        )
        / TASK_COUNT,
        "cad_spec_consistency": sum(
            float(reward.get("cad_spec_consistency", 0.0)) for _, reward in found
        )
        / TASK_COUNT,
        "combined": sum(
            float(reward.get("combined", reward.get("score", 0.0)))
            for _, reward in found
        )
        / TASK_COUNT,
    }

    declared = manifest["declared"]
    combined_delta = abs(metrics["combined"] - float(declared["mean_composite"]))
    if combined_delta > COMBINED_TOLERANCE:
        raise ValueError(
            f"{manifest_path.name}: public rewards differ from declared combined "
            f"score by {combined_delta}"
        )

    return {
        "source": {
            "hf_repo": result["hf_repo"],
            "hf_commit_oid": result["hf_commit_oid"],
            "runs_prefix": result["runs_prefix"],
        },
        "task_count": TASK_COUNT,
        "reward_count": len(found),
        "missing_reward_tasks": missing_reward_tasks,
        "missing_subscores": missing_subscores,
        "declared_exceptions": int(declared["exceptions"]),
        "metrics": metrics,
    }


def _source_url(source: dict[str, Any]) -> str:
    path = urllib.parse.quote(source["runs_prefix"].rstrip("/"), safe="/")
    return (
        f"https://huggingface.co/datasets/{source['hf_repo']}/tree/"
        f"{source['hf_commit_oid']}/{path}"
    )


def _model_name(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1]


def _model_display(model_id: str, effort: str | None) -> str:
    model = _model_name(model_id)
    return f"{model} ({effort})" if effort else model


def _manifest_effort(manifest: dict[str, Any]) -> str | None:
    notes = manifest.get("notes", "")
    explicit = re.search(r"reasoning_effort\s*=\s*([a-z0-9_-]+)", notes, re.I)
    if explicit:
        return explicit.group(1).lower()
    prose = re.search(
        r"\b(xhigh|high|medium|low|max|minimal)\s+reasoning(?:\s+effort|\s+mode)?",
        notes,
        re.I,
    )
    return prose.group(1).lower() if prose else None


def _display_score(score: float, *, bold: bool = False) -> str:
    value = f"{score * 100:.1f}"
    return f"**{value}**" if bold else value


def _row_metrics(
    *,
    geometry: float,
    spec: float,
    combined: float,
    cost_usd: float,
    total_trials: int,
    exceptions: int,
    missing_subscores: int,
) -> dict[str, Any]:
    return {
        "geometry": geometry,
        "display_geometry": _display_score(geometry),
        "spec": spec,
        "display_spec": _display_score(spec),
        "combined": combined,
        "display_combined": _display_score(combined, bold=True),
        "cost_usd": cost_usd,
        "display_cost": f"${cost_usd:,.2f}",
        "total_trials": total_trials,
        "exceptions": exceptions,
        "missing_subscores": missing_subscores,
    }


def _build_rows(
    root: Path, source_metrics: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    baselines = _read_json(root / "baselines/v1.json")
    rows: list[dict[str, Any]] = []

    for baseline in baselines["rows"]:
        effort = baseline.get("leaderboard_reasoning_label")
        model_id = baseline["model"]["id"]
        source = {
            "hf_repo": baselines["source"]["hf_repo"],
            "hf_commit_oid": baselines["source"]["hf_commit_oid"],
            "runs_prefix": baseline["runs_prefix"],
        }
        metrics = baseline["metrics"]
        rows.append(
            {
                "metadata": {
                    "model": model_id,
                    "model_display": _model_display(model_id, effort),
                    "agent": baseline["agent"]["name"],
                    "agent_version": baseline["agent"]["version"],
                    "reasoning_effort": effort,
                    "contributor": "gnucleus-ai",
                    "submission_type": "baseline",
                    "benchmark_tag": "v1",
                    "dataset_content_hash": DATASET_HASH,
                    "source": {
                        "url": _source_url(source),
                        "label": "Pinned public results",
                    },
                },
                "metrics": _row_metrics(
                    geometry=float(metrics["geometry"]),
                    spec=float(metrics["spec"]),
                    combined=float(metrics["combined"]),
                    cost_usd=float(metrics["cost_usd"]),
                    total_trials=int(baseline["trials"]),
                    exceptions=int(baseline["exceptions"]),
                    missing_subscores=int(baseline["missing_subscores"]),
                ),
                "status": "display",
                "trial_ids": [],
            }
        )

    for manifest_path in sorted((root / "submissions/v1").glob("*.yaml")):
        manifest = _read_manifest(manifest_path)
        recovered = source_metrics[manifest_path.name]
        source = recovered["source"]
        effort = _manifest_effort(manifest)
        model_id = manifest["model"]["id"]
        declared = manifest["declared"]
        metrics = recovered["metrics"]
        metadata = {
            "model": model_id,
            "model_display": _model_display(model_id, effort),
            "agent": manifest["agent"]["name"],
            "agent_version": manifest["agent"]["version"],
            "contributor": manifest["contributor"]["handle"],
            "submission_type": "contributor",
            "benchmark_tag": "v1",
            "dataset_content_hash": DATASET_HASH,
            "source": {
                "url": _source_url(source),
                "label": "Pinned public results",
            },
        }
        if effort:
            metadata["reasoning_effort"] = effort
        rows.append(
            {
                "metadata": metadata,
                "metrics": _row_metrics(
                    geometry=float(metrics["geometry_similarity"]),
                    spec=float(metrics["cad_spec_consistency"]),
                    combined=float(metrics["combined"]),
                    cost_usd=float(declared["cost_usd"]),
                    total_trials=int(declared["total_trials"]),
                    exceptions=int(declared["exceptions"]),
                    missing_subscores=int(recovered["missing_subscores"]),
                ),
                "status": "display",
                "trial_ids": [],
            }
        )

    rows.sort(
        key=lambda row: (
            -row["metrics"]["combined"],
            row["metadata"]["model"],
            row["metadata"]["agent"],
        )
    )
    return {"rows": rows}


def build(
    *,
    root: Path,
    cache_dir: Path,
    source_metrics_output: Path,
    rows_output: Path,
    workers: int,
) -> None:
    benchmark = _read_json(root / "benchmarks/v1.json")
    task_names = sorted(
        task.rsplit("/", 1)[-1] for task in benchmark["task_digests"]
    )
    if len(task_names) != TASK_COUNT:
        raise ValueError(f"expected {TASK_COUNT} tasks, found {len(task_names)}")

    recovered = {
        manifest_path.name: _aggregate_manifest(
            manifest_path, task_names, cache_dir, workers
        )
        for manifest_path in sorted((root / "submissions/v1").glob("*.yaml"))
    }
    source_snapshot = {
        "schema_version": 1,
        "description": (
            "Per-axis means re-derived from each accepted v1 manifest's exact "
            "pinned public Hugging Face reward artifacts. Missing rewards and "
            "omitted subscores contribute zero."
        ),
        "dataset_content_hash": DATASET_HASH,
        "rows": recovered,
    }
    rows = _build_rows(root, recovered)
    if len(rows["rows"]) != 28:
        raise ValueError(f"expected 28 leaderboard rows, found {len(rows['rows'])}")

    source_metrics_output.parent.mkdir(parents=True, exist_ok=True)
    source_metrics_output.write_text(
        json.dumps(source_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rows_output.write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {source_metrics_output}")
    print(f"Wrote {rows_output} ({len(rows['rows'])} rows)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "cad-bench-v1-public-rewards",
    )
    parser.add_argument(
        "--source-metrics-output",
        type=Path,
        default=REPOSITORY_ROOT / "leaderboards/v1-source-metrics.json",
    )
    parser.add_argument(
        "--rows-output",
        type=Path,
        default=REPOSITORY_ROOT / "leaderboards/v1-rows.json",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    build(
        root=REPOSITORY_ROOT,
        cache_dir=args.cache_dir,
        source_metrics_output=args.source_metrics_output,
        rows_output=args.rows_output,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
