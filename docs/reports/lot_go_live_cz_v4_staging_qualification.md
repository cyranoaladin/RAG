# Lot CZ — qualifier V4 sur le staging, un seul sens pour chaque dimension servie

- Branche : `go-live/cz-v3-staging-qualification`
- Base : `7c65ec4b9eeeb2db62905e0e258ba3d5ea3e90f4` (main après #250)
- Décisions du propriétaire : option A (2026-09-24, qualifier les octets exacts
  sur le staging) ; voie S (2026-09-24, successeur V4 aux programmes cohérents).
- ADR : **ADR-0060** (qualification staging d'une release de production),
  **ADR-0061** (programme_version et visibilité servies des profils V4).

## 1. Ce que le banc a mesuré avant ce lot

Aucune release `production-profile-gate` ne pouvait être publiée sur le
staging, pour quatre raisons découvertes l'une après l'autre sur les vraies
releases : Worker B exigeait des profils de staging et vérifiait le reçu PII
réel avec des clés de test (A) ; les autorisations acquises sont LOT41A-V1
alors que la publication exige V2 (A) ; `programme_version` portait un
identifiant de corpus là où le retrieval sert le programme officiel (S) ; la
visibilité des profils (`public`) n'était pas celle que le retrieval sert
(`internal`, ADR-0045).

## 2. Ce que le lot change

| Pièce | Rôle |
|---|---|
| `ingestion_profiles/release_qualification.py` | `ReleaseBoundQualification`, déduite d'une readiness de staging vérifiée qui nomme la release, son manifeste et l'image ; jamais d'un argument |
| `multilevel_publication_resume_cli` / `multilevel_runtime_authority` | sous qualification : profils de production de la release, chaîne PII vérifiée avec les clés qui l'ont signée ; production et répétition ordinaire inchangées |
| migration 019 + `bind-publication-authorities` | autorité de publication LOT41A-V2 liée, en ajout seul, à chaque placement adopté, à côté de l'autorité d'acquisition |
| `publication_attestation` (chemin batch) | exige une autorité liée au contenu : V2, contenu nommé, même collection |
| profils `v3_livraison_315` + manifeste | V4 : programme officiel par collection, visibilité servie ; provenance nommée |
| producteur | lit la lignée déclarée en rehearsal ; refuse, hors lignée historique, un programme non officiel |
| release V4 `release-024f8625ebfeb7ce` | successeur de V3 (manifeste `bab9c398…`) |
| `build_lot41a_r4_authorizations.py` | onze r4 dérivées (versées par leur propre PR) |
| registre de politique V4 + onze scopes | émis par l'émetteur canonique ; `nexus-contracts` 0.21.0 |
| `measure_staging_state.sh` | mesure du staging en lecture seule |

## 3. V4 face à V3 (`docs/reports/evidence/lot_cz_profile_gate_v4/diff_v3_v4.json`)

| Catégorie | Constat |
|---|---|
| Octets documentaires, texte et identité des chunks | 315 artefacts, 8 268 chunks : identiques |
| Couples collection–contenu | 479 : identiques |
| Placements | seuls `programme_version`, `visibility` et `placement_id` (dérivé) changent, sur les 479 |
| Inventaire, preuve PII, registre de programme, pré-vol | identiques octet pour octet |
| Actualité | dispositions identiques ; seule la référence à l'audit réseau change (identité de release) |
| Autorités | une seule modifiée : `profile_manifest_sha256`, motif prouvé par commit |
| Droits, audiences, domaines, exclusions, décisions PII | inchangés |

Chaîne PII : `verify-release-sources` sur V4 → 293 `CLEARED`, 22
`DETECTED_REVIEWED_ACCEPTED`, 0 refus, chaîne de revue égale à celle que V4
déclare (jeu `1b70d91b…`, reçu `22361dd1…`, expiration 2026-10-23).

## 4. Concordance de programme (onze collections)

Taxonomie de la collection = registre de programme de V4 = profil V4 =
placements scellés = r4 = scope de retrieval V4 (`evidence_subject`), pour les
onze. Visibilité : `internal` du profil au scope.

## 5. Épreuves

Voir § 7 (banc sur vraies releases) et § 8 (CI).

## 6. Points à confirmer par un humain

1. ADR-0060 et ADR-0061 (review de cette PR).
2. Pour les trois collections décidées sous ADR-0053 (HGGSP ×2, HLP
   terminale), l'admissibilité est portée à `currentness=official_snapshot`
   (ADR-0059) dans le registre de politique V4 ; la décision de politique
   elle-même est reconduite telle quelle.
3. L'accès des élèves (`student` ne lit que `public`, les scopes sont
   `internal` depuis ADR-0045) reste une décision produit hors de ce lot.
4. **Escalade — retrieval dense et chunks identiques (hors périmètre, non
   corrigé ici).** Le canal dense refuse une requête, fermé par conception
   (lot 40, `dense ann tie overflow`), quand les rangs 200 et 201 de son pool
   sont à égale distance. Deux chunks au texte identique ont le même vecteur :
   si la frontière du pool tombe sur eux, la requête est refusée. Le banc l'a
   prouvé sur dgemc (paire `1a332fef…`/`af87abb8…`, distance
   0.18326674799521137 aux deux rangs). Sur tout V4 : 15 groupes de doublons
   exacts dans 7 collections (17 chunks en surplus sur 12 316 couples
   chunk–collection). Taux de refus mesuré sur le banc (requêtes par vecteur
   de chunk) : dgemc 3/343 (0,9 %), nsi première 2/483 (0,4 %), svt première
   0/663. Corriger demande de toucher le retrieval (départage stable
   des égalités, ou dédoublonnage à la construction d'une release future) :
   décision à prendre hors de ce lot.
5. **Observation — rappel de l'ANN sur le chemin servi.** `PgCandidateStore`
   (psycopg, chemin v2 servi) ne fixe pas `hnsw.ef_search` et reste au défaut
   de pgvector (40), alors que l'ancien chemin asyncpg (`database.py`) le
   fixait à 100. Sur un run intermédiaire du banc, un chunk interrogé par son
   propre vecteur n'est pas sorti en tête (l'index HNSW est reconstruit à
   chaque run, son rappel varie) ; le run final retrouve en tête tous les
   chunks non refusés. L'isolation de scope n'est jamais en cause : aucun
   candidat hors du jeu publié. Le réglage relève du retrieval, hors de ce
   lot.

## 7. Banc sur vraies releases

`services/rag-engine/tests/integration/test_v4_staging_direct_real_chain.py`
rejoue, par les vrais CLI, sur les octets réels de V4, le chemin direct que
suivra le staging : bases de contrôle et produit jetables (image pgvector
épinglée, vraies migrations), forge GitHub locale, modèle E5 réel, chaîne
PII réelle. Run final du 2026-09-24 : 10 tests réussis en 20 min, dont Worker B sur CPU pour l'essentiel.

| Étape | Mesure |
|---|---|
| Onze r4 enregistrées par `authorize_scope_cli` | 11 |
| Worker A (`sealed_release_ingestion_cli`) sous les r4 | 11 runs, 479 ressources / candidats / artefacts, 4 790 événements, `NEEDS_REVIEW`, 0 écriture produit |
| `propose-release-batch-review` puis `record-release-batch-attestation` | 479 projetés, 479 attestations ; la revue ne nomme que des r4 |
| Worker B | `authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION`, `production_approval=false` ; 60 jobs (dgemc, nsi première, svt première), 0 erreur, 60 `RETRIEVAL_ELIGIBLE` |
| Base produit relue | 60 artefacts, 60 placements (`placement_id` de V4, r4, attestation du job), 1 489 chunks en 1 024 dimensions ; programme BOEN de chaque collection, `internal`, `officiel_public` |
| Identité des chunks (`test_3b`) | 0 écart sur 60 contenus : chaque `(chunk_id, chunk_sha256, chunk_index)` publié est celui que V4 scelle |
| Retrieval (`test_4`) | jeton `teacher` signé sous le scope que nomme `production-profile-scope-successors-v4.yml` (`prod_*_v3`), vrai `PgCandidateStore` : chaque chunk publié interrogé par son vecteur (1 489 requêtes denses) et une requête lexicale par collection ; **aucun candidat hors du jeu publié de la collection** ; programme BOEN et `internal` portés par le scope |
| Rappel dense (même run) | dgemc 340/343, nsi première 481/483, svt première 663/663 retrouvés en tête ; 0 manqué ; 5 refus, tous constatés à la source comme `dense ann tie overflow` (§ 6, point 4) |
| Contre-épreuve d'accès | rôle `student` sous les mêmes scopes : refusé (`internal` hors de ses visibilités) |

Contre-épreuves, chacune un test :

* r2 (LOT41A-V1, visibilité `public`) à la place d'une r4 : Worker A
  n'ingère rien (`authorizes scope … differs`).
* readiness de staging nommant V3 avec la release V4 : démarrage refusé
  (`authorises release manifest c0f5897b…, not bab9c398…`).
* profils de V3 avec la release V4 : démarrage refusé (`release allowlist
  authority digest differs`).
* reprise après écriture produit : aucun doublon, autorité inchangée.

Défaut trouvé et corrigé par le banc : sur le chemin scellé, Worker B filtrait
les fragments non textuels puis renumérotait. 15 des 1 489 chunks scellés de
8 contenus manquaient, et les `chunk_id` divergeaient. Worker B publie
désormais exactement les chunks scellés, vérifiés empreinte par empreinte et
dans l'ordre ; tout écart est un refus
(`select_publication_chunks`, `test_governed_publication_sealed_chunks.py`).
Les 15 fragments sont scellés par V4 tels quels ; leur qualité est une
observation pour une release future, pas une substitution au moment de
publier.

## 8. CI

Mesures locales du 2026-09-24 sur la branche (les venvs partagés du checkout
principal, sources du worktree en `PYTHONPATH`) :

| Périmètre | Résultat |
|---|---|
| `packages/contracts/tests` | 979 réussis |
| `scripts/qualification/tests` | 421 réussis, 4 ignorés |
| `scripts/tests` | 541 réussis, 7 ignorés, 4 échecs **hors lot** : readiness go-live exige 40 Go libres, 19 disponibles (`disk_policy_ok`) |
| rag-pedago `tests` | 3 562 réussis, 4 ignorés, 0 échec, après ré-attestation de la provenance du producteur (les scopes V4 changent l'empreinte du registre) |
| rag-engine unitaire | 4 133 réussis, 1 échec **hors lot** : `test_r1_operator_flow` compare la version installée de `nexus-contracts` (0.19.0 dans le venv partagé) à celle du checkout (0.21.0) ; la CI réinstalle en éditable |
| `ruff check` (fichiers du lot) | vert ; `mypy` : aucune erreur nouvelle (les erreurs restantes datent d'avant la base) |
| verrous de gouvernance | 18 clés conformes à la base |
| unicité des autorités | PASS |
| banc réel V4 (§ 7) | `test_v4_staging_direct_real_chain.py` : 10 réussis sur 10 (20 min) |

La CI GitHub de la PR fait foi pour la reproduction hermétique.

## 9. Ce qui reste, par ordre de dépendance

1. Revue et fusion de ce lot ; reconstruction des images worker **et** ingestor
   (nouvelles dépendances : contrats 0.21.0, code worker).
2. Mesure du staging en lecture seule (accès réseau à rétablir).
3. Amendement staging portant les images finales et les opérations exactes
   (chemin direct ou reprise contrôlée selon la mesure).
4. PR des r4, enregistrées pendant qu'elle est ouverte ; signatures des
   readiness ; exécution ; revue batch ; Worker B ; retrieval.
