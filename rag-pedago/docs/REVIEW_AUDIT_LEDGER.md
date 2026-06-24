# Review audit ledger

Le registry JSONL des décisions reste utile pour l'export et la lecture simple.
Le ledger SQLite devient la source locale requêtable pour auditer les packages
de revue, les décisions humaines et les tentatives d'import contrôlé.

## Pourquoi tracer la revue dans SQLite

Un import opérationnel doit pouvoir répondre à quatre questions :

- quel package a été présenté à l'humain ;
- qui a approuvé ou rejeté ;
- quels hashes ont été vérifiés au moment de l'import ;
- est-ce que des écritures documentaires ont été réalisées.

SQLite permet de requêter cet historique sans relire tous les rapports Markdown.

## Audit ledger vs document ledger

Les tables historiques `runs`, `documents`, `document_states`, `chunks` et
`errors` décrivent les métadonnées de manifests et les futures étapes
documentaires.

Les tables d'audit de revue décrivent la gouvernance avant import :

- `review_packages` ;
- `review_decisions` ;
- `controlled_import_attempts` ;
- `controlled_import_verifications`.

Un gate bloqué peut donc créer une écriture d'audit sans créer de run document,
de document ou d'état. Cette séparation est volontaire.

## Tables

`review_packages` stocke le package de revue, son statut, les statuts gate,
readiness et coverage, les hashes des rapports, manifests, taxonomies et
référentiel officiel, ainsi que le JSON complet.

`review_decisions` stocke une approbation ou un rejet humain. La décision pointe
vers un package existant et conserve le reviewer, la date, les hashes et le JSON
complet.

`controlled_import_attempts` stocke chaque tentative d'import contrôlé, y
compris les tentatives bloquées par le gate. Les champs `review_id` et
`package_id` sont renseignés quand la revue obligatoire est utilisée.

`controlled_import_verifications` stocke les contrôles effectués pour une
tentative : gate évalué, revue présente, package présent, hashes des manifests,
taxonomies, référentiel officiel et gate, puis écriture ledger réalisée ou non.

## Requêtes exemples

Lister les tentatives d'un batch :

```sql
SELECT attempt_id, status, gate_status, review_required, created_at
FROM controlled_import_attempts
WHERE batch_id = 'batch-official-profiles-clean'
ORDER BY created_at DESC;
```

Voir les vérifications d'une tentative :

```sql
SELECT check_name, passed, message
FROM controlled_import_verifications
WHERE attempt_id = :attempt_id
ORDER BY id;
```

Retrouver la décision liée à un import :

```sql
SELECT d.review_id, d.decision, d.reviewer, d.reviewed_at
FROM controlled_import_attempts a
JOIN review_decisions d ON d.review_id = a.review_id
WHERE a.attempt_id = :attempt_id;
```

## CLI

Les commandes de revue et d'import acceptent `--audit-ledger` :

```bash
python -m rag_pedago.imports.review_package_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
python -m rag_pedago.imports.approve_review_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
python -m rag_pedago.imports.controlled_import_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
```

Sans cette option, le comportement existant est conservé.

## Limites

Le ledger d'audit valide et trace les métadonnées, hashes et décisions. Il ne
valide pas le contenu réel des PDF, corrigés, barèmes ou ressources
pédagogiques. Aucun `source_uri` n'est ouvert et aucun parsing documentaire
n'est effectué.
