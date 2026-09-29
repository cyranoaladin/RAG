---
name: postgres-migration
description: Conçoit et teste localement une migration PostgreSQL rag-engine (schéma produit ou ingestion_control) avec son rollback, ses tests d'intégration et la mise à jour de HEAD. À utiliser dès qu'un lot ajoute ou modifie une table, contrainte, index, rôle ou GRANT. N'applique jamais rien hors d'une base de test locale.
argument-hint: "<produit|ingestion_control> <objet>"
---

# /postgres-migration — local et testé, jamais appliqué en live

Règles détaillées : `.claude/rules/postgres-migrations.md` (chargée avec les fichiers).

## Workflow

1. Lire `HEAD` de la chaîne visée et les deux dernières migrations + rollbacks pour copier
   leurs conventions (en-tête explicatif, idempotence, absence de `BEGIN;`/`COMMIT;`).
2. Vérifier qu'aucune PR ouverte n'occupe le numéro suivant
   (`gh pr list --state open --json number,files`) ; sinon le signaler et s'arrêter.
3. Écrire `NNN_<objet>.sql` (rejouable) et `rollbacks/NNN_<objet>.down.sql`.
4. Mettre à jour `HEAD`, la cascade de `test_lot44f_migration_rollback_rehearsal.py` et les
   assertions de `SCHEMA_HEAD`.
5. Tests d'intégration : upgrade depuis le HEAD précédent, rejeu, rollback, privilèges des
   rôles runtime. Une suite Docker à la fois.
6. Code applicatif (`ingestion_control/*.py`) : tests unitaires + intégration.
7. Si un rôle ou un GRANT change : le justifier ligne à ligne dans le rapport.

## Arrêt

Migration + rollback + tests verts en local. L'application en staging ou production est
un autre lot, via `/staging-operation` après autorisation.

## Sortie

Fichiers créés, HEAD avant/après, tests exécutés (commande, compteur), privilèges modifiés,
risques de rejeu, procédure de rollback.
