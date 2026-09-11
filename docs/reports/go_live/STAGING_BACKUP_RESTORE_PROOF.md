# Sauvegarde de la base de revue : preuve de restauration

Document dérivé. Ne pas éditer à la main.

Une sauvegarde non restaurée n'est pas une sauvegarde.

Restauration prouvée : **oui** — comptages et digests logiques du texte de revue identiques.

## Comptages

| table | source | restauré |
| --- | ---: | ---: |
| `artifacts` | 2473 | 2473 |
| `chunks` | 23744 | 23744 |
| `page_provenances` | 26736 | 26736 |
| `provenances` | 2473 | 2473 |

Digests logiques du texte de revue identiques : **oui**.

Des comptages égaux sur un texte différent ne prouveraient rien : c'est
pourquoi les digests sont comparés en plus des comptages.

## Contrôles

| contrôle | valeur |
| --- | ---: |
| colonnes_vectorielles | 0 |
| contenus_distincts | 2473 |
| extension_vector | 0 |
| pages_avec_texte_canonique | 26736 |
| pdf_avec_texte_canonique | 2473 |
