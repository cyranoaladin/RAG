# LOT 1c — dettes préexistantes

Échecs constatés pendant le lot, **non causés par lui**, antériorité prouvée.

## 1. Cinq tests de `test_build_production_profile_release.py`

```
test_registered_release_is_the_only_active_release_and_exact
test_aggregate_covers_exactly_26_contents_and_18_profiles
test_every_authority_is_named_path_bound_and_digest_checked
test_any_authority_binding_mutation_is_refused
test_preflight_proves_real_e5_bounds_and_no_empty_page
```

**Cause :** l'arbre de travail porte une release de 11 sujets et 486 artefacts ;
`ffc1bae` en déclare 18 et 26. Les tests lisent les fichiers de données, pas le code.

**Antériorité prouvée :** générateur d'origine remis en place, les cinq échouent à
l'identique (`5 failed, 16 deselected`).

## 2. `test_deploy_verified_release_cli.py::…::test_v2_bundle_materializes_and_reverifies_every_governance_file`

```
DeploymentWrapperError: readiness V2 rejected: authorization set verification refused:
  review binding receipt expired at 2026-08-30T12:00:00Z (now=2026-08-30T21:17:56Z)
  — a proof of review ages, and a stale one never authorizes a publication
```

**Cause — et ce n'est pas une dette ordinaire.** La fixture construit son reçu avec

```python
V2_NOW    = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)     # horloge FIGÉE
expires_at = V2_NOW + timedelta(days=7)                   # → 2026-08-30T12:00:00Z
```

puis le fait vérifier contre l'**horloge réelle**. Une date d'expiration figée, confrontée
à une horloge qui avance : le test devait virer au rouge le 2026-08-30 à 12:00 UTC, et il
l'a fait. Il était vert hier, il est rouge aujourd'hui, **et aucun commit n'est en cause**.

**Antériorité prouvée :** compose de `ffc1bae` remis en place, le test échoue à
l'identique.

**Portée réelle :** ce n'est pas un test à rafraîchir, c'est un instrument qui mesure
partiellement l'horloge de la machine au lieu de mesurer le code. Tout test de la même
forme — fixture figée, validation contre `datetime.now()` — porte une date d'échéance
qu'aucune revue ne voit passer. La correction n'est pas de repousser la date : c'est de
figer l'horloge de vérification comme la fixture l'est déjà.

Hors périmètre du LOT 1c. Signalé au titre de `AGENTS.md` § Escalade.

---

## Mesure d'antériorité complète — suite entière, worktree détaché

Les deux suites ont été exécutées dans des worktrees séparés du plan de travail, avec les
mêmes venvs, la même machine, à quelques minutes d'intervalle.

```
                        total   passed  failed  skipped
packages/contracts        468      468       0        0
rag-pedago               2822     2820       0        2
rag-engine (socle)       3445     3417      20        8
rag-engine (ffc1bae nu)  3444     3416      20        8
```

**Les vingt échecs sont exactement les mêmes de part et d'autre** — comparaison des noms
complets, `comm` sur les deux listes triées : zéro nouveau, zéro disparu. Le socle exécute
un test de plus (`test_host_artifact_variables_have_no_fabricating_default`), et il passe.

**Aucune régression.** Le garde-fou de `AGENTS.md` est satisfait au sens qu'il définit :
aucun test vert ne passe au rouge.

### Attribution des vingt échecs

```
 4  bombe d'horloge — « review binding receipt expired at 2026-08-30T12:00:00Z »
      test_readiness_gate_v2::test_v2_production_path_loads_the_exact_set_and_release_material_from_env
      test_readiness_gate_v2::test_runtime_context_rereads_revocations_bindings_and_expiry
      test_deploy_verified_release_cli::…::test_v2_bundle_materializes_and_reverifies_every_governance_file
      test_lot44f_create_job_cli_idempotency::…::test_exact_scope_is_created_and_caller_authority_override_is_not

16  tests d'intégration exigeant Docker et une base réelle
      test_lot44f_worker_resume ............... 6
      test_lot41a_worker_enforcement .......... 4
      test_lot44f_ingestion_up_failure ........ 3
      test_lot44f_worker_attestation .......... 2
      test_lot41a_docker_authority_e2e ........ 1
```

**Correction d'un chiffre publié.** Le rapport initial disait « une seule bombe d'horloge a
explosé ». C'était un sondage sur six fichiers, annoncé comme tel, et il était trop étroit :
`test_readiness_gate_v2.py` et `test_lot44f_create_job_cli_idempotency.py` n'y figuraient
pas. **La fixture figée au 2026-08-23 fait échouer quatre tests, pas un.** Le mécanisme
est inchangé — `V2_NOW + timedelta(days=7)` confronté à `datetime.now()` — et la correction
aussi : figer l'horloge de vérification comme la fixture l'est déjà.
