# Lot HGGSP — successeur complémentaire de V4 (option B)

Branche `go-live/hggsp-complementary-successor`, créée après `git fetch
origin` et vérification de `origin/main` =
`2124826ae3302179a2fe19a5356c48c1bee63c28`. Arbitrage humain :
option B, deux collections HGGSP seulement. Aucun accès serveur ou base,
aucun Worker B et aucune opération sur #262 n'ont eu lieu dans ce lot.

## Diagnostic et décision

`build_profile_gate_successor.sh` repartait de V1, même avec une référence
V4. Le producteur `build_production_profile_release.py` lisait les sujets
V1 (`subjects[].artifacts`), recopiait le mapping de sujets source en mode
répétition et, en mode production, pointait vers
`eduscol_profile_gate_subjects.yml` par constante. Il ne pouvait donc pas
émettre honnêtement un sous-ensemble V4 avec le mapping HGGSP additif.

La voie historique sans nouvelles options reste inchangée. La voie
complémentaire exige une source V2 par manifeste épinglé, une sélection de
collections, un chemin de mapping et son SHA réel. Le wrapper borne cette
voie à l'identité `production-profile-gate-2026-2027-v5-hggsp`, aux deux
collections HGGSP et au mapping additif du commit
`fb8a7cc8e85448115a64de8ff5325d639ef9ee70`. Il vérifie les SHA des
52 PDF du miroir, les registres scellés V4, le motif d'autorité et les
cardinalités calculées avant et après construction. Le mécanisme existant
`--authority-change-motive` a prouvé le commit qui porte le nouveau mapping.

V4 n'est pas réécrite. Le registre mixte `registry_version=2` attribue
explicitement ses neuf collections servies à V4 et les deux HGGSP au
successeur. Le chargeur valide chaque manifeste **entier** avant projection,
puis refuse collection étrangère, doublon, collision d'artefact et divergence
de modèle. Le registre version 1 conserve sa sémantique exacte. ADR-0062
documente cette propriété par collection ; ce registre candidat n'est
installé dans aucun runtime par ce lot.

## Release et preuves

| Élément | Valeur |
|---|---|
| Release | `production-profile-gate-2026-2027-v5-hggsp` |
| Manifeste | `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json` |
| SHA du manifeste | `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` |
| Mapping HGGSP | `services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml` |
| SHA du mapping HGGSP | `b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a` |
| SHA du mapping V4, inchangé | `85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c` |
| Registre mixte | `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json` |
| SHA du registre mixte | `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6` |
| Diff machine V4 → complément | `docs/reports/evidence/profile_gate_v4_to_hggsp_v5_diff.json` (`bbb5b0fac53f4cd965eb422ebf93fbcdbf489a17c7e3c2a7ab8e3bf29f78d0b0`) |
| Preuve de construction | `docs/reports/evidence/hggsp_v5_complementary_build_proof.json` (`549d204b58002634c9a3389f95cd63539cdf470f243f0ded3140357fbecae554`) |

Le recalcul indépendant depuis les subjects et l'artefact registry V4 donne
HGGSP Première **39 placements**, HGGSP Terminale **35**, soit **74
placements**, **52 artefacts uniques** et **2 590 chunks**. Les neuf autres
collections donnent 405 placements, 263 artefacts et 5 678 chunks.
L'intersection des identifiants d'artefacts est vide. Le produit contient
exactement les 74 identifiants de placement HGGSP de V4 et aucun des 405
autres ; le diff machine constate 405 placements retirés du périmètre, zéro
placement ajouté. La somme des deux lignées reste 479 placements,
315 artefacts et 8 268 chunks.

Le miroir local a fourni les 52 PDF HGGSP : 52/52 fichiers présents avec un
SHA-256 réel égal à `content_sha256`. Les 28 fichiers suivis de V4 ont été
comparés octet par octet au commit de base : zéro différence. Une seconde
construction complète, avec les mêmes entrées dans une autre sortie locale,
a donné le même SHA de manifeste et les mêmes octets pour ses 19 fichiers.
La différence machine est également identique.

La première tentative de build a correctement refusé une projection PII
naïve : le jeu signé de revue porte sur les 315 contenus V4 et ne peut pas
être présenté comme une revue de 52. La voie complémentaire vérifie le
SHA de la preuve PII source V4 (`33e3fbfb943ffded360d2db254061edebe8ccff9e08b7509ebcdf4cd305ca700`),
sa population et sa chaîne humaine signée, puis rescane les 52 PDF avec le
scanner et la politique gouvernés. Les 52 résultats sont `CLEARED`, sans
détection et sans décision PII HGGSP ; ils sont confrontés aux 52 résultats
V4 scellés. La preuve émise porte `SIGNED_SOURCE_SUBSET_V1`, le SHA parent et
le digest de l'ensemble de 52. Les quatre SHA de la chaîne signée restent
dans le manifeste et ont été revérifiés par les chargeurs canoniques. La
garde générale de projection PII n'a pas été assouplie.

Les chargeurs canoniques ont relu le produit : catalogue 52, préflight 52,
PII 52 `CLEARED`, actualité 52 instantanés officiels et chaîne de revue
vérifiée. Le registre mixte réel se charge avec V4 = 9/263/405/5 678 et
successeur = 2/52/74/2 590 ; le calcul C1 et le binding retrieval par
collection donnent les mêmes propriétaires.

## Qualification locale

| Suite | Résultat |
|---|---|
| Producteur, PII, lignée, identité, actualité | 159 tests réussis avec le runtime canonique `pypdf 6.14.2` |
| Readiness et gouvernance des sujets DI | 201 tests réussis, dont la projection multi-placement avec ancre physique hors collection servie |
| Retrieval, garde runtime, parité d'autorité, montage | 111 tests réussis |
| C1 et clôture de release V2 | 44 tests réussis, 2 ignorés |
| Wrapper complémentaire et orchestrateur historique | 22 tests réussis, dont contre-épreuves sur vrai miroir PDF |
| Revue humaine fiable | 27 tests et 34 sous-tests réussis |
| `ruff` sur les Python touchés | vert |
| `mypy` ciblé sur les deux modules Python touchés | 2 fichiers, zéro erreur |
| Syntaxe Bash du wrapper et `git diff --check` | verts |
| Repository hygiene + tests, governance locks (18 clés), authority uniqueness + tests, topologie CI | verts ; baseline d'unicité étendue pour la copie du registre d'exclusion V4, vérifiée octet pour octet |
| Deux builds complets, diff machine, chargeurs canoniques et comparaison des 19 fichiers | verts |

Les essais intermédiaires ont fait apparaître puis corriger la collision de
population PII. Le contrôle d'unicité des autorités a d'abord refusé les
nouveaux tests non ajoutés à l'index ; ils ont été ajoutés et le contrôle est
vert. Une invocation globale de `mypy` depuis la racine a importé des modules
hors périmètre avec un contexte de chemins incorrect ; l'invocation ciblée
sur les deux fichiers touchés est verte.

## État de sûreté et suite

Le manifeste reste `rehearsal`, `PRE_REVIEW`, `NOT_PROMOTABLE` et
`NO_PRODUCTION_ACTIVATION`. L'autorisation de staging placée sous `proposed/`
est explicitement inactive : image, scopes et readiness successeurs ne sont
pas épinglés ni activés. Elle ne permet aucune mutation serveur. La procédure
gouvernée ultérieure est dans
`docs/runbooks/staging_hggsp_complementary_SUCCESSOR_PLAN.md` ; elle exige
une PR d'activation distincte, puis readiness, r4, revue batch, 74 nouvelles
attestations et jobs, Worker B limité à deux collections, vérification
indépendante, et seulement ensuite une invalidation séparée des 74 anciens
jobs HGGSP V4. #262 reste ouverte et inchangée. Une image Worker B et une
image retrieval portant le nouveau chargeur v2 devront être construites et
épinglées avant un usage runtime ; ce lot n'en invente pas les digests.
