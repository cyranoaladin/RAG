# Rapport — Lot 1.1 : Parsing + chunking pédagogique (corpus pilote Terminale)

## Inventaire corpus

### Retenu (périmètre pilote Terminale)

| Fichier | Matière | Audience |
|---|---|---|
| `corpus/Specialites/SPE_MATHEMATIQUES.md` | mathematiques | tous |
| `corpus/Specialites/SPE_NSI.md` | nsi | tous |
| `corpus/Tronc_commun/TRONC_PHILOSOPHIE.md` | philosophie | tous |
| `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` | orientation | libre |

### Reporté (Phase 5)

| Fichier | Raison |
|---|---|
| `corpus/Specialites/SPE_HGGSP.md` | Hors vertical pilote |
| `corpus/Specialites/SPE_PHYSIQUE_CHIMIE.md` | Hors vertical pilote |
| `corpus/Specialites/SPE_SES.md` | Hors vertical pilote |
| `corpus/Specialites/SPE_SVT.md` | Hors vertical pilote |
| `corpus/Tronc_commun/TRONC_EMC.md` | Tronc commun non évalué en terminale (pilote) |
| `corpus/Tronc_commun/TRONC_ENSEIGNEMENT_SCIENTIFIQUE.md` | Idem |
| `corpus/Tronc_commun/TRONC_EPS.md` | Idem |
| `corpus/Tronc_commun/TRONC_FRANCAIS_EAF.md` | Épreuve anticipée 1ère, hors terminale |
| `corpus/Tronc_commun/TRONC_HISTOIRE_GEO.md` | Hors vertical pilote |
| `corpus/Tronc_commun/TRONC_LANGUES_VIVANTES.md` | Hors vertical pilote |

## Stratégie de chunking

- **Structure-aware** : découpage par hiérarchie de headings markdown (H1/H2/H3), pas par fenêtre fixe.
- Chaque chunk = une section cohérente, préfixée par le chemin de titres (breadcrumb) pour le contexte embedding.
- Si une section dépasse ~500 tokens, subdivision avec overlap d'1 phrase et breadcrumb en préfixe.
- Jamais de coupure au milieu d'une phrase.

## Statistiques

| Matière | Chunks | Taille médiane (mots) | type_doc | notions non vides |
|---|---|---|---|---|
| mathematiques | 9 | 63 | cours:2, programme:2, examen:2, referentiel:1, methode:2 | 2/9 |
| nsi | 8 | 85 | cours:2, programme:2, examen:1, referentiel:1, methode:2 | 6/8 |
| philosophie | 7 | 40 | cours:2, programme:1, examen:1, referentiel:1, methode:2 | 0/7 |
| referentiel_candidat_libre | 27 | 108 | referentiel:21, examen:5, methode:1 | 0/27 |
| **Total** | **51** | | | |

### Notions — fallbacks documentés

- **Maths** : notions mappées depuis `taxonomy/maths/terminale_specialite.yml` (2/9 chunks avec match, les autres sont des sections transverses comme Identité/Attendus).
- **NSI** : notions mappées depuis `taxonomy/nsi/terminale.yml` (6/8 chunks).
- **Philosophie** : aucune taxonomie disponible — notions vides. Fallback documenté : les notions philo (liberté, vérité, justice…) seront taguées au Lot 1.2 quand une taxonomie philo sera créée.
- **Référentiel candidat libre** : contenu de statut/procédure, pas disciplinaire — notions vides par design.

## Exemples de chunks taggés

### Chunk disciplinaire `[tous]` (maths)
```json
{
  "chunk_id": "spe-mathematiques_0003",
  "text": "[Spécialité — Mathématiques (voie générale) › 3. Programme — Terminale (4 domaines)]\n\n- **Analyse** : suites et limites, raisonnement par récurrence...",
  "metadata": {
    "tenant": "terminale",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "mathematiques",
    "audience": ["tous"],
    "type_doc": "programme_officiel",
    "notions": ["Suites", "recurrence", "limites_de_suites", ...],
    "official": true
  }
}
```

### Chunk référentiel `[libre]`
```json
{
  "chunk_id": "referentiel-candidat-libre_0001",
  "text": "[Référentiel — Candidat libre au baccalauréat général › 1. Définition du statut « candidat individuel »]\n\nEst « candidat individuel » (usuellement « candidat libre ») ...",
  "metadata": {
    "tenant": "terminale",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "orientation",
    "audience": ["libre"],
    "type_doc": "referentiel",
    "notions": [],
    "official": true
  }
}
```

## Tests (13/13 PASS)

- JSONL existent pour les 4 matières
- 100% des chunks valident `ChunkMetadata`
- Audience disciplinaire = `[tous]`, référentiel = `[libre]`, aucun `[aefe]`
- Non-perte de contenu : tous les headings source présents dans les chunks
- Statistiques imprimées

## CI locale

```
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  governance-guard-tests
Total: 5 passed, 0 failed
```

## Décisions prises

- **matiere = "orientation"** pour le référentiel candidat libre (pas disciplinaire, mais relatif au parcours/statut).
- **Philosophie sans taxonomie** : notions vides, fallback documenté.
- **type_doc heuristique** : dérivé du titre de section (programme, épreuve, attendus, etc.).

## Aucun verrou rag-pedago modifié
