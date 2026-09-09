# Harbor leaderboard snapshots

This directory contains reviewed import inputs for curated CAD-Bench
leaderboards on Harbor Hub.

## Active v2

- `v2.yaml` mirrors the public Parametric CAD Bench v2 definition and is bound
  to dataset revision `v2`.
- `cad_bench_submission.build_v2_leaderboard_row` audits one complete public
  100-task Harbor job and generates a row matching that definition.
- Generated rows start with status `hide` so maintainers can inspect the row and
  its 100 trial associations before making it visible.

Download and audit the source job declared by a reviewed manifest:

```bash
harbor job download <job-uuid> --output-dir .audit
uv run python -m cad_bench_submission.artifact_validation \
  submissions/v2/<manifest>.yaml \
  --artifacts-root .audit
```

Build and import the hidden row. Supply `--cost-audit` when an independent cost
backfill is required for a provider whose Harbor agent result lacks complete
costs.

```bash
uv run python -m cad_bench_submission.build_v2_leaderboard_row \
  submissions/v2/<manifest>.yaml \
  --artifacts-root .audit \
  --output /tmp/cad-bench-v2-row.json

harbor hub leaderboard row create gnucleus-ai/cad-bench/v2 \
  --config /tmp/cad-bench-v2-row.json \
  --json
```

Verify the returned row ID and its 100 trial associations. Keep the row hidden
until the reviewed manifest is merged, and only then display it:

```bash
harbor hub leaderboard row show <row-uuid>
harbor hub leaderboard row trial list <row-uuid> --quiet
harbor hub leaderboard row update <row-uuid> --status display
```

## Frozen v1

- `v1.yaml` defines the public Harbor leaderboard bound to dataset revision `v1`.
- `v1-rows.json` contains the 10 frozen first-party baselines and 18 accepted
  contributor rows.
- `v1-source-metrics.json` records the per-axis aggregates re-derived from each
  contributor manifest's exact pinned public Hugging Face rewards. Missing
  rewards and omitted subscores contribute zero.
- `v1.frozen` activates PR-diff protection after this publication snapshot is
  merged.
- `../frozen/v1-leaderboard-lock.json` protects the exact publication inputs.

The legacy runs predate Harbor Hub job publication, so these are metric-only
curated rows with empty `trial_ids`. Their source links point to immutable
public Hugging Face revisions.

To reproduce the generated JSON from those public artifacts before the freeze:

```bash
uv run python -m cad_bench_submission.build_v1_leaderboard
```

To create the leaderboard from this snapshot:

```bash
harbor hub leaderboard create \
  --config leaderboards/v1.yaml \
  --rows leaderboards/v1-rows.json \
  --json
```

To synchronize the existing public leaderboard definition and rows:

```bash
harbor hub leaderboard update \
  gnucleus-ai/cad-bench/v1 \
  --config leaderboards/v1.yaml \
  --rows leaderboards/v1-rows.json \
  --json
```

Verify all 28 rows:

```bash
harbor hub leaderboard show gnucleus-ai/cad-bench/v1
harbor hub leaderboard row list gnucleus-ai/cad-bench/v1 --limit 100
```
