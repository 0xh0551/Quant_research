# Ml Research

See [architecture.md](architecture.md) for the module overview and [data_pipeline.md](data_pipeline.md) for the data conventions used by all pipeline stages.

The `src/analysis/` and `src/` modules for this research area are implemented as standalone Python modules. They can be exercised via the CLI commands below or called directly from notebooks and scripts.

```bash
# Run the full pipeline which includes this stage
uv run quant-research research-all --data-dir data/processed --output reports/global_research/index.html
```

Detailed methodology documentation for this module is in progress.
