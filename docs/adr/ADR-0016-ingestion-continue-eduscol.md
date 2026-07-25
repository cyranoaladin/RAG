# ADR-0016 — Ingestion continue gouvernée depuis eduscol (agents et planification)

- **Statut** : proposé (LOT 28)
- **Date** : 2026-07-26
- **Contexte** : AUDIT_LOT28_GLOBAL §2.4 (E-03)

## Décision

1. **`EduscolAgent`** (`services/rag-pedago/agents/eduscol_agent.py`) : fetch GET-only via `scrapers.fetch.governed_fetch` (whitelist + robots.txt existants), dépôt **staging uniquement**, détection de changement par SHA-256 du contenu normalisé, TTL 7 jours, budgets par passe (pages, octets, durée), découverte de liens 1 niveau en statut `to_review`.
2. **Politesse réseau durcie** : le robots.txt réel d'eduscol (relevé le 26/07/2026) impose `Crawl-delay: 10` pour `User-agent: *` et interdit `/recherche/`. L'agent applique un délai par domaine ≥ crawl-delay (`continuous_ingestion.yml > per_domain_delay` : eduscol 10 s). **Constat d'audit** : le `RATE_LIMIT_SECONDS = 2.0` de `scrapers/fetch.py` est insuffisant pour eduscol — durcissement recommandé dans le module partagé au lot suivant (hors périmètre lot 28, signalé conformément à AGENTS.md §Escalade).
3. **Sources semences** (`configs/eduscol_sources.yml`) : 20 sources déclarées, **8 vérifiées** (fetch/recherche officielle du 26/07/2026), 12 `to_verify` ignorées jusqu'à validation humaine. Aucune URL `/recherche/`.
4. **Planification externe** (`agents/continuous_orchestrator.py` + `scripts/continuous-ingestion.sh` + `scripts/systemd/*.timer`) : une passe = un run ; la continuité est assurée par systemd timer (quotidien, jitter 30 min). Le module ne boucle jamais lui-même.
5. **Verrous consultés en fail-closed** : `data_staging_allowed` et `network_allowed` requis ; aucune écriture pgvector, aucun contournement quality → gate → review, `answer_generation_allowed` inchangé (false).
6. **Procédure d'activation d'une source `to_verify`** : revue humaine de l'URL et des droits → bascule `status: verified` dans `eduscol_sources.yml` via PR → traçabilité ledger.

## Dette signalée (préexistante, hors périmètre)

- `OrchestratorAgent.fetch` exige `ingestion_allowed == false`, or le verrou est à `true` depuis ADR-0008 : l'orchestrateur historique est **inopérant en l'état**. Le garde-fou doit être réaligné sur la sémantique actuelle des verrous (lot suivant).
- Smoke test lot 28 : chaîne de gouvernance validée de bout en bout dans le sandbox (skips, ledger, rapport) ; le fetch réseau réel retourne HTTP 403 depuis le sandbox (restriction d'égresse — à rejouer sur l'hôte de production où eduscol est joignable).
