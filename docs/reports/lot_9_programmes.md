# Rapport — Lot 9 : Récupération des programmes officiels

## Registre des programmes

`data/programmes/registre_programmes.yml` : 13 entrées, 6 récupérables (cache.media URLs), 7 à vérifier.

## Programmes réellement récupérés

| Matière | Niveau | Taille | SHA-256 (16 chars) | Statut |
|---|---|---|---|---|
| Mathematiques | Seconde | 410 341 octets | 7f4fe97474... | **OK** |
| NSI | Première | 307 943 octets | 7ca9a32e18... | **OK** |
| Mathematiques | Terminale | — | — | 404 (URL périmée) |
| NSI | Terminale | — | — | 404 (URL périmée) |
| Philosophie | Terminale | — | — | 404 (URL périmée) |
| Mathematiques | Première | — | — | 404 (URL périmée) |

**4 URLs cache.media retournent 404** — les noms de fichiers ont changé sur le serveur. Ces programmes devront être récupérés manuellement.

## Rapports de correspondance

### Maths Seconde vs BO officiel
- **PDF** : 43 828 chars extraits
- **Coverage** : 25/27 notions trouvées (92.6%)
- **Non trouvées** : `droites_plan/parallelisme_perpendicularite`, `statistiques_descriptives`
- **Verdict** : taxonomie globalement fidèle au BO ; 2 formulations à ajuster

### NSI Première vs BO officiel
- **PDF** : 23 059 chars extraits
- **Coverage** : 20/25 notions trouvées (80.0%)
- **Non trouvées** : `complexite`, `formulaires_evenements`, `systemes_exploitation/commandes_shell`, `reseaux/tcp_ip`, `reseaux/adressage`
- **Verdict** : termes techniques de la taxonomie plus spécifiques que le BO (le BO dit "protocoles de communication" pas "tcp_ip")

## Écarts détectés

Les taxonomies PREMIER JET contiennent des notions **plus détaillées** que le BO officiel (subnotions non explicitement nommées dans le texte). Ce n'est pas nécessairement faux — le BO liste les thèmes, les manuels détaillent — mais le `programme_version` doit refléter que ces notions fines viennent de l'interprétation pédagogique, pas du texte officiel brut.

## Conformité

- robots.txt : cache.media.education.gouv.fr autorisé ✓
- Whitelist respectée ✓
- `data_staging_allowed=true` vérifié ✓
- `ingestion_allowed=false` ✓
- Checksums SHA-256 enregistrés ✓

## CI locale : 7/7 PASS
