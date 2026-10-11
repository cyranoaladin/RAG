# Lot A2 — Continuité temporelle du successeur public

Statut du lot : **preuve temporelle A2 préparée, non consommée par C**. Base du worktree propre : `origin/main` `7cf15f1516d542636f7d839f9371018e09e27b60`. Aucune écriture de base, staging ou production.

L'ancre de contenu A1 approuvée est `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`, release `student-public-successor-20261010-40b956c6f5ec0c60`. Le manifeste reste `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85`, le CAS privé `1ad82df91bfbc28a62a01f1c2dd5af45891d4035994206409e3d2ecee19c25d4`, le registre de droits `34c1887133878c2fe622cc17334ddadaf5357e8d5491dfbcdfe6df1f5cee44f5` et le registre PII `fcecdcf80539a4e5a4e163fea46b24f3f4793fc26f91abe7e52f0cab4cb9a918`.

Le nouveau constat source privé, capturé le 11 octobre 2026, comprend 15/15 pages-listes HTTP 200 et 315 sources : 296 identités courantes exactes et 19 sources non prouvées, hors des 253 admises. L'attestation liée aux 253 dérivés est `f19ea43406a6eb3994be1620f9c31200e5963c3b395a92ad6e3d5f50058c8e84` ; son index source est `ba826c1ce0d590f813aa8dcfe584327544fe5e18245507157684fa0964490209`. Le rejeu privé exact par le producteur a rendu `253/253 PASS`. Le pack privé stable `nexus-a2-source-revalidation-20261011-main7cf` reste hors Git ; son rapport source est `43aea8d9508eeb60614a355fa9bb604db91230393e2ebae0f765f17b44b4028a`.

L'autorité A2 [`student_public_successor_temporal_continuity_a2_20261011_v2.json`](go_live/student_public_successor_temporal_continuity_a2_20261011_v2.json) a le SHA-256 `5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4`. La politique [`public_successor_temporal_policy_a2_v1.yml`](../../governance/student_public_rights/public_successor_temporal_policy_a2_v1.yml) a le SHA-256 `13a9f27279c552968326920f9186735eeb55cc0f248a1094eb428ce15df8577c`. Le rapport machine [`student_public_successor_temporal_continuity_a2_20261011_v2_report.json`](go_live/student_public_successor_temporal_continuity_a2_20261011_v2_report.json) a le SHA-256 `5d35864de48f5235b819744a2b736edce28b01d806072979697ac69454f62a89`.

`issued_at_utc=valid_from_utc=2026-10-11T21:54:37.014823Z` ; `valid_until_utc=2026-10-18T21:54:37.014823Z`. La politique exige encore au moins 24 heures résiduelles et un nouveau constat indépendant de source/révocation au temps C. L'autorité A2 elle-même ne prolonge pas l'ancien reçu A1 de 24 heures.

Les huit invariants demandés ont été recalculés par comparaison des octets A1 et de la population source approuvée #300 :

```text
CONTENT_SET_UNCHANGED=true
MANIFEST_UNCHANGED=true
CAS_INDEX_UNCHANGED=true
RIGHTS_REGISTRY_UNCHANGED=true
PII_REGISTRY_UNCHANGED=true
EXCLUSION_SET_UNCHANGED=true
CFTR_STILL_EXCLUDED=true
ONLY_TEMPORAL_AUTHORITIES_CHANGED=true
```

Population : `11 collections / 253 dérivés textuels / 377 placements / 3 975 chunks`. L'ensemble exact des 253 couples dérivé/PDF a l'empreinte `90ae79f6e667775700ba6afceda3270acc79ed633aba8bb72c59310531329fc5`. Les 62 sources exclues, calculées comme différence entre l'inventaire #300 approuvé de 315 sources et les 253 sources A1, ont l'empreinte `5dc39e54c17b208599a9a26bad42e5db22290e35682f8469af4166e603349913`. CFTR reste dans ces exclusions.

Les tests ciblés couvrent refus de l'ancien rapport A1, source manquante/dupliquée/dérivée, source ou URI changée, reçu de dérivé changé, révocation, preuve de page absente, CFTR, date falsifiée, inventaire #300 changé, ancre A1 alternative, pulse C identique, horizon expiré et digest d'autorité modifié. Lint et tests sont verts dans un environnement Python propre propre à ce worktree.

`A2_CONSUMED_BY_C=false` et `PUBLICATION_AUTHORIZED=false`. La PR #327 doit intégrer le vérificateur A2 et refaire 11 autorisations versionnées avec bindings signés, scopes B et pin/plan selon leurs protocoles. Le consommateur C doit rejouer le nouveau pack privé C avant d'appeler `verify_temporal_successor`. Une preuve de maintien/retrait en cas de révocation après activation reste à mettre en place. Le constat provisoire antérieur `8d2263…`, dépourvu de `valid_from_utc`, a été conservé uniquement comme diagnostic privé et n'entre pas dans cette PR.
