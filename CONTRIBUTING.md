# Contributing to Parametric CAD Bench

Thanks for running your `(agent, model)` against the current frozen version of
[`gnucleus-ai/cad-bench`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench).
This page is the full submission contract: produce the artifact tree
the bench's own runs produce, point at it from a manifest, open a PR,
and a maintainer re-grades it by hand.

## The model in 30 seconds

| Layer | Stored on | What lives there |
|---|---|---|
| Lightweight pointer | **This repo** (GitHub) | `submissions/v2/<your-handle>-<agent>-<model>.yaml` — one manifest per submission |
| Heavyweight artifacts | **Harbor Hub** | Public source jobs with full per-trial results, configuration, generated CAD, trajectory, and verifier output |
| Verifier | **Maintainers** | Manual review — see [Verification](#verification) |

Why split the two? Real submissions are multi-GB (100 tasks × N trials ×
FCStd + log + trajectory). GitHub stays clean for PR review, while Harbor Hub
provides stable job/trial identities and the artifacts used to derive a row.

## What you produce locally

```text
jobs/
└── <job>/
    ├── config.json                   # job-level dataset/run configuration
    └── <trial>/                      # exactly one trial for each of 100 tasks
        ├── result.json               # timing, exception, tokens, model, job/trial IDs
        ├── config.json               # pinned task identity and digest
        ├── artifacts/app/
        │   ├── answer.FCStd           # parametric CAD result (REQUIRED when score > 0)
        │   └── answer.py              # script that produced it (REQUIRED when score > 0)
        ├── agent/
        │   ├── trajectory.json        # Harbor ATIF tool/model trace
        │   └── <agent>.txt            # full agent log
        └── verifier/
            ├── reward.json            # {"reward": <combined>}
            └── reward_details.json    # geometry/spec/combined details
```

Harbor 0.20 writes the canonical trajectory as one ATIF document in
`trajectory.json`. A complete legacy `trajectory.jsonl` trace, with one
JSON object per line, is also accepted. At least one of these trajectory
artifacts is required wherever this document requires a trajectory.

The frozen v1 archive retains its legacy Hugging Face layout. New v2
submissions use native Harbor job artifacts as shown above.

## Artifact contracts

Artifacts from different bench versions must never be mixed. v1 is retained
only for historical audit; only v2 accepts submissions.

| Tag | Dataset content hash | Reward contract | FreeCAD | Leaderboard |
|---|---|---|---|---|
| `v1` (closed) | `sha256:22be8aa80fdbf2d9844e73c9d91ee7e01082d70bcf706d347216d0b97bdf862e` | `reward.json` contains `geometry_similarity`, `cad_spec_consistency`, and `combined` | 0.21.2 | `v1` |
| `v2` (open) | `sha256:ab2e040d0adcfd2779b4f1ad554890cd98b5aa19845e00162933ba165144fe56` | `reward.json` contains the Harbor `reward`; `reward_details.json` contains the three detailed scores | 1.1.0 | `v2` |

The machine-readable policies under [`benchmarks/`](benchmarks/) are
authoritative. A v2 manifest must include its exact `dataset_content_hash`,
structured agent display and authentication metadata, one public Harbor source
job, an exact `source_filter`, and the declared mean reward.

## What you push

1. **Upload the complete job to Harbor Hub as public.** Add `--upload --public`
   to `harbor run`, or upload a completed local job afterwards:

   ```bash
   harbor upload jobs/<job-directory> --public
   ```

   The job and every selected trial must be readable without contributor
   credentials. A submission is one complete 100-task Harbor job with retries
   disabled; failed trials remain in the cohort and count as zero.

2. **Optionally mirror the artifacts to Hugging Face.** If supplied, the
   manifest must pin a full commit OID. This mirror is archival redundancy;
   Harbor jobs remain authoritative for selection and grading.

3. **Open a PR here** adding one file:
   `submissions/v2/<your-handle>-<agent>-<model>.yaml`. Match the schema in
   [`submissions/_schema/manifest-v2.schema.json`](submissions/_schema/manifest-v2.schema.json);
   start from [`submissions/_template/example-v2.yaml`](submissions/_template/example-v2.yaml).

4. **A maintainer takes it from there.** No further action needed
   unless the review flags a problem.

## Verification

A maintainer reviews each PR by hand:

1. **Manifest sanity** — reads the manifest for obvious red flags
   (impossible costs, missing trial count, unexplained outliers,
   mismatched declared values).
2. **Source-job check** — verifies every Harbor job and selected trial is
   publicly readable and that the source filter matches the declared metadata.
3. **Schema check** — validates the manifest against
   [`submissions/_schema/manifest-v2.schema.json`](submissions/_schema/manifest-v2.schema.json).
4. **Cohort and digest check** — checks all 100 official task IDs, every trial's
   task digest, exactly one trial per task, and the artifact
   contract for the selected version. Missing and failed trials count as zero.
5. **Spot-check re-grade** — pulls a handful of `answer.FCStd` files
   from the Harbor trials and re-runs
   [`gnucleus-freecad-validator`](https://github.com/gNucleus-AI/freecad-validator)
   in the matching FreeCAD/scorer environment, confirming the re-graded score
   is within `1e-4` of the submitted verifier output.
6. **Trajectory sanity** — eyeballs the agent log and `trajectory.json`
   (or legacy `trajectory.jsonl`) from a few representative trials to
   confirm an actual agent produced the work (not hand-authored FCStd).
7. **Cost audit** — uses complete cost data recorded by Harbor, or an
   independent provider-specific audit when the agent result is incomplete.
   The declared `cost_usd` is informational and is not copied into the row.
8. **Build and stage** — generate a hidden row using
   `cad_bench_submission.build_v2_leaderboard_row`, import it into
   `gnucleus-ai/cad-bench/v2`, and verify the row and its 100 trial
   associations.
9. **Merge** — once everything checks out, the manifest lands on `main` as the
   durable record for the Harbor `v2` row.
10. **Display** — change the verified row's status from `hide` to `display`
    only after the manifest is merged.

Turnaround is bounded by maintainer availability — typically a few
days. Open a draft PR if you'd like an early sanity check before
finalizing.

## Hermeticity, briefly

The bench's **scoring is hermetic**: reference geometry and validator
are sealed into each task image, so any party — you, us, third-party
auditors — re-grading the same `.FCStd` gets the same number. The
**agent runtime is network-permissive** (your agent needs to reach its
model endpoint), matching the SWE-Bench / Terminal-Bench convention.
Our re-grade runs hermetic-scoring only; **we do not re-execute your
agent**. Trust in trajectory + cost is built from inspection and
reputation, not from us paying your API bill.

## Benchmark integrity

- Run the complete frozen cohort once per trial index; do not select only
  successful tasks or selectively rerun failures.
- Never expose held-back references, benchmark protobufs, official scores,
  prior candidates, or cached intermediates to the generating agent.
- Do not manually edit or substitute generated FreeCAD, Python, STEP, render,
  or intermediate artifacts before submission.
- Preserve full trajectories and failed trials. Failures contribute zero to
  every reported aggregate.
- Report the exact agent version, model, reasoning effort, runtime, and cost.

## Tolerances and edge cases

- **Validator non-determinism**: surface-area / bounding-box checks are
  deterministic to ≥6 decimal places in the matching version's environment
  (FreeCAD 0.21.2 for v1; 1.1.0 for v2). Tolerance is `1e-4` to absorb
  floating-point jitter across maintainer hardware.
- **Missing FCStd**: a trial without `answer.FCStd` cannot prove the
  agent produced editable CAD, so it scores `0` on re-grade regardless
  of what your `reward.json` claims. The harmonic-mean gate enforces
  this — `cad_spec_consistency = 0` → composite = 0.
- **Partial submissions**: all 100 task ids are required. We do not
  accept "best 80 of 100" submissions; the geometric-spread of the
  task suite is the point.
- **One trial per task**: v2 rows contain exactly 100 trials, one for each
  official task, with Harbor retries disabled. Run a new complete cohort for a
  later submission; do not selectively replace failures from an earlier run.

## Trust model

Every submission must retain the full Harbor trajectory, trial configuration,
agent log, generated artifacts, and verifier output. Public source jobs make the
row reproducible and keep failures available for audit.

## Frequently asked

**Q: Can I submit results from a closed-source agent?**
Yes. The manifest's `agent.import_path` and `agent.version` are
informational; the trust signal is reproducible scoring on submitted
FCStd files, not source availability.

**Q: My agent doesn't use Harbor — can I still submit?**
The v2 leaderboard intake is Harbor-native. A custom or closed-source agent is
fine, but it must run through a Harbor adapter so the result can be uploaded as
a complete public Harbor job with pinned task digests.

**Q: Do I still need to upload to Hugging Face?**
No. A pinned Hugging Face mirror is optional archival redundancy. The Harbor
source jobs are authoritative.

**Q: How do I update an existing submission?**
Open a new PR with a new v2 manifest file (same handle, bumped
`submission.version` field). The current leaderboard shows the latest verified
entry per `(handle, agent, model)`. v1 entries cannot be updated.

**Q: Will running the bench cost me anything?**
Yes — your model API costs are yours. The task suite itself is free
to download and run.

## Related

- [`gnucleus-ai/cad-bench`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench) — the v1 and v2 task suites
- [`gnucleus-ai/cad-gen-freecad`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad) — source data
- [`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench) — reference results
- [`gNucleus-AI/freecad-validator`](https://github.com/gNucleus-AI/freecad-validator) — validator (`pip install gnucleus-freecad-validator`)
