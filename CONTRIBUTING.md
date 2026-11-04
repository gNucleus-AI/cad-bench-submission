# Contributing to Parametric CAD Bench v3

Only **v3** accepts new or updated submissions. Submit one manifest in
`submissions/v3/`, matching [manifest-v3.schema.json](submissions/_schema/manifest-v3.schema.json).
Start from [example-v3.yaml](submissions/_template/example-v3.yaml).
V1 and v2 are historical and closed to intake.

## Run contract

- Dataset: `gnucleus-ai/cad-bench@v3`, pinned to
  `sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a`.
- Harbor **0.23.0**, FreeCAD **1.1.0**, task schema **1.3**; use the published task
  environments without changing the verifier or task contents.
- Local Docker and Hosted Harbor (`harbor run --launch`) are accepted.
- One complete public Harbor job: **100 trials**, exactly one per official task,
  with automatic retries disabled. No cherry-picking or selective replacement.
  A fresh complete cohort is required for a new run. Infrastructure exceptions
  requiring replacement need maintainer review before submission; the automated
  intake does not accept merged/retried cohorts.
- The cohort contains 30 create, 30 create-and-edit, and 40 image-to-CAD tasks.
  Preserve the published prompts, drawings, time/resource limits, and network
  policy. Configure the agent's allowed hosts for its provider; model-time
  network access defaults to denied. Do not expose reference artifacts or prior
  solutions to the agent. Disclose multimodal adapter and system-prompt changes.
- Pin and report the agent version, exact provider/model, reasoning effort, and
  authentication mode (`api-key`, `subscription`, or `vertex-adc`). The manifest's
  source filter must select that same configuration in the public job.

The machine-readable release identity, all task digests, task modes, and artifact
contracts are in [benchmarks/v3.json](benchmarks/v3.json). Contributors do not need
a separate checkout of the benchmark source repository.

## Required artifacts

Retain root `config.json`, `lock.json`, and `result.json`, plus each trial's
`config.json`, `result.json`, agent log, trajectory, and verifier output.
A canonical Harbor `agent/trajectory.json` ATIF document or a complete
`trajectory.jsonl` trace is accepted. Agent logs may be `agent.log` or
`agent/<agent-name>.txt`. Antigravity may instead retain both
`agent/antigravity-cli.err` and `agent/antigravity-stream.jsonl`; its trajectory
is still required. When the agent version is not recorded in the requested
job options, every trial must report the same declared installed version.

| Mode | Required outputs when reward is positive | Reward details |
|---|---|---|
| Create | `answer.py`, `answer.FCStd` | `geometry_similarity`, `cad_spec_consistency`, `combined` |
| Create-and-edit | `answer.py`, `answer_base.FCStd`, `answer_edit.FCStd` | `base` and `target` each contain those three fields; top-level `combined` is their combined-score harmonic mean |
| Image-to-CAD | `answer.py`, `answer.FCStd` | `geometry_similarity`, `cad_spec_consistency`, `combined` |

Outputs may be at the trial root, `artifacts/app/`, or the verifier's retained
`agent/answer/` directory. Do not edit generated outputs before submission.
`verifier/reward.json` contains `{"reward": <number>}`;
`verifier/reward_details.json` contains the detailed scores. Files at the trial
root are also accepted. Rewards must agree with `result.json`.

The published verifiers can emit a scored zero as
`{"score": 0.0, "reason": "candidate did not produce ..."}` in the details file.
This includes `"reason": "scorer crashed"`. Consistent with the published v3
rows, a finite zero reward without a trial exception is counted as a scored
zero, including these verifier failures; `n_errors` is not a count of all
unsuccessful outcomes. A missing reward
or an exception contributes zero and increments `n_errors`. Failed trials must
remain present with their available artifacts and trace; contact maintainers if
an infrastructure failure prevented the required trace from being produced.

Overall score is the mean reward across all 100 tasks, including failures as
zero. Mode means use denominators 30, 30, and 40 respectively; the overall score
is weighted by those task counts, not an unweighted mean of the three modes.
The create-and-edit base and target are one trial, not two leaderboard entries.

Hosted trial configs may contain only a temporary task path. Keep each trial's
`lock.json`: the audit combines the result's public `task_name` with the locked
content digest, checks the matching config/lock path and dataset source, and
compares the digest with the frozen v3 task map. Root-lock entries named `task`
are resolved by digest, not by their order. The root job lock is still required
to verify the Harbor version and retry policy; if an older download omits it,
retain the original job lock or obtain it from the job owner before publication.

## Publish and submit

Use `harbor run --upload --public` locally, add `--launch` for Hosted Harbor, or
`harbor upload jobs/<job-directory> --public`. The job and all selected trial
artifacts must be publicly readable. Review artifacts for credentials and private
information before publication. An optional pinned Hugging Face mirror provides
archival redundancy; the Harbor job is authoritative.

```bash
uv run python -m cad_bench_submission.validation submissions/v3/<manifest>.yaml
uv run pytest
```

Open a PR with the manifest. CI checks its structure, frozen release identity,
source filter, and declared cohort size. It does not fetch or re-grade the job.

## Verification

Maintainers:

1. Confirm the source job is public and the agent/model configuration matches
   the manifest. Download it with `harbor job download <job-uuid> --output-dir .audit`.
2. Run `cad_bench_submission.artifact_validation` with the manifest and
   `--artifacts-root .audit`. Verify all 100 task digests and required artifacts.
3. Inspect trajectories and spot-check re-grading in the matching task verifier
   environment, including both outputs for create-and-edit. Use a `1e-4` review
   tolerance for numerical differences; investigate mismatches. Artifact audits
   check file presence and reported scores, not CAD geometry or agent authenticity.
4. Build a row with `cad_bench_submission.build_v3_leaderboard_row`. It re-derives
   overall/per-mode scores, confidence interval, errors, durations, and available
   cost/token totals. Declared cost is informational; incomplete coverage displays
   as N/A. An independent complete cost audit can be supplied with `--cost-audit`.
5. Import the row **hidden** into `gnucleus-ai/cad-bench/v3`, verify its 100 trial
   associations, merge the reviewed manifest, and only then display the row.
   See [publication commands](leaderboards/README.md#active-v3).

The builder accepts the standard complete, retry-free job layout. It does not
publish anything itself or launch the agent again. Submitters retain the cost of
their original model calls. New agents may use a custom Harbor adapter; source
availability is not required, but complete reviewable run artifacts are.

For historical inspection only, manifest validation supports `--include-archive`
for the frozen v1 archive, and artifact validation supports `--allow-archived` for
v1/v2. Neither option opens old-version intake. The v3 row builder rejects both.
