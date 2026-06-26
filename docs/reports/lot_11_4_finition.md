# Rapport — Lot 11.4 : Finition extraction (queue d'article) + détecteur complet

## Faille corrigée

10/16 fichiers gardaient une queue de chrome (Voir aussi, Articles connexes, Bibliographie, Wiktionnaire, Wikimedia) après l'extraction BS4 du Lot 11.3.

## Correctif

### Retrait structurel (BeautifulSoup)
- Classes ajoutées : `.sister-project`, `.sistersitebox`, `.side-box`, `.navbox-wikimedia`, `.reflist`, `.refbegin`
- Sections terminales : traitées en h2 ET h3 (pas seulement h2)
- Sections ajoutées : « Sur les autres projets », « Références »
- Conteneurs footer par texte : « portail : », « catégorie : », « sur les autres projets »

### Filet de troncature post-extraction
Marqueurs complétés : « Voir aussi », « Articles connexes », « Sur les autres projets », « Notes et références », « Bibliographie ». Troncature au premier marqueur dans la dernière moitié du texte.

### Détecteur de qualité complété
Marqueurs chrome ajoutés : « sur les autres projets », « articles connexes », « wiktionnaire », « sur wikiversity », « notices d'autorité ». `"portail"` → `"portail :"` pour éviter le faux positif NSI.

## Preuve : 0/16 fichiers avec queue de chrome

```
grand_oral/grand_oral_expression_orale.json         CLEAN
grand_oral/grand_oral_transversalite.json            CLEAN
mathematiques/mathematiques_continuite.json          CLEAN
mathematiques/mathematiques_convexite.json           CLEAN
mathematiques/mathematiques_derivation.json          CLEAN
mathematiques/mathematiques_limites.json             CLEAN
mathematiques/mathematiques_suites.json              CLEAN
nsi/nsi_arbres.json                                  CLEAN
nsi/nsi_files.json                                   CLEAN
nsi/nsi_graphes.json                                 CLEAN
nsi/nsi_listes.json                                  CLEAN
nsi/nsi_piles.json                                   CLEAN
philosophie/philosophie_droit.json                    CLEAN
philosophie/philosophie_etat.json                     CLEAN
philosophie/philosophie_justice.json                  CLEAN
philosophie/philosophie_liberte.json                  CLEAN

Tail-clean: 16/16
```

## Tests (20/20 PASS)

- `test_mediawiki_extraction_strips_tail_chrome` : Voir aussi + Articles connexes + Wikiversity → absent
- `test_no_false_positive_portail_nsi` : texte NSI « portail web » → nav=False
- `test_no_false_positive_categorie_maths` : texte maths « catégorie » → nav=False

## Couverture substantielle : 16/30 (53%) — confirmé

Même chiffre qu'au Lot 11.3 — le nettoyage de la queue n'a pas changé le nombre de notions trouvées, mais a rendu le contenu réellement propre pour le chunking/embedding.

## CI locale : 7/7 PASS
