# Management et Sciences de Gestion et du Numérique — Terminale STMG

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_2_2020-02-13) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie technologique STMG — spécialité.
- Horaire : 6 h/semaine (commun à tous les enseignements spécifiques STMG).
- Collection cible : `rag_nexus_msdgn_terminale_stmg_specialite` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_2_2020-02-13)
- **Management** : Les organisations : structures et fonctionnement, Finalités et stratégie de l'organisation, Le management des hommes.
- **Sciences de gestion et du numérique** : L'information au service de la décision, Systèmes d'information et transformation numérique, Mesure et pilotage de la performance.

## 3. Épreuves
### Épreuves terminales de spécialité
- Deux épreuves écrites de **4 h** chacune, **coefficient 16** chacune (une par spécialité conservée).
- S'ajoute le **Grand oral** (coefficient 10) adossé aux spécialités — voir corpus `Referentiels/REF_GRAND_ORAL.md`.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/stmg/msdgn_terminale.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=technologique`, `matiere=msdgn`, `statut_enseignement=specialite`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
