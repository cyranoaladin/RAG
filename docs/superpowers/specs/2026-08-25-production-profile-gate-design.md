# Profile gate de production 2026-2027 — Design

**Statut :** décisions produit P01-P24 approuvées par la Direction projet le
2026-08-25. Ce document fige leur traduction technique avant implémentation.
La revue humaine GitHub reste distincte et n'est pas simulée.

## Objectif et frontière

Ce lot transforme le set pré-profile de 72 contenus en un set de production
exact, puis produit les profils, le manifeste de profils et la projection de
placement nécessaires aux autorisations ultérieures. Il ne crée aucune
autorisation, aucun `ReviewBinding`, aucune campagne réelle, aucune écriture
PostgreSQL et aucun déploiement.

Les quatre travaux indépendants sont :

1. profile gate et PR de profils ;
2. rehearsal Docker atomique V2 ;
3. audit DB, backup et restore rehearsal ;
4. GitHub Environment `production`.

Seul le premier est contenu dans la PR de profils. Une correction du harness
Docker part dans une PR technique séparée. Les preuves opérationnelles sont
sanitisées avant versionnement.

## Entrées immuables

- commit `main` : `3f0317e91c9ac8eff8ff1089d100a25f7c875793` ;
- tree : `5bc5234ea395486810638d553c3c9bc2e7d57d75` ;
- corpus manifest :
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- set pré-profile : 72 SHA, digest
  `3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0` ;
- snapshot Drive et ledgers versionnés sous
  `docs/reports/evidence-index/` ;
- matrice proposée de PR #130 ;
- politique P24 et profil `h2c-v1` existants.

Les 61 PDF examinés localement (56 P11-P23 et 5 P24) ont été récupérés par ID
Drive figé. Le SHA-256 de chaque fichier est égal au nom de contenu attendu.
Ils restent hors Git et ne deviennent pas une nouvelle source de vérité.

## Résolution P01-P10 et P24

Les dix profils P01-P10 sont copiés depuis `staging/multilevel/` vers la
racine production du registre. Les octets YAML sont identiques ; aucun champ
de scope, version ou sémantique n'est modifié. Ils couvrent onze contenus.

P24 conserve exactement le profil, sa version `h2c-v1`, son fingerprint et
les cinq placements de `h2_initial_placement_policy.yml`. Il est ajouté à une
release enregistrée qui nomme `rag_nexus_philo_terminale_tc` et lie le même
profil et le manifeste de profils final.

## Résolution P11-P23

Chaque SHA reçoit un record individuel avec les dimensions demandées, leurs
preuves versionnées, un statut et un code de raison. Les buckets
`multi-niveaux` et `non-classe` ne sont jamais recopiés comme niveau.

Dix contenus sont `EXACTLY_GROUNDED` :

- P16 : `db43d342...` — physique-chimie, première générale, spécialité,
  `BOEN_special_1_2019-01-22` ;
- P18 : `06e491d3...` et `2f1035c7...` — SES, première et terminale
  générales, spécialité, BOEN spécial 1 et 8 ;
- P19 : `8eb0e41f...` et `d2cbd06f...` — SVT, première et terminale
  générales, spécialité, BOEN spécial 1 et 8 ;
- P21 : `e591a87a...` — DGEMC, terminale générale, option,
  `BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A` ;
- P23 : `4433fee9...`, `60eeb7dd...`, `64f5b342...` et `9357dfde...` —
  HLP première générale, spécialité, `BOEN_special_1_2019-01-22`.

Les quatre ressources HLP sont rattachées à la première par les thèmes
officiels « La parole » / « Les représentations du monde » ou par la mention
explicite « classe de première ». Le bandeau générique 1re/Tle ne suffit pas
à lui seul et n'est pas utilisé comme preuve.

Les 46 autres contenus sont `AMBIGUOUS` ou `UNRESOLVED` et deviennent
`REVIEW_REQUIRED` pour cette release. Les raisons sont bornées : plusieurs
niveaux ou matières réels, voie technologique sans stratégie de release,
ressource transversale sans classe exacte, programme primaire absent, ou
ressource française millésimée devenue impropre à 2026-2027. Ils restent
comptés dans l'inventaire et n'entrent dans aucune autorisation ni release.

Le résultat attendu est donc :

- `FINAL_PRODUCTION_ELIGIBLE_COUNT=26` ;
- `FINAL_PROFILE_REVIEW_REQUIRED_COUNT=46` ;
- 18 profils de production : P24, dix promotions et sept nouveaux profils ;
- un digest final recalculé depuis les 26 SHA triés avec LF final, forcément
  différent du digest historique des 72.

## Collections et profils nouveaux

Les collections existantes sont réutilisées :

- `rag_nexus_pc_premiere_specialite` ;
- `rag_nexus_ses_premiere_specialite` ;
- `rag_nexus_ses_terminale_specialite` ;
- `rag_nexus_svt_premiere_specialite` ;
- `rag_nexus_svt_terminale_specialite` ;
- `rag_nexus_hlp_premiere_specialite`.

La seule collection à créer est
`rag_nexus_dgemc_terminale_option`, après preuve terminale/générale/option.
Elle reste `instanciee: false` tant que le cutover et l'ingestion réels ne
l'activent pas. Aucun verrou `*_allowed` n'est modifié.

Les sept profils nouveaux ont `profile_version: production-v1`, candidat
`libre`, audience `[libre, tous]`, visibilité `internal` et année
`2026-2027`. Leurs autres dimensions viennent exclusivement des sources
primaires listées dans les records.

## Manifeste de profils et release exécutable

`services/rag-engine/configs/ingestion_manifest.yml` devient le manifeste
exact des 18 profils chargés par le registre non récursif. Chaque fingerprint
est recalculé avec le contrat partagé, jamais copié à la main.

La release existante P01-P10 reste inchangée. Une release additionnelle
`production-profile-gate-2026-2027-v1` contient les cinq contenus P24 et les
dix nouveaux contenus. Elle réutilise le format
`MULTILEVEL_AGGREGATE_RELEASE_V1`, déjà accepté par le runtime. Ses chunks
sont produits par le chunker PDF page-aware canonique
`publication_chunking.chunk_publication`, avec le tokenizer E5 réel et sans
vecteurs. Les manifests ne stockent que les identités/digests/pages déjà
attendus par `release_readiness`.

Un producteur déterministe prend uniquement : PDF dont le SHA est vérifié,
records de résolution, profils vérifiés et preuves versionnées. Il refuse un
fichier absent ou changé, un profil non exact, une page vide, un chunk trop
long, une collection non déclarée ou un contenu hors set final. Le format de
release existant et son loader ne sont pas élargis.

## Projection `ReleaseScopePlacementV1`

Le producteur exact-Git de PR #129 lit depuis le même tree :

- la matrice finale ne contenant que les 26 contenus groundés ;
- les placements acceptés ;
- le registre de releases ;
- le set final ;
- les 18 faits de profils vérifiés ;
- le manifeste de profils.

Il doit produire exactement 26 lignes, zéro gap/extra/ambiguïté et relire
chaque source de profil par blob Git. Les 46 résiduels ne sont pas placés ;
leur disposition `REVIEW_REQUIRED` est prouvée séparément dans le ledger
terminal final.

## Comptabilité globale

Le recalcul repart des 2 582 lignes uniques du ledger, remplace uniquement la
disposition des 46 résiduels du set pré-profile et vérifie :

- `UNIQUE_CONTENTS=2582` ;
- `UNACCOUNTED_CONTENTS=0` ;
- `TERMINAL_DISPOSITION_COVERAGE=100%` ;
- set final = P24 (5) ∪ P01-P10 (11) ∪ nouveaux groundés (10) ;
- union disjointe, sans doublon ni SHA artificiel.

Le rapport Master Go-Live nomme explicitement l'ancien set
`FINAL_PRE_PROFILE_ELIGIBLE` et le nouveau set
`FINAL_PRODUCTION_ELIGIBLE`. Aucune valeur aval `AUTHORIZED`, `REPUBLISHED`,
`H2_COVERED`, `INGESTED` ou `API_DISCOVERABLE` n'est avancée dans cette PR.

## TDD et cas adversariaux

Les tests rouges précèdent chaque comportement : promotion byte-identique,
résolution exhaustive 56/56, refus `unknown`/`lycee_gt`/programme synthétique,
digest final exact, manifest 18/18, release registry réellement chargeable,
P24 5/5, profil/source/fingerprint modifié, PDF modifié, mauvais digest de
release, gap/extra/overlap de placement, résiduel placé, et comptabilité
2 582/2 582.

La vérification finale comprend contrats, rag-pedago, rag-engine, ruff, mypy,
governance locks, repository controls, gitleaks différentiel et mutations.
Deux revues contradictoires fraîches précèdent le push final. Le lot s'arrête
sur la vraie challenge `trusted-human-review` du HEAD immuable de la PR.

## Rollback

La PR ne mutera ni DB ni service. Son rollback est le revert de la PR : les
profils staging, les releases historiques et les dispositions antérieures
restent présents et auditables. Les fichiers source téléchargés sont des
temporaires ignorés et peuvent être recréés depuis les IDs Drive figés.
