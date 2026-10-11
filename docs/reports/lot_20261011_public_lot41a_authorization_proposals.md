# Lot — propositions LOT41A-V2 du successeur public

Date UTC : 2026-10-11. Source initiale : `origin/main=96975735a128d0a2ed4a914c35ace5b28d40e4e5`, arbre `b15a2f9b09e2a0be2c938ab5706a0c147044491f`. Rebase après #328 : `origin/main=25605df14773460c8cbed4d71150b50cc0939cec`. Worktree et venv isolés. Ce lot ne modifie ni staging ni production et ne produit aucune revue, signature ou autorisation enregistrée.

## Population et décisions préparées

La première exécution historique du générateur `scripts/go_live/build_public_lot41a_authorizations.py` relisait l'ancre A `docs/reports/go_live/student_public_successor_content_anchor_20261010.json` (SHA-256 `159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0`), son manifeste `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`, ses onze subjects et profils, le registre des 253 dérivés, les 253 entrées de droits et PII, et l'attestation d'actualité liée par A (SHA-256 `4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`). Elle produisait onze `ScopeAuthorizationArtifactV2` pour **377 placements** de A, soit **253 identités uniques**. Ces onze propositions ont été retirées de la PR après l'expiration scellée d'A le `2026-10-11T13:39:22.520Z` ; elles ne sont plus des matériaux de décision courants.

Chaque proposition future portera la portée publique du profil de sa collection, `rights_categories=[public_allowed]`, le domaine `eduscol.education.gouv.fr`, le registre PII scellé de la **nouvelle** A, `pii_absence_attested=true`, et la décision `AUTHORIZE_INGESTION_SCOPE`. Toutes les entrées de droits devront porter `EDUSCOL_ETALAB_2_0_SITEWIDE` ; toutes les entrées PII devront être positives et liées aux mêmes dérivés et PDF sources. Les dates de début et de fin proviendront respectivement de la nouvelle attestation scellée et du nouvel index de préparation. Le générateur refuse après l'expiration sans prolonger la date. Les PDF originaux restent hors des listes positives ; aucun nouveau scope n'est émis par ce lot.

Le CLI exige maintenant explicitement `--anchor-path`, `--anchor-sha256`, `--release-root` et `--currentness-attestation-path` : aucune ancienne identité n'est codée comme valeur par défaut. Il n'écrit les onze propositions qu'avec `--write` et les compare à la nouvelle A avec `--check`. Il refuse une divergence préexistante avant toute écriture. Les tests sur l'A historique contrôlent la dérivation et les refus pour un droit négatif, une preuve PII négative, l'expiration, un placement divergent ou un scope `internal` ; ils ne qualifient pas une nouvelle A encore absente.

Les quatre entrées concrètes manquent encore : chemin et SHA-256 opposable de la nouvelle ancre A, racine immuable de sa release, chemin de l'attestation d'actualité liée par son `preparation-index.json`. Après réception de ces octets, depuis le checkout propre au HEAD courant de cette PR :

```bash
./.venv/bin/python scripts/go_live/build_public_lot41a_authorizations.py \
  --write --anchor-path "$NEXUS_A_ANCHOR" --anchor-sha256 "$NEXUS_A_ANCHOR_SHA256" \
  --release-root "$NEXUS_A_RELEASE_ROOT" \
  --currentness-attestation-path "$NEXUS_A_CURRENTNESS_ATTESTATION"
./.venv/bin/python scripts/go_live/build_public_lot41a_authorizations.py \
  --check --anchor-path "$NEXUS_A_ANCHOR" --anchor-sha256 "$NEXUS_A_ANCHOR_SHA256" \
  --release-root "$NEXUS_A_RELEASE_ROOT" \
  --currentness-attestation-path "$NEXUS_A_CURRENTNESS_ATTESTATION"
```

Les comptes de dérivés et placements seront recalculés depuis cette A. En présence d'un sujet absent, d'une source hors autorité, d'un droit ou contrôle PII non positif, ou d'une expiration, la génération s'arrête sans décision positive.

## Frontière de revue et de signature

Les futurs onze fichiers seront des **propositions**, pas onze autorisations utilisables. La PR qui les portera doit rester ouverte jusqu'au contrôle de fermeture de LOT41A. Le rebase technique sur #328 est fait ; cette PR reste draft tant que la nouvelle A et ses onze propositions manquent. Après leur intégration et une CI verte, elle pourra être rendue prête et recevoir une unique review GitHub `APPROVED` de `abenrhouma` sur son HEAD/base/challenge exacts. Le vérificateur canonique refuse une PR draft, fermée ou à HEAD divergent. Le contexte `trusted-human-review/head-pinned` doit être `success` avant tout usage. Une seule review peut couvrir les onze blobs de la même PR, mais chacun exige son propre `ScopeAuthorizationReviewBindingV1` signé, avec son chemin, SHA-256 et Git blob SHA-1 exacts.

Le chemin de scope V3 actuel ne peut pas être rejoué sur la nouvelle A avec la seule review #294 : `pr294_scope_review_receipt.FILES["anchor"]` lie la review fusionnée aux octets de l'ancre `20261010`, et `emit_student_public_scopes.verify_live_scope_policy_review` exige ce chemin et son SHA inchangés dans le HEAD revu. Une nouvelle ancre et de nouveaux `subject_sha256` nécessitent une autorité de scope revue pour ces nouveaux octets avant émission B. Changer seulement le paramètre de l'émetteur ne résout pas ce blocage.

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

Venv isolé de ce worktree : suite `packages/release-chain/tests` **107 réussites** avant l'expiration d'A. Sur l'ancien HEAD de #329, les sept tests initiaux et la CI standard 14/14 ont passé. Après rebase #328, deux tests CLI ont d'abord échoué sur les valeurs figées puis passé avec l'interface explicite ; la suite ciblée rend **9 réussites**, Ruff passe et `--check` sur l'ancienne A refuse `currentness expired`. La suite élargie rend 115 réussites et un échec temporel : `test_content_anchor_without_final_envelope_cannot_activate` attend `authority envelope` mais reçoit l'expiration d'A. Cet échec identique a été reproduit sur un worktree détaché propre de `origin/main=25605df` et son venv distinct ; sa correction est hors de #329. Les onze anciens fichiers sont retirés ; aucune vérification `--write/--check` sur une nouvelle A n'est encore possible. Ces résultats locaux ne valent pas CI du nouveau HEAD ni qualification staging. `CURRENT_AUTHORIZATION_PROPOSALS=0`, `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false`, `REVIEW_BINDINGS_SIGNED=0`, `STAGING_MUTATED=false`, `PRODUCTION_MUTATED=false`.
