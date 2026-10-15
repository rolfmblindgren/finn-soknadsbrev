# Finn søknadsbrev

Analyse av søknadsbrev-praksis i norske FINN Jobb-annonser.

## Status (2026-10-15)

Rapport, scripts, figurer og analyse-sidecars er på `main`. Datasettene (observations JSONL) er ikke pushet hit.

## Hvordan lese forskningsrapporten

Full rapport ligger i fire deler (GitHub MCP payload-grense). Sett sammen lokalt:

```bash
cat reports/forskningsrapport.md.part.* > reports/forskningsrapport.md
```

Kompakt oversikt uten sammensetting: [`reports/resultatoversikt.md`](reports/resultatoversikt.md).

Analyse-JSON (`research_results*.json`, m.m.) ligger som gzip+base64-sidecars. Pakk ut med:

```bash
python scripts/unpack_gz_sidecars.py
```

### Tall fra den fullførte analysen (aktiv populasjon)

| Størrelse | Verdi |
|---|---:|
| Live union (`industry ∪ occupation`) | 13 886 |
| Sikre klasser (nevner) | 13 836 |
| Asks | 867 (**6,27 %**) |
| Silent | ~93 % |
| Rejects | ~0,74 % |
| Churn i v2 utenfor aktiv nevner | 228 |
| Fryst v1 | 8 988 |
| Merged v2 | 14 114 |

Hovedfunn: bransjefiltre alene dekket ikke katalogen (~5 100 annonser uten bransjetagg). `group_count` = unike annonser; `match_count` = stillinger.

### Artefakter

| Artefakt | Sti |
|---|---|
| Forskningsrapport (deler) | `reports/forskningsrapport.md.part.00`–`.03` |
| Resultatoversikt | `reports/resultatoversikt.md` |
| Dekning | `reports/dekning.md` |
| Aktive resultater (sidecar) | `data/analysis/research_results_active.json.gz.b64.*` |
| Validering (sidecar) | `data/qa/validation_report.json.gz.b64.*` |

### OSF

Krever `OSF_TOKEN` (PAT med `osf.full_write`) injisert i Cloud Agent-environmentet ved oppstart.
