# Rapport — Lot 6 : Sous-pages Wikiversité + sources NSI libres

## Sous-pages Wikiversité

Extracteur de liens de sous-pages créé (`subpage_extractor.py`). Pour les pages d'index Wikiversité (navigation_suspected=True), les liens `/wiki/Titre/Chapitre_N` sont extraits et fetchés.

## Wikipedia pour NSI

`fr.wikipedia.org` ajouté à la whitelist (robots `/wiki/` autorisé, licence CC-BY-SA 4.0). 3 notions NSI récupérées :
- **recursivite** : 17771 chars, navigation_suspected=False
- **graphes** : 59199 chars, navigation_suspected=False
- **arbres** : 13507 chars, navigation_suspected=True (page de sommaire)

## Couverture substance

| Matière | Notions ciblées | Substance (nav=False) | Sommaire/404 |
|---|---|---|---|
| maths | 5 | 4 (suites, exp, dérivation, probas) | 1 (primitives 404) |
| nsi | 4 | 3 (récursivité, graphes, SQL) | 1 (arbres = sommaire) |
| **Total** | **9** | **7** | **2** |

## Dettes corrigées (BACKLOG lot 5.1)

- **Assertion preflight** : lit `data_staging_allowed` du contrat, assertion sémantique correcte
- **Test verrou pilot_fetch** : `data_staging_allowed=false` → refus, `error` dans le retour (test passant)

## Conformité

- robots.txt respecté (Wikiversité `/wiki/` + Wikipedia `/wiki/`)
- Rate limit 2s
- Licences CC-BY-SA 4.0 vérifiées
- `ingestion_allowed=false` ; garde-fou 17/17

## CI locale : 6/6 PASS avec staging peuplé (8 fichiers)
