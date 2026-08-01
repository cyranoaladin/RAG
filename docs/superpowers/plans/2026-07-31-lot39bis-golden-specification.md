# LOT39bis — plan d’implémentation de la spécification golden

> **Lot :** LOT39bis
> **Branche :** `lot-39bis-specification-golden`
> **Base :** `main@56d8389f132de8f8a575efce5c856bb8b11adda9`
> **Périmètre :** spécification sans lecture de document réel, sans jugement de chunk et sans baseline.

**Objectif :** versionner une spécification golden exhaustive, réfutable et gelée pour les 39 notions du pilote `libre_terminale`, puis bloquer sa promotion tant que la revue humaine des 255 requêtes et de leurs attentes n’est pas prouvée.

**Architecture :** deux fichiers de requêtes, un par matière, sont liés au scope et aux taxonomies canoniques de LOT38. Un manifeste fixe les catégories, filtres, seuils et cardinalités. Un verrou de contenu adresse tous les octets normatifs. Un manifeste de revue distinct atteste ou refuse la couverture humaine. L’auditeur produit séparément le verdict d’intégrité technique et le verdict de revue humaine.

**Contraintes :** aucune donnée de corpus n’est ouverte ; aucun `doc_id`, `chunk_id`, score ou résultat réel n’est inventé ; tous les verrous restent à `false` ; le stash historique LOT39-40 reste intact.

---

## Tâche 1 — Formaliser le contrat interne de spécification

**Fichiers :**

- Créer `services/rag-pedago/configs/pilot_golden_spec.yml`.
- Créer `services/rag-pedago/configs/pilot_golden_spec.lock.json`.
- Créer `services/rag-pedago/configs/pilot_golden_human_review.yml`.
- Créer `services/rag-pedago/tests/golden_queries/README.md`.
- Créer `services/rag-pedago/tests/unit/test_pilot_golden_spec.py`.

1. Écrire d’abord les tests de schéma strict, cardinalités, liaison au scope, filtres, seuils, unicité et absence d’identifiants réels.
2. Définir quatre catégories exactes : `positive`, `no_source`, `confusion`, `adversarial`.
3. Imposer exactement 195/20/20/20 cas, cinq positifs par notion et dix cas de chaque autre catégorie par matière.
4. Imposer, selon la catégorie, programme officiel, attente pédagogique, classe de source candidate, refus attendu et `must_not_return`.
5. Imposer les seuils absolus de la section 11.1, globalement, par matière et par notion.
6. Refuser tout `doc_id`, `chunk_id`, `relevant_chunk_ids`, score ou déclaration de substance réelle.

## Tâche 2 — Écrire les 255 requêtes substantielles

**Fichiers :**

- Créer `services/rag-pedago/tests/golden_queries/lot39bis_maths.yml`.
- Créer `services/rag-pedago/tests/golden_queries/lot39bis_nsi.yml`.

1. Écrire cinq questions réellement distinctes pour chacune des 13 notions de mathématiques et des 26 notions de NSI : compréhension, méthode, application, diagnostic et transfert.
2. Écrire dix cas sans source par matière, explicitement hors programme ou impossibles à soutenir par le futur corpus officiel.
3. Écrire dix cas de confusion par matière avec notion cible et exclusions `must_not_return` précises.
4. Écrire dix cas d’injection/exfiltration par matière avec refus des instructions malveillantes et exclusions de secrets, PII ou contenu hors scope.
5. Vérifier la langue française, l’unicité des textes et la substance pédagogique de chaque attente.

## Tâche 3 — Implémenter l’auditeur réfutable

**Fichiers :**

- Créer `services/rag-pedago/rag_pedago/governance/pilot_golden.py`.
- Créer `services/rag-pedago/scripts/pilot_golden_spec_audit.py`.
- Modifier `services/rag-pedago/Makefile`.
- Modifier `services/rag-pedago/configs/make_target_safety.yml`.
- Modifier `services/rag-pedago/tests/unit/test_make_target_safety_audit.py` si nécessaire.

1. Réutiliser le parseur YAML strict et borné du même service.
2. Charger tous les chemins relativement à la racine du service et refuser absolus, traversals et symlinks sortants.
3. Comparer le scope, les taxonomies et leurs hashes à LOT38.
4. Vérifier exhaustivement chaque requête et chaque cardinalité ; trier les raisons d’échec pour un résultat déterministe.
5. Calculer le digest de spécification depuis les hashes des fichiers normatifs et vérifier le lock.
6. Produire deux états explicites : `SPECIFICATION_VALID/INVALID` et `HUMAN_REVIEW_APPROVED/PENDING/INVALID`.
7. Classer la cible Make comme `SAFE_DIAGNOSTIC` et prouver qu’elle ne lit ni corpus, ni `.env`, ni réseau.

## Tâche 4 — Revue indépendante et preuve humaine

**Fichiers :**

- Créer `docs/reports/lot_39bis_golden_suite.md`.
- Créer `docs/reports/evidence/lot_39bis/golden_human_review_packet.md`.

1. Faire relire indépendamment le code, les cardinalités et le contenu par matière.
2. Générer un paquet lisible couvrant les 255 identifiants, textes et jugements, lié au digest de spécification.
3. Laisser le verdict global `NO_GO` et la revue `PENDING` jusqu’à une attestation humaine explicite couvrant le paquet complet.
4. Après cette attestation seulement, enregistrer identité stable, rôle, heure UTC, digest revu et preuve ; ne jamais auto-attester.

## Tâche 5 — Vérifier, publier par PR et intégrer

1. Exécuter les tests ciblés en rouge puis en vert, `ruff`, `mypy`, la cible d’audit et `bash scripts/ci-local.sh`.
2. Capturer les commandes, versions, hashes et résultats dans le rapport du lot.
3. Vérifier qu’aucun verrou de gouvernance, contrat, corpus réel ou fichier hors périmètre n’a changé.
4. Commiter avec un message impératif scopé `rag-pedago: …`.
5. Pousser la branche et ouvrir une PR ; attendre les checks obligatoires et la preuve de revue humaine.
6. Squash-merger sans contournement, vérifier le run `push` exact sur `main`, puis supprimer uniquement la branche et le worktree LOT39bis.
