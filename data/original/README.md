# Original frozen dataset (v1)

| File | Role |
|---|---|
| `observations.v1.jsonl` | **Immutable** 8988 observations from the first full industry-filter scan |
| `observations.v1.manifest.json` | Counts / freeze metadata |
| `freeze.json` | Freeze timestamp + SHA-256 |

Do not overwrite these files. Coverage expansions append via `data/incremental/`
and merge into `data/observations.v2.jsonl`.
