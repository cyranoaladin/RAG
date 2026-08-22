# Lot — Audit scope/profile et architecture multi-scope (2026-08-22, read-only)

## Conclusion (résumé exécutif)

```
MULTISCOPE_ARCHITECTURE_DECISION=Le pipeline d'autorisation actuel (CorpusCampaignV1
  -> ScopeAuthorizationArtifactV2 -> --authority unique de generate_coverage_report
  -> republish_catalog -> promote.yml campaign_id unique) est architecturé de bout
  en bout pour exactement UN ResourceScope par run. Le set authority-required réel
  (72 items) couvre au moins 22 couples (niveau, matière) réels distincts (jamais
  un seul), donc ce pipeline ne peut pas aujourd'hui prouver une couverture
  multi-scope en un seul passage sans élargir artificiellement un scope.
EXISTING_CONTRACT_SUFFICIENT=false
CONTRACT_CHANGE_REQUIRED=true
```

Évidence : voir §4. Aucun code contractuel touché dans ce lot. ADR-0043
(branche quarantinée) n'a pas été relu comme source de cette conclusion —
tout ce qui suit est rederivé directement des contrats de `main` propre.

## 1. Périmètre et méthode

Travail exclusivement dans `~/Bureau/RAG-tier-a-currentness-clean`
(`rag-pedago/tier-a-currentness-clean-20260822`, base commit `9fd2f08`).
Aucune donnée ni logique réutilisée depuis la branche quarantinée
`rag-pedago/tier-a-currentness-byte-identity-20260820`.

## 2. Étape 1 — Reproduction indépendante du set authority-required (72)

Rejoué directement les fonctions réelles (`pii_scan_reconciliation`,
`corpus_catalog_compiler.compile_governed_sealed_catalog`,
`h2b_coverage_report._load_currentness_verification_evidence` +
`_promote_currentness_verified_candidates` + `authority_required_candidate_facts`
+ `authority_required_set_digest`) — jamais dupliqué leur logique — pour
obtenir la liste réelle des 72 `content_sha256`, pas seulement leur digest.

```
AUTHORITY_REQUIRED_COUNT=72
AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
```
→ **identique** à la reproduction indépendante déjà confirmée dans
`docs/reports/lot_tier_a_set_algebra_20260822.md`. **MATCH CONFIRMED.**

## 3. Étape 2/3 — Grounding ResourceScope et mapping profils

Source gouvernée utilisée pour `matiere`/`niveau` :
`catalog["artifacts"][content_sha256]["pedagogical_placements"]`
(dérivé du vrai placement catalog EDUSCOL, `00_ADMIN/eduscol_affectations.tsv`)
— jamais le chemin brut du fichier.

```
AUTHORITY_REQUIRED_CONTENT_COUNT=72
DISTINCT_LEVEL_SUBJECT_PAIRS=22          # (niveau, matière) réels distincts, jamais un échantillon
MATIERE_AMBIGUOUS_COUNT=15               # items avec >1 matière déclarée par le placement catalog (jamais choisie arbitrairement)
NIVEAU_GRADE_SPECIFIC_COUNT=9            # niveau réel = seconde/première/terminale/4e
NIVEAU_NON_GRADE_SPECIFIC_COUNT=63       # niveau réel = "non-classe" ou "multi-niveaux" (valeur gouvernée légitime, mais pas une classe précise)
DISTINCT_CANONICAL_RESOURCE_SCOPES (10 dimensions, entièrement groundées) = 0
ITEMS_WITH_UNRESOLVED_DIMENSION = 72/72
```

**Constat central, pas une erreur de calcul** : sur les 10 dimensions de
`ResourceScope`, seules `matiere` et `niveau` sont partiellement groundables
depuis les données de corpus existantes (placement EDUSCOL réel), et
`school_year` au niveau de la release (dossier de config
`configs/prerentree_2026_2027/`, jamais par contenu individuel — aucune
autre trace de school_year par item n'existe dans le catalogue pour ce
set "actuel" routé par zone, à la différence du set `a_verifier`/`unclassified`
qui, lui, porte `current_for_school_year` dans le registre de currentness).
`tenant`, `collection`, `voie`, `candidat`, `audience`, `visibility`,
`programme_version` n'ont **aucune source gouvernée au niveau du contenu** —
ce sont par construction des attributs assignés par un `CollectionProfile`/une
campagne, jamais intrinsèques au PDF. Donc `DISTINCT_CANONICAL_RESOURCE_SCOPES`
au sens strict (10-uplet complet) est **structurellement non calculable avant
la création de profils** — ce n'est pas un trou de cet audit, c'est la preuve
qu'aucune autorisation multi-scope n'existe encore, cohérent avec
`AUTHORITY_REQUIRED_NO_PROFILE=72` ci-dessous.

Cas notable : les 5 items `PHILOSOPHIE` du set ont `niveau` réel = `non-classe`
(le placement EDUSCOL ne classe jamais Philosophie par classe, car la
matière n'existe qu'en Terminale dans le système français — un fait connu
mais **non déductible d'une source gouvernée**, donc non utilisé ici). Le
seul profil de production existant
(`philosophie_terminale_tc_h2c_v1.yml`, `scope.niveau=terminale`) ne fait
donc **pas** un match exact strict avec ces 5 items sur cette seule base de
données — un point à trancher humainement (enrichir le placement catalog,
ou élargir la définition de "match" pour ce cas précis), pas quelque chose
que ce lot a tranché de son propre chef.

```
PRODUCTION_PROFILE_FILES=1     # philosophie_terminale_tc_h2c_v1.yml (vérifié, pas supposé)
STAGING_PROFILE_FILES=2        # francais_troisieme_tc_wave0_v1.yml, maths_troisieme_tc_wave0_v1.yml (+ multilevel/ + multilevel_manifest.json non comptés comme profils leaf)
AUTHORITY_REQUIRED_MAPPED_PRODUCTION=0
AUTHORITY_REQUIRED_MAPPED_STAGING=0
AUTHORITY_REQUIRED_NO_PROFILE=72
AUTHORITY_REQUIRED_AMBIGUOUS_PROFILE=0
```

Recoupement indépendant fort : `AUTHORITY_REQUIRED_NO_PROFILE=72` est
**identique** au chiffre déjà cité par la mission/le WIP quarantiné pour
cette même quantité — jamais copié, recalculé ici depuis le mapping réel.

## 4. Étape 4 — Audit architecture multi-scope (lecture seule)

Preuves exactes, fichier par fichier :

| Composant | Fichier | Fait vérifié |
|---|---|---|
| `ScopeAuthorizationArtifactV2` | `packages/contracts/src/nexus_contracts/authority_artifacts.py:349` | `scope: ResourceScope` — champ **singulier**, pas une liste/tuple de scopes. `allowed_content_sha256` est bien une liste, mais tous ses éléments partagent obligatoirement l'unique `scope` déclaré. |
| `CorpusCampaignV1` | `services/rag-pedago/rag_pedago/governance/corpus_campaign.py:119` | `scope: ResourceScope` — même contrainte : **une campagne = un scope**. |
| `generate_coverage_report` | `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` (`--authority` CLI arg, `_authority_structural_validation`) | `authority_path` est un chemin de fichier **unique** ; `_authority_structural_validation` appelle `parse_scope_authorization_artifact(raw)` et exige `isinstance(artifact, ScopeAuthorizationArtifactV2)` — un seul objet, jamais une liste/bundle. La complétude (`authority_required_candidate_facts` vs `authority_allowlist`) est calculée sur **tout** le catalogue en un seul passage, comparée à l'allowlist d'une **seule** autorisation. |
| `catalog_republish.republish_catalog` | `services/rag-pedago/rag_pedago/governance/catalog_republish.py:126-172` | `authority_path: Path` — même signature singulière, même lecture d'un seul fichier d'octets. |
| `promote.yml` | `.github/workflows/promote.yml` | `campaign_id: string` (input unique, pas une liste) — le workflow transmet un seul identifiant de campagne à `_produce-h2-evidence.yml`. |
| Runtime worker | `services/rag-engine/src/ingestor/ingestion_worker/runtime_authority.py:41-70` | `RuntimeAuthorityInputs`/`GovernedRuntimeAuthorities` portent un `collection_config_path`/`collection_config_sha256` **singulier** ("Nexus collection catalogue or staging overlay") — même motif : une configuration de collection par démarrage de worker, pas une liste de scopes à résoudre dynamiquement par contenu. |

**Verdict, avec preuve croisée sur 6 composants indépendants de deux
services** : l'intégralité de la chaîne (campagne → autorisation → gate H2
→ republish → promotion CI → runtime) est conçue pour **exactement un
ResourceScope par exécution**. Ce n'est pas un bug isolé dans un seul
fichier — c'est un choix architectural cohérent et répété partout.

Le set réel à autoriser (72 items, ≥22 couples niveau/matière réels
distincts, la plupart des dimensions encore non assignées) ne peut donc
pas être prouvé complet par une seule autorisation sans, au choix :
- **élargir artificiellement le scope d'une autorisation unique**
  (interdit explicitement par les critères de la mission — jamais un
  wildcard, jamais un scope élargi) ; ou
- **fabriquer une autorisation par couple** puis exécuter le gate H2
  autant de fois qu'il y a de scopes — mais `authority_required_candidate_facts`
  mesure la complétude sur **tout** le catalogue à chaque appel, donc
  aucun run individuel ne peut aujourd'hui rapporter "complet pour CE
  scope" — chaque run partiel rapporterait `coverage_complete=false`
  jusqu'à ce que la dernière autorisation manquante soit fournie, sans
  jamais pouvoir composer/unioner plusieurs preuves de scopes différents
  en une preuve globale unique. C'est exactement le trou d'Option A tel
  que conçu aujourd'hui : le modèle de données (`ScopeAuthorizationArtifactV2`)
  supporte bien "un scope par autorisation", mais l'**orchestration**
  (`--authority` singulier, complétude mesurée globalement) ne supporte
  pas d'agréger plusieurs autorisations à scope unique en une preuve de
  couverture globale.

**Option A** (une campagne + une autorisation par scope) : le *modèle de
données* le permettrait déjà (chaque `ScopeAuthorizationArtifactV2` a son
propre scope), mais l'*orchestration* actuelle (CLI/`generate_coverage_report`/
`catalog_republish`/`promote.yml`, tous à authority/campaign singulier) ne
sait pas encore accepter ni composer plusieurs autorisations en une preuve
de couverture globale sur un périmètre multi-scope.

**Option B** (bundle gouverné multi-scope sous une campagne globale) :
n'existe dans aucun contrat accepté aujourd'hui — ni `CorpusCampaignV1` ni
`ScopeAuthorizationArtifactV2` ne portent de liste de scopes.

**Option C** (architecture déjà anticipée par un ADR accepté) : aucun ADR
accepté (ADR-0001, ADR-0035, ADR-0042 lus) n'anticipe explicitement le
multi-scope — seul ADR-0043 (quarantiné, non ratifié) en parlait, et il
porte sur la migration H2 V1→V2, pas sur le multi-scope d'autorisation ;
non réutilisé comme source de cette conclusion.

**Changement minimal nécessaire (décrit, non codé, non ADR rédigé ici)** :
étendre l'orchestration (pas le modèle `ResourceScope`/`ScopeAuthorizationArtifactV2`
lui-même) pour accepter *plusieurs* fichiers d'autorisation en entrée de
`generate_coverage_report`/`catalog_republish`, vérifier qu'ils portent des
scopes et des `allowed_content_sha256` deux-à-deux disjoints (zéro overlap
implicite), et redéfinir la complétude comme "l'union des allowlists
couvre exactement le authority-required set global". Cela reste une
évolution de contrat/orchestration réelle (nouvelle sémantique CLI, nouveau
calcul de complétude) et exigerait donc un ADR et une PR séparée, jamais
implicite — hors périmètre de ce lot d'audit.

## 5. Ce qui n'a pas été fait ici

- Aucun profil créé, aucun contrat modifié, aucun ADR rédigé.
- Aucune autorité, campagne ou autorisation réelle.
- Le mapping ci-dessus porte sur le set 72 actuel (pré-byte-identity) —
  à rejouer après l'audit réseau byte-identity si le
  `AUTHORITY_REQUIRED_SET` change.

## 6. Booléens finaux

```
GOVERNANCE_LOCKS_TOUCHED=false
REAL_AUTHORITY_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
NEW_PROFILE_CREATED=false
CONTRACT_FILES_MODIFIED=false
ADR0043_STATUS=UNREVIEWED_WIP  # non utilisé comme source de cette analyse
```
