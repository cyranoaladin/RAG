# Histoire-Géographie — Terminale

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_8_2019-07-25) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie générale — tronc commun.
- Horaire : 3 h/semaine.
- Collection cible : `rag_nexus_hg_terminale_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_8_2019-07-25)
- **Histoire** : La fragilité des démocraties et la paix dans l'entre-deux-guerres, La guerre froide : affrontement et coexistence, Décolonisation et construction des indépendances, La France et les Républiques : IIIe, IVe, Ve.
- **Géographie** : Aires et mers : un enjeu du monde contemporain, La mondialisation en fonctionnement, L'Union européenne dans la mondialisation.

## 3. Épreuves
### Évaluations en terminale
- Matières du tronc commun : contrôle continu et/ou évaluations terminales selon la note de service de la session (coefficients declared_or_null).
- Le **Grand oral** (coefficient 10) s'appuie sur deux questions liées aux spécialités.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/histoire_geo/terminale_tronc_commun.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=generale`, `matiere=hg`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
