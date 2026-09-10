# Lot — candidats d’autorisation production 2026-2027

## Résultat

Le producteur relit exclusivement les blobs du commit `main`
`3566cafb44138d6a7f00296dc0654257f9bf0ad6`, tree
`8c5081a52096d531f1bd027790e600eb83b05bd5`. Il construit 18
`ScopeAuthorizationArtifactV2` qui partitionnent exactement les 26 contenus
finaux.

```text
AUTHORIZATION_CANDIDATE_COUNT=18
AUTHORIZATION_CANDIDATE_CONTENT_UNION=26
AUTHORIZATION_CANDIDATE_OVERLAP=0
AUTHORIZATION_CANDIDATE_GAP=0
AUTHORIZATION_CANDIDATE_EXTRA=0
AUTHORIZATION_CANDIDATE_UNION_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
AUTHORIZATION_CANDIDATES_MATERIALIZED=true
AUTHORIZATION_CANDIDATE_REPLAY_CHECK=true
```

Les artefacts sont sous `governance/authorizations/`. La matrice exhaustive
est `docs/reports/production_authorization_matrix_20260825.json`, SHA-256
`9ac6a4fb4959dac8449ea418d4d92151e18f823a523e5f85b80791176cacfa74`.
Chaque ligne porte la liste triée des contenus, son digest, le scope et son
digest, le profil exact, le subject release exact ainsi que les paths et
digests droits, PII et currentness.

## Topologie des preuves

Le modèle V2 existant est conservé sans ajout de champ ni protocole. Les
preuves communes restent liées par le HEAD intégral de la future review :

```text
PROFILE_MANIFEST_DIGEST=57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c
RELEASE_SCOPE_PLACEMENT_SHA256=b1a36aef251d05f0098bfe88d7eae45b36333452f1613741e15dc6a89de75315
CORPUS_MANIFEST_SHA256=d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e
PII_EVIDENCE_SHA256=cec9baca680439afa0dd6b4aadbb0f805514424a853a10303e6216dd8ffa7e99
CURRENTNESS_EVIDENCE_SHA256=822677cb14987f1069ff849241e33d6f7c9fb66425a5d00c3e38d71b592b793c
CURRENTNESS_AUDIT_SHA256=4c6395e3ce4c9a61a0d3a8a3b7f94da75ba91b00419c3f0c042f2d2e7adcf520
RIGHTS_EVIDENCE_SHA256=e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff
```

Le producteur enregistre 43 blobs d’entrée avec leur Git object ID et leur
SHA-256. Il refuse les replace refs, les chemins non littéraux, les digests
mutés, les gaps/overlaps/extras, les profils ou collections dérivés, les
preuves PII partielles, les sources currentness substituées et les droits non
approuvés. Les écritures utilisent des descripteurs de répertoire
`O_NOFOLLOW`, des fichiers temporaires locaux et `os.replace`; un ancêtre
symlinké est refusé.

## Vérifications du lot

```text
pytest tests/test_production_authorization_candidates.py = 40 passed
pytest packages/contracts/tests = 467 passed
pytest services/rag-pedago = 2848 passed, 2 skipped
pytest rag-engine profile/release-scope = 170 passed
ruff targeted = pass
mypy targeted = pass
ruff rag-pedago/rag-engine = pass
mypy rag-pedago/rag-engine = pass
write replay = pass
check replay = pass
missing output refused = true
modified output refused = true
extra output refused = true
symlinked ancestor refused = true
governance locks + mutation tests = pass
repository controls + failsafe mutations = pass
gitleaks differential 3566caf..HEAD = no leaks found
```

La CI GitHub est consignée après son exécution sur le HEAD de PR figé.

## Statut d’autorité

Ces fichiers sont des candidats non effectifs : aucune identité GitHub n’est
simulée et aucune clé privée n’est utilisée dans ce lot.

```text
REAL_AUTHORIZATIONS_CREATED=false
EFFECTIVE_AUTHORIZATION_COUNT=0
SIGNED_REVIEW_BINDING_COUNT=0
REAL_AUTHORIZATION_SET_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
```

La PR d’autorité doit rester ouverte et son HEAD immuable pendant toute la
validité. Après sa vraie review exact-head, les 18 `ReviewBinding` seront
émis depuis un checkout détaché propre du producteur de confiance, avec la clé
détenue uniquement par l’opérateur.
