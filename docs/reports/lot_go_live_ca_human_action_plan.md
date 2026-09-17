# Go-Live — Paquet d'action des verrous humains

- Lot : `LOT_GO_LIVE_FINAL_CA_HUMAN_GATES_ACTION_PACKET`
- Branche : `go-live/human-action-plan` — base `3b921b40ed3871c07b90a57830d95df56e68774e`
- **Décision : `GO_LIVE_HUMAN_GATES_ACTION_PACKET_READY`**
  (`PII_MINIMAL_REVIEW_PACKET_READY` · `STAGING_EXECUTION_PLAN_READY_REQUIRES_SSH_AUTHORIZATION` · `CONCURRENCY_ARBITRATION_READY`)
- Le chantier n'est pas terminé : il attend les décisions humaines **minimales** ci-dessous pour reprendre vers
  `GO_LIVE_READY=true`. Ce lot ne décide rien, n'importe rien, ne se connecte nulle part, ne modifie ni gate, ni budget,
  ni compteur. Le dossier scellé de #213 n'est pas rescellé.

## Les trois décisions à rendre

| # | Décision | Ce que vous faites | La phrase qui me fait reprendre |
|---|---|---|---|
| 1 | **PII / actualité** | remplir `docs/reports/go_live/pii_currentness_minimal_c1_review.tsv` (75 lignes) avec `PII_CURRENTNESS_REVIEWER_GUIDE.md`, contrôler avec le validateur | `PII_DECISIONS_VALIDATED fichier=<chemin> reviewer=<login> — IMPORT AUTORISÉ` |
| 2 | **Staging** | autoriser le mode A, ou désigner un hôte séparé | `SSH_STAGING_AUTHORIZED sur nexus-prod pour le commit <SHA>` (ou l'hôte du mode B) |
| 3 | **Concurrence** | choisir une voie dans `CONCURRENCY_ARBITRATION_OPTIONS.md` | `CONCURRENCY_DECISION voie=A\|B\|C …` |

1 et 2 sont indépendantes ; 3 se mesure sur le staging de 2.

## 1. PII / actualité

| Fichier | Rôle |
|---|---|
| `docs/reports/go_live/pii_currentness_minimal_c1_review.tsv` | **à remplir** : 3 actualité + 23 contenus promus + 49 findings, dans l'ordre de revue ; colonnes d'aide `review_order`, `open_this_file`, `WHAT_TO_FILL_ON_THIS_ROW` |
| `docs/reports/go_live/PII_CURRENTNESS_REVIEWER_GUIDE.md` | colonnes, valeurs autorisées, quand choisir chaque option, comment éviter une décision invalide, ordre d'import |
| `docs/reports/go_live/PII_CURRENTNESS_MINIMAL_C1_VIEW.md` | vue de lecture des 26 contenus, sans colonne de décision |
| `scripts/go_live/validate_pii_currentness_review_sheet.py` | contrôle une feuille **remplie** : n'importe rien, n'écrit rien. 9 épreuves |

L'extrait est dérivé : projeté sur les colonnes de la feuille complète, chacune de ses lignes en est une à l'identique
(épreuve) ; aucune cellule de décision n'est remplie (épreuve) ; aucun chemin absolu machine-local
(`$NEXUS_PII_REVIEW_ROOT`). Feuille vierge au validateur : 0 décidé, 26 en attente, 0 invalide.

À savoir : ces 75 lignes ramènent `release_promoted_refused_contents` à 0 et ouvrent C1, mais `pii_undecided` ne descend
qu'à 126 ; les 126 contenus restants (feuille complète) sont aussi requis pour le go-live. Toute décision qui retire un
contenu promu exige un ADR préalable : le constructeur de release ne sait pas exclure.

## 2. Staging cloisonné sur `nexus-prod`

`docs/runbooks/staging_externe_nexus_prod_cloisonne_EXECUTION_PLAN.md` : projet Compose `nexus-staging`, ports loopback
proposés 18001 / 15435 / 19191, volumes `nexus-staging_*`, 21 variables (noms seuls), image `ingestor` **figée par
digest** (`--no-build` ensuite), photographie préalable, 9 phases à points d'arrêt, healthchecks, smoke tests API /
retrieval / Cockpit par **tunnel SSH** (Nginx, DNS, certificats intouchés ; Cockpit sur le poste de travail), rollback
éprouvé, trois `diff` prouvant zéro production touchée et zéro current switch, 10 conditions d'arrêt immédiat.

Risque critique trouvé en préparant : `apply_pgvector_migrations.sh` vise un conteneur **par nom**, défaut
`rag_pgvector` — possiblement la base de production sur cet hôte. Le plan impose `PGVECTOR_CONTAINER=nexus-staging-pgvector-1`
et une vérification préalable du nom.

À fixer par vous avant le jour J : la source de l'index de staging (ingestion gouvernée multilevel, ou dump de la base
vectorielle de staging), le répertoire de corpus servables et ses empreintes, la fenêtre horaire, et la confirmation
qu'une sauvegarde de production récente existe. Limite déclarée du mode A : même machine que la production.

## 3. Concurrence

`docs/reports/go_live/CONCURRENCY_ARBITRATION_OPTIONS.md` compare dimensionnement, plafond de rerank et profil de charge,
avec les coûts mesurés à 8 et à 2 threads. Deux faits structurants : à 2 CPU une requête **seule** prend ≈ 3,6 s ; et le
profil actuel (8 clients sans temps de réflexion) équivaut à ≈ 170 utilisateurs en recherche simultanée.
**Recommandation, non adoptée : voie A avec GPU d'inférence, précédée de la mesure séquentielle C0 sur le staging.**
`CONCURRENCY_TARGET_HOST_MEASUREMENT_PLAN.md` décrit cette mesure ; budget inchangé, preuve `BUDGET_FAILED` conservée.

## Ce que je ferai à réception, sans nouvelle question

| Reçu | Lots enchaînés |
|---|---|
| Décisions PII | import sous contrat + PR à revue épinglée → (ADR d'exclusion si nécessaire) → BW : rescellement gouverné, C1 |
| Autorisation SSH | exécution du plan phase par phase → preuve mode A → STAGING_EXTERNE ; puis mesure C0 |
| Décision concurrence | configuration ou ADR **avant** mesure → C0 / C1 → CONCURRENCE |
| Les trois clos | BX : manifeste de production signé → BY : préparation du déploiement → `GO_PROD_EXECUTE` |

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=4` (C1, STAGING_EXTERNE,
CONCURRENCE, MANIFESTE_PRODUCTION), `pii_undecided=149`, `release_promoted_refused_contents=26`, `current_switch=0`,
`production_db_writes=0`, `production_deployments=0`.
