# Go-Live — Plan d'action humain (PII/actualité · staging cloisonné · concurrence)

- Lot : `LOT_GO_LIVE_FINAL_CA_HUMAN_ACTION_PLAN`
- Branche : `go-live/human-action-plan` — base `3b921b40ed3871c07b90a57830d95df56e68774e`
- **Décision : `HUMAN_ACTION_PLAN_READY`**
- Ce lot ne décide rien, n'importe rien, ne se connecte nulle part, ne modifie ni gate, ni budget, ni compteur.

## A. PII / actualité — les 75 lignes qui débloquent C1

| Fichier | Rôle |
|---|---|
| `docs/reports/go_live/PII_CURRENTNESS_C1_MINIMAL_SHEET.md` | **vue de lecture** : les 3 + 23 contenus, risque, classes, pages, décision V1. Aucune colonne de décision |
| `docs/reports/go_live/pii_currentness_c1_minimal_sheet.tsv` | **feuille à remplir** : 75 lignes (3 actualité, 23 contenus, 49 findings) |
| `docs/reports/go_live/pii_currentness_decision_sheet.tsv` | feuille complète (631 lignes) ; l'extrait en est un sous-ensemble strict, ligne pour ligne |

Remplir **une seule** des deux feuilles ; à l'import vous désignerez laquelle. Les deux sont dérivées par
`build_pii_currentness_decision_packet.py` ; une épreuve garantit que l'extrait ne contient que des lignes de la feuille
complète et qu'aucune cellule de décision n'est remplie. Le dossier scellé (#213) n'est pas rescellé.

### Colonnes — en minuscules : à lire ; en MAJUSCULES : à remplir

| Colonne | Sens |
|---|---|
| `row_kind` | `CURRENTNESS_CONTENT`, `PII_CONTENT` ou `PII_FINDING` : détermine quelles colonnes vous remplissez |
| `priority` | toujours `P1_PROMOTED_BLOCKS_RELEASE` dans l'extrait |
| `content_sha256` | identité du contenu ; relie un finding à son contenu |
| `title`, `source_path` | le document |
| `risk_tier` | `ELEVE` / `MOYEN` / `A_QUALIFIER`, repris du tableau de pilotage : ordonne, ne décide pas |
| `signal_classes`, `finding_count`, `pages` | ce que le scanner a relevé, et où |
| `finding_id`, `pattern_id`, `page`, `extraction_path` | pour une ligne `PII_FINDING` : quel motif, quelle page, texte natif ou OCR |
| `review_bundle_dir` | dossier du paquet hors dépôt : `~/nexus-pii-review-v2-20260907/<review_bundle_dir>/` (`document.pdf`, `pages/page-NNNN.txt`) |
| `prior_v1_decision_not_extended` | décision V1 sur l'ancien texte : **information**, pas décision |
| `currentness_declared` | ce que la source déclare |
| `allowed_options` | les valeurs recevables pour cette ligne |
| **`FINDING_DISPOSITION`** | lignes `PII_FINDING` seulement : `FALSE_POSITIVE_TECHNICAL` \| `PUBLIC_INSTITUTIONAL_DATA` \| `SYNTHETIC_EXAMPLE` \| `PERSONAL_DATA_PRESENT` |
| **`HUMAN_DECISION`** | `PII_CONTENT` : `PII_CLEARED` \| `PII_REDACTION_REQUIRED` \| `EXCLUDE_FROM_SERVABLE_SET` \| `HUMAN_REVIEW_REQUIRED`. `CURRENTNESS_CONTENT` : `KEEP_IF_STILL_CURRENT_WITH_EVIDENCE` \| `REPLACE_WITH_CURRENT_SOURCE` \| `EXCLUDE_FROM_PROMOTED_RELEASE` \| `HUMAN_REVIEW_REQUIRED` |
| **`JUSTIFICATION_CATEGORY`** | `PII_CONTENT` : `INSTITUTIONAL_CONTACT` \| `PEDAGOGICAL_EXAMPLE` \| `FICTIONAL_IDENTITY` \| `TECHNICAL_FALSE_POSITIVE` \| `PUBLIC_OFFICIAL_PUBLICATION` \| `PERSONAL_DATA_PRESENT` |
| **`REVIEWER_LOGIN`** | votre identifiant GitHub, sur chaque ligne de contenu décidée |
| **`EVIDENCE_REFERENCE`** | obligatoire pour `KEEP_IF_STILL_CURRENT_WITH_EVIDENCE` : référence datée prouvant que le texte est en vigueur |
| **`COMMENT`** | libre ; **ne jamais y recopier une donnée personnelle** |

### Ordre de travail conseillé

1. Les 3 lignes d'actualité (une décision chacune).
2. Pour chaque contenu PII, dans l'ordre de la feuille : ouvrir le paquet, statuer **chaque** finding, puis la ligne de contenu.
   Règle du contrat, appliquée à l'import : `PII_CLEARED` est refusé si un seul finding du contenu est `PERSONAL_DATA_PRESENT`.
3. Une ligne laissée vide ou `HUMAN_REVIEW_REQUIRED` laisse le contenu bloquant : sans risque.

Conséquences à connaître avant de choisir : `PII_REDACTION_REQUIRED` crée un **autre** contenu (nouvelle empreinte →
nouvelle acquisition, nouveau scan, nouvelle revue) ; toute exclusion d'un contenu promu exige un rescellement de release,
et le constructeur de release **ne sait pas exclure** aujourd'hui (ADR préalable, lot BW).

Pour reprendre : `PII_DECISIONS_READY fichier=<chemin> — import autorisé`.

## B. Staging cloisonné sur `nexus-prod`

Procédure complète : `docs/runbooks/staging_cloisonne_nexus_prod.md` — principes de cloisonnement, ports proposés
(18001 / 15435 / 19191, loopback), volumes `nexus-staging_*`, 21 variables (noms seuls), 9 phases avec commandes et
points d'arrêt, risques, interdits. Accès par **tunnel SSH uniquement** : Nginx, DNS et certificats ne sont pas touchés ;
le Cockpit de staging tourne sur le poste de travail.

Trouvé en préparant : `apply_pgvector_migrations.sh` vise un conteneur par nom, défaut `rag_pgvector` — possiblement la
base de production sur cet hôte. La procédure impose `PGVECTOR_CONTAINER=nexus-staging-pgvector-1` et une vérification
préalable du nom. C'est le risque le plus grave du volet.

Trois faits que vous seul pouvez fixer avant le jour J : la source de l'index de staging (ingestion gouvernée multilevel,
ou dump de la base vectorielle de staging locale), le répertoire de corpus servables et ses empreintes, la fenêtre horaire.

Limite déclarée : même machine que la production. La preuve dira `production_cloisonnee` ; si vous exigez une séparation
physique, c'est le mode B.

Pour reprendre : `SSH_STAGING_AUTHORIZED sur nexus-prod pour le commit <SHA>`. Sans cette phrase, aucune connexion.

## C. Concurrence

Plan : `docs/reports/go_live/CONCURRENCY_TARGET_HOST_MEASUREMENT_PLAN.md`. Budget inchangé (empreinte liée), preuve
`BUDGET_FAILED` conservée comme diagnostic, mesure en deux temps sur le staging cloisonné : **C0** séquentiel (faible coût,
décisif : si p50 > 3000 ms pour une requête seule, le budget est inatteignable et la décision est de dimensionnement),
puis **C1** profil complet sur feu vert distinct. **Aucun ADR de profil n'est proposé** : il ne le sera que sur donnée
d'usage fournie par vous, fixé avant mesure, dans un commit distinct de toute fermeture.

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=4`, `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
