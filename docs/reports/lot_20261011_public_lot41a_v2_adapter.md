# Lot #327 — LOT41A-V2 lié à la continuité A2

## Identité et état

Base locale : `origin/main=0f1c359377a5ab428fc777e0a70b4748639793a9`, arbre `0573c84a86099e5ee3b8b385f1b094500e8bf960`, après fusion de #332. Le HEAD distant de #327 `d5783c302efb353c8712fb56232cb58ada2f5630` a été réappliqué, puis le commit A2 `52f88221a1f86a5a74d111c920f9daf3efd5876f` intégré. Le HEAD définitif et la CI seront constatés après revue du diff et push. Aucun transfert, ingestion, staging ou production n'a été modifié.

`LOT41A_A2_PROPOSALS_PASS=true` ; `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false` ; `A2_CONSUMED_BY_C=false` ; `PUBLIC_SUCCESSOR_ACTIVATION_PASS=false` ; `PUBLICATION_AUTHORIZED=false`. Les onze bindings signés, leurs enregistrements DB et le pulse C restent absents.

## Contenu A1 et autorité A2

A1 conserve l'ancre SHA-256 `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`, la release `student-public-successor-20261010-40b956c6f5ec0c60` et le manifeste `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85` : **11 collections, 253 dérivés textuels, 377 placements, 3 975 chunks**. A2 a le SHA-256 `5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4`, une validité du 11 octobre `21:54:37.014823 UTC` au 18 octobre `21:54:37.014823 UTC`, et les huit invariants de continuité vrais : contenu, manifeste, CAS, droits, PII et exclusions inchangés ; CFTR exclu ; seules les autorités temporelles changent.

Le producteur A2 a été rejoué dans ce worktree depuis les captures privées Chromium/PDF, les 253 preuves d'actualité/révocation, le CAS privé et le paquet #300. Les octets reconstruits de l'autorité et du rapport sont identiques aux fichiers versionnés : SHA-256 `5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4` et `5d35864de48f5235b819744a2b736edce28b01d806072979697ac69454f62a89`. Attestation source privée : SHA-256 `f19ea43406a6eb3994be1620f9c31200e5963c3b395a92ad6e3d5f50058c8e84`. Ce rejeu n'est pas un nouveau constat C. La feuille finale #300, SHA-256 `d9d37f3f1d78b269c011281fb1d671fe8ddb62184b3066c72fe675fa16970d12`, porte CFTR `EXCLUDE` ; le paquet préparatoire antérieur ne fait pas autorité sur ce verdict.

## Onze propositions et adaptateur

Le générateur conserve son chemin A1 historique et ajoute un chemin A2 explicite. Celui-ci vérifie l'empreinte scellée d'A2, l'ancre A1, les identités du contenu, la politique et au moins 24 heures de validité résiduelle. Droits, PII, domaine Éduscol, profils et placements sont relus sur A1. Onze nouveaux IDs `lot41a-student-public-*-v2` sont produits sans modifier les anciens `-v1` : visibilité `public`, droit `public_allowed`, dates exactes A2, union de 253 SHA et somme de 377 placements. Les propositions ne contiennent ni review ni signature. Le CLI `--check` a rendu `PROPOSALS=11 REVIEW_BINDINGS=0`.

L'adaptateur refuse de traiter des IDs `-v1` comme renouvellement A2. Il exige onze `-v2` et les dates exactes A2, puis conserve le contrôle de onze bindings distincts et `verify_authorization_set_v2`. Le CLI peut recevoir A2 mais garde stdout vide et un code non nul sans bindings signés réels. Aucun opérateur humain n'est présenté comme ayant approuvé ces propositions à ce stade.

## Cible, plan et binding

Le producteur canonique de pin V1 inchangé (code SHA-256 `4451add6d77a607a1b06f24c2052ef81b689c27e5986c84a917cf20bfa66f1b4`) a capturé en lecture seule, le 11 octobre à `23:47:31.927082 UTC`, la cible dédiée `korrigo` : conteneur Docker `5fe53fb652d8876d4e0701f58a7fdb0b145c93ae733d0e80ad2a89adce19131e`, DB `ragdb_student_public_qual` (system ID `7695463567278473254`), répertoire `/srv/nexus-public-qual-20261011/servable-text`. Le nouveau pin SHA-256 `1bbbe72d0809e5cd77a7e53bba85d26ba286b74e799b055923d9c3a920517d72` expire le 12 octobre à `23:47:31.927082 UTC`. La capture est non approuvée ; elle n'a écrit ni dans la DB ni dans ce répertoire.

Le plan V1 sous son nouveau chemin A2 reste **octet pour octet identique** au plan release40b, SHA-256 `212385841d6966875f8f20567378bbfeb9afa18f308da4faaf763bd0ee8ee19c` : CAS, inventaire, allowlist, release ID, 253 textes, 253 reçus et 377 placements sont inchangés. Il reste `PLANNED_NOT_TRANSFERRED`. La nouvelle liaison est l'objet `public_successor_a2_transfer_binding_20261012.json`, SHA-256 `6b8f744c1748b4614cc84cc1a572535430035789d6f4717e058e4d62577de661`, qui scelle A2, pin, plan, A1 et release. Son statut est `REVIEW_CANDIDATE_NOT_AUTHORIZED`. Le vérificateur rejette substitution de digest, population différente et expiration ; il ne remplace pas l'observation live du pin, le rejeu CAS du plan ou la révocation C.

## Vérifications et conditions suivantes

Venv propre dédié à ce worktree : `nexus-lot41a-a2-main0f1`, avec les packages locaux contracts, release-chain et pdf-page-policy. Les tests TDD ont échoué avant correction sur le chemin A2, le réemploi des IDs V1, le CLI A2 et le binding. Vérification après correction : `pytest packages/release-chain/tests -q` **156/156**, `pytest scripts/tests/test_build_public_lot41a_authorizations.py -q` **11/11**, Ruff ciblé, mypy ciblé et `git diff --cached --check` verts. Les 18 verrous de gouvernance sont inchangés ; `check-authority-uniqueness.sh` est vert après ajout explicite des deux nouveaux fichiers de code à l'index Git (`UNTRACKED_CODE_FILES_INVISIBLE=0`).

Le pack doit être gelé au HEAD exact de #327 avant review. Après review valide : produire onze bindings signés distincts depuis ce HEAD, les enregistrer en DB, puis relire en direct le même pin sur la même cible avant merge. Un changement de HEAD, de parent de merge ou l'expiration du pin impose un nouveau pack et une nouvelle review. C doit encore consommer sémantiquement A2 et le binding, rejouer un pulse privé post-A2 sur les 253 sources/révocations et contrôler scopes B, DB, transfert et readiness. Aucun de ces prérequis C n'est déclaré vert ici.
