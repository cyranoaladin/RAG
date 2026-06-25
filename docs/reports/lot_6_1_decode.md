# Rapport — Lot 6.1 : Décodage des entités HTML

## Faille

`extract_text_from_html` supprimait les balises HTML mais ne décodait pas les entités (`&#160;`, `&amp;`, `&eacute;`). Les marqueurs de navigation Wikiversité contenaient `&#160;:` — le détecteur anti-navigation les manquait.

## Correction

`html.unescape()` (stdlib) ajouté après la suppression des balises, avant les contrôles qualité.

## Tests unitaires (15/15 PASS)

- `test_extract_decodes_html_entities` : vérifie que `&#160;`, `&amp;`, `&#233;` sont décodés
- `test_navigation_detected_with_html_entities` : HTML nav Wikiversité → `navigation_suspected=True`
- `test_course_content_not_flagged_as_navigation` : cours maths → `navigation_suspected=False`

## Résultat du fetch corrigé

Les entités sont bien décodées dans les text_preview (plus de `&#160;`). Les pages Wikiversité maths restent `navigation_suspected=False` (index légers, < 4 marqueurs nav). Le sub-page extractor se déclenche correctement quand une page a ≥ 4 marqueurs.

## Couverture inchangée

7/9 notions avec contenu non-navigation. Le décodage d'entités n'a pas changé la classification nav/contenu pour ce corpus.

## CI locale : 6/6 PASS, staging peuplé, garde-fou 17/17
