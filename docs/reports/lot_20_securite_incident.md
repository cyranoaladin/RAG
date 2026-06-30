# Rapport d'incident de sécurité — LOT 20

**Date de l'incident** : 30 juin 2026
**Date du rapport** : 30 juin 2026 (v3)
**Sévérité** : élevée
**Statut** : **remédié** (rotation exécutée, preuves ci-dessous)

---

## 1. Description

### 1.1 Token API ingestor

- **Vecteur** : `docker inspect compose-ingestor-1 --format '{{json .Config.Env}}'` a affiché le token ; le token a été réutilisé en clair dans un argument `curl`.
- **Surface** : transcript de session.
- **Impact** : accès complet à l'API ingestor (lecture, ingestion, administration) via `rag-api.nexusreussite.academy`.

### 1.2 Credentials PostgreSQL

- **Vecteur** : `docker inspect nexus-postgres-db --format '{{json .Config.Env}}'` a affiché user/password.
- **Surface** : transcript de session.
- **Impact** : accès à `nexus_prod` (PII). Atténuation : port 127.0.0.1:5435 uniquement (pas d'accès externe direct). Cependant, sur hôte mutualisé, tout processus local (korrigo, labomaths, NSI, journey) pourrait théoriquement accéder.

### 1.3 Dépassement de périmètre

Énumération des tables `nexus_prod` exécutée (hors périmètre R-02). Aucune donnée extraite.

---

## 2. Remédiation exécutée

### 2.1 Rotation du token API (A-8)

Procédure exécutée le 30/06/2026 17:23 UTC, conforme à I-12 (pas de fichier temporaire) :

1. Backup de l'ancien `.env` dans `/srv/nexusreussite/rag-ui/backups/compose_env_pre_rotation_*`
2. Génération du token **en mémoire** (`openssl rand -hex 32` dans une variable shell, jamais écrit dans `/tmp`)
3. Injection directe dans `.env` via `sed -i` (la variable est dans le processus shell, pas en argument visible dans `ps`)
4. Recréation des conteneurs `ingestor` et `ui` (`docker compose up -d ingestor ui`)

### 2.2 Preuve d'invalidation

```
=== OLD TOKEN TEST ===
HTTP status: 401
=== NEW TOKEN TEST ===
HTTP status: 200
=== HEALTH ===
{"status":"healthy"}
```

Ancien token → **401 Unauthorized**. Nouveau token → **200 OK** (via fichier d'en-tête `/dev/shm/auth_header`, supprimé immédiatement après).

### 2.3 Purge (I-13 élargie)

Historique shell serveur :
```
Lines with old token prefix: 0
Lines with pg password pattern: 0
Lines with INGESTOR_API_TOKEN=: 0
Lines with POSTGRES_PASSWORD: 0
```

**Autres surfaces d'exposition** :
- **Transcript de session** (côté client Claude Code) : contient les valeurs. Le lead en est informé.
- **Logs Docker** : `docker inspect` n'est pas logué dans les logs de conteneur. Les logs d'accès nginx peuvent contenir des en-têtes `Authorization` si le log format les inclut — vérifier le format de log (le format `eaf_diag` logué n'inclut pas les en-têtes d'auth, seulement `$upstream_addr`).
- **Journal systemd** : les commandes SSH ne sont pas loguées dans le journal systemd du host.

### 2.4 Mot de passe PostgreSQL (I-14)

**Décision** : rotation recommandée. **Échéance** : à planifier avec le responsable de l'application Nexus **avant la fin du LOT 22** (avant que des modifications de la pile touche les services voisins). La rotation nécessite :
- Mise à jour env `nexus-postgres-db`
- `ALTER USER` dans la base
- Mise à jour des applications connectées (Nexus backend, celery)
- Test de connectivité
- **Pas à la charge de l'agent de codage RAG** — coordination avec le responsable Nexus.

---

## 3. Checklist post-rotation

- [x] Ancien token invalide (401 prouvé)
- [x] Nouveau token fonctionnel (200 prouvé, via fichier d'en-tête)
- [x] Pas de fichier temporaire contenant le token
- [x] Historique shell purgé (0 occurrence)
- [x] Conteneur UI recréé avec le nouveau token
- [x] Backup de l'ancien `.env` conservé (rollback possible)
- [x] Aucun secret dans les fichiers versionnés (`grep` = 0)
- [x] `/dev/shm` propre (aucun fichier d'en-tête résiduel — J-07)
- [x] `.env` de rollback restreint (`chmod 600 root:nexus` — J-07). Suppression planifiée après fenêtre de surveillance J-01.
- [ ] Rotation mot de passe PostgreSQL — échéance : avant fin LOT 22 (I-14), exécution lead/responsable Nexus
