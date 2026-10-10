# Lot — proposition de politique de scope pour les dérivés étudiants

Base : `origin/main` `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`.

L'autorité `governance/student_public_rights/public_scope_policy_authority_v1.yml`
décrit les onze collections de dérivés textuels du candidat #312. Son statut
est `PENDING_EXACT_HEAD_AUTHORITY_REVIEW`. Elle lie par SHA-256 ADR-0064, le
manifeste candidat, les profils, le registre de droits, le manifeste des
dérivés et l'autorité Éduscol–Etalab approuvée dans #300. Les onze liaisons
portent uniquement le SHA du **subject candidat** et le fingerprint du profil
proposé ; `final_subject_sha256` et `scope_id` sont `null` partout. Aucun
artefact `RetrievalScopeArtifactV3` actif n'est émis.

Le vérificateur pur `scripts/go_live/check_public_scope_policy_authority.py`
utilise le contrat `RetrievalScopeTargetPolicy` existant. Il exige
`student → public`, audience `libre`, matière unique, artefacts textuels et
droits Etalab explicites pour les 253 identités. Il refuse les PDF, les droits
manquants, `officiel_public` ajouté comme raccourci, les divergences de SHA et
toute tentative de remplir l'identité d'un scope final dans cette proposition.
Le registre historique V4/V5 `internal` reste inchangé.

L'approbation exacte de cette nouvelle autorité, la génération des nouveaux
subjects finaux, la revue des droits au moment de la promotion, les
autorisations de scope et l'émission des onze artefacts V3 sont des étapes
ultérieures. Ce lot ne modifie ni staging ni production.

Contrôles dans un venv isolé de ce worktree :

```sh
python -m pytest -q scripts/tests/test_public_scope_policy_authority.py
# 14 passed
python -m pytest -q packages/contracts/tests/test_aria_retrieval_scope_v3.py packages/contracts/tests/test_student_public_policy_authority.py
# 31 passed
ruff check scripts/go_live/check_public_scope_policy_authority.py scripts/tests/test_public_scope_policy_authority.py
# All checks passed
```
