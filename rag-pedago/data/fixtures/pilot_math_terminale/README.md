# Fixture pilote mathematiques terminale

Ce dossier contient des manifests JSONL synthetiques pour cadrer un futur corpus pilote
metadata-only en mathematiques terminale specialite.

## Role

- Valider le format `DocumentMeta` attendu par les outils existants.
- Tester la chaine quality, readiness, coverage, gate et review package sans document source.
- Couvrir un profil AEFE Tunisie scolarise avec des ressources de specialite mathematiques.

## Contenu

- `manifests/pilot_math_terminale_specialite.valid.jsonl` : lot synthetique nominal.
- `manifests/pilot_math_terminale_specialite.invalid_missing_rights.jsonl` : ligne invalide sans `rights`.
- `manifests/pilot_math_terminale_specialite.invalid_unknown_rights.jsonl` : ligne valide mais non recuperable car `rights=unknown`.

## Interdictions

- Ne pas ajouter de PDF ou document reel dans ce dossier.
- Ne pas remplacer les URI `synthetic://` par des chemins prives.
- Ne pas ouvrir ni creer de fichier cible pour les `source_uri`.
- Ne pas utiliser ce dossier pour une ingestion documentaire reelle.
