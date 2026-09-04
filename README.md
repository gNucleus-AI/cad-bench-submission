# cad-bench-submissions

Submission portal for the **Parametric CAD Bench** leaderboard at
[cadbench.ai](https://cadbench.ai).

This repository accepts third-party `(agent, model)` results for the current
frozen version of the
[`gnucleus-ai/cad-bench`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench)
Harbor task suite. Each merged submission becomes a version-specific
leaderboard row.

| Bench tag | Status | Harbor leaderboard | FreeCAD |
|---|---|---|---|
| `v1` | Frozen; submissions closed | `v1` | 0.21.2 |
| `v2` | Current; submissions open | `main` | 1.1.0 |

The immutable dataset IDs, content hashes, task counts, task digests, artifact
contracts, and leaderboard routing live under [`benchmarks/`](benchmarks/).

## What gets submitted

A **manifest YAML** pointing at one or more public Harbor Hub jobs. The manifest
also declares the exact `(agent, agent version, model, reasoning effort)` filter
that selects its trials. Harbor jobs are authoritative; a pinned Hugging Face
mirror may be included as optional archival redundancy.

Harbor 0.20 writes trajectories as a single ATIF document in
`trajectory.json`. Complete legacy `trajectory.jsonl` traces are also
accepted.

GitHub holds the lightweight pointer; Harbor Hub holds the job and trial
artifacts. No binary files are committed here.

## How to submit

1. Run the current frozen bench and upload it publicly:

   ```bash
   harbor run -d gnucleus-ai/cad-bench@v2 \
     -a <your-agent> -m <your-model> \
     --upload --public
   ```

   For an existing local job, use `harbor upload jobs/<job-directory> --public`.
2. Open a PR adding one file under `submissions/v2/`: a manifest YAML matching
   [`submissions/_template/example-v2.yaml`](submissions/_template/example-v2.yaml).
3. **A maintainer reviews your submission manually** — see
   [CONTRIBUTING.md](CONTRIBUTING.md#verification) for what the review
   covers.

Before opening a PR, validate the manifest locally:

```bash
uv run python -m cad_bench_submission.validation path/to/submission.yaml
uv run pytest
```

After downloading every declared source job into one otherwise-empty directory,
maintainers can audit the full selected cohort and its task digests with:

```bash
harbor job download <job-uuid> --output-dir .audit
uv run python -m cad_bench_submission.artifact_validation \
  path/to/submission.yaml --artifacts-root .audit
```

Full contract: [CONTRIBUTING.md](CONTRIBUTING.md).

## Frozen v1 leaderboard

The v1 leaderboard is immutable. It is assembled from two frozen sources:

- [`baselines/v1.json`](baselines/v1.json) records the 10 first-party matrix
  runs whose artifacts are pinned in the public Hugging Face result dataset.
- [`submissions/v1/`](submissions/v1/) archives the accepted third-party v1
  manifests already merged into this repository.

These are deliberately separate: a benchmark-owner matrix run is not a
contributor submission. New or updated v1 manifests are rejected by CI. The
`v1` leaderboard is imported once, while accepted v2 manifests feed the Harbor
`main` leaderboard.

For this freeze to be enforceable, the GitHub `main` branch ruleset must require
pull requests and the **Validate submissions** status check, and must disallow
direct pushes that bypass required checks. The checksum lock also detects local
or accidental drift in the archived files.

## Related

- **Tasks**: [`gnucleus-ai/cad-bench`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench) (`v1` historical, `v2` current)
- **Source data**: [`gnucleus-ai/cad-gen-freecad`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad) (Hugging Face)
- **Reference results**: [`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench) (Hugging Face)
- **Validator**: [`gNucleus-AI/freecad-validator`](https://github.com/gNucleus-AI/freecad-validator) (`pip install gnucleus-freecad-validator`)
- **FreeCAD**: [freecad.org](https://www.freecad.org/) (LGPL-2.1+)

## License

Apache-2.0. See [LICENSE](LICENSE).
