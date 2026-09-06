# Release multi-niveaux du 2026-08-13 — remplacée

Conservée telle quelle comme preuve historique. Aucune réécriture.

```
OLD_DATE                = 2026-08-13
OLD_RELEASE_SHA256      = d8ee6703d3497e34e6e5273bee00da90ab9c82094f0f9a1257eef0ff91da1828
OLD_EXPECTED_CHUNKS     = 359
OLD_EXTRACTOR_LINEAGE   = anterieur a a4b1f96 (avant la page policy PDF)
OLD_PREFLIGHT_SHA256    = e440745c7bc04b5398863a80bf6d4ad8128fc8726d0615d6947412f8d557cf5f
OLD_PREFLIGHT_PRODUCER  = outil externe, hors depot (2026-08-12)

SUPERSEDED_REASON       = page-policy/extractor semantic change
SUPERSEDED_BY_COMMIT    = a4b1f96 (PR #142), qui a modifie
                          ingestion_agents/extractor.py et publication_chunking.py
```

Sous la sémantique actuelle, les mêmes onze artefacts rendent **353** chunks au
lieu de 359, à nombre de pages identique (137). L'écart n'est pas une dérive de
contenu : c'est un changement de découpage, assumé et daté.

La release courante nomme désormais son runtime d'extraction
(`MULTILEVEL_RELEASE_PREFLIGHT_V2`), précisément pour que deux préflights issus
de deux extracteurs cessent d'être indiscernables.
