# Manifest gate

Le gate report fusionne les décisions readiness et coverage pour produire une décision humaine finale avant toute ingestion documentaire.

## Différence readiness / coverage / gate

- `readiness` vérifie si les manifests sont techniquement et juridiquement importables selon la politique qualité.
- `coverage` vérifie si les métadonnées déclarées couvrent les notions connues des taxonomies contrôlées.
- `gate` combine ces deux vues et donne une décision finale : bloqué, revue nécessaire ou prêt pour import contrôlé.

## Règles de décision

1. Si readiness vaut `blocked`, le gate vaut `blocked`.
2. Sinon, si coverage vaut `coverage_insufficient`, le gate vaut `blocked`.
3. Sinon, si readiness vaut `ready_with_warnings`, le gate vaut `review_required`.
4. Sinon, si coverage vaut `coverage_partial`, le gate vaut `review_required`.
5. Sinon, le gate vaut `ready_for_controlled_import`.

## Statuts

- `blocked` : les manifests doivent être corrigés avant tout import.
- `review_required` : une validation humaine est nécessaire avant import contrôlé.
- `ready_for_controlled_import` : un import contrôlé de manifests peut être lancé.

## Garanties

- aucun `source_uri` n'est ouvert ;
- aucun appel réseau n'est effectué ;
- aucune ingestion documentaire n'est lancée ;
- aucun PDF n'est lu ou parsé ;
- aucune connexion Qdrant ou PostgreSQL n'est utilisée.

## Limites

Le gate est une décision sur les métadonnées déclarées. Il ne valide pas le contenu réel des documents, ne télécharge rien et ne prépare aucun chunk. Même en statut `ready_for_controlled_import`, le parsing documentaire reste interdit tant qu'un lot dédié n'a pas défini ses règles.

## Commande

```bash
python -m rag_pedago.imports.gate_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
```

## Fixtures

- `batch_001` : fixture volontairement problématique, doit être bloquée par readiness puis par le gate.
- `batch_clean_001` : fixture nominale, doit passer readiness, coverage et gate avec le statut `ready_for_controlled_import`.
- `batch_official_profiles_clean` : fixture nominale multi-profils pour
  troisième/DNB, seconde GT, première, terminale, candidat individuel, AEFE
  scolarisé et double cursus.

## Références officielles

Le gate hérite des issues de qualité official refs. Un document officiel ou
d'examen avec une référence inconnue, absente ou incohérente peut bloquer le
gate avant tout import contrôlé. Le batch nominal `batch_clean_001` porte des
refs officielles vérifiées et sert de chemin de référence.

Depuis le lot 10.5, le gate bloque aussi les sources ou claims dont
`applies_to` ne correspond à aucune référence déclarée par le document. Ce
contrôle évite d'utiliser une source DNB pour justifier un document bac, ou une
claim candidat individuel pour un document scolarisé sans lien explicite.

Depuis le lot 11.5, le gate inclut les explications de compatibilité dans son
JSON et dans une section Markdown `Official reference compatibility`. La
fixture `batch_official_mismatch` doit être bloquée et sert de cas d'audit.

Depuis le lot 12, le JSON gate contient aussi les hashes SHA-256 des manifests
du batch. Ces hashes rendent possible une approbation humaine qui devient
invalide si le batch est modifié avant import contrôlé.
