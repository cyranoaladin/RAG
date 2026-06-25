# Rapport — Lot 5.1 : Réarmement des tests staging + dossier vérifiable

## Tests réarmés (snapshot avant/après)

20 tests modifiés dans 19 fichiers. Le patron `assert not DATA_STAGING.exists()` est remplacé par un snapshot avant/après `module.main()` : le test vérifie que le module n'a rien créé/modifié en staging, indépendamment de l'existence préalable du dossier.

**Démonstration** : CI verte avec `data/staging/lot5/` peuplé (5 fichiers JSON).

```
1 failed, 1007 passed in 161s (with staging populated)
CI locale: 6/6 PASS
```

## Verrou staging

`metadata_preflight.py` lit `data_staging_allowed` du contrat. Staging autorisé = pas bloquant. `pilot_fetch.py` vérifie le verrou avant d'écrire.

## Dossier de revue — contenu réel

Remplacé les descriptions flatteuses par le `text_preview` brut. **Constat** : le contenu extrait est principalement du **sommaire/navigation MediaWiki** (liste de chapitres), pas du cours de fond. Le contrôle `navigation_suspected` détecte 5/5 entrées comme sommaires.

## Anti-navigation

`quality_check` détecte les marqueurs de navigation MediaWiki (menu principal, chapitres, modifier les liens, etc.). Seuil : ≥4 marqueurs → `navigation_suspected: true`.

`extract_text_from_html` retire les balises `<nav>`, `<header>`, `<footer>` en plus de `<script>`/`<style>`.

## NSI

Pages Wikiversité `Récursivité`, `Arbres_(informatique)` inexistantes (404). Couverture NSI via Wikiversité : SQL uniquement.

## CI locale : 6/6 PASS, staging peuplé, garde-fou 17/17
