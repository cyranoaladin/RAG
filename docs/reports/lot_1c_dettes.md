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
