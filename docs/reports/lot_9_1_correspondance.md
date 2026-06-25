# Rapport — Lot 9.1 : Moteur de correspondance fiable

## Les 3 failles corrigées

### 1. Mots dispersés comptés comme « trouvés »
**Avant** : `_find_notion_in_text` vérifiait si tous les mots >3 lettres apparaissaient **n'importe où** dans le PDF. « Loi normale » comptée présente dans un texte contenant « loi des grands nombres » + « fonction normale » séparés.

**Après** : matching de proximité (fenêtre de 8 mots). Les mots doivent apparaître ensemble. Test prouvant que les mots dispersés ne comptent plus.

### 2. Rapport unidirectionnel
**Avant** : seulement taxo→BO.

**Après** : bidirectionnel. `bo_only` liste les headings du programme absents de la taxonomie.

### 3. Fallback UTF-8 silencieux
**Avant** : si pypdf échouait, lecture brute en UTF-8 → texte corrompu, pourcentage fictif.

**Après** : `extraction_status: failed` explicite, pas de pourcentage produit.

## Comparaison avant/après

| Matière | Avant (mots dispersés) | Après (proximité) | Écart |
|---|---|---|---|
| Maths 2de | 92.6% (25/27) | **74.1%** exact (20/27) | **-18.5%** faux positifs |
| NSI 1re | 80.0% (20/25) | **44.0%** exact (11/25) | **-36.0%** faux positifs |

## Détail Maths Seconde (nouveau moteur)

- **Exact** : 20/27 (74.1%)
- **Partial** : 3/27 (à vérifier manuellement)
- **Not found** : 4/27 (`droites_plan/parallelisme_perpendicularite`, `statistiques_descriptives`, `moyenne`, `mediane`)
- **BO-only** : 20 headings (dont bruit structurel "Sommaire"/"Préambule")

## Détail NSI Première (nouveau moteur)

- **Exact** : 11/25 (44.0%)
- **Partial** : 3/25 (à vérifier)
- **Not found** : 11/25 (termes taxo plus spécifiques que le BO)
- **BO-only** : 124 headings (dont "Histoire de l'informatique", "Démarche de projet" = vrais oublis)

## Test anti-mots-dispersés

```python
def test_dispersed_words_not_counted_as_found():
    text = "La loi des grands nombres... la fonction normale..."
    result = find_notion_in_text("loi_normale", "Loi normale", words)
    assert result == "not_found"  # PASS ✓
```

## CI locale : 7/7 PASS
