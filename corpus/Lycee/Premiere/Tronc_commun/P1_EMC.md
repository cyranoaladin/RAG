# EMC — Première

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_1_2019-01-22) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **premiere** — voie générale — EMC.
- Horaire : Environ 18 h/an.
- Collection cible : `rag_nexus_emc_premiere_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_1_2019-01-22)
- **La puissance publique** : L'État et l'action publique, L'action des citoyens dans la démocratie.

## 3. Épreuves
### Évaluations en première
- Matières du tronc commun : évaluations communes de contrôle continu (coefficients fixés par note de service de la session — declared_or_null).
- Tous les élèves passent l'**épreuve anticipée de mathématiques** (écrit 2 h, sans calculatrice, coefficient 2, sujet différencié selon la voie).
- Les spécialités conservées en terminale donnent lieu aux épreuves terminales ; une spécialité abandonnée est évaluée sur le programme de première.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/emc/premiere.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=premiere`, `voie=generale`, `matiere=emc`, `statut_enseignement=emc`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
