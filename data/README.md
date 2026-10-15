# Data

## `observations.jsonl`

Én JSON-linje per annonse. Se `observations.schema.json` og
[`../docs/ETTERPROVBARHET.md`](../docs/ETTERPROVBARHET.md).

Filen kan bli stor (full annonsetekst) og er derfor gitignorert. Bygg på nytt:

```bash
python3 scripts/rebuild-observations.py
```

Manifest med SHA-256: `observations.manifest.json` (committes når et snapshot er låst).

## `audit-sample.json`

Deterministisk kontrollutvalg (seed + ID-lister). Genereres med:

```bash
python3 scripts/export-audit-sample.py --seed 14 --asks 100 --silent 100
```
