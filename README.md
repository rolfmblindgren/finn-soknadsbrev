# Finn søknadsbrev-agent

BDK chat-agent som går gjennom åpne stillingsannonser på [Finn Jobb](https://www.finn.no/job/search) og teller hvor mange som:

- **ber om søknadsbrev** (`asks`)
- **ikke nevner søknadsbrev** (`silent`)
- **eksplisitt sier nei til søknadsbrev** (`rejects`)

## Status (2026-10-15)

Full forskningsrapport, dekning og aktive populasjonsanalyser er klare i `reports/`.

| Artefakt | Sti |
|---|---|
| Forskningsrapport | `reports/forskningsrapport.md` |
| Resultatoversikt | `reports/resultatoversikt.md` |
| Dekning | `reports/dekning.md` |
| Aktive resultater | `data/analysis/research_results_active.json` |

**Aktiv nevner:** live union 13 886 annonser; sikre 13 836; asks 867 (6,27 %). 228 churn-rader utenfor aktiv nevner.

## Kom i gang

```bash
npm install
npx @cursor/bdk@0.2.24 serve --dir . --mode single --dev
```

```bash
python3 scripts/enrich_observations.py
python3 scripts/run_research_analysis.py
```

## Secrets for Cloud Agent / OSF

1. Sett `OSF_TOKEN` (OSF PAT med `osf.full_write`) som environment secret.
2. Start agenten fra **environmentet som har secretet** (desktop-restart er ikke nok).
3. Fulltekst-JSONL (~50 MB) følger ikke nødvendigvis med i GitHub; bruk `data/analysis/*` og rapporter for OSF-publisering av sammendrag/andeler.
