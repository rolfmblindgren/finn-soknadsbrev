# Incremental coverage gap-fill

Rows fetched after the frozen v1 snapshot to cover FINN ads that are not
reachable via industry filters alone (discovered via `occupation` filters).

| File | Role |
|---|---|
| `observations.v2add.jsonl` | New ads only (not in v1) |
| `../observations.v2.jsonl` | v1 ∪ additions (deduped by id; v1 wins) |
| `../original/observations.v1.jsonl` | **Immutable** original 8988-row freeze |

`industry` / `industryValue` are `null` for ads discovered outside industry filters.
