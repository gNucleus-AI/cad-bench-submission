# Contributing to Parametric CAD Bench

Thanks for running your `(agent, model)` against
[`gnucleus-ai/cad-bench@v1`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench).
This page is the full submission contract: produce the artifact tree
the bench's own runs produce, point at it from a manifest, open a PR,
and a maintainer re-grades it by hand.

## The model in 30 seconds

| Layer | Stored on | What lives there |
|---|---|---|
| Lightweight pointer | **This repo** (GitHub) | `submissions/<your-handle>-<agent>-<model>.yaml` — one manifest per submission |
| Heavyweight artifacts | **Your Hugging Face dataset** | `runs/<agent>/<model>/<task_id>/{result.json, config.json, answer.FCStd, answer.py, agent.log, trajectory.jsonl, reward.json}` |
| Verifier | **Maintainers** | Manual review — see [Verification](#verification) |

Why split the two? Real submissions are multi-GB (100 tasks × N trials ×
FCStd + log + trajectory). GitHub is the wrong blob store; HF is the
right one. GitHub stays clean for PR review.

## What you produce locally

```text
runs/
└── <agent>/                          # e.g. codex, claude-code, mini-swe-agent
    └── <model>/                      # e.g. openai-gpt-5_5 (filesystem-safe slug)
        └── <task_id>/                # e.g. freecad-0603c53148 — all 100 task_ids required
            ├── result.json           # trial metadata: timing, exception, token counts, model id
            ├── config.json           # trial config: env, agent kwargs, mounts
            ├── reward.json           # geometry_similarity, cad_spec_consistency, combined
            ├── answer.FCStd          # the parametric CAD file your agent saved (REQUIRED)
            ├── answer.py             # the script that produced it (REQUIRED)
            ├── agent.log             # full terminal transcript
            └── trajectory.jsonl      # tool-use / model-call trace (one JSON object per line)
```

This is **the exact layout** that
[`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench)
uses for the reference baseline runs — browse that dataset on Hugging
Face to see a complete example of every required file before you build
your own.

## What you push

1. **Upload `runs/<agent>/<model>/` to a Hugging Face dataset you own.**
   Either fork [`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench)
   and push to your fork, or create a fresh dataset (e.g.
   `<your-handle>/cad-bench-results`). Pin the commit you want graded.

2. **Open a PR here** adding one file:
   `submissions/<your-handle>-<agent>-<model>.yaml`. Match the schema in
   [`submissions/_schema/manifest.schema.json`](submissions/_schema/manifest.schema.json);
   start from [`submissions/_template/example.yaml`](submissions/_template/example.yaml).

3. **A maintainer takes it from there.** No further action needed
   unless the review flags a problem.

## Verification

A maintainer reviews each PR by hand:

1. **Manifest sanity** — reads the manifest for obvious red flags
   (impossible costs, missing trial count, unexplained outliers,
   mismatched declared values).
2. **Schema check** — validates the manifest against
   [`submissions/_schema/manifest.schema.json`](submissions/_schema/manifest.schema.json).
3. **Spot-check re-grade** — pulls a handful of `answer.FCStd` files
   from your linked Hugging Face commit and re-runs
   [`gnucleus-freecad-validator`](https://github.com/gNucleus-AI/freecad-validator)
   on them locally, confirming the re-graded score is within `1e-4` of
   your declared `reward.json`.
4. **Trajectory sanity** — eyeballs `agent.log` and `trajectory.jsonl`
   from a few representative trials to confirm an actual agent
   produced the work (not hand-authored FCStd).
5. **Cost re-derivation** — derives USD from declared token counts ×
   the model's published price; the re-derived number is what lands on
   the leaderboard (we don't propagate your declared `cost_usd`).
6. **Merge** — once everything checks out, the manifest lands on
   `main`. `cadbench.ai` reads merged manifests as the authoritative
   leaderboard.

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

## Tolerances and edge cases

- **Validator non-determinism**: surface-area / bounding-box checks
  are deterministic to ≥6 decimal places on the same FreeCAD version
  (`0.21.2`, what the task images ship). Tolerance set to `1e-4` to
  absorb any floating-point jitter across maintainer hardware.
- **Missing FCStd**: a trial without `answer.FCStd` cannot prove the
  agent produced editable CAD, so it scores `0` on re-grade regardless
  of what your `reward.json` claims. The harmonic-mean gate enforces
  this — `cad_spec_consistency = 0` → composite = 0.
- **Partial submissions**: all 100 task ids are required. We do not
  accept "best 80 of 100" submissions; the geometric-spread of the
  task suite is the point.
- **Multiple trials per task**: optional but encouraged. Manifest
  reports mean composite across all trials and per-task standard
  deviation. Single-trial submissions are accepted but flagged in the
  leaderboard.

## Trust model

For your first submission, the **full trajectory** (`agent.log` +
`trajectory.jsonl`) is required so a maintainer can sanity-check that
a real agent produced the work. After 2–3 verified-clean submissions
from the same contributor, we'll relax the requirement to just
`{result.json, reward.json, answer.FCStd, answer.py}`. This mirrors
the SWE-Bench-Verified path.

## Frequently asked

**Q: Can I submit results from a closed-source agent?**
Yes. The manifest's `agent.import_path` and `agent.version` are
informational; the trust signal is reproducible scoring on submitted
FCStd files, not source availability.

**Q: My agent doesn't use Harbor — can I still submit?**
Yes, as long as you can produce the seven required per-trial files
matching our schema. Harbor is the *recommended* runner, not the
required one. Your `config.json` must still reference the
`cad-bench@v1` task digest so we know which spec your agent saw.

**Q: How do I update an existing submission?**
Open a new PR with a new manifest file (same handle, bumped
`submission.version` field). The leaderboard always shows the latest
verified entry per `(handle, agent, model)`.

**Q: Will running the bench cost me anything?**
Yes — your model API costs are yours. The task suite itself is free
to download and run.

## Related

- [`gnucleus-ai/cad-bench@v1`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench) — the task suite
- [`gnucleus-ai/cad-gen-freecad`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad) — source data
- [`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench) — reference results
- [`gNucleus-AI/freecad-validator`](https://github.com/gNucleus-AI/freecad-validator) — validator (`pip install gnucleus-freecad-validator`)
