# Punkt 1–2: Datagrunnlag og klassifiseringsvalidering

**Dato:** 2026-10-14  
**Formål:** Sikre etterprøvbart grunnlag før analyse av variasjon og hypoteser (punkt 3–5).

## 1. Datagrunnlag

### 1.1 Fryst originaldatasett

| Felt | Verdi |
|---|---|
| Fil | [`data/original/observations.v1.jsonl`](../data/original/observations.v1.jsonl) |
| Policy | Immutable — ikke overskriv |
| Antall rader | **8988** |
| SHA-256 | `f661d455e4b61a4f2b33ed5fc34a556cd45385a16bd74185f875bbe14ab9cecc` |
| Fryst | 2026-10-14T21:50:54Z |

Alle videre analyser skal lese denne fila.

### 1.2 Unike ID-er, duplikater og manglende verdier

| Sjekk | Resultat |
|---|---|
| Unike FINN-ID-er | **8988** (= antall rader) |
| Duplikate ID-er | **0** |
| Mangler `id` / `url` / klassifisering | **0** |
| Mangler `classificationText` | **2** |
| Mangler `industry` | **1** |
| Predikert fordeling | asks 498 · silent 8442 · rejects 47 · error 1 |

Restfeil:

1. `478157143` — `error` under live-skanning (ingen tekst).
2. `478496863` — 404 ved re-hent (annonse borte); mangler tekst og bransje.

### 1.3 Bransjefordeling (first-seen)

Datasettet har **68** bransjenavn (av 69 live filtre). Verdien `6` (*Underholdning*) finnes live, men ingen rad har den som *first-seen*-bransje (annonsene er trolig også tagget i andre bransjer og ble lagret der først).

Største first-seen-bransjer i uttrekket:

| Bransje | n |
|---|---:|
| Helse og omsorg | 1389 |
| Butikk og varehandel | 885 |
| Drift og vedlikeholdstjenester | 511 |
| Barn, skole og undervisning | 431 |
| Konsulent og rådgivning | 427 |
| Bygg og anlegg | 354 |

**Viktig:** `industry` i datasettet er **første bransjefilter** der annonsen ble sett i skannerrekkefølgen, ikke «eneste» eller «primære» bransje på FINN. En annonse kan ligge i flere filtre. Derfor kan sent skannede bransjer ha lav *first-seen*-andel selv om de ble paginert.

### 1.4 Dekker vi alle åpne stillinger?

**Kort svar: Nei — ikke hele FINN Jobb-katalogen.**

| Benchmark (live snapshot 2026-10-14T21:52Z) | Verdi |
|---|---:|
| `match_count` | 28 896 |
| `group_count` | 14 259 |
| Unike ID-er i vårt uttrekk | 8 988 |
| Ufiltrert søk maks via paginering | 2 500 (50 sider × 50) |

Metode:

- Offentlig FINN-søk (`SEARCH_ID_JOB_FULLTIME`) paginert **per bransjefilter** (69 filtre).
- Deduplisering på FINN-ID.
- Annonsetekst fra JobPosting JSON-LD.
- Skanning ferdig ca. **2026-10-14T20:21:25Z**.

Vurdering:

1. Ufiltrert søk alene kan ikke dekke katalogen (50-siders tak).
2. Bransjesplitting utvider dekningen, og ingen live bransje har nå >2500 treff (sidetak ikke bindende per filter i snapshot).
3. Likevel er 8988 unike ID-er vesentlig lavere enn live `group_count` (~14k). Mulige årsaker:
   - markedschurn etter innsamling (nye/fjernede annonser),
   - annonser utenfor/uten bransjefilter,
   - mulige hull i paginering eller stopp før alle nye ID-er i sene filtre,
   - ulik semantikk mellom `group_count` og «unik annonse i minst ett bransjefilter».
4. Summen av live bransjetreff (≈17k) > `group_count` fordi annonser teller i flere bransjer — forventet.

**Konklusjon for videre analyse:** Datasettet er et **stort, etterprøvbart tverrsnitt** av FINN Jobb på innsamlingstidspunktet, men **ikke en komplett census** av alle åpne stillinger. Andeler bør tolkes som estimater innen dette uttrekket, ikke som eksakte populasjonsandeler for hele FINN.

Detaljer: [`data/qa/dataset_qa.json`](../data/qa/dataset_qa.json).

### 1.5 Begrensninger (datagrunnlag)

- Tekst for tidlige rader ble re-hentet; kan avvike fra teksten ved første klassifisering.
- Én annonse mangler bransje; to mangler tekst.
- First-seen-bransje ≠ full bransjemedlemskap.
- Ingen garantiert dekning av annonser uten bransjetagg.

---

## 2. Klassifiseringsvalidering

### 2.1 Kontrollutvalg

| Egenskap | Verdi |
|---|---|
| Type | Stratifisert tilfeldig innen predikert klasse |
| Frø | **14** |
| Generator | `random.Random(14)`; sortert på id; `shuffle`; ta første n |
| asks | n=100 av 498 |
| silent | n=100 av 8442 |
| rejects | **census** — alle 47 |
| Lagret | [`data/qa/validation_sample.json`](../data/qa/validation_sample.json) |

Utvalget er tilfeldig **innen** hvert stratum, ikke SRS over alle annonser.

### 2.2 Gullstandard (4 kategorier)

Ved manuell/regelbasert gjennomgang av lagret annonsetekst:

| Gullabel (`gold4`) | Betydning |
|---|---|
| `required` | Krever / ber om søknadsbrev, motivasjonsbrev, søknadstekst, personlig søknad o.l. |
| `optional` | Omtaler søknadsbrev som valgfritt |
| `explicit_reject` | Sier eksplisitt nei / ikke nødvendig / ikke send |
| `no_info` | Ingen relevant informasjon |
| `uncertain` | Soft motivasjonsspråk uten klart krav (f.eks. «fortell litt om deg selv») — **ikke** behandlet som sikker asks/rejects |

Usikre tilfeller er ekskludert fra nevneren for sikker treffsikkerhet.

### 2.3 Feilrater per stratum

| Predikert | n | Usikre | Feilrate (sikre) | Wilson 95 % CI |
|---|---:|---:|---:|---|
| asks | 100 | 0 | **11,0 %** | 6,3–18,6 % |
| silent | 100 | 0 | **1,0 %** | 0,2–5,5 % |
| rejects | 47 | 0 | **0,0 %** | 0–7,6 % |

**Stratifisert samlet feilrate:**  
\(\sum_h W_h e_h \approx\) **1,55 %** (vektet approx. Wilson-bånd ca. 0,5–6,2 %).

Gold4 i utvalget:

- asks: 89 `required`, 11 `explicit_reject` (ingen `optional` i utvalget)
- silent: 99 `no_info`, 1 `required`
- rejects: 47 `explicit_reject`

### 2.4 Typiske feil

**A. Falske asks (egentlig eksplisitt nei)** — 11/100  
Produksjonen treffer ordet «søknadsbrev» i formuleringer som «Du trenger ikke skrive søknadsbrev» (hyppig Bane NOR-mal).

**B. Missede asks i silent** — census over alle 8442 silent (lagret tekst):

| Gull | Antall i silent-predikert |
|---|---:|
| `required` (burde vært asks) | **88** |
| `optional` | 0 |
| `explicit_reject` | 28 |
| `uncertain` (ikke omklassifisert som sikker) | 40 |

Dominerende signaler blant missede `required`: *søknadstekst*, *personlig søknad/brev*, bøyde former av *søknadsbrev*.

**C. Rejects** — 0 falske positive i full census av 47.

### 2.5 Observert vs. korrigert (3-veis)

Kun sikre omklassifiseringer. Usikre holdes i silent.

| | Observert | Korrigert punktestimat |
|---|---:|---:|
| asks | **5,54 %** | **~5,91 %** |
| silent | **93,94 %** | **~92,64 %** |
| rejects | **0,52 %** | **~1,44 %** |

Asks-andel intervall (propagerer Wilson-usikkerhet på asks-feilrate i n=100): ca. **5,5–6,2 %**.  
Silent→required og rejects-kvalitet er census på lagrede tekster (ingen utvalgsfeil der).

Detaljer: [`data/qa/validation_report.json`](../data/qa/validation_report.json).

### 2.6 Hva vi *ikke* konkluderer ennå

- Om rekrutteringsbransjen «avskaffer» søknadsbrevet (krever punkt 3–4).
- Bransje-/sektorforskjeller (punkt 3).
- At 5–6 % er andelen blant *alle* FINN-annonser — bare innen dette uttrekket, med dekningsforbehold.

---

## Status

| Punkt | Status |
|---|---|
| 1 Datagrunnlag | Ferdig — fryst, QA-dokumentert, dekning begrenset |
| 2 Validering | Ferdig — stratifisert utvalg lagret, feilrater + korrigerte estimater |
| 3–5 | **Ikke startet** — venter på godkjenning av 1–2 |
