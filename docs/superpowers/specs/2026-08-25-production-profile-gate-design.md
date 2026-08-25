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
Ils restent hors Git et ne deviennent pas une nouvelle source de vérité. Leur
inspection produit toutefois
`docs/reports/production_profile_primary_evidence_20260825.json` : un record
par contenu avec ID Drive, SHA du PDF, chemin canonique, URL officielle,
pages/sections contrôlées, courts faits textuels déterminants et identifiants
BO/NOR. Le digest de ce document est lié aux records de résolution. Ainsi les
affirmations HLP/DGEMC sont auditables et ne reposent pas sur la seule
existence d'un chemin.

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
  différent du digest historique des 72 :
  `fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0`.

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

Les sept profils nouveaux ont `profile_version: profile-gate-v1`, candidat
`libre`, audience `[libre, tous]`, visibilité `internal` et année
`2026-2027`. Leurs autres dimensions viennent exclusivement des sources
primaires listées dans les records.

## Manifeste de profils et release exécutable

`services/rag-engine/configs/ingestion_manifest.yml` devient le manifeste
exact des 18 profils chargés par le registre non récursif. Chaque fingerprint
est recalculé avec le contrat partagé, jamais copié à la main.

Les manifests historiques Wave 0 et P01-P10 restent byte-identiques et
auditables, mais toutes leurs anciennes entrées de registre sont remplacées
par une release unique
`production-profile-gate-2026-2027-v1` couvrant les 26 contenus et les 18
profils. Cela évite que P01-P10 restent liés au digest du manifeste staging
alors que les placements et autorisations futurs utilisent le manifeste de
production, et empêche les deux contenus Wave 0 hors set final d'entrer dans
la readiness runtime. Le registre de production contient exactement cette
release unique ; les anciens fichiers restent seulement des preuves
historiques non enregistrées. La release réutilise le format
`MULTILEVEL_AGGREGATE_RELEASE_V1`, déjà accepté par le runtime. Les chunks
P01-P10 sont repris après validation des manifests historiques ; ceux des 15
autres contenus sont produits par le chunker PDF page-aware canonique
`publication_chunking.chunk_publication`, avec le tokenizer E5 réel et sans
vecteurs. Les manifests ne stockent que les identités/digests/pages déjà
attendus par `release_readiness`.

Le bundle lie réellement, par digest, les entrées versionnées suivantes sous
`services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/` :

- `candidate_inventory.json` — exactement 26 contenus/placements ;
- `currentness_evidence.json` — exactement les 26 identités de téléchargement
  et l'année 2026-2027 ;
- `pii_evidence.json` — projection exacte des décisions PII du ledger et de
  leurs preuves antérieures ;
- `preflight_evidence.json` — extraction, pages, chunks et comptages complets ;
- `programme_registry.json` — les 18 scopes et identifiants primaires ;
- `level_mapping.json`, `subject_mapping.json` et
  `document_type_mapping.json` ;
- le registre de droits existant, la policy PII, les inventaires de modèles,
  le catalogue scellé et son delta, tous nommés avec chemin et digest dans
  `authority_bindings.json` ;
- le manifeste des 18 profils de production.

Un producteur déterministe prend ces preuves, les PDF dont le SHA est vérifié,
les profils vérifiés et les manifests historiques P01-P10. Il prouve que
chaque autorité couvre exactement les 26 SHA avant d'en inscrire le digest.
Il refuse un fichier absent ou changé, une couverture partielle, un profil non
exact, une page vide, un chunk trop long, une collection non déclarée ou un
contenu hors set final. Chaque binding d'autorité possède un test de mutation.
Le format de release existant et son loader ne sont pas élargis.

Le consommateur production est testé au-delà de
`load_release_registry_file` : le chemin runtime charge le registre, les
profils production et le bundle exact. Le resolver multi-niveaux accepte un
manifeste de profils production strict en plus du manifeste staging historique
strict ; aucun fallback entre les deux schémas n'est permis et les tests
staging restent inchangés.

## Projection `ReleaseScopePlacementV1`

Le producteur exact-Git de PR #129 lit depuis le même tree :

- la matrice finale ne contenant que les 26 contenus groundés ; pour P01-P10,
  tous les `source_of_truth` et `evidence_sources` nomment les copies YAML de
  production, jamais les chemins staging ;
- les placements acceptés ;
- le registre de releases ;
- le set final ;
- les 18 faits de profils vérifiés ;
- le manifeste de profils.

Il doit produire exactement 26 lignes, zéro gap/extra/ambiguïté et relire
chaque source de profil par blob Git. Les 46 résiduels ne sont pas placés ;
leur disposition `REVIEW_REQUIRED` est prouvée séparément dans le ledger
terminal final.

La génération n'est pas auto-référentielle : un premier commit fige tous les
inputs et blobs de preuve ; le producteur lit ce commit exact ; un second
commit ajoute uniquement la projection dérivée et sa provenance. Un contrôle
final compare les blob SHA de tous les inputs entre le commit source et le
HEAD de PR. Tout changement ou rebase régénère la projection.

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
résolution exhaustive 56/56, preuve primaire page/section et digest, refus
`unknown`/`lycee_gt`/programme synthétique, digest final exact, manifest
18/18, release registry réellement consommable par le runtime, mutations de
chaque autorité, P24 5/5, profil/source/fingerprint modifié, PDF modifié,
mauvais digest de release, source staging dans la matrice production,
union du registre différente des 26 contenus ou des 18 collections,
gap/extra/overlap de placement, résiduel placé, dérive post-freeze d'un input,
et comptabilité 2 582/2 582.

La vérification finale comprend contrats, rag-pedago, rag-engine, ruff, mypy,
governance locks, repository controls, gitleaks différentiel et mutations.
Deux revues contradictoires fraîches précèdent le push final. Le lot s'arrête
sur la vraie challenge `trusted-human-review` du HEAD immuable de la PR.

## Rollback

La PR ne mutera ni DB ni service. Son rollback est le revert de la PR : les
profils staging, les releases historiques et les dispositions antérieures
restent présents et auditables. Les fichiers source téléchargés sont des
temporaires ignorés et peuvent être recréés depuis les IDs Drive figés.
