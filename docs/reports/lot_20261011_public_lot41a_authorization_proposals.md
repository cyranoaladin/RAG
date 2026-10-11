# Lot — propositions LOT41A-V2 du successeur public

Date UTC : 2026-10-11. Source : `origin/main=96975735a128d0a2ed4a914c35ace5b28d40e4e5`, arbre `b15a2f9b09e2a0be2c938ab5706a0c147044491f`, dans un worktree propre et un venv propre. Ce lot ne modifie ni staging ni production et ne produit aucune revue, signature ou autorisation enregistrée.

## Population et décisions préparées

Le générateur `scripts/go_live/build_public_lot41a_authorizations.py` relit l'ancre A `docs/reports/go_live/student_public_successor_content_anchor_20261010.json` (SHA-256 `159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0`), son manifeste `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`, ses onze subjects et profils, le registre des 253 dérivés, les 253 entrées de droits et PII, et l'attestation d'actualité liée par A (SHA-256 `4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`). Il dérive de ces octets onze `ScopeAuthorizationArtifactV2` sous `governance/authorizations/lot41a-student-public-*-v1.json`. Aucune liste positive de contenus n'est ressaisie à la main : les onze listes sont les identités des **377 placements** de A, soit **253 identités uniques**.

Chaque autorisation porte la portée publique du profil de sa collection, `rights_categories=[public_allowed]`, le domaine `eduscol.education.gouv.fr`, le registre PII scellé de A, `pii_absence_attested=true`, et la décision `AUTHORIZE_INGESTION_SCOPE`. Les 253 entrées de droits doivent toutes porter `EDUSCOL_ETALAB_2_0_SITEWIDE`; les 253 entrées PII doivent toutes être positives et liées au même dérivé et PDF source. La date de début provient de l'attestation scellée : `2026-10-10T13:49:12Z`. La fin est celle d'A : **`2026-10-11T13:39:22.520Z`**. Le générateur refuse après cette fin, sans la prolonger. Les PDF originaux restent hors des listes positives ; aucun nouveau scope n'est émis par ce lot.

Le générateur n'écrit les onze propositions qu'avec `--write` et les compare à A avec `--check`. Il refuse une divergence préexistante avant toute écriture. Les tests réels de ce lot contrôlent la population exacte de chaque collection, les champs canoniques, l'absence de prétendue review et les refus pour un droit négatif, une preuve PII négative, l'expiration, un placement divergent ou un scope `internal`.

## Frontière de revue et de signature

Les onze fichiers sont des **propositions**, pas onze autorisations utilisables. La PR qui les porte doit rester ouverte jusqu'au contrôle de fermeture de LOT41A. Après la fusion du correctif technique post-#294, cette PR devra être rebasée sur le nouveau `main`, rendue prête une fois sa CI verte, puis recevoir une unique review GitHub `APPROVED` de `abenrhouma` sur son HEAD/base/challenge exacts. Le vérificateur canonique refuse une PR draft, fermée ou à HEAD divergent. Le contexte `trusted-human-review/head-pinned` doit être `success` avant tout usage. Une seule review peut couvrir les onze blobs de la même PR, mais chacun exige son propre `ScopeAuthorizationReviewBindingV1` signé, avec son chemin, SHA-256 et Git blob SHA-1 exacts.

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

## Vérification locale

Venv isolé de ce worktree : suite `packages/release-chain/tests` **107 réussites** au départ. Tests du générateur **7 réussites**, dont quatre sabotages droits/PII/placement/visibilité et un refus d'expiration ; Ruff ciblé vert ; `--write` puis `--check` rendent onze propositions et zéro binding. Ces résultats sont locaux et ne valent pas CI de la PR ni qualification staging. `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false`, `REVIEW_BINDINGS_SIGNED=0`, `STAGING_MUTATED=false`, `PRODUCTION_MUTATED=false`.
