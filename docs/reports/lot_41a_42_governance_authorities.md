# Rapport de lot — LOT41A/LOT42 : autorité de scope + chaîne d'attestations de publication

- **Branche** : `track-a/lot41a-lot42-governance-authorities`
- **Statut** : mécanismes candidats implémentés, testés, remédiés après revue GATE H1. **Aucune autorisation de scope réelle, aucune attestation de publication réelle n'existe** à l'issue de ce lot.
- **ADR** : ADR-0032 (LOT41A), ADR-0033 (LOT42) — toutes deux **Proposées**, non Acceptées.
- **Mandat** : décision de gouvernance TRACK A de l'utilisateur — construire les mécanismes candidats LOT41A/LOT42 puis STOP au GATE H1, sans jamais fabriquer d'autorité humaine.

---

## 1. Le problème que ce lot résout

Une review GitHub `APPROVED` prouve qu'un humain a lu **un diff précis, à un commit précis**. Toute la valeur de la gouvernance en dépend. La question centrale de ce lot est donc : *comment relier cette preuve à ce que la machine applique ensuite ?*

La première implémentation ne les reliait pas. Elle vérifiait qu'une review approuvée existait, puis enregistrait une décision lue **ailleurs** — un fichier local passé par l'opérateur (`--scope-file`), ou des arguments de ligne de commande (`--rights-status`, `--quality-passed`…). Faire approuver un scope étroit puis enregistrer un scope large ne violait aucune vérification. C'est ce que la revue GATE H1 a relevé, et c'est ce que cette remédiation corrige.

La chaîne est désormais :

```
PR approuvée -> head SHA exact -> chemin canonique dérivé de l'identifiant
  -> octets Git exacts -> parse canonique -> digest recalculé -> ligne PostgreSQL
  -> points de contrôle appliqués à chaque étape de l'ingestion
```

Aucun maillon n'est reconstruit depuis la base : à chaque usage, tout est relu et recomparé.

---

## 2. Remédiation GATE H1 — les treize items

| Item | Constat de revue | Correction |
|---|---|---|
| **A** | `nanoid` 3.3.16 vulnérable (GHSA-2v37-7h3g-55p8, High) | Bump 3.3.18, fusionné dans `main` via PR #94 |
| **B** | La review n'était liée à aucun octet | Artefact canonique `governance/authorizations/<id>.json`, relu depuis le blob Git du HEAD approuvé, digest SHA-256 recalculé intégralement, égalité **octet à octet** exigée |
| **C** | `ORDER BY valid_until DESC LIMIT 1` faisait d'une écriture en base une décision d'autorité | `authorization_id` explicite, obligatoire dans le payload du job ; la sélection par récence est supprimée du code **et** l'index qui la matérialisait est retiré |
| **D** | La `VerifiedAuthorization` était calculée puis ignorée | Quatre points de contrôle (`pre_fetch`, `destination`, `redirect`, `rights`), revalidation live avant l'étape des droits, refus journalisé avec le nom du point de contrôle |
| **E** | L'opérateur affirmait librement `content_sha256`, `rights_status`, `quality_passed`, `gate_passed`… | Ces options **n'existent plus**. Les faits viennent de `workflow_events` (append-only), écrits par le pipeline lui-même ; l'artefact de revue est dérivé de la base et recomparé octet à octet |
| **F** | Une chaîne négative pouvait être attestée | Irreprésentable à **trois** niveaux : l'artefact refuse de se construire, la contrainte `CHECK` refuse la ligne, la relecture refuse la transition |
| **G** | `challenge in live_challenges.values()` acceptait un autre reviewer / une autre review | Comparaison **champ par champ** des huit champs d'évidence, puis de l'artefact contre chaque colonne persistée |
| **H** | Cycle de vie de la PR d'autorité non décidé | ADR-0032 § 7 : une PR d'autorité fermée ou fusionnée cesse d'autoriser ; testé de bout en bout |
| **I** | `gh` n'existe pas dans l'image du worker | Transport `httpx` en lecture seule (`github_authority`), décision d'ADR-0025 chargée **non modifiée** ; E2E dans l'image réellement construite |
| **J** | Une panne GitHub pouvait bloquer indéfiniment | Échéance globale monotone (`NEXUS_GITHUB_TOTAL_TIMEOUT_S`), vérifiée jusque dans le conteneur |
| **K** | Cumul des rôles sur une même surface | DSN séparés sans repli + deux services Compose ponctuels isolés, un seul secret chacun ; privilèges vérifiés contre PostgreSQL réel |
| **L** | Chemin vers `RETRIEVAL_ELIGIBLE` non unique | Point d'ancrage unique `attempt_retrieval_eligible_transition`, ancré par test |
| **M** | Test psql non déterministe | Corrigé (commit `95f9158`) |
| **N** | Provenance du fork non documentée, tests possiblement vacants | §5 et §6 ci-dessous |

---

## 3. Ce qui a été livré

### Contrats (`packages/contracts`)

- **`nexus_contracts/authority_artifacts.py`** (nouveau) — `ScopeAuthorizationArtifact` et `PublicationReviewArtifact`, leur sérialisation canonique, leur digest, leurs chemins Git canoniques, et `normalize_hostname`. `extra="forbid"` partout.
- **`scope_authorization.py` / `publication_attestation.py`** (supprimés) — deux définitions parallèles de la même décision étaient précisément la confusion que l'item B corrige.

### Plan de contrôle (`services/rag-engine`)

- `ingestion_control/github_authority.py` — transport GitHub GET-only, échéance globale, relecture de blob avec vérification du SHA d'objet Git.
- `ingestion_control/scope_authority.py` — vérification live complète (items B, C, G).
- `ingestion_control/scope_enforcement.py` (nouveau) — points de contrôle purs (item D).
- `ingestion_control/publication_evidence.py` (nouveau) — seule source des faits durables (item E).
- `ingestion_control/publication_attestation.py` — relecture complète LOT42 (items E, F).
- `ingestion_control/db.py` — trois DSN distincts, aucun repli (item K).
- `ingestion_agents/quality_agent.py`, `rights_agent.py` — persistent leurs verdicts dans `workflow_events`, **y compris négatifs**.
- `ingestion_worker/authorize_scope_cli.py`, `attest_publication_cli.py` — reconstruits autour des artefacts revus.
- `ingestion_worker/runner.py` — les quatre points de contrôle, câblés.
- `ssrf_guard.py` — rappel `on_destination` par saut, seul endroit d'où une chaîne de redirection est observable.

### Infrastructure

- Migrations `007`/`008` étendues (colonnes de liaison cryptographique, contraintes `CHECK` structurelles, suppression de l'index par récence).
- `provision_ingestion_control_roles.sh` — le rôle attestor obtient `SELECT` sur `workflow_events`, ce qui lui évite d'avoir *aussi* besoin du DSN worker.
- `docker-compose.ingestion.yml` — deux services ponctuels `profiles: [operator]`, secret GitHub monté à l'exécution.
- `Dockerfile.ingestion-worker` — n'embarque plus l'adaptateur `gh`, seulement la décision pure d'ADR-0025.

---

## 4. Un bug de production que seul le E2E Docker pouvait trouver

`github_authority.py` résolvait la racine du dépôt par `Path(__file__).resolve().parents[5]`, **au moment de l'import**. Dans l'image aplatie, ce fichier vit sous `/app/ingestion_control/` — deux niveaux seulement. L'import levait donc `IndexError` **avant** que les surcharges d'environnement du Dockerfile puissent servir.

Conséquence : *toute* vérification d'autorité aurait échoué dans l'image réellement déployée, alors que tout passait en développement. Ni `ruff`, ni `mypy`, ni un seul test unitaire ne pouvaient le voir — seul l'exercice du code **dans le conteneur produit** le révèle. C'est la justification concrète de l'item I.

La résolution est désormais paresseuse et tolère une arborescence courte ; un chemin non résolu produit une erreur explicite plutôt qu'un chemin deviné.

---

## 5. Item N — provenance du fork

**Mandat initial du sous-agent.** Un sous-agent avait été mandaté, dans une session antérieure, pour écrire les tests d'adversité LOT41A/LOT42 accompagnant l'implémentation candidate.

**Dépassement de mandat.** Le sous-agent a produit, au-delà du périmètre attendu, une infrastructure de test complète incluant sa propre frontière GitHub simulée (un faux binaire `gh` déposé sur `PATH`).

**Fichiers générés** — introduits par le commit `9cdd100`, mesurés par `git show --numstat 9cdd100` :

| Fichier | Lignes | Devenir |
|---|---|---|
| `tests/integration/_fake_github.py` | 195 | **Supprimé** |
| `tests/integration/test_lot41a_scope_authority.py` | 464 | **Remplacé intégralement** |
| `tests/integration/test_lot42_publication_attestation.py` | 663 | **Remplacé intégralement** |
| **Total** | **1322** | **0 ligne conservée** |

**Revue manuelle indépendante.** Les trois fichiers ont été relus ligne à ligne pendant cette remédiation. Aucun n'a été conservé, pour trois raisons distinctes :

1. **`_fake_github.py` reposait sur un transport qui n'existe plus.** Il simulait `gh` sur `PATH`. Or l'item I a établi que `gh` n'a jamais été présent dans l'image du worker : ces tests validaient donc un chemin de code qui ne pouvait pas s'exécuter en production. Remplacé par `tests/_local_github.py`, un vrai serveur HTTP qui exerce le transport réellement déployé.
2. **`test_lot41a_scope_authority.py` testait un mécanisme qui a changé de nature.** Il exerçait `--scope-file` et `verify_scope_authorization_by_id`, tous deux supprimés par les items B et C. Ses assertions étaient correctes pour l'ancien mécanisme et sans objet pour le nouveau.
3. **`test_lot42_publication_attestation.py` fabriquait lui-même les faits qu'il vérifiait.** Il insérait des lignes `resources`/`artifacts` par SQL direct puis attestait dessus. Un test qui écrit lui-même sa propre preuve ne prouve rien sur le système ; la nouvelle version fait produire les `workflow_events` par les vraies fonctions du pipeline.

**Conclusion.** Aucune ligne fork-authored ne subsiste. La question « les tests fork-authored conservés prouvent-ils leur valeur ? » est donc sans objet — mais la question sous-jacente (« ces tests prouvent-ils quelque chose ? ») reste posée pour les tests **actuels**, et c'est l'objet de la matrice de mutation ci-dessous.

---

## 6. Item N — matrice de non-vacuité (12/12)

Un test adverse qui passe peut passer parce que la protection fonctionne, ou parce que l'assertion ne mesure rien. La seule preuve est de **casser la protection** et de vérifier que le test devient rouge.

`scripts/governance/h1_mutation_matrix.py` automatise cela : pour chaque invariant, mutation ciblée → le test doit devenir **RED** → restauration → le test doit redevenir **GREEN**. Le script vérifie en sortie que l'arbre de travail est identique à son état initial, et échoue bruyamment sinon. **Aucune mutation n'est jamais commitée.**

| # | Invariant | Protection mutée | Résultat |
|---|---|---|---|
| 1 | Liaison à l'artefact revu | comparaison `artifact_blob_sha` + `authorization_digest` | NON-VACUOUS |
| 2 | Liaison à l'`authorization_id` | `enforce_before_fetch` | NON-VACUOUS |
| 3 | Liaison au `review_id` GitHub | `_verify_live_review` | NON-VACUOUS |
| 4 | Liaison au reviewer | `_verify_live_review` | NON-VACUOUS |
| 5 | Liaison au challenge | `_verify_live_review` | NON-VACUOUS |
| 6 | Révocation | garde `live.approved` | NON-VACUOUS |
| 7 | Scope divergent | comparaison `scope_key` | NON-VACUOUS |
| 8 | Qualité négative | `_reject_negative_chain` | NON-VACUOUS |
| 9 | Gate négatif | validateur `PublicationReviewArtifact` | NON-VACUOUS |
| 10 | Droits interdits | `enforce_rights` | NON-VACUOUS |
| 11 | Échéance globale | `_Deadline.check` | NON-VACUOUS |
| 12 | Isolation des privilèges PostgreSQL | `GRANT` du script de provisioning | NON-VACUOUS |

Le résultat machine complet est reproductible par :

```bash
services/rag-engine/.venv/bin/python scripts/governance/h1_mutation_matrix.py --json /tmp/h1-matrix.json
```

---

## 7. État honnête du pipeline vivant

`classify_conformity_core` est un placeholder documenté (remédiation PR#90) : `niveau_conformity`, `voie_conformity` et `programme_conformity` valent toujours `False` — « non vérifié », jamais « vérifié non conforme ».

**Conséquence directe, mesurée et non contournée : aucune ressource ne peut aujourd'hui franchir le gate de publication, quelle que soit la richesse de son contenu.** `TestLivePipelineCannotYetPublish` fixe ce fait pour qu'il ne puisse pas changer sans qu'on s'en aperçoive.

C'est exactement ce que signifie `LOT42_LIVE_PIPELINE_WIRED=false`. Les scénarios *positifs* de LOT42 sont donc exercés en substituant **la seule pièce documentée comme non implémentée** — la sortie du classifieur — tout en laissant `run_rights_agent` et `run_quality_agent`, qui écrivent l'évidence durable, faire leur vrai travail.

---

## 8. Hors périmètre (escaladé, non implémenté)

- Toute autorisation de scope réelle, toute attestation de publication réelle.
- Le raccordement bidirectionnel formel `rag-pedago` ↔ LOT41A (ADR-0032, hors périmètre explicite).
- La chaîne `STAGED → NEEDS_REVIEW → REVIEWED` (aucune ressource n'y accède) — `attempt_retrieval_eligible_transition` reste donc non appelée en production.
- Un classifieur réel pour niveau/voie/programme (§7).
- La publication produit réelle (chunking/embedding/écriture `rag_chunks`).

---

## 9. Risques connus

- **Dépendance à la disponibilité de GitHub.** Toute vérification d'autorité exige un aller-retour réseau réussi. Fail-closed par construction : aucune ingestion ne procède sans preuve fraîche, jamais un cache qui masquerait une panne. L'échéance globale garantit que l'échec est **borné en temps**, jamais un worker bloqué.
- **Nouvelles variables d'environnement.** `docker-compose.ingestion.yml` référence `NEXUS_GITHUB_TOKEN_HOST_FILE`, `PG_INGESTION_CONTROL_AUTHORITY_DSN`, `PG_INGESTION_CONTROL_ATTESTOR_DSN`. Aucune n'est *requise* au sens Compose (`:?`) : Compose interpole le fichier entier avant d'appliquer `profiles:`, donc les rendre requises casserait `make v2-ingestion-up` pour les déploiements existants. Leur absence est fail-closed **à l'usage** (jeton vide refusé, DSN vide refusé), jamais au démarrage.
- **Coût des tests d'intégration.** Chaque suite d'autorité démarre un PostgreSQL jetable ; le E2E Docker construit l'image complète du worker. Compter plusieurs dizaines de minutes pour `pytest tests/integration/`.

---

## 10. GATE H1 — demande d'approbation humaine

Ce lot s'arrête ici. Aucune autorisation LOT41A, aucune attestation LOT42 n'a été créée. ADR-0032 et ADR-0033 restent **Proposées**.

`LOT41A_AUTHORITY_VALID=false`, `LOT42_AUTHORITY_VALID=false` jusqu'à revue humaine `APPROVED` par `@abenrhouma` sur le HEAD exact de la PR #93, avec le challenge produit par le check LOT41V de ce HEAD.
