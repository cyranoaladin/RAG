# Lot 2026-10-10 — diagnostic externe du successeur public

## Point de départ et portée

Branche isolée créée après `git fetch origin`, depuis le HEAD exact de la PR #313
`f30d0ceb8dfbe11b3c3db033ae00bb83164da033` (tree
`e52962c30806dfd0ae5b69bb9366642c46c8e146`). Environnement Python
nouveau, avec `nexus-contracts` et `nexus-release-chain` installés depuis ce
worktree. Aucune écriture staging ou production, aucun transfert, aucun changement
de Worker A, aucune release finale créée par ce lot.

L'ADR-0070 exige 21 autorités pour `release_mode=public_successor`, puis le
lecteur `release-chain` et Worker A refusent encore cette release. Le script
`check_public_successor_external_gate.py` apporte un **diagnostic de liaison en
lecture seule**. Il ne lève aucun des deux refus. Même lorsque les 21 fichiers
possèdent les SHA déclarés **et que les preuves fournies passent leurs contrôles
disponibles**, la sortie porte
`PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS=false`, `PROMOTION_ALLOWED=false`,
`semantic_verification_complete=false` et le processus sort avec code 1.
`--assert-ready` sort également avec code 1. Une erreur de structure ou de
digest sort avec code 2. Aucun code de sortie 0 n'est possible dans cette
version.

## Contrôles opposables maintenant

Le manifeste final est exigé par digest externe fourni à la commande. Le
parseur canonique valide son mode, son identité neuve, ses 21 champs exacts,
les sujets, profils, placements publics, artefacts textuels, chunks et comptes ;
le diagnostic exige ensuite son refus terminal explicite. Une réussite
inattendue du parseur serait elle-même refusée.

Le diagnostic relit dans `source_preparation/` les octets exacts du manifeste
préparatoire, de l'index et de l'inventaire. Il vérifie les SHA, les statuts
`candidate/NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`, les références
index → manifeste/inventaire/registre et la distinction entre le manifeste
candidat #312 et le manifeste préparatoire #313. Il vérifie ensuite que
l'inventaire final nomme le préparatoire, que ses collections restent toutes
non vides, que chaque dérivé/placement provient du même inventaire source et
que sa population et ses identités correspondent au registre final. Un fichier
de preuve optionnel par autorité est contrôlé par SHA. La feuille d'inclusion
#313, lorsqu'elle est fournie, subit aussi le contrôle de population ci-dessous ;
les autres fichiers optionnels restent des vérifications d'octets seulement.

La feuille `inclusion_attestation_sha256` est maintenant ouverte. Son SHA doit
égaler les deux références de l'index préparatoire scellé. Le diagnostic compare
ses autorités de candidat, droits, PII, actualité et CAS à celles de cet index,
recalcule le digest de ses 253 décisions, exige une décision finale unique par
SHA du préparatoire, confronte chaque PDF source et chaque empreinte de preuve,
puis exige que l'ensemble `INCLUDE` soit exactement celui de l'inventaire
final. Le résultat `preparation_inclusion_population_verified=true` ne décrit
que ce lien de population. Sans l'option de rejeu privé, il ne valide ni les
octets privés du CAS, ni les rapports PII/actualité sous-jacents, ni leur
fraîcheur au moment de promouvoir, ni les droits, scopes ou revues ; les 21 champs demeurent dans
`semantic_unverified_authorities` et le gate reste rouge. En l'absence de la
feuille dans `--evidence-map`, ce nouvel indicateur reste `false`.

La revue indépendante de la première version a révélé que
`preparation_chain_verified=true` pouvait encore apparaître après duplication
d'un candidat final ou renommage concerté d'une collection dans les deux
inventaires, alors que les sujets canoniques gardaient l'ancien nom. La garde
exige maintenant l'unicité des SHA par collection, l'égalité des onze noms
avec les sujets du manifeste et l'égalité exacte des couples
`(artifact_id, source_placement_id)` entre l'inventaire final et chaque sujet.
Les deux sabotages ont été observés rouges avant le correctif puis verts.

La re-revue a identifié un troisième cas : l'inventaire préparatoire pouvait
déclarer un SHA supplémentaire sans changer le final, et
`preparation_chain_verified=true` restait affiché. L'ADR-0070 autorise
explicitement « 253 ou moins » dérivés finaux ; imposer l'égalité des
populations aurait transformé une exclusion gouvernée légitime en erreur de
schéma. La sortie distingue donc maintenant le **lignage de sous-ensemble**
(`preparation_subset_lineage_verified`) de l'égalité de population
(`preparation_chain_verified`). Tout retrait est énuméré par collection et SHA
dans `unreconciled_preparation_exclusions`, et l'indicateur complet reste
`false` tant qu'aucune preuve sémantique d'exclusion n'est disponible. Le
sabotage source 7/final 6 a été rouge avant cette correction puis produit
`preparation_chain_verified=false` ; le gate de promotion demeure rouge.

Ces contrôles ne démontrent pas que l'ancien candidat #312, les inclusions, les
droits, les revues ou les octets transférés sont valides **aujourd'hui**. Les
trois fichiers préparatoires présents dans le paquet final ne contiennent pas
les sujets et le registre préparatoires complets ; leur chaîne locale ne vaut
pas une relecture autonome de toute la PR #313 ni une approbation au HEAD exact.
La sortie `semantic_unverified_authorities` énumère donc toujours les 21 champs.

## Contrôles sémantiques encore absents

Avant tout verdict de promotion, un lot distinct devra définir les formats de
reçu et des vérificateurs qui ouvrent les preuves, avec population et identité
exactes :

| Autorités | Vérification requise |
| --- | --- |
| `source_candidate_release_manifest_sha256`, `inclusion_attestation_sha256` | Le rejeu privé facultatif ouvre le candidat #312 et les preuves privées de #313. Il faut encore vérifier les exclusions gouvernées et la validité temporelle au moment de la promotion finale. |
| `derivative_pii_evidence_sha256`, `derivative_currentness_evidence_sha256` | Rejouer les preuves fraîches sur chaque dérivé final ; refuser une preuve périmée ou une identité remplacée. |
| `public_profile_manifest_sha256`, `public_scope_authority_sha256`, `exact_head_scope_review_receipt_sha256` | Les onze profils préparatoires #313 sont relus avec le rejeu privé ; il faut encore ouvrir les profils/scopes **finaux**, vérifier l'identité student/public et lire la review GitHub canonique au HEAD/base exacts. |
| `public_rights_registry_sha256`, `public_pii_registry_sha256`, `rights_authority_sha256`, `delegated_evidence_pack_sha256`, `pr300_final_authority_receipt_sha256` | Relier chaque dérivé à la preuve #300, aux conditions Etalab, à l'attribution et aux exclusions ; revérifier l'autorité approuvée. |
| `authorization_set_sha256`, `exact_head_authorization_review_receipt_sha256` | Vérifier les onze autorisations LOT41A au scope final et leur approbation GitHub exacte. |
| `publication_batch_review_receipt_sha256` | Vérifier le batch LOT42 sur les 377 placements ou les nouveaux comptes réels et son absence de révocation. |
| `artifact_transfer_manifest_sha256`, `observed_transfer_receipt_sha256` | Le diagnostic peut désormais relire plan et reçu #320, confronter leur population à l'inventaire final et re-hacher toute la destination. Il manque encore une qualification indépendante de l'identité de cible avant d'en faire une autorité de promotion. |
| `revocation_evidence_sha256` | Interroger l'état courant des révocations pour toutes les autorités pertinentes. |

Les trois autres champs (`source_preparation_release_manifest_sha256`,
`source_preparation_index_sha256`, `candidate_inventory_sha256`) bénéficient de
la vérification de chaîne locale décrite ci-dessus, mais restent dans la liste
globale des autorités non pleinement validées tant que leur source et le HEAD
approuvé ne sont pas vérifiés. Aucun simple fichier JSON `{}` au bon SHA ne
répond à ces exigences.

## Vérification

Cycle TDD : import absent (rouge), implémentation minimale (vert), puis sabotage
rouge/vert d'un inventaire final rescéllé qui omet un artefact du registre, et
sortie CLI rouge par défaut. Les tests refusent également le mode candidat, la
modification de l'index préparatoire, un fichier de preuve de mauvais SHA et
une clé d'autorité inconnue. Une fixture qui fournit des octets au bon SHA pour
les 21 champs reste bloquée sur la sémantique.

Le 2026-10-10 vers 15:05 UTC : 17 tests ciblés verts (`scripts/tests` et
`packages/release-chain/tests/test_public_successor_readiness.py`), Ruff vert,
`git diff --check` vert. Les nombres 11/253/377/3975 rencontrés dans les tests
proviennent de la **fixture préparatoire #313**, pas d'un staging final. Le
verdict réel demeure `PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS=false`,
`STAGING_FINAL_PASS=false`, `GO_LIVE_READY=false` et
`RAG_PRODUCTION_DEPLOYED=false`.

Après correction de revue, la suite ciblée compte 19 tests réussis ; Ruff et
`git diff --check` passent encore. Le verdict de promotion reste inchangé.
Après re-revue, 20 tests ciblés passent avec le cas source-seul ; aucun compte
final n'est forcé à 253.

Après fusion de #313, le 10 octobre à 15:34 UTC, la branche a intégré
`origin/main=829bc9acec1eeb17dc9800389c92102b6f2c2297` par merge sans
réécriture de son historique distant. Le seul conflit, dans le rapport de
#313, a été résolu en conservant la version fusionnée sur main ; le delta de
#319 reste limité au présent rapport, au diagnostic et à ses tests. Un venv
isolé Python 3.12 pointe exclusivement vers les paquets de ce worktree.
Les 20 tests ciblés passent en 2,85 s, Ruff passe sur les deux fichiers Python
et `git diff --check` est vert. Le contrôleur reste en refus terminal ; aucune
preuve de staging final ou de promotion n'a été créée.

Après fusion de #316, la branche a intégré
`origin/main=b93c83a0031946fae72e0d519ef42a10befa2fea` sans force-push.
Le cycle TDD a d'abord mis en rouge quatre cas de feuille d'inclusion
rescélée (lien positif absent, mauvais PDF source, dérivé exclu encore présent,
empreinte de preuve altérée), puis deux cas d'autorité manquante ou d'index
contradictoire. Le contrôle ciblé les refuse à présent. **26 tests ciblés**,
Ruff et `git diff --check` passent dans le venv propre du worktree. Il ne
s'agit toujours pas d'une preuve de staging final ni d'une autorisation de
promotion.

Après fusion de #318, la branche a intégré
`origin/main=8b82b7c233a42762becf8080423e52efa844a635`. L'option explicite
`--private-cas-root` exige également `--repository-root` et la feuille
d'inclusion scellée. Elle réutilise les contrôles existants des approbations
#300 et #312, la lecture du candidat source et le rejeu intégral du CAS privé ;
le résultat recalculé doit être identique à la feuille fournie et au digest
nommé par le manifeste final. Une panne GitHub, un CAS manquant, un candidat
différent ou une feuille substituée provoque un refus, sans repli. Sans ces
arguments, `preparation_private_cas_replay_verified=false`.

Un rejeu local en lecture seule du CAS privé existant sur une **fixture de
manifeste final**, construite à partir du préparatoire #313, a pris 15,1 s et
retourné `preparation_inclusion_population_verified=true` et
`preparation_private_cas_replay_verified=true`. Il ne prouve pas qu'un vrai
manifeste final, un transfert observé ou des scopes/revues finaux existent.
Le même résultat conserve `semantic_verification_complete=false`,
`PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS=false` et `PROMOTION_ALLOWED=false`.

La branche vérifie désormais, après ce rejeu privé, les trois registres
préparatoires #313 (droits, PII, actualité) et les onze profils complets.
Chaque registre est relu sous le digest de l'index et, lorsque applicable,
de l'agrégat préparatoire. Ses 253 lignes uniques sont recoupées avec les
décisions rejouées et le registre d'artefacts : PDF source, reçu dérivé,
citation, preuve PII, preuve d'actualité, statut de révocation et restrictions
d'usage. Les onze profils doivent concorder avec leurs références, octets
YAML, scopes publics et empreintes. Un test rouge/vert a révélé qu'un profil
YAML `internal` rescéllé pouvait auparavant échapper au contrôle ; il est
maintenant refusé. Huit sabotages ciblent également registre, preuve, doublon
et profil. **29 tests ciblés** et Ruff passent. Un nouveau rejeu local en
lecture seule du CAS privé v4 sur la fixture finale a pris 16,6 s et retourne
`preparation_registries_verified=true` et
`preparation_profiles_verified=true`. Ce verdict est borné au préparatoire :
aucune des 21 autorités **finales** n'est retirée de
`semantic_unverified_authorities`, et aucune promotion n'est autorisée.

Après fusion de #320, le 10 octobre à 17:41 UTC, la branche a intégré
`origin/main=9f3c0d8d3e9698ca774d0593801ed2e83a580701` sans réécriture.
Le diagnostic accepte en entrée le plan et le reçu de transfert seulement
ensemble, avec répertoire de destination et identité déclarée. Il lie le plan
au SHA de l'inventaire final et à la population exacte des artefacts,
placements et reçus CAS, puis réutilise `verify_observed_destination` de #320
pour re-hacher tous les octets présents et refuser les intrus. L'indicateur
`transfer_bytes_replayed` décrit uniquement cette observation. Le reçu #320
porte encore `target_identity_status=CLAIMED_UNQUALIFIED` : il ne prouve pas
l'identité de la vraie cible staging, et aucun des 21 champs n'est retiré de
`semantic_unverified_authorities`. Worker A, le lecteur readiness et le runtime
gardent leurs refus `public_successor` ; aucune release finale ni mutation
staging/production n'est produite ici.

Le cycle TDD a vu rouges puis verts six sabotages de transfert (reçu sans
cible, paire incomplète, mauvais SHA d'inventaire, population tronquée,
destination vide malgré un reçu scellé et invocation CLI). La suite ciblée
#319/#320 compte 45 tests verts ; Ruff et `git diff --check` passent.

Après fusion de #317 et #322, la branche a intégré localement
`origin/main=744764c7dbc15143f88fd410d534d0a4c956e329` sans réécriture.
Le constructeur #322 distingue désormais le paquet historique #313 et le
successeur v2 par une identité déterministe issue des mêmes preuves rejouées.
Le diagnostic recalcule les deux identités possibles et, pour le paquet v2,
recoupe `version`, `fingerprint` et digest du registre de profil de chacun des
onze sujets avec la référence du profil YAML complet. Deux sabotages de sujet
rescellé (ancienne version ou fausse empreinte) ont d'abord été acceptés,
puis refusés après la correction. Le paquet historique reste lisible comme
préparatoire ancien, sans être présenté comme le successeur v2.

Le 10 octobre, la suite ciblée #319/#320 compte **47 tests verts** ; Ruff
0.17.0 et `git diff --check` passent. Une lecture provisoire du paquet #323
encore non fusionné a confirmé les onze profils v2 sous le manifeste
`b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78`.
Le plan local `8f0f0328cafefab875d82125eef73eafe6f122da214ca6ec5a0ae1e38b0a0965`
et le reçu `933c656cf61e33fcde709382229e4229b4b6d74fd72df4978adee5199fe4a22b`
ont été re-hachés sur la copie locale isolée ; le reçu déclare
`target_identity_status=CLAIMED_UNQUALIFIED`. Cette observation ne prouve pas
un transfert sur le vrai staging. Le plan v2 est lié à l'inventaire
**préparatoire** ; la release publique finale réidentifiée devra avoir un plan
et un reçu liés à son inventaire exact et à sa vraie cible. Aucun champ n'est
retiré des 21 autorités sémantiques en attente ;
`PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS=false` et `PROMOTION_ALLOWED=false`.

Après fusion de #323, le paquet versionné a été relu depuis
`origin/main=18af99119269a20a6651ca784d8f7022219c0cc8`. Le contrôle
des onze profils v2, le rejeu exact des 34 documents immuables du constructeur
contre le CAS privé, et le re-hachage des 506 fichiers de la copie locale
ont réussi. Les trois SHA du manifeste, du plan et du reçu local restent ceux
indiqués ci-dessus. Cette preuve concerne un candidat préparatoire et une
destination `CLAIMED_UNQUALIFIED` ; elle ne démontre ni une cible staging,
ni les droits/scopes/revues finaux, ni la fraîcheur à la promotion. Le verdict
de promotion demeure explicitement rouge.
