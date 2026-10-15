# Forskningsrapport: leseveiledning

`reports/forskningsrapport.md` lastes opp i deler (`forskningsrapport.md.part.00` …) fordi MCP-payload er begrenset.

```bash
cat reports/forskningsrapport.md.part.* > reports/forskningsrapport.md
```

Kompakt oversikt uten stitching: `reports/resultatoversikt.md`.

Aktive populasjonstall: `python scripts/unpack_gz_sidecars.py` (pakker ut analysis/QA JSON fra `.gz.b64.*`).
