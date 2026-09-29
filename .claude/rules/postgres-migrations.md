---
paths:
  - "services/rag-engine/infra/postgres/**"
  - "services/rag-engine/infra/scripts/**"
  - "services/rag-engine/src/ingestor/ingestion_control/**"
  - "services/rag-engine/tests/integration/test_*migration*"
  - "services/rag-engine/tests/integration/test_*rollback*"
---

# Migrations PostgreSQL (rag-engine)

Deux chaînes distinctes : schéma produit `infra/postgres/migrations/` et
`infra/postgres/ingestion_control/migrations/`, chacune avec son fichier `HEAD`
et ses `rollbacks/*.down.sql`. Workflow complet : skill `/postgres-migration`.

- Une migration appliquée est immuable : son empreinte d'octets est vérifiée au
  bootstrap. Corriger = nouvelle migration, jamais réécriture.
- Pas de `BEGIN;`/`COMMIT;` dans un fichier : le runner applique en
  `psql --single-transaction` (voir `infra/scripts/lib/sql_transaction_control.sh`).
- Rejouable : `IF NOT EXISTS`, et tout `ADD CONSTRAINT` précédé de son
  `DROP CONSTRAINT IF EXISTS` homonyme.
- Chaque palier a son rollback `.down.sql`, son test d'intégration, et étend la
  cascade de `test_lot44f_migration_rollback_rehearsal.py` et les assertions de
  `SCHEMA_HEAD` (`tests/integration/_pg_authority.py`).
- Rôles runtime à privilèges minimaux : l'API ne reçoit jamais le propriétaire ni
  les credentials de migration ; tout `GRANT` nouveau se justifie dans le rapport.
- Aucune migration n'est appliquée hors test local sans autorisation explicite
  (skill `/staging-operation`). Les suites d'intégration ne tournent jamais en
  parallèle.
