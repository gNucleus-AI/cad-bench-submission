# Active CAD-Bench v2 submissions

This is the only directory accepting new leaderboard manifests. Copy
[`example-v2.yaml`](../_template/example-v2.yaml) here, name it
`<github-handle>-<agent>-<model>.yaml`, and run:

```bash
uv run python -m cad_bench_submission.validation
uv run pytest
```
