# cad-bench-submissions

Submission portal for the **Parametric CAD Bench** leaderboard at
[cadbench.ai](https://cadbench.ai).

This repository accepts third-party `(agent, model)` results for the
[`gnucleus-ai/cad-bench@v1`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench)
Harbor task suite. Each merged submission becomes a leaderboard row.

## What gets submitted

A **manifest YAML** pointing at a Hugging Face dataset commit that hosts
your raw run artifacts (per-trial `result.json`, `answer.FCStd`,
`trajectory.jsonl`, etc., matching the layout of
[`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench)).

GitHub holds the lightweight pointer; Hugging Face holds the multi-GB
artifacts. No binary files are committed here.

## How to submit

1. Run the bench: `harbor run -d gnucleus-ai/cad-bench@v1 -a <your-agent> -m <your-model>`.
2. Push your `runs/<agent>/<model>/` tree to a Hugging Face dataset you control.
3. Open a PR adding one file under `submissions/`: a manifest YAML matching
   [`submissions/_template/example.yaml`](submissions/_template/example.yaml).
4. **A maintainer reviews your submission manually** — see
   [CONTRIBUTING.md](CONTRIBUTING.md#verification) for what the review
   covers.

Full contract: [CONTRIBUTING.md](CONTRIBUTING.md).

## Related

- **Tasks**: [`gnucleus-ai/cad-bench@v1`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench) (Harbor Hub)
- **Source data**: [`gnucleus-ai/cad-gen-freecad`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad) (Hugging Face)
- **Reference results**: [`gnucleus-ai/cad-gen-freecad-bench`](https://huggingface.co/datasets/gnucleus-ai/cad-gen-freecad-bench) (Hugging Face)
- **Validator**: [`gNucleus-AI/freecad-validator`](https://github.com/gNucleus-AI/freecad-validator) (`pip install gnucleus-freecad-validator`)
- **FreeCAD**: [freecad.org](https://www.freecad.org/) (LGPL-2.1+)

## License

Apache-2.0. See [LICENSE](LICENSE).
