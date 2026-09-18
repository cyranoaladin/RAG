# Lot CH2 — Amendement d'autorisation SSH de staging (Port API 18003)

- Lot : `LOT_GO_LIVE_FINAL_CH2_STAGING_AUTHORIZATION_AMEND_PORT_18003`
- Branche : `go-live/staging-authorization-amend-port-18003`
- Décision : `GO_LIVE_CH2_STAGING_AUTHORIZATION_AMENDMENT_PR_OPEN`
- Aucune connexion active ouverte. Aucun compteur modifié, aucun blocker fermé.

**L’approbation de cette PR par abenrhouma vaut amendement de l’autorisation SSH_STAGING_AUTHORIZED : le staging cloisonné sur nexus-prod utilisera le port loopback 18003 au lieu de 18001, toutes les autres interdictions et limites de #220 restant inchangées.**

---

## 1. Contexte du constat Phase 0

Lors de la reconnaissance en lecture seule de la Phase 0 sur l'hôte cible `korrigo` (88.99.254.59) :
- Le port `127.0.0.1:18001` a été détecté comme déjà occupé par le conteneur existant `compose-ingestor-1` (`Up 2 months`).
- Le port `127.0.0.1:18002` est occupé par `rag_ingestor`.
- Le port `127.0.0.1:18003` est rigoureusement libre.
- Les ports `127.0.0.1:15435` (pgvector staging) et `127.0.0.1:19191` (prometheus staging) sont libres.

Conformément à la condition d'arrêt immédiat n°1 du plan d'exécution (§ 4), l'agent s'est arrêté et a rapporté l'indisponibilité de 18001 sans altérer aucun conteneur en place.

Cet amendement acte le basculement sur le port libre `18003` par voie de PR formelle, préservant l'intégrité absolue de la production et des conteneurs existants.

---

## 2. Périmètre amendé et invariants stricts

| Grandeur | Valeur CH (#220) | Valeur amendée CH2 | Statut |
|---|---|---|---|
| **Port API ingestor staging** | `18001` | **`18003`** | Amendé |
| **Port PGVector staging** | `15435` | `15435` | Inchangé |
| **Port Prometheus staging** | `19191` | `19191` | Inchangé |
| **Liaison réseau** | `127.0.0.1` | `127.0.0.1` | Strictement loopback |
| **Hôte** | `nexus-prod` (88.99.254.59) | `nexus-prod` (88.99.254.59) | Inchangé |
| **Projet Compose** | `nexus-staging` | `nexus-staging` | Inchangé |
| **Conteneur PGVector** | `nexus-staging-pgvector-1` | `nexus-staging-pgvector-1` | Obligatoire |
| **Image Ingestor** | Pinned by digest | Pinned by digest | Inchangé |
| **Current switch** | 0 | 0 | Strictement interdit |
| **Écritures DB production** | 0 | 0 | Strictement interdit |
| **Exposition publique** | `false` | `false` | Strictement tunnel SSH |
| **Interdictions machine (15)** | 15 vérifiées | 15 vérifiées | Strictement tenues |

Empreinte mise à jour du plan d'exécution : `57bcad2b4e3691018a673e3345ae4e385a4229f6a9b1339a07a681e5089383df`.

---

## 3. Gardes-fous et tests automatisés

La suite `scripts/qualification/tests/test_staging_ssh_authorization.py` (29 épreuves) prouve que :
1. `check_staging_authorization.py` accepte `18003` ;
2. `check_staging_authorization.py` refuse l'ancien port `18001` ;
3. Tout port public, hors plage ou non-loopback est rejeté immédiatement ;
4. Tout changement de `PGVECTOR_CONTAINER` est rejeté ;
5. Tout élargissement de périmètre ou omission d'une des 15 interdictions est rejeté ;
6. L'autorisation est fail-closed tant qu'elle n'est pas fusionnée à l'identique sur `origin/main`.
