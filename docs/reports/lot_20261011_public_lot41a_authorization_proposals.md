# Lot — propositions LOT41A-V2 du successeur public

Date UTC : 2026-10-11. Source actuelle : `origin/main=525db1d34d1e247c512d12d6625a546fd232413e`, arbre `d7380c9927357460c4fc25e02fc920e366a1c72b`. Rebase propre de #329 après #331 ; worktree et venv isolés. Ce lot ne modifie ni staging ni production et ne produit aucune revue, signature ou autorisation enregistrée.

## Population et décisions préparées

Le générateur `scripts/go_live/build_public_lot41a_authorizations.py` a relu l'ancre A renouvelée `docs/reports/go_live/student_public_successor_content_anchor_20261011.json` (SHA-256 `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`), son manifeste `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85`, les onze subjects et profils, le registre des 253 dérivés, les 253 entrées de droits et PII, et l'attestation d'actualité `docs/reports/go_live/student_derivative_source_currentness_20261011.json` (SHA-256 `76c68ea269f6031244d9f8824186abe0299f2810494e1d28b02e13cc4e2d912c`). Il a écrit et relu avec `--check` onze `ScopeAuthorizationArtifactV2` canoniques pour **377 placements**, **253 identités uniques** et **11 collections**. L'ancien A 20261010 a expiré et n'est pas repris.

Chaque proposition porte la portée publique du profil de sa collection, `rights_categories=[public_allowed]`, le domaine `eduscol.education.gouv.fr`, le registre PII scellé de A, `pii_absence_attested=true`, et la décision `AUTHORIZE_INGESTION_SCOPE`. Les contrôles exigent `EDUSCOL_ETALAB_2_0_SITEWIDE` pour les droits et un contrôle PII positif lié aux mêmes dérivés et PDF sources. `valid_from=2026-10-11T14:05:36Z` provient de l'attestation ; `valid_until=2026-10-12T13:58:41.752Z` vient de l'index scellé. Le générateur refuse après cette échéance. Les PDF originaux restent hors des listes positives ; aucun nouveau scope n'est émis par ce lot.

Le CLI exige explicitement `--anchor-path`, `--anchor-sha256`, `--release-root` et `--currentness-attestation-path` : aucune ancienne identité n'est codée comme valeur par défaut. Il n'écrit les onze propositions qu'avec `--write` et les compare à A avec `--check`. Il refuse une divergence préexistante avant toute écriture. Les tests sont désormais épinglés aux SHA de A, de l'attestation et des onze propositions, et couvrent la dérivation et les refus pour un droit négatif, une preuve PII négative, l'expiration, un placement divergent ou un scope `internal`.

Exécution locale depuis le worktree #329 rebasé, avec venv propre de ce worktree :

```bash
python scripts/go_live/build_public_lot41a_authorizations.py \
  --write --anchor-path docs/reports/go_live/student_public_successor_content_anchor_20261011.json \
  --anchor-sha256 1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0 \
  --release-root services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60 \
  --currentness-attestation-path docs/reports/go_live/student_derivative_source_currentness_20261011.json
python scripts/go_live/build_public_lot41a_authorizations.py \
  --check --anchor-path docs/reports/go_live/student_public_successor_content_anchor_20261011.json \
  --anchor-sha256 1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0 \
  --release-root services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60 \
  --currentness-attestation-path docs/reports/go_live/student_derivative_source_currentness_20261011.json
```

Les deux commandes ont rendu `PROPOSALS=11 REVIEW_BINDINGS=0`. En présence d'un sujet absent, d'une source hors autorité, d'un droit ou contrôle PII non positif, ou d'une expiration, la génération s'arrête sans décision positive.

Les chemins ci-dessous sont sous `governance/authorizations/` et suivent la forme `lot41a-student-public-<suffixe>-v1.json` :

| Suffixe | SHA-256 des octets canoniques | Placements |
|---|---|---:|
| `dgemc-terminale-option` | `5f262cd9ece3a0d8a21e567ae5cc02d716d7c2505ee5da2de2d7684f7ce4ef45` | 6 |
| `hggsp-premiere-specialite` | `6d150e54f28b5ca954094c008cf9842e03d2b98af407c89fa2fbbe5fe2fca18c` | 32 |
| `hggsp-terminale-specialite` | `726c3484d63ff7de4b7c1b2edab6b9f56f0bdc931e7d8bb8164ab701835f6271` | 28 |
| `hlp-premiere-specialite` | `6ad6009102b8485877ea383e8c158cc9d2083200ff1093ce2668c371814a90d1` | 98 |
| `hlp-terminale-specialite` | `34ae3b8e740484a38f3ed3d90bada4a48b353446bc490ceb6f12502559ddb00e` | 73 |
| `nsi-premiere-specialite` | `50fa0b2ec42c2f8988a26a9577faad00bb5136a5c0f9e5bd179598ad2eca3158` | 20 |
| `nsi-terminale-specialite` | `56840efb09d102535ba87c34daeb9724f215b7833c932cdde6583c8f1ed6fd56` | 34 |
| `ses-premiere-specialite` | `5417b457f724593cc14de6ca099c84f1b7fbba5d44cd6bb64caa91511e882fc6` | 26 |
| `ses-terminale-specialite` | `cfd6865868d2ce44f0e32766fe2539b5f2b25256e6d298c8e9b86c6a614d85aa` | 25 |
| `svt-premiere-specialite` | `6e321483785b980a5e9bc7674898f3ba7f91f8a1d95cd85c3a42be99592cbf1f` | 10 |
| `svt-terminale-specialite` | `349186c4af739eb0daf16c22e1afddaa1f1e23724ab53a3696355b1e4d2ca731` | 25 |

La somme des placements vaut 377 ; des dérivés apparaissent dans plusieurs scopes, donc les identités uniques restent 253.

## Frontière de revue et de signature

Les onze fichiers sont des **propositions**, pas onze autorisations utilisables. La PR #329 doit rester ouverte jusqu'au contrôle de fermeture de LOT41A. Elle reste draft tant que la CI et le HEAD final ne sont pas validés. Ensuite, une unique review GitHub `APPROVED` de `abenrhouma` sur son HEAD/base/challenge exacts peut couvrir les onze blobs. Le vérificateur canonique refuse une PR draft, fermée ou à HEAD divergent. Le contexte `trusted-human-review/head-pinned` doit être `success` avant tout usage. Chaque artefact exige son propre `ScopeAuthorizationReviewBindingV1` signé, avec chemin, SHA-256 et Git blob SHA-1 exacts.

Le chemin B pour la nouvelle A dépend de la review exacte de #330 et de son reçu post-fusion ; les onze autorisations proposées ici n'accordent aucune portée B à elles seules.

La clé privée Ed25519 correspondant à l'ancre `governance/trust-anchors/review-binding-v1.json`, `key_id=review-binding-v1-2026-08-25`, est détenue par l'opérateur hors Git/CI/serveur. Elle ne se déduit pas de l'ancre et ne doit jamais être fournie dans le chat. Le producteur officiel est `services/rag-engine/src/ingestor/ingestion_worker/issue_review_binding_cli.py`; il relit la PR et le blob depuis GitHub, recalcule le challenge et écrit un seul reçu canonique sur stdout après auto-contrôle. Le jeton GitHub est lu depuis `NEXUS_GITHUB_TOKEN_FILE` de préférence. Préparer un venv propre de **ce** worktree avec `nexus-contracts`, `httpx`, `psycopg[binary]` puis, seulement après review et statut requis verts, exécuter dans un checkout au HEAD revu :

```bash
NEXUS_AUTH_PR=$(gh pr view --json number --jq .number)
NEXUS_AUTH_HEAD=$(gh pr view --json headRefOid --jq .headRefOid)
python scripts/github/trusted_human_review_github.py \
  --repository cyranoaladin/RAG --pull-request "$NEXUS_AUTH_PR" \
  --expected-head "$NEXUS_AUTH_HEAD" --check || exit 1
gh pr checks "$NEXUS_AUTH_PR" --required || exit 1
NEXUS_MATERIAL_DIR=$(mktemp -d)
mkdir -p "$NEXUS_MATERIAL_DIR/governance/authorizations" "$NEXUS_MATERIAL_DIR/governance/review-bindings"
cp governance/authorizations/lot41a-student-public-*-v1.json "$NEXUS_MATERIAL_DIR/governance/authorizations/"
for NEXUS_AUTH_FILE in governance/authorizations/lot41a-student-public-*-v1.json; do
  NEXUS_AUTH_ID=${NEXUS_AUTH_FILE##*/}
  NEXUS_AUTH_ID=${NEXUS_AUTH_ID%.json}
  PYTHONPATH="services/rag-engine/src:packages/contracts/src" .venv/bin/python \
    -m ingestor.ingestion_worker.issue_review_binding_cli issue \
    --repository cyranoaladin/RAG --pull-request "$NEXUS_AUTH_PR" \
    --expected-head "$NEXUS_AUTH_HEAD" --authorization-id "$NEXUS_AUTH_ID" \
    --key-id review-binding-v1-2026-08-25 \
    > "$NEXUS_MATERIAL_DIR/governance/review-bindings/$NEXUS_AUTH_ID.json.tmp" || exit 1
  mv "$NEXUS_MATERIAL_DIR/governance/review-bindings/$NEXUS_AUTH_ID.json.tmp" \
    "$NEXUS_MATERIAL_DIR/governance/review-bindings/$NEXUS_AUTH_ID.json"
done
unset NEXUS_REVIEW_BINDING_SIGNING_KEY
```

Cette commande requiert `NEXUS_REVIEW_BINDING_SIGNING_KEY` injectée uniquement dans le processus opérateur et un jeton GitHub opérationnel ; elle n'imprime aucune valeur de clé. Le répertoire temporaire doit rester privé et être contrôlé avant incorporation dans un bundle gouverné. **Aucun de ces reçus n'a été produit dans ce lot.** L'assemblage V2 de la PR #327 consommera ensuite exactement les 22 fichiers et vérifiera les signatures, révocations, onze scopes, 253 contenus et 377 liaisons. La commande de #327 n'est pas une preuve réelle tant que ses matériaux n'existent pas.

L'enregistrement éventuel des onze lignes `scope_authorizations` dans une cible qualifiée exige encore la PR **OPEN**, revue et non révoquée : `authorize_scope_cli record-authorization` refuse après fusion. Cette écriture, comme les signatures et tout staging, est hors de ce lot. Il ne faut donc pas merger la PR d'autorisation avant ce contrôle de fermeture. Si A expire avant la review ou le scellement, il faut renouveler l'évidence extérieure, resceller A, régénérer ces onze autorisations puis recalculer le HEAD et le challenge ; aucune prolongation manuelle de `valid_until` n'est admise.

## Vérification locale et état

Venv non contaminé de ce worktree : `scripts/tests/test_build_public_lot41a_authorizations.py` **9/9**, Ruff ciblé vert, `--write` puis `--check` **11/11** sur A 20261011. La CI du nouveau HEAD et toute qualification de staging restent distinctes de cette preuve locale. `CURRENT_AUTHORIZATION_PROPOSALS=11`, `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false`, `REVIEW_BINDINGS_SIGNED=0`, `STAGING_MUTATED=false`, `PRODUCTION_MUTATED=false`.
