# Lot status

| Lot | Sujet | Statut | Commit | Tests | Remarques |
| --- | --- | --- | --- | --- | --- |
| 1 | Socle dépôt isolé | commité | `1e32b21` | OK | Arborescence, doctor, scaffold. |
| 2 / 2.5 | Schémas, taxonomies, profils métier | commité | `f11597a` | OK | `DocumentMeta`, profils, droits, taxonomies. |
| 3 | Ledger SQLite minimal | commité | `3321355` | OK | Runs, documents, états, chunks, erreurs. |
| 3.5 | Durcissement ledger | commité | `be519cc` | OK | Diagnostics, revalidation Pydantic. |
| 4 | Import manifest local | commité | `5de617b` | OK | JSONL local vers ledger, metadata-only. |
| 4.5 | Durcissement import manifest | commité | `548a2b1` | OK | Hash manifest, erreurs normalisées. |
| 5 | Import dossier manifests | commité | `a80539b` | OK | Dry-run, doublons, rapport global. |
| 5.5 | Politique qualité | commité | `7432bf3` | OK | Blocages configurables. |
| 6 | Readiness report | commité | `db82f95` | OK | Décision humaine pré-ingestion. |
| 6.5 | Coverage report | commité | `4099730` | OK | Comparaison manifests/taxonomies. |
| 7 | Pre-ingestion gate | commité | `3e9db66` | OK | Décision combinée. |
| 7.5 | Batch clean nominal | commité | `6a803c7` | OK | Chemin nominal validé. |
| 8 | Import contrôlé par gate | commité | `2831ed2` | OK | Gate obligatoire avant écriture. |
| 9 | Référentiel officiel | commité | `60869de` | OK | Sources, niveaux, examens, candidats. |
| 9.5 | Intégrité référentielle | commité | `0bf6cbc` | OK | Claims, examens composés, AEFE contexte. |
| 10 | Qualité refs officielles | commité | `5f0613c` | OK | Manifests contrôlés contre `data/reference/`. |
| 10.5 | Fixtures profils officiels | commité | `ed76275` | OK | DNB, EAF, EAM, bac, AEFE, double cursus. |
| 11 | Resolver officiel | commité | `c8a9272` | OK | Compatibilités indirectes. |
| 11.5 | Explicabilité resolver | commité | `d490271` | OK | Explications dans issues et rapports. |
| 12 | Review package et approval | commité | `490055a` | OK | Revue humaine traçable. |
| 12.5 | Durcissement review | commité | `9276da5` | OK | Hashes canoniques, registry, reviewer policy. |
| 13 | Audit runtime ledger | commité | `0fa3756` | OK | Packages, décisions, tentatives et vérifications dans SQLite. |
