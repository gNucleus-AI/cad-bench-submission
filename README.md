# Parametric CAD Bench submissions

Submit third-party `(agent, model)` results for the
[Parametric CAD Bench v3 leaderboard](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench).
**Only v3 accepts submissions. V1 and v2 intake is closed.**

V3 has 100 tasks: **30 create, 30 create-and-edit, and 40 image-to-CAD**.
It uses FreeCAD 1.1.0 and Harbor 0.23.0. Use an agent that can inspect images
for the image-to-CAD tasks, and disclose any adapter or prompt modifications.

## Submit

1. Run the frozen v3 dataset with one attempt per task and no automatic retries.
   Allow only the model-provider hosts needed by your agent:

   ```bash
   harbor run -d gnucleus-ai/cad-bench@sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a \
     -a <your-agent> -m <your-model> \
     --allow-agent-host <model-provider-host> \
     --upload --public
   ```

   For Hosted Harbor, add `--launch` to the same run command. The submission
   format and complete-cohort requirements are the same for both venues.

   The digest is the immutable release behind `gnucleus-ai/cad-bench@v3`.
   Pin the agent version and reasoning effort in your run configuration; retain
   `config.json` and `lock.json`. Verify that the lock has zero retries.
   To publish a completed local job, use `harbor upload jobs/<job-directory> --public`.
2. Copy [example-v3.yaml](submissions/_template/example-v3.yaml) to
   `submissions/v3/<handle>-<agent>-<model>.yaml` and fill in the actual run metadata.
3. Validate and open a PR:

   ```bash
   uv run python -m cad_bench_submission.validation submissions/v3/<manifest>.yaml
   uv run pytest
   ```

CI validates manifests; maintainers separately download and audit the public job,
spot-check CAD outputs, and stage a hidden leaderboard row before publication.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the artifact and review requirements.
The repository stores pointers, not job archives or binary CAD artifacts.

## Maintainer commands

```bash
harbor job download <job-uuid> --output-dir .audit
uv run python -m cad_bench_submission.artifact_validation \
  submissions/v3/<manifest>.yaml --artifacts-root .audit
uv run python -m cad_bench_submission.build_v3_leaderboard_row \
  submissions/v3/<manifest>.yaml --artifacts-root .audit \
  --output /tmp/cad-bench-v3-row.json
```

The row includes overall and per-mode mean rewards. Failures contribute zero;
create-and-edit counts as one task, using its combined base/edited score.
See [leaderboard publication](leaderboards/README.md#active-v3).

## Historical versions

V1's accepted manifests and leaderboard remain checksum-protected and immutable.
V2's policy, schema, and leaderboard definition are retained for historical
inspection; there are no accepted v2 manifests in this repository. New manifests
under `submissions/v1/` or `submissions/v2/` are rejected by CI. Historical audit
options do not enable intake or publication of old versions.

Require the **Validate submissions** check and pull requests on `main`, with no
bypass of required checks, to enforce these rules.

## Related

- [Harbor tasks](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench)
- [Legacy v1 source data](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad)
- [Legacy v1 reference results](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench)
- [FreeCAD validator](https://github.com/gNucleus-AI/freecad-validator)

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

The license covers this repository's code and the Parametric CAD Bench task
specifications, reference models, and drawings of v1, v2, and v3 published on
Harbor Hub. FreeCAD and Open CASCADE Technology retain their own LGPL-2.1 license.
