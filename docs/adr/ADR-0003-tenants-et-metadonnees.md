# ADR-0003 — Isolation par tenant et schéma de métadonnées des chunks

- **Statut** : Accepté
- **Date** : 2026-06-24
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation), ADR-0002 (contrat partagé)
- **Révise** : la nomenclature de tenants annoncée dans `docs/ROADMAP.md` (`{population}_{niveau}`)
- **Conditionne** : Lot 1.1 (chunking pédagogique), Lot 1.2 (indexation), Lot 2 (retrieval filtré)

## Contexte

`rag-engine` (pgvector) isole les données par une colonne `tenant` et filtre finement via un index GIN sur `metadata` JSONB. Le contrat `nexus-contracts` produit déjà des filtres dérivés du profil élève (`niveau`, `voie`, `matiere`, `statut_enseignement`, `candidat`). Avant d'indexer quoi que ce soit (Lot 1.2), il faut figer deux choses : la granularité du tenant, et le schéma de métadonnées que le chunking (Lot 1.1) devra poser sur chaque chunk.

La roadmap annonçait une nomenclature `{population}_{niveau}` (`libre_terminale`, `aefe_terminale`, …). En instruisant le Lot 1, ce choix se révèle coûteux et inadapté, d'où la présente révision.

## Problème

Les deux populations cibles (candidats libres, élèves AEFE scolarisés) partagent l'essentiel du **contenu disciplinaire** pour un même niveau : programmes, cours, exercices, corrigés, méthodes sont identiques qu'un élève soit libre ou scolarisé. Ce qui diffère relève du **statut** : modalités d'examen (le candidat libre est examiné à 100 %, sans contrôle continu), procédures d'inscription, référentiel candidat libre, accompagnement.

Un tenant `population × niveau` dupliquerait donc le contenu disciplinaire commun dans six tenants : double (voire sextuple) coût d'embedding et de stockage, et surtout double maintenance — un cours corrigé devrait l'être dans chaque tenant. C'est contraire à l'optimisation des coûts et fragilise la cohérence.

## Décision

### 1. Granularité du tenant = niveau

Les tenants sont : `troisieme`, `seconde`, `premiere`, `terminale`. La **population n'est pas une frontière de tenant** ; c'est une dimension de métadonnée filtrable. Le contenu disciplinaire commun est indexé **une seule fois** par niveau.

Justification du choix de l'isolation par tenant au niveau « niveau » et non « niveau × matière » : un cockpit élève correspond à un niveau et plusieurs matières ; la sélection par matière se fait efficacement par filtre GIN. La granularité pourra être affinée vers `niveau_matiere` ultérieurement **sans rupture de contrat** (seule la valeur de `tenant` change), si le volume l'impose.

### 2. La population/statut devient une métadonnée `audience`

Chaque chunk porte une clé `audience` : sous-ensemble de `{libre, aefe, tous}`. `tous` = contenu disciplinaire commun aux deux populations. Le contenu spécifique au statut candidat libre porte `audience: [libre]` ; le contenu spécifique AEFE, `audience: [aefe]`.

Un cockpit requête son tenant (= niveau de l'élève) en filtrant systématiquement `audience` selon la population du profil : un cockpit candidat libre Terminale interroge le tenant `terminale` avec `audience ⊇ {libre} OU audience = {tous}`. Ce filtre est **appliqué côté `rag-engine` à partir du profil, jamais optionnel**, et couvert par golden queries.

### 3. Schéma de métadonnées minimal des chunks (conditionne le Lot 1.1)

Colonne dédiée : `tenant` (= niveau). Dans `metadata` JSONB, clés **obligatoires** :

- `niveau` — redondant avec le tenant, conservé pour requêtes cross-tenant.
- `voie` — `generale` | `technologique`.
- `matiere` — identifiant normalisé (`mathematiques`, `nsi`, `philosophie`, …).
- `audience` — liste ⊆ `{libre, aefe, tous}`.
- `type_doc` — `programme` | `cours` | `exercice` | `corrige` | `methode` | `referentiel` | `modalite_examen` | …
- `notions` — liste de notions issues de la taxonomie du niveau/matière.
- `source_label`, `source_uri`, `rights` — requis pour construire la `Citation` obligatoire du contrat.
- `official` — booléen : issu ou non d'une source officielle.
- `doc_id` — lien de traçabilité vers le ledger `rag-pedago`.

Clés **optionnelles** : `difficulte` (1–5), `page`, `chapitre`.

### 4. Évolution induite du contrat

`StudentProfile.to_payload_filters()` doit produire la dimension `audience` (dérivée de `candidat`/`status_detail`). C'est un ajout rétro-compatible → **bump mineur** de `nexus-contracts` (0.1.x → 0.2.0), réalisé au Lot 1, conformément à ADR-0002 §3 (pas de changement cassant, pas d'ADR supplémentaire requis au-delà de celui-ci).

## Conséquences

### Positives
- Contenu disciplinaire commun indexé et maintenu une seule fois par niveau ; coûts d'embedding et de stockage minimisés.
- Le filtrage par population réutilise le mécanisme de métadonnées déjà prévu par le contrat.
- Schéma de métadonnées figé : le Lot 1.1 sait exactement quoi taguer.

### Négatives
- Requêtes systématiquement assorties d'un filtre `audience` ; oubli = fuite inter-population.
- Tenants volumineux (toutes matières d'un niveau) ; acceptable avec HNSW + GIN, affinable plus tard.

### Risques et mitigations
- *Fuite inter-population* → filtre `audience` non optionnel, dérivé du profil côté `rag-engine`, couvert par golden queries dédiées (un profil libre ne doit jamais recevoir de chunk `audience:[aefe]` exclusif, et inversement).
- *Mauvais étiquetage `audience` à l'ingestion* → règle par défaut conservatrice : un contenu disciplinaire est `tous` ; un contenu lié au statut est étiqueté explicitement et passe par la revue du gate `rag-pedago`.

## Suites
- Mettre `docs/ROADMAP.md` en cohérence (tenants = niveaux, non `{population}_{niveau}`).
- Lot 1.1 : chunking taguant ce schéma.
- Lot 1 : bump mineur de `nexus-contracts` ajoutant `audience` aux filtres.
- ADR-0004 : ingestion agentique (les sources admises sont étiquetées `audience` au moment de l'admission).
