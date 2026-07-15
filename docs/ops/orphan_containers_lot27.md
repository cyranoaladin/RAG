# Conteneurs Compose orphelins observés après le LOT 27

## Périmètre et méthode

Cet inventaire reprend l'observation de production en lecture seule du
2026-07-14. Il ne constitue ni une autorisation d'arrêt ni une autorisation de
suppression : aucune commande Docker de mutation n'a été exécutée pour ce
document.

| Conteneur | Image | Projet Compose | Service | Ports observés | État observé | Impact production | Décision | Risque | Action future |
|---|---|---|---|---|---|---|---|---|---|
| `infra-web-1` | `infra-web` | `infra` | `web` | `127.0.0.1:13002->3000/tcp` | `Up 7 weeks (healthy)` | Aucun impact observé sur RAG v2 ; port lié à loopback, sans conflit proxy constaté | **ne pas supprimer sans audit propriétaire** | Faible si aucun conflit de port ou de proxy n'apparaît | Audit Ops dédié : identifier le propriétaire, l'usage et le cycle de vie. |
| `infra-postgres-1` | `pgvector/pgvector:pg15` | `infra` | `postgres` | `5432/tcp` (interne) | `Up 7 weeks (healthy)` | Aucun impact observé sur RAG v2 ; aucune exposition de port hôte relevée | **ne pas supprimer sans audit propriétaire** | Faible si aucun conflit de port ou de proxy n'apparaît | Audit Ops dédié : identifier le propriétaire, les dépendances et les sauvegardes. |
| `infra-minio-1` | `minio/minio:latest` | `infra` | `minio` | `9000/tcp` (interne) | `Up 7 weeks` | Aucun impact observé sur RAG v2 ; aucune exposition de port hôte relevée | **ne pas supprimer sans audit propriétaire** | Faible si aucun conflit de port ou de proxy n'apparaît | Audit Ops dédié : identifier le propriétaire, les buckets et les dépendances. |

## Décision Ops

Ces conteneurs semblent relever d'un ancien projet Compose `infra`. Leur
présence doit rester documentée jusqu'à un audit Ops propriétaire. En cas de
conflit de port, de proxy ou de dépendance applicative identifié, le niveau de
risque doit être réévalué avant toute action.
