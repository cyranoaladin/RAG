# Lot 311 — Déploiement atomique local du candidat public

## Base et portée

- **LIVE au fetch initial, 2026-10-09** : `origin/main`
  `59da01c9821cbbff8b12194394d232dc33ecf149`.
- **SEALED dépendance non fusionnée** : les neuf commits du lot 310 de
  `be9973cb` à `aa0862ba` ont été rejoués localement, sans conflit, sur un
  worktree propre. Le HEAD obtenu avant ce lot était
  `ea542ae1e18c3b09d42a7a6ff7fbcd7deec22a71`, arbre
  `a94affb8f4ee5ed7717b24f95ef4d1655ae7146c`.
- Venv Python 3.12 distinct, `nexus-contracts` et packages PDF/release-chain
  installés depuis ce checkout en mode non éditable. Aucun staging, registre,
  serveur ou base de production n'a été muté. Aucune clé opérateur n'a été
  lue, créée ou signée. Aucune image applicative n'a été construite ou poussée.
- Le lot restera local jusqu'à la fusion de #310. Il devra ensuite être
  réappliqué sur le nouveau `main` et revérifié avant toute PR.

## Changement

Le wrapper existant accepte le bundle public V2 en exécution seulement après
GO final explicite et succès frais du garde canonique `--assert-ready` sur le
checkout propre au SHA signé. Il revalide le bundle, la signature, la
provenance V2, le Compose effectif et le préflight des matériaux et secrets.
Il refuse toute ressource existante dans la couleur sélectionnée, exécute
`pull` puis `up --wait` sur cinq services explicites et des images par digest,
et retire seulement la couleur candidate si le démarrage échoue. Le rollback
explicite relit le bundle, garde les volumes et ne dépend pas d'une readiness
qui pourrait avoir changé après le lancement. La voie V1 reste inchangée.

Le code ne change aucun vhost Nginx ni ancien projet Compose. Il ne prétend
pas qualifier une release publique finale : droits étudiant, image finale,
load C0, backup/restore, signature opérateur et GO de production restent à
prouver séparément. Le drapeau `--final-cutover-go` est une frontière
technique explicite ; le protocole humain de cutover reste obligatoire.

## TDD et qualification locale

- Red : huit nouveaux tests ont d'abord échoué sur l'API de déploiement
  publique absente ; quatre tests CLI/rollback sur leur chemin manquant ;
  un test de checkout sale ; un test de timeout `up` ; un test de projet
  préflight `infra` ; un test du scratch privé du harnais historique.
- Green : la suite élargie de contrats readiness, signer, provenance,
  préflight/Compose public, wrapper V1/V2 et harnais historique a collecté
  **467 tests** et terminé avec **466 réussites, 1 skip préexistant** sur le
  commit de code `e9dd95d7cb5c7d1eb44f8df35c270811c55226a7`, arbre
  `c4bb5b77a1a5a698a97c6e6d72e0be9dc140b538`. `ruff check` sur les cinq
  fichiers Python modifiés et `git diff --check` : zéro erreur. `mypy` ciblé
  sur wrapper et harnais signale 49 erreurs dans cinq fichiers ; aucun
  diagnostic ne vise les fonctions publiques ajoutées, mais le contrôle
  n'est **pas** déclaré vert et devra être comparé à la base après #310.
- Un test Docker local synthétique a réellement démarré cinq services Alpine
  sur `nexus-rag-blue` avec une image disponible par digest, sans port ni
  volume, puis les a arrêtés. Le conteneur témoin étranger est resté identique
  (ID, `StartedAt`, compteur de redémarrage et état). Le projet candidat ne
  laisse aucun conteneur, réseau ou volume. Le test remplace les seules
  frontières de signature/préflight par des faits synthétiques : il prouve
  l'ordre des commandes et l'isolation Docker, pas la release RAG finale.
- Le harnais Docker V2 historique, rejoué depuis ce checkout après correction
  de son scratch privé, a rendu `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`,
  `BAD_DIGEST_REFUSED=true`, `BAD_READINESS_REFUSED=true`,
  `ROLLBACK_REHEARSAL_PASS=true`, `FOREIGN_SERVICES_TOUCHED=0`,
  `REMOVE_ORPHANS_USED=false`, `PRODUCTION_PROJECT_NAME_USED=false`, zéro
  conteneur, réseau et volume résiduels. Évidence synthétique reproductible
  observée le `2026-10-09T18:50:06Z` sur le commit de code et son arbre
  précités : [JSON](evidence/local_311/atomic_docker_v2_rehearsal_20260825.json),
  SHA-256
  `18cb67d6039388a6b443c2e1b3f0361580d325f31c8eb4287249c6be21d0222b`.
  Les fichiers [transcript](evidence/local_311/atomic_docker_v2_rehearsal_20260825.transcript.txt)
  et [empreintes](evidence/local_311/atomic_docker_v2_rehearsal_20260825.sha256)
  accompagnent le JSON. Cette preuve ne qualifie pas le candidat final ; le
  harnais sera rejoué après synchronisation avec #310.

## Reste pour le go-live

La cible d'inférence dédiée, la release publique successeur gouvernée, les
droits étudiant par collection, les images finales et leur inventaire V2,
le staging final, les 11 collections, la qualité retrieval, C0, la sauvegarde
et restauration du candidat, le rollback edge, la signature hors ligne et
la qualification de la cible production ne sont pas établis par ce lot.
`PRODUCTION_READY=false`, `GO_LIVE_READY=false` et
`RAG_PRODUCTION_DEPLOYED=false` restent les seuls verdicts honnêtes ici.
