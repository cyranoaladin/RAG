# Philosophie — Terminale

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_8_2019-07-25) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie générale — tronc commun.
- Horaire : 4 h/semaine.
- Collection cible : `rag_nexus_philo_terminale_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_8_2019-07-25)
- **Le sujet** : La conscience, L'inconscient, L'existence et le temps.
- **La culture** : L'art, La technique, La nature, La religion.
- **La raison** : La raison, La science, La théorie et l'expérience, La vérité.
- **La morale** : Le devoir, Le bonheur, La liberté, Le travail.
- **La politique** : L'État, La justice.

## 3. Épreuves
### Épreuve terminale de philosophie
- Écrit **4 h**, **coefficient 8**, au choix : dissertation ou explication de texte.
- Évaluation sur les 17 notions officielles du programme.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/philosophie/terminale_tronc_commun.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=generale`, `matiere=philosophie`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
