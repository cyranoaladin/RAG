# Runbook — Déploiement du cockpit v2 sur rag-ui.nexusreussite.academy (LOT 28)

**Prérequis** : accès SSH à l'hôte de production, droits sudo, branche `lot-28` fusionnée dans `main`.
**Règles** : R-01 (pas de secret en argument), R-03 (commande incertaine non exécutée). Chaque étape est réversible.

---

## Étape 0 — Sauvegarde et point de restauration

```bash
# Sur l'hôte
sudo systemctl stop docker 2>/dev/null || true   # NE PAS exécuter si d'autres piles tournent — préférer :
cd /srv/nexusreussite/rag-ui
tar czf backups/rag-ui_pre-v2_$(date +%Y%m%d).tgz compose data creds
docker compose ps > backups/rag-ui_pre-v2_conteneurs.txt
```

Point de restauration : l'archive `rag-ui_pre-v2_*.tgz` + le fichier `backups/…conteneurs.txt`.

## Étape 1 — Build du cockpit v2 depuis le dépôt (corrige la divergence I-05)

```bash
# Sur l'hôte (ou en CI) — JAMAIS depuis un répertoire local non versionné
cd /srv/nexusreussite && git clone --depth 1 https://github.com/cyranoaladin/RAG.git rag-v2-build
cd rag-v2-build/services/cockpit
npm ci
VITE_RAG_API_BASE=https://rag-api.nexusreussite.academy npm run build
# Artefact : services/cockpit/dist/
```

## Étape 2 — Publication statique derrière nginx (coexistence avec le legacy)

Ne pas couper le legacy immédiatement. Servir le v2 sur un vhost de staging :

```nginx
# /etc/nginx/sites-available/rag-ui-v2-staging
server {
    listen 443 ssl;
    server_name rag-ui-v2.nexusreussite.academy;
    root /srv/nexusreussite/rag-v2-build/services/cockpit/dist;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:18001; proxy_read_timeout 300s; }
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header Strict-Transport-Security "max-age=63072000" always;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/rag-ui-v2-staging /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Étape 3 — Recette sur le vhost de staging

- [ ] Les 6 vues se chargent ; le badge passe à « API connectée »
- [ ] `/search` retourne des résultats NSI (collection instanciée) avec citations
- [ ] Aucune collection n'est créée par navigation (vérifier ChromaDB/pgvector : nombre de collections stable)
- [ ] La page Ingestion affiche les 8 sources vérifiées / 12 à valider
- [ ] Les verrous affichés correspondent à `pedago_interface_contract.yml`

## Étape 4 — Bascule DNS/vhost principal

Après recette OK, pointer `rag-ui.nexusreussite.academy` vers `dist/` (même bloc que l'étape 2), recharger nginx, conserver le legacy **arrêté mais restaurable** 14 jours :

```bash
cd /srv/nexusreussite/rag-ui/compose
docker compose stop ui            # legacy Streamlit arrêté, conteneur conservé
# Restauration si incident : docker compose start ui + rétablir l'ancien vhost
```

## Étape 5 — Ingestion continue (systemd)

```bash
mkdir -p ~/.config/systemd/user
cp /srv/nexusreussite/rag-v2-build/scripts/systemd/nexus-rag-continuous-ingestion.* ~/.config/systemd/user/
# Adapter RAG_ROOT dans l'unité vers /srv/nexusreussite/rag-v2-build
systemctl --user daemon-reload
systemctl --user enable --now nexus-rag-continuous-ingestion.timer
systemctl --user list-timers | grep nexus-rag
journalctl --user -u nexus-rag-continuous-ingestion.service -n 50
```

Vérifier après la première passe : `services/rag-pedago/data/reports/continuous_ingestion_latest.md`
et `data/ledger/continuous_ingestion.jsonl`. En cas de HTTP 403 généralisé, vérifier l'égresse réseau de l'hôte vers eduscol (le sandbox CI est bloqué ; l'hôte de production ne doit pas l'être).

## Étape 6 (Phase C, lot ultérieur) — Décommissionnement legacy

- Migration gouvernée des 9 199 chunks admissibles (quality → gate → review) vers pgvector 1024d
- Suppression des collections ChromaDB legacy et de `ressources_pedagogiques_terminale` (résiduelle)
- Arrêt et suppression des conteneurs `compose-ui-1`, `compose-chroma-1`, `compose-ollama-1` (sauf si Ollama partagé)

## Rollback

1. `docker compose start ui` (legacy Streamlit)
2. Rétablir l'ancien bloc nginx `rag-ui` → `127.0.0.1:18501`, `sudo nginx -t && sudo systemctl reload nginx`
3. `systemctl --user stop nexus-rag-continuous-ingestion.timer` (gèle l'ingestion sans perte : staging et ledger conservés)
