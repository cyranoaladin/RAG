# Lot DH — récupération de la publication V4 après fermeture de la revue #257

- Branche : `claude/lot-dh-publication-recovery`
- Base : `e8d125eac58ac8176c1fc92c1def63f1210f0883` (main après #258), vérifiée
  égale à `origin/main` au démarrage de la session cloud.
- Statut : **cadrage** — ce document sera complété en rapport de lot.

## 0. Frontière

Session cloud uniquement : aucun accès SSH au serveur Nexus, aucune base réelle,
aucun secret. Les états du staging ci-dessous sont **transmis par l'opérateur**,
pas remesurés ici. Le pré-vol de récupération devra les constater avant toute
écriture.

## 1. Incident (contexte opérateur, non remesuré)

- #258 fusionnée ; V4 ingérée dans `ragdb_profile_gate_v4` (479 ressources,
  315 contenus, 11 collections) ; `ragdb` inchangée.
- #257 (revue batch `lot42-release-batch-v4-staging-20260924`, artefact
  `…-19ba49a2….json`, head `85f90001…` d'après `refs/pull/257/head`) a été
  **fusionnée** avant que Worker B ne publie.
- Worker B refuse chaque attestation : `human_review is no longer approved
  (reason=pull_request_not_open)`. C'est le comportement voulu par ADR-0033 § 5
  (« PR fermée » est une cause d'invalidation), pas un défaut.
- Dernier relevé : Worker B arrêté ; 0 publication ; 479 attestations encore
  actives en base (le rôle applicatif ne peut pas persister l'invalidation —
  `_mark_invalidated` échoue sans bruit, par conception) ; 479 jobs, dont un
  sous bail au moment du relevé.

## 2. Décision de conception (validée par l'opérateur)

Conserver base, ressources, artefacts, projections et r4. Pas de nouvelle base,
pas de réingestion, pas de nouvelle release. Historique préservé : aucune ligne
supprimée, aucun ancien job réaffecté, anciennes attestations invalidées (pas
supprimées).

Séquence :

1. **aperçu** en lecture seule de l'ensemble exact concerné, identités vérifiées
   (release, empreintes, revue #257, références croisées job ↔ attestation ↔
   ressource ↔ artefact) — toute ligne étrangère est un refus ;
2. **annulation des jobs périmés** sous `ingestion_control_app` (déjà
   `UPDATE` sur `jobs`) — jamais un job sous bail actif ;
3. **invalidation des anciennes attestations** sous
   `ingestion_control_attestor` (déjà `UPDATE (invalidated_at,
   invalidated_reason)`) ;
4. **reprise** : nouvelle revue humaine (PR ouverte, approuvée au head exact,
   inchangée pendant l'usage), nouvelles attestations, nouveaux jobs nommant
   les artefacts existants, Worker B, vérification.

Aucun droit nouveau, aucune migration modifiée, aucun artefact scellé modifié.

## 3. Plan de travail

- outil `scripts/go_live/staging_v4_publication_recovery.py` (aperçu,
  annulation, invalidation), exécuté depuis `/repo` dans l'image épinglée comme
  la mise en file DG — n'importe que des primitives déjà présentes dans l'image ;
- préconditions de revue avant mise en file et avant lancement de Worker B ;
- orchestrateur : étapes de récupération ; amendement d'autorisation **proposé**
  (non actif) ;
- qualification sur PostgreSQL jetable : chaîne complète revue → attestations
  → fermeture → refus réel → récupération → nouvelle revue de test → Worker B →
  publication → retrieval → rejeu.
