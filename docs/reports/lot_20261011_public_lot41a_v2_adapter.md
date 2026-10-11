# Lot 2026-10-11 — assemblage LOT41A-V2 du successeur public

## Périmètre et source

PR #327 rebasée depuis `origin/main` `525db1d34d1e247c512d12d6625a546fd232413e`, arbre `d7380c9927357460c4fc25e02fc920e366a1c72b`, dans un worktree et un venv propres. Aucune écriture staging ou production. Aucun changement de contrat, de scope public ou de verrou de gouvernance. La PR reste draft : aucun HEAD de revue ni autorité signée n'est présumé.

La source préparatoire A actuelle est `docs/reports/go_live/student_public_successor_content_anchor_20261011.json`, SHA-256 `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`. Son manifeste A a pour SHA-256 `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85`. Relecture locale : 11 subjects, 253 dérivés textuels, 377 placements, 3 975 chunks déclarés. L'évidence d'actualité scellée expire le **2026-10-12 à 13:58:41.752 UTC** ; l'assemblage refuse après cette heure. Ces chiffres décrivent A préparatoire, pas un staging ou une production servis.

## Changement

`public_lot41a_adapter.py` projette les 377 placements des onze subjects A avec le lecteur canonique. Il relit les sidecars droits/PII scellés, les 253 identités et URL source Éduscol, les profils et la fenêtre d'actualité. Il exige onze `ScopeAuthorizationArtifactV2` distincts, chacun couvrant exactement son scope et ses contenus, `public_allowed`, le registre PII A, le domaine source et une validité au plus égale à celle de A. Il appelle ensuite l'unique `produce_authorization_set_v2` existant puis `verify_authorization_set_v2` sur les 22 octets d'autorisation et de binding, l'ancre de confiance, les reviewers acceptés et le registre partagé de révocation. Il ne fabrique ni digest d'autorisation, ni review, ni signature.

Le CLI `scripts/go_live/produce_public_lot41a_v2.py` lit les artefacts sous les chemins canoniques, fixe l'ancre et la liste des reviewers gouvernées du dépôt, emploie l'heure UTC courante et le mode `production`. Il écrit les octets canoniques V2 sur stdout **seulement après** vérification complète ; tout refus donne stdout vide et un code non nul. Le CLI n'émet pas de reçu d'approbation GitHub live et ne modifie aucune cible. Le signer final doit continuer à rejouer la revue exacte, les révocations et la DB selon son protocole.

Une même review GitHub exacte peut couvrir les onze artefacts présents dans une seule PR : les onze bindings restent distincts et lient chacun son chemin, ses octets et son identifiant à cette review commune. Le contrat V2 vérifie chacun séparément. Cette possibilité ne constitue pas une review réelle.

## Preuves et état

Les tests TDD du lot sont désormais épinglés à la nouvelle ancre A. Ils démontrent le chemin positif uniquement avec onze signatures de **fixture** et le refus d'une review manquante, des droits internes, d'une preuve PII divergente, d'un domaine étranger, d'une révocation, de l'expiration de A et d'un répertoire de matériau lié par symlink. Le changement d'ancre a d'abord fait échouer le chemin positif sur les dates expirées de la fixture ; la correction des seules dates de fixture l'a rendu vert. Aucun octet de fixture n'est une autorité de production.

Contrôle croisé local avec les onze fichiers exacts proposés dans la PR #329, HEAD `7162b7e8d0a4a4872c05996610cf5bfdfb82c187` : en leur adjoignant uniquement des bindings de **test** signés par la clé synthétique du test, l'assembleur rend `authorization_count=11`, `unique_content_count=253` et `authorization_binding_count=377`. Ce contrôle prouve la compatibilité de format des propositions, sans attester une review GitHub réelle, une signature opérateur, un enregistrement DB ou une publication.

À l'instant de ce rapport, #329 ne porte que onze **propositions** LOT41A publiques ; ses onze bindings signés de production n'existent pas. Le CLI réel refuse donc l'émission. `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false` et `PUBLIC_SUCCESSOR_ACTIVATION_PASS=false`. Il reste à faire approuver les onze artefacts au HEAD/base exacts de #329, produire leurs onze bindings depuis la review réellement vérifiée, puis rejouer le CLI avant l'expiration de A. Si cette échéance passe, renouveler l'évidence extérieure et resceller A avant de préparer ces autorisations. Les scopes publics B émis et les autres preuves C restent des dépendances séparées de l'activation finale ; aucun scope ou verdict C n'est déduit de ce lot.

## Vérification

Dans le venv propre de ce worktree, le test ciblé `packages/release-chain/tests/test_public_lot41a_adapter.py` : **10 tests verts** sur A 20261011. `pytest packages/release-chain/tests -q` : **118 tests verts** après installation du backend `setuptools` requis par les tests de packaging. Ruff ciblé et mypy ciblé avec `MYPYPATH=packages/contracts/src:packages/release-chain/src` : verts. `check-authority-uniqueness.sh` : PASS avec `AUTHORIZATION_V2_PRODUCER=1`. `check-governance-locks.sh` : PASS sur 18 clés. `git diff --check` : vert. Le contrôle croisé local avec les octets #329 rend 11/253/377 avec signatures exclusivement synthétiques. La CI exacte du nouveau HEAD sera consignée après push ; ce rapport ne lui attribue pas un verdict anticipé.
