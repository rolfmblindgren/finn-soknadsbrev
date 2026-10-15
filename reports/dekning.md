# Dekningsrapport: FINN søknadsbrev-uttrekk

**Generert:** 2026-10-14T23:12:50Z

## Hva vi teller

| FINN-felt | Betydning | Dette uttrekket |
|---|---|---|
| `group_count` | Unike **annonser** (ad-id) | Målenhet for dekning |
| `match_count` | **Stillinger/posisjoner** (`no_of_positions`) | Ikke samme enhet |
| Vår rad | Én observasjon per FINN-id | Samme som `group_count` |

Ved enumeringstidspunkt: `group_count` = **13886**, `match_count` = **28135**.

## Hvorfor 8988 ikke var nok

1. **Hovedårsak:** Skanningen paginerte bare **bransjefiltre**. Live bransjeunion = **8778** unike ID-er — ikke hele katalogen.
2. Annonser **uten bransjetagg** ≈ **5108** er usynlige for `industry=*`.
3. **Ikke** sidebegrensning per bransje: ingen bransje hadde >2500 treff; enum ≈ claimed for hvert filter.
4. Tidligere «lav dekning» per bransje basert på *first-seen* var **misvisende** (dedupe), ikke bevis på manglende paginering.
5. Av live bransjeunion manglet v1 bare **18** ID-er; **228** v1-ID-er er ikke lenger i live bransjeunion (churn / uten bransje nå).

## Utvidet strategi

- Enumererte alle **occupation**-filtre (alle <2500 treff, ingen sidetak).
- `industry ∪ occupation` = **13886** = `group_count` (**gap 0**).
- Hentet kun ID-er som manglet i fryst v1 (`data/original/observations.v1.jsonl` uendret).

## Resultat etter gap-fill

| Størrelse | Antall |
|---|---:|
| Fryst v1 | 8988 |
| Live union (industry∪occupation) | 13886 |
| Manglet ved start av gap-fill | 5126 |
| Nye rader hentet | 5126 |
| Fetch-feil blant nye | 0 |
| Merged v2 | 14114 |
| Overlap v2 ∩ live | 13886 |
| Fortsatt mangler i live | 0 |
| Dekningsandel av live union | 1.0 |
| v2 men ikke i live (churn fra v1 m.m.) | 228 |

### Klassifisering

| Sett | asks | silent | rejects | error |
|---|---:|---:|---:|---:|
| v1 | 498 | 8442 | 47 | 1 |
| Tillegg | 235 | 4887 | 4 | 0 |
| v2 | 733 | 13329 | 51 | 1 |

## Bransjefiltre: faktisk pagineringsdekning

For hvert av 69 bransjefiltre var `enumerated == claimedHits` (ingen sidetak truffet).
Differansen mot first-seen-andeler i tidligere QA skyldes **dedupe**, ikke hull i paginering.

## Hva vi fortsatt ikke vet / ikke kan hente

- Markedschurn: populasjonen er et øyeblikksbilde; v1-rader utenfor live union er historiske observasjoner.
- `group_count` endrer seg over tid (etter gap-fill kan live `group_count` avvike litt fra enumeringstidspunktet).
- `industry` er null for gap-fill-rader oppdaget via occupation uten bransjetagg.
- Noen annonsesider mangler JSON-LD; tekst ble da hentet fra HTML (`ad-description`).
- Analyseplan punkt 3–5 er ikke startet.

## Filer

- Live ID-union: `data/qa/ids_industry_occupation.txt`
- Manglende ved gap-fill: `data/qa/missing_ids.txt`
- Tillegg: `data/incremental/observations.v2add.jsonl`
- Merged: `data/observations.v2.jsonl`
- Maskinlesbar rapport: `data/qa/coverage_report.json`
