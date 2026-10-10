# Lot — candidat technique d'accès étudiant public (2026-10-08)

## Verdict

**PROPOSÉ, NON ACTIVÉ.** Au `main` source `2f9665b29805cf0cdacf2b5192cb4f9135e871c2` (arbre `dad0fd7fdca4745d1e7db7753f62f572157e709e`), les onze profils de placement candidats sont `public` et l'émetteur canonique accepte la future autorité `NEXUS_HUMAN_DECISION_ADR_0064` seulement pour ces onze politiques internes épinglées, avec population/candidat `libre`, droit `officiel_public` et visibilités de sujet/politique `public`. Aucun manifeste de profils approuvé, scope public packagé, autorisation de publication publique ou placement public n'est créé par ce lot. `STUDENT_SERVABLE=false` demeure vrai jusqu'à qualification réelle sur une cible nouvelle.

La décision de visibilité [ADR-0064](https://github.com/cyranoaladin/RAG/pull/286) a été approuvée au HEAD exact et fusionnée dans ce `main`. La présente PR porte seulement le candidat technique et la [proposition de décision de droits](../governance/student_public_rights_decision_proposal_20261008.yml), toujours `PENDING_HUMAN_APPROVAL`. Le registre des droits en vigueur autorise l'usage RAG interne et production Eduscol sous attribution, mais ne porte pas encore l'ouverture du service aux élèves. L'approbation de cette PR ne remplace pas la revue documentaire individuelle des 315 contenus : chaque restriction est traitée avant toute nouvelle release publique, et un contenu refusé impose un nouveau périmètre et de nouveaux digests.

## Périmètre matériel opposable

Sources relues par SHA-256 sur le `main` source : manifeste V4 `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be` ; manifeste HGGSP V5 `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` ; registre mixte `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`. La proposition porte les neuf subjects non-HGGSP de V4 et les deux subjects HGGSP de V5 : **11 collections, 315 `artifact_id`/`content_sha256` uniques, 479 placements**. Le digest de l'ensemble des 315 SHA, triés lexicalement, un SHA minuscule par ligne avec saut de ligne final, vaut `04b731e20a9ebd9dcd08f00fe516489191690f67ec18e4ba4996a8612961bd12`. Les 315 entrées du registre de release correspondant à ces placements pointent dans `01_EDUSCOL_OFFICIEL/`. Le test du paquet recalcule l'ensemble, les digests des subjects et des registres d'artefacts, les cardinalités et la zone source ; il ne transforme pas cette preuve de provenance en décision de droits.

| Collection | Placements de référence | Empreinte du profil public candidat | Scope interne épinglé à remplacer |
|---|---:|---|---|
| `rag_nexus_dgemc_terminale_option` | 12 | `1c4724498f30c07a993d0d0c9b9db2447e0f3bee0568257a6974dabc848279b1` | `prod_dgemc_terminale_option_v3` |
| `rag_nexus_hggsp_premiere_specialite` | 39 | `9b462af9e32251b39d35e8eccbc5177b114b7586cbbf47a11294be661580bec2` | `prod_hggsp_premiere_specialite_v3` |
| `rag_nexus_hggsp_terminale_specialite` | 35 | `0dbe91e70b226f942b9e4d466f95d785215a01611a47b7726060adc2f60830b0` | `prod_hggsp_terminale_specialite_v3` |
| `rag_nexus_hlp_premiere_specialite` | 115 | `bf5379f7cec9ad6532f672c907c5dc9241a62ce9718df868c417c3908efec98b` | `prod_hlp_premiere_specialite_v3` |
| `rag_nexus_hlp_terminale_specialite` | 89 | `bc2b0e99da2b43b42ed48cec2e28f80f8f1ea0b976c44f5f05e3be5a566956df` | `prod_hlp_terminale_specialite_v2` |
| `rag_nexus_nsi_premiere_specialite` | 29 | `ae88037bb7564b6afbc3c08c8b39f4ab27fe2c71f2623f2e6fc50b5c74e3df6f` | `prod_nsi_premiere_specialite_v3` |
| `rag_nexus_nsi_terminale_specialite` | 47 | `d6e490626f5e58a8ea9bb51cbc6c2d74d08f6df21dc68f6923fea611cb794c50` | `prod_nsi_terminale_specialite_v3` |
| `rag_nexus_ses_premiere_specialite` | 30 | `48db5fe66a6053d27634b7801a5401aee640e45a79fe22fe79f44cdb35d97546` | `prod_ses_premiere_specialite_v3` |
| `rag_nexus_ses_terminale_specialite` | 28 | `6ef5b7e1c134e9afefecc02e234e476042abaa344878013f6b6cb49819069ee7` | `prod_ses_terminale_specialite_v3` |
| `rag_nexus_svt_premiere_specialite` | 19 | `c6e25c11c7e7b95dd7be22737d1b9e5b74185cae9001401ea29123000174ddf3` | `prod_svt_premiere_specialite_v3` |
| `rag_nexus_svt_terminale_specialite` | 36 | `d6d40ff04036ae45e3fa5f27fba493bf29c90d1a53c0d197db0b00ca15481bdb` | `prod_svt_terminale_specialite_v3` |

Chaque profil candidat diffère du profil V3 correspondant uniquement sur `profile_version` (`profile-gate-v4-public`) et `scope.visibility` (`public`). Le manifeste V3 actif ne pointe pas vers le répertoire candidat. Les onze profils sont chargés par le registre canonique et possèdent onze empreintes distinctes.

## Garde de l'émetteur et limites de preuve

La garde `NEXUS_HUMAN_DECISION_ADR_0064` compare les dimensions curriculaires, audiences, programme et identité cible aux onze scopes prédécesseurs immuables ; elle exige `officiel_public`, `public/public`, `libre` et une entrée déclarée `GOVERNED_BY_HUMAN_DECISION` sans `policy_source_scope_id`. Elle refuse une douzième collection et toute extension de rôle, candidat, audience ou droit. Le chemin ADR-0053 existant reste inchangé. Le constructeur continue à comparer les placements au registre de politique et à l'autorité de programme ; aucun champ n'est retiré du cross-check.

Les tests de chemin de rôle construisent **en mémoire seulement** onze scopes publics fictifs à partir des scopes internes, pour vérifier `student` et `teacher` sur la collection exacte, le refus hors collection et le refus de `student` sur les scopes internes. Ce ne sont pas des tests E2E, ni des scopes émis, ni une preuve de service sur pgvector. La règle `_ROLE_VISIBILITIES['student'] == ('public',)` et les anciennes colonnes de chunks ne changent pas.

## Après la décision, ordre exécutable

1. ADR-0064 étant approuvée, faire statuer sur cette proposition de droits au HEAD exact et vérifier les droits individuels, PII, actualité et révocations des 315 contenus sur la cible finale. Un refus documentaire retire l'artefact concerné et impose un nouveau périmètre et de nouveaux digests, jamais un ajustement silencieux.
2. Depuis un `main` frais, un venv propre et le miroir PDF vérifié, fabriquer un **manifeste de profils public approuvé** qui lie les onze empreintes ci-dessus, puis deux releases successeurs immuables : neuf collections non-HGGSP et deux HGGSP. Utiliser les producteurs et vérificateurs existants, la matrice/contenu final épinglés, de nouveaux `release_id` et un registre mixte à propriétaire unique. Les vieux manifests et autorisations restent intacts.
3. Émettre les nouveaux registres de politique et scopes V2 par `build_retrieval_scope_artifacts.py` : onze `subject_sha256` issus des **nouveaux** manifests, `evidence_visibility=policy_visibility=public`, revue au HEAD exact, droits `officiel_public` et autorisations/attestations liées aux contenus. Les digests futurs ne sont pas calculables honnêtement avant l'émission et la revue de ces octets ; aucune valeur source V4/V5 ne peut leur être substituée.
4. Publier sur une base de qualification **propre**, jamais en ajoutant 479 placements publics aux 479 internes de `ragdb_profile_gate_v4`. Exiger 11/315/479/8268, tests student **et teacher** positifs et cités via BFF→API→pgvector dans leur portée, et des refus hors portée pour les deux rôles ; puis qualité/charge sur cette même cible avant toute promotion.

## Vérification du lot

Code testé : `826f5e7a163cca5045c099a4515439e889e9989b` (arbre `d399710e4c45783b0ca4076f040f328f6fdc3d06`), dans un worktree propre fondé sur le `main` indiqué plus haut. Venv isolé `/tmp/rag-student-tech-venv-2f9665b2`, installé avec `pip install -e 'packages/contracts[dev]' -e packages/release-chain fastapi==0.115.0` depuis ce worktree ; l'import du contrat résout ce même worktree. Les commandes suivantes ont abouti ; le dernier commit de rapport ne modifie que cette preuve textuelle :

```sh
/tmp/rag-student-tech-venv-2f9665b2/bin/python -m pytest -q packages/contracts/tests
# 1041 passed in 10.39s
/tmp/rag-student-tech-venv-2f9665b2/bin/python -m pytest -q \
  packages/contracts/tests/test_student_public_policy_authority.py \
  packages/contracts/tests/test_student_public_rights_proposal.py \
  packages/contracts/tests/test_build_retrieval_scope_artifacts.py \
  packages/contracts/tests/test_emit_from_policy_registry.py \
  services/rag-engine/tests/test_student_public_profile_proposals.py \
  services/rag-engine/tests/test_student_public_scope_proposal.py
# 119 passed in 6.03s
/tmp/rag-student-tech-venv-2f9665b2/bin/ruff check \
  packages/contracts/scripts/build_retrieval_scope_artifacts.py \
  packages/contracts/tests/test_student_public_policy_authority.py \
  packages/contracts/tests/test_student_public_rights_proposal.py \
  packages/contracts/tests/test_emit_from_policy_registry.py \
  services/rag-engine/tests/test_student_public_profile_proposals.py \
  services/rag-engine/tests/test_student_public_scope_proposal.py
bash scripts/check-governance-locks.sh
bash scripts/check-repository-hygiene.sh
```

Le cycle TDD du candidat a montré `20 failed, 33 passed` sur le précédent `main` `ce5c6fe5` sans le delta, puis 119 tests ciblés verts avec le delta. Sur le `main` `2f9665b2` de ce lot, la suite ciblée et la suite complète du contrat sont vertes. Deux tests parcourent réellement l'émetteur avec une autorité de nommage réutilisant chacun des identifiants HGGSP V3 ; ils exigent le refus. La CI globale et la review humaine font foi pour l'intégration. Aucune écriture staging, production ou `main` n'a été effectuée.
