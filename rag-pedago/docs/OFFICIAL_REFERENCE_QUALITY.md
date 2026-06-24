# Qualité des références officielles dans les manifests

Le lot 10 branche `data/reference/` dans la politique qualité des manifests. Les documents officiels, réglementaires et d'examen peuvent maintenant être bloqués avant toute écriture ledger si leurs références institutionnelles sont absentes ou invalides.

## Quand les official refs sont obligatoires

Pour `programme_officiel` et `ressource_officielle` :

- `official_level_ref` est obligatoire ;
- `official_subject_ref` est obligatoire si le document porte une matière ;
- au moins une source ou claim vérifiée doit soutenir le document ;
- `official_claim_refs` est obligatoire pour les documents réglementaires.

Pour les documents d'examen (`annale`, `sujet_zero`, `corrige`, `bareme`, `bac_blanc`, `brevet_blanc`, `grille_evaluation`, `grille_grand_oral`) :

- `official_exam_ref` est obligatoire ;
- `candidate_status_ref` est obligatoire si le contenu dépend du statut candidat ;
- `official_exam_ref` et `candidate_status_ref` doivent exister dans le référentiel.

## official_source_refs vs official_claim_refs

- `official_source_refs` pointe vers les pages, BO ou sources institutionnelles consultées.
- `official_claim_refs` pointe vers les affirmations réglementaires structurées, par exemple `bac_general_40_60`.

Une source prouve l'origine. Une claim prouve le champ ou la règle soutenue.

## candidate_status_ref vs establishment_context_ref

`candidate_status_ref` décrit la modalité d'examen : `scolarise`, `candidat_individuel`, `cned_reglemente`, `cned_libre`.

`establishment_context_ref` décrit le contexte : `aefe`, `systeme_tunisien`, `double_cursus`, `cned`.

AEFE est déprécié comme statut candidat. `candidate_status_ref=aefe` produit un warning par défaut et devient bloquant en mode strict.

## pending vs verified

Une source ou claim `pending` peut être conservée comme information à vérifier, mais elle ne doit pas soutenir seule une règle définitive. En mode strict, les sources ou claims pending deviennent bloquantes pour les documents réglementaires.

## Compatibilité applies_to

Depuis le lot 10.5, une `official_source_ref` ou `official_claim_ref` doit
s'appliquer à au moins une référence portée par le document :

- `official_level_ref` ;
- `official_exam_ref` ;
- `official_subject_ref` ;
- `candidate_status_ref` ;
- `establishment_context_ref`.

Un mismatch produit :

- `official_claim_applies_to_mismatch` ;
- `official_source_applies_to_mismatch`.

Ces issues sont bloquantes par défaut, car une source vraie mais hors périmètre
ne doit pas justifier une règle appliquée au mauvais niveau, examen ou statut
candidat.

Depuis le lot 11, cette compatibilité passe par
`OfficialReferenceResolver`. Une source qui s'applique à `bac_general` peut
couvrir `grand_oral` ou `bac_specialite_ecrit` via le graphe officiel. Une
source DNB ne peut pas couvrir un document bac, même si les deux documents
portent une matière commune.

Depuis le lot 11.5, les issues `official_source_applies_to_mismatch` et
`official_claim_applies_to_mismatch` portent une `compatibility_explanation`.
Les rapports JSON conservent cette structure, et les rapports Markdown
affichent la section `Official reference compatibility`.

## Contextes d'établissement

`establishment_context_ref` est optionnel par défaut. Lorsqu'il est renseigné,
il doit exister dans le référentiel. Un contexte inconnu produit
`unknown_establishment_context_ref` et bloque la qualité.

Cas attendus :

- `candidate_status_ref=scolarise` + `establishment_context_ref=aefe` : valide ;
- `candidate_status_ref=aefe` : warning par défaut, bloquant en strict ;
- `establishment_context_ref=double_cursus` : contexte accepté, la carte
  d'examen reste nécessaire pour trancher les épreuves concrètes.

## Mode strict vs non strict

Par défaut :

- refs inconnues : bloquantes ;
- claims pending : bloquantes pour les documents réglementaires ;
- `candidate_status_ref=aefe` : warning.

En mode strict :

- `candidate_status_ref=aefe` devient bloquant ;
- les droits inconnus restent bloquants sauf `--allow-unknown-rights` ;
- les documents d'examen sans `official_exam_ref` restent bloquants.

## Exemple valide

```json
{
  "doc_id": "programme-maths-terminale",
  "type_doc": "programme_officiel",
  "official_level_ref": "terminale_generale",
  "official_subject_ref": "mathematiques",
  "official_source_refs": ["education_maths_reforme_lycee"],
  "official_claim_refs": ["terminale_generale_two_specialties"]
}
```

## Exemple invalide

```json
{
  "doc_id": "programme-sans-source",
  "type_doc": "programme_officiel",
  "official_level_ref": "terminale_generale"
}
```

Ce manifest est bloqué : il manque `official_subject_ref` et une source ou claim vérifiée.
