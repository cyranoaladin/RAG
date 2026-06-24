# Brouillons remplis synthetiques — pilote mathematiques terminale

Ce dossier contient des brouillons YAML remplis pour tester le compilateur offline du
lot 15D.

## Role

- Simuler un petit manifest pilote reel deja renseigne manuellement.
- Verifier la compilation YAML vers JSONL compatible `DocumentMeta`.
- Tester les rejets de placeholders, droits inconnus et chemins interdits.

## Garanties

- Les `source_uri` du brouillon valide utilisent uniquement `synthetic://`.
- Aucun PDF ou document reel n'est present.
- Aucun fichier source correspondant aux `source_uri` n'est cree.
- Aucun dossier `data/staging` n'est cree par ces fixtures.

## Fichiers

- `pilot_manifest.filled.valid.yml` : brouillon rempli nominal.
- `pilot_manifest.filled.invalid_placeholder.yml` : placeholder restant.
- `pilot_manifest.filled.invalid_unknown_rights.yml` : droits inconnus.
- `pilot_manifest.filled.invalid_forbidden_source.yml` : chemin interdit volontaire.
