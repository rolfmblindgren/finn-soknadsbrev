# Finn søknadsbrev

Analyse av søknadsbrev-praksis i norske FINN Jobb-annonser.

## Status (2026-10-15)

**GitHub inneholder foreløpig ikke datasettene eller rapportfilene.**  
Alt arbeidet ble gjort i Cloud Agent [`bc-01a13b0b-44e4-7254-a538-ff4b209dee01`](https://cursor.com/agents/bc-01a13b0b-44e4-7254-a538-ff4b209dee01). Et forsøk på å pushe rapportene hit endte med bare filen `PLACEHOLDER`.

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

### For å få filene inn i dette repoet

1. Åpne den **opprinnelige** agenten: https://cursor.com/agents/bc-01a13b0b-44e4-7254-a538-ff4b209dee01  
2. Lim inn:

```text
Push hele prosjektet til https://github.com/rolfmblindgren/finn-soknadsbrev
(GitHub write fungerer nå via MCP). Prioritet: reports/, scripts/,
data/analysis/*.json, data/qa/coverage_report.json. Fulltekst-JSONL
kan hoppes over hvis for stort; public dataset først.
```

3. Eller last ned / eksporter workspace derfra og pushe manuelt.

### OSF

Krever `OSF_TOKEN` (PAT med `osf.full_write`) injisert i Cloud Agent-environmentet **ved oppstart** av en agent som også har tilgang til filene.

### Artefakter som skal ligge her (når pushet)

| Artefakt | Sti |
|---|---|
| Forskningsrapport | `reports/forskningsrapport.md` |
| Resultatoversikt | `reports/resultatoversikt.md` |
| Dekning | `reports/dekning.md` |
| Aktive resultater | `data/analysis/research_results_active.json` |
| Delbart datasett | `data/analysis/observations.public.jsonl` |
