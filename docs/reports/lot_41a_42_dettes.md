# Dettes constatées — LOT41A/LOT42 (GATE H1)

Ce fichier ne recense que des échecs **préexistants**, dont l'antériorité est
prouvée contre `origin/main`, conformément à AGENTS.md (« un lot peut être
livré avec des échecs préexistants, à condition qu'ils soient tracés […] avec
antériorité prouvée contre le commit parent »).

Aucun test vert n'a été rendu rouge par ce lot.

---

## D1 — `packages/contracts` : test de version épinglé sur une version dépassée

**Test** : `packages/contracts/tests/test_schema_export.py::test_package_version_is_0_5_0`

**Symptôme** : le test affirme `pyproject.project.version == "0.5.0"`, alors
que le paquet est en `0.6.0`.

**Antériorité prouvée** — reproduit sur un worktree détaché d'`origin/main`
(`e65bc29`), sans aucun fichier de cette branche :

```
$ git worktree add --detach <tmp> origin/main
$ pytest <tmp>/packages/contracts/tests/test_schema_export.py::test_package_version_is_0_5_0
FAILED — assert '0.6.0' == '0.5.0'
```

**Impact CI** : aucun. Le job requis `packages/contracts` (`.github/workflows/ci.yml`)
n'exécute pas cette suite ; il installe le paquet et vérifie l'importabilité
du contrat. L'échec est donc strictement local.

**Pourquoi ce lot ne le corrige pas** : le test épingle une version de
contrat. Le corriger reviendrait à décider quelle version fait autorité —
une décision de gouvernance de contrat (SemVer + ADR, cf. AGENTS.md), hors
du périmètre LOT41A/LOT42. Le modifier « au passage » serait précisément le
genre d'effet de bord que ce lot doit éviter.

**Correction attendue** : soit remplacer l'assertion par une comparaison
avec la version réellement déclarée, soit la supprimer au profit du test de
déterminisme du schéma déjà présent dans le même fichier. À traiter dans un
lot dédié au versionnement de `nexus-contracts`.

---

## Non-dettes — points vérifiés et verts

Pour éviter toute ambiguïté sur ce que ce fichier recense :

- `pytest -m "not integration"` (rag-engine) : vert.
- `pytest tests/integration/` (rag-engine, PostgreSQL et Docker réels) : vert.
- `packages/contracts` : 94 tests verts, 1 échec préexistant (D1).
- `ruff`, `mypy` : verts sur `rag-engine` et `packages/contracts`.
- Cockpit (Node 22.22.0) : `lint`, `typecheck`, `test` (178), `build`,
  `audit` et `audit --omit=dev` — **0 vulnérabilité**.
- `scripts/check-governance-locks.sh` : 18/18 clés conformes à la baseline.
