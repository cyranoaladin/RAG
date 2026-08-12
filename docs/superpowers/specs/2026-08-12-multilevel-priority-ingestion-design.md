# Extension d’ingestion multi-niveaux prioritaire — design

## Décision et matrice fermée

La release étend l’architecture Wave 0 existante à dix collections. La
Troisième reste immuable. La spécification utilisateur approuve ce design ; la
PR #95 reste Draft, sans écriture publique ni mutation de production.

| Phase | Collection | Externe | Preuve curriculum | Cible élève | Programme exact | Scope signé |
|---|---|---|---|---|---|---|
| A | `rag_nexus_maths_seconde_tc` | `seconde`/`mathematiques` | `seconde`/`generale`/`maths`/`tronc_commun` | `premiere`/`generale`/`maths`/`tronc_commun` | `BOEN_special_1_2019-01-22` | `entree_premiere_maths_v1` |
| A | `rag_nexus_francais_seconde_tc` | `seconde`/`francais` | `seconde`/`generale`/`francais`/`tronc_commun` | `premiere`/`generale`/`francais`/`tronc_commun` | `BOEN_special_1_2019-01-22` | `entree_premiere_francais_v1` |
| A | `rag_nexus_maths_quatrieme_tc` | `4e`/`mathematiques` | `quatrieme`/`college`/`maths`/`tronc_commun` | `troisieme`/`college`/`maths`/`tronc_commun` | `BOEN_special_11_2018-07-26_aj_2020` | `entree_troisieme_maths_v1` |
| A | `rag_nexus_francais_quatrieme_tc` | `4e`/`francais` | `quatrieme`/`college`/`francais`/`tronc_commun` | `troisieme`/`college`/`francais`/`tronc_commun` | `BOEN_special_11_2018-07-26_aj_2020` | `entree_troisieme_francais_v1` |
| B | `rag_nexus_maths_premiere_gen_specialite` | `premiere`/`mathematiques` | `premiere`/`generale`/`maths`/`specialite` | `terminale`/`generale`/`maths`/`specialite` | `BOEN_special_1_2019-01-22` | `entree_terminale_maths_v1` |
| B | `rag_nexus_nsi_premiere_specialite` | `premiere`/`nsi` | `premiere`/`generale`/`nsi`/`specialite` | `terminale`/`generale`/`nsi`/`specialite` | programme NSI Première résolu depuis son index canonique | `entree_terminale_nsi_v1` |
| B | `rag_nexus_francais_premiere_tc` | `premiere`/`francais` | `premiere`/`generale`/`francais`/`tronc_commun` | `premiere`/`generale`/`francais`/`tronc_commun` | `BOEN_special_1_2019-01-22` | `eaf_premiere_francais_v1` |
| C | `rag_nexus_maths_terminale_gen_specialite` | `terminale`/`mathematiques` | `terminale`/`generale`/`maths`/`specialite` | `terminale`/`generale`/`maths`/`specialite` | `BOEN_special_8_2019-07-25` | `terminale_maths_v1` |
| C | `rag_nexus_nsi_terminale_specialite` | `terminale`/`nsi` | `terminale`/`generale`/`nsi`/`specialite` | `terminale`/`generale`/`nsi`/`specialite` | programme NSI Terminale résolu depuis son index canonique | `terminale_nsi_v1` |
| C | `rag_nexus_pc_terminale_specialite` | `terminale` attendu/`physique-chimie` | `terminale`/`generale`/`physique_chimie`/`specialite` | `terminale`/`generale`/`physique_chimie`/`specialite` | `BOEN_special_8_2019-07-25` | `terminale_physique_chimie_v1` |

Chaque scope autorise une seule collection, un rôle `teacher` et la visibilité
`internal`; les autres dimensions de l’enveloppe signée sont celles des deux
colonnes cible/preuve ci-dessus. Chaque collection utilise un profil staging
`multilevel-v1` exact. Pour la Quatrième en 2026-2027, la version cycle 4
`BOEN_special_11_2018-07-26_aj_2020` doit être confirmée par l’index canonique
Quatrième et la preuve officielle avant création des profils ; sinon la
collection reste inactive. La Physique-Chimie Terminale est explicitement un
cas d’audit : le catalogue courant ne porte pas encore son niveau exact.

Les dimensions communes des dix artefacts V2 sont fermées : année
`2026-2027`, audience cible `libre`, candidates cibles `[libre]`, candidat de
preuve `libre`, audiences de preuve `[libre, tous]`, droits
`[officiel_public]`, visibilité `internal`. Le tenant cible est
`libre_<niveau-cible>` et le tenant de preuve `libre_<niveau-preuve>` ; aucune
dérivation n’utilise la collection physique fournie par le client. Chaque
`source_sha256` est le SHA du manifest de release matière correspondant, et
l’enveloppe signée porte exactement l’unique collection du scope. `teacher` est
le rôle HTTP d’acceptance, distinct de l’audience pédagogique `libre`.

## Approches évaluées

1. Accepter uniquement l’exact-grade déjà classé : sûr, mais incomplet.
2. Router par matière/chemin : rapide, mais permissif et interdit.
3. **Approche retenue : release data-driven tierée.** Exact-grade d’abord,
   réaffectation uniquement avec preuve officielle exacte, puis corpus delta
   append-only si les octets officiels actuels manquent réellement.

## Contrat, catalogue et profils

`Niveau.quatrieme` est ajouté au contrat canonique avec bump SemVer mineur,
schemas et types cockpit régénérés. Deux collections grade-specific sont créées
`instanciee=false`. La voie Seconde est alignée sur l’autorité `generale` après
tests collection/profil/index/retrieval.

Les mappings niveau, matière et type documentaire sont des données fermées.
Une valeur inconnue est refusée, sans fallback `cycle4`, `lycee_gt` ou `autre`.
Chaque collection possède un profil staging exact et un manifest de profils
scellé : année, programme, domaine Eduscol, `human_review`, fingerprint et
digest. Profil absent, désactivé ou divergent arrête le startup.

Les profils sont nommés exactement :
`maths_seconde_tc_multilevel_v1.yml`,
`francais_seconde_tc_multilevel_v1.yml`,
`maths_quatrieme_tc_multilevel_v1.yml`,
`francais_quatrieme_tc_multilevel_v1.yml`,
`maths_premiere_gen_specialite_multilevel_v1.yml`,
`nsi_premiere_specialite_multilevel_v1.yml`,
`francais_premiere_tc_multilevel_v1.yml`,
`maths_terminale_gen_specialite_multilevel_v1.yml`,
`nsi_terminale_specialite_multilevel_v1.yml` et
`pc_terminale_specialite_multilevel_v1.yml`.

## Inventaire et corpus delta

L’inventaire décrit artefacts, placements, objets physiques et valeurs externes
des dix lignes. Un zéro, ou une collection sans candidat finalement éligible,
déclenche six recherches consignées : (1) placements, (2) chemins physiques
scellés, (3) `multi-niveaux`, (4) `non-classe`, (5) matière+programme, (6)
catalogue Eduscol et sources officielles configurées.

Une ressource multi-niveaux n’est liée que si une preuve officielle identifie
exactement grade, voie, statut et programme. Si les octets officiels actuels
manquent du catalogue — même si une ancienne version existe — un delta corpus
append-only lie l’ancien manifest, provenance, octets, SHA, placements et
nouveau catalogue scellé. Tous les gates sont alors rejoués ; aucun manifest
historique n’est modifié.

Après tout delta, le builder reconstruit obligatoirement l’inventaire final
depuis le catalogue vNext, puis une preuve currentness et une preuve PII portant
exactement son set SHA. Les manifests de release ne peuvent pinner que ces
autorités finales ; les inventaires et preuves pré-delta restent historiques et
ne peuvent pas autoriser Worker A/B.

## Gates, releases et multi-placement

Chaque SHA passe currentness, droits, PII v5, extraction et chunking E5 réel.
La preuve currentness scelle `school_year=2026-2027` à la racine et par artefact,
programme applicable, digests inventaire/catalogue, chemin exact, URL
officielle, SHA téléchargé et identité d’octets. Une divergence rend uniquement
l’artefact concerné non éligible.

Chaque collection possède un manifest ; un agrégat les référence par chemin
relatif et SHA. Les partitions vérifient
`candidates = release_eligible + named_noneligible`, sans trou ni double compte.

Les chemins de release sont fermés :
`seconde/{maths,francais}.release.json`,
`quatrieme/{maths,francais}.release.json`,
`premiere/{maths_specialite,nsi_specialite,francais}.release.json`,
`terminale/{maths_specialite,nsi_specialite,physique_chimie_specialite}.release.json`
et l’agrégat `multilevel.release.json`.

Un SHA peut apparaître dans plusieurs releases si ses faits physiques et son
chunk set sont identiques. L’agrégat fusionne les placements et conserve un seul
embedding set ; il refuse uniquement les définitions conflictuelles.
`source_placement_id` est propagé de Worker A à Worker B.

## Ingestion, identité, readiness et recherche

L’exécution réutilise LOT41A → Worker A → LOT42 → Worker B. Un job représente
un placement. Les CLI chargent l’agrégat et toutes les preuves au startup.

Les dix scope IDs de la matrice sont V2, à collection unique, indépendamment
révocables et utilisent `teacher/internal` pour l’acceptance. La cible élève et
la preuve curriculaire restent distinctes. Les nouveaux scopes NSI sont bloqués
jusqu’à readiness exacte ; le scope legacy demeure séparé et les anciennes
lignes ne sont jamais certifiées rétroactivement.

Le validateur compare les sets exacts par collection. Les collections dormantes
ne sont activées qu’après release non vide et réconciliation exacte. Après
l’ingestion complète, chaque collection ingérée reçoit trois requêtes naturelles
et une probe par artefact. Le batch complet est rejoué pour l’idempotence. La
socket HTTP réelle rejoue aussi les scopes existants Troisième afin de détecter
toute régression de registre ou de readiness.

Les deux modèles sont des autorités de release non substituables : embedding
`intfloat/multilingual-e5-large`, dimension `1024`, inventory
`e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a` ;
reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, inventory
`bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1`.
L’acceptance impose `FAKE_VECTOR_ROWS=0`.

## Erreurs et preuves de succès

- Mapping inconnu, placement ambigu, autorité/modèle divergent : DENY.
- Currentness non prouvé, PII, OCR ou extraction échouée : non-éligible nommé,
  puis poursuite du batch.
- Collection sans ressource sûre : inactive, `CORPUS_DELTA_REQUIRED=true` et
  preuve exhaustive du manque.

La livraison exige les dix lignes de métriques, réconciliation exacte,
idempotence, vrais modèles, CLI multi-collection, smokes et discoverability,
CI locale et GitHub vertes. Trusted review reste rouge attendu sur la PR Draft.
