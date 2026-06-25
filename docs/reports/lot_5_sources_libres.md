# Rapport — Lot 5 : Sources libres + staging autorisé

## Transition staging

`data_staging_allowed: true` tracé dans pedago_interface_contract.yml, transition_authorization.yml, et baseline (17 clés, ADR-0004). `ingestion_allowed` reste `false`.

## Source branchée : Wikiversité (CC-BY-SA 4.0)

Domaine `fr.wikiversity.org` ajouté à la whitelist. Pages `/wiki/` autorisées par robots.txt (API `/w/api.php` interdite → non utilisée).

### Résultats du fetch réel

| Notion | Matière | Résultat | Taille |
|---|---|---|---|
| suites | maths | **OK** | 3298 chars |
| fonction_exponentielle | maths | **OK** | 4915 chars |
| derivation | maths | **OK** | 4820 chars |
| probabilites_conditionnelles | maths | **OK** | 3314 chars |
| primitives | maths | 404 | — |
| recursivite | nsi | 404 | — |
| arbres | nsi | 404 | — |
| sql | nsi | **OK** | 5240 chars |

**5/8 pages récupérées** avec contenu réel de cours (leçons Wikiversité). 3 pages 404 (articles inexistants sur Wikiversité FR).

### Couverture substance (pilote)

Sur 79 notions taxonomie : 5 notions avec contenu de substance, 74 restent à découvert. La couverture est **réelle** (contenu de cours, pas une page institutionnelle générique).

## Conformité

- **robots.txt** : respecté (pages `/wiki/` autorisées, API refusée et non utilisée)
- **Rate limit** : 1.4–1.9s observé entre requêtes (cible 2s)
- **Licence** : CC-BY-SA 4.0 étiquetée sur chaque entrée
- **`ingestion_allowed=false`** : rien importé au corpus
- **Garde-fou** : 17/17, ADR existant vérifié

## Dossier de revue

`data/acquisition/dossier_revue_lot5.md` : 5 entrées `à_valider`, avec source, licence, extrait.

## CI locale : 6/6 PASS
