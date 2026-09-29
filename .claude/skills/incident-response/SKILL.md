---
name: incident-response
description: Conduit un diagnostic d'incident Nexus RAG (staging ou production) en lecture d'abord — classification, chronologie, hypothèses prouvées — et propose sans l'appliquer une remédiation ou un rollback. Invocation manuelle uniquement.
disable-model-invocation: true
argument-hint: "<symptôme> <environnement>"
---

# /incident-response — diagnostiquer avant d'agir

`docs/runbooks/rag_incident_response.md` et `docs/runbooks/rollback.md` décrivent encore
en partie l'ancienne pile (`/opt/rag-local`, build sur serveur) : les confronter au Compose
v2 et à la release déployée avant d'en suivre une commande.

## Workflow

1. Classifier (P1–P4) à partir du symptôme ; noter l'heure de début et la source du signal.
2. Relire le dépôt : SHA et release censés être déployés, derniers changements fusionnés.
3. Lecture live seulement après accord (SSH demandé par le hook) : état des conteneurs,
   santé, journaux bornés (`--tail`), métriques. Aucune commande d'écriture.
4. Construire une chronologie ; chaque hypothèse est confirmée ou réfutée par une mesure.
5. Proposer la remédiation ou le rollback, avec commandes exactes, effet et risque.
   Ne pas l'exécuter sans autorisation explicite.
6. Aucun secret, DSN complet, jeton ni PII dans la sortie ou les journaux copiés.

## Arrêt

Cause établie ou hypothèses restantes listées, et proposition présentée à l'humain.

## Sortie

Sévérité · chronologie · mesures (commande, résultat) · cause · remédiation proposée ·
rollback · suivi (rapport `docs/reports/`, test de non-régression à écrire).
