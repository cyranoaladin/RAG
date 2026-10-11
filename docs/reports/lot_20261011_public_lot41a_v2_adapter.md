# Lot 2026-10-11 — assemblage LOT41A-V2 du successeur public

## Périmètre et source

Branche créée depuis `origin/main` `fa8292c0254f16fe6fce8db40148b7edac733c6d` dans un worktree propre. Aucune écriture staging ou production. Aucun changement de contrat, de scope #294 ou de verrou de gouvernance.

La source préparatoire A est `docs/reports/go_live/student_public_successor_content_anchor_20261010.json`, SHA-256 `159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0`. Le manifeste A a pour SHA-256 `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`. Relecture locale au SHA de branche : 11 subjects, 253 dérivés textuels, 377 placements, 3 975 chunks déclarés. L'évidence d'actualité scellée expire le **2026-10-11 à 13:39:22.520 UTC** ; l'assemblage refuse après cette heure. Ces chiffres décrivent A préparatoire, pas un staging ou une production servis.

## Changement

`public_lot41a_adapter.py` projette les 377 placements des onze subjects A avec le lecteur canonique. Il relit les sidecars droits/PII scellés, les 253 identités et URL source Éduscol, les profils et la fenêtre d'actualité. Il exige onze `ScopeAuthorizationArtifactV2` distincts, chacun couvrant exactement son scope et ses contenus, `public_allowed`, le registre PII A, le domaine source et une validité au plus égale à celle de A. Il appelle ensuite l'unique `produce_authorization_set_v2` existant puis `verify_authorization_set_v2` sur les 22 octets d'autorisation et de binding, l'ancre de confiance, les reviewers acceptés et le registre partagé de révocation. Il ne fabrique ni digest d'autorisation, ni review, ni signature.

Le CLI `scripts/go_live/produce_public_lot41a_v2.py` lit les artefacts sous les chemins canoniques, fixe l'ancre et la liste des reviewers gouvernées du dépôt, emploie l'heure UTC courante et le mode `production`. Il écrit les octets canoniques V2 sur stdout **seulement après** vérification complète ; tout refus donne stdout vide et un code non nul. Le CLI n'émet pas de reçu d'approbation GitHub live et ne modifie aucune cible. Le signer final doit continuer à rejouer la revue exacte, les révocations et la DB selon son protocole.

Une même review GitHub exacte peut couvrir les onze artefacts présents dans une seule PR : les onze bindings restent distincts et lient chacun son chemin, ses octets et son identifiant à cette review commune. Le contrat V2 vérifie chacun séparément. Cette possibilité ne constitue pas une review réelle.

## Preuves et état

Les tests TDD du lot démontrent le chemin positif uniquement avec onze signatures de **fixture** et le refus d'une review manquante, des droits internes, d'une preuve PII divergente, d'un domaine étranger, d'une révocation, de l'expiration de A et d'un répertoire de matériau lié par symlink. Aucun octet de fixture n'est une autorité de production.

À l'instant de ce rapport, les onze autorisations LOT41A publiques et leurs bindings signés de production n'existent pas dans A. Le CLI réel refuse donc l'émission. `AUTHORIZATION_SET_V2_PUBLIC_ISSUED=false` et `PUBLIC_SUCCESSOR_ACTIVATION_PASS=false`. Il reste à faire approuver au HEAD exact les onze artefacts individuels dans une PR gouvernée, produire leurs onze bindings depuis la review réellement vérifiée, puis rejouer le CLI avant l'expiration de A. Si cette échéance passe, renouveler l'évidence extérieure et resceller A avant de préparer ces autorisations. Le scope public #294 et les autres preuves C restent des dépendances séparées de l'activation finale ; aucun scope ou verdict C n'est déduit de ce lot.

## Vérification

Dans le venv propre de ce worktree, `pytest packages/release-chain/tests` : **117 tests verts**. Ruff et mypy ciblés verts. `check-authority-uniqueness.sh` passe avec les nouveaux fichiers dans l'index et conserve `AUTHORIZATION_V2_PRODUCER=1` ; `check-governance-locks.sh` passe sur 18 clés inchangées. La CI exacte de la PR reste à consigner après ouverture et push.
