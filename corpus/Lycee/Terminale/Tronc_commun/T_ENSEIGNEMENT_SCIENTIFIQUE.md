# Enseignement scientifique — Terminale

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_8_2019-07-25) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie générale — enseignement scientifique.
- Horaire : 2 h/semaine.
- Collection cible : `rag_nexus_es_terminale_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_8_2019-07-25)
- **Science, climat et société** : Le climat : enjeux scientifiques et sociétaux.
- **Le futur des énergies** : Choix énergétiques et impacts.
- **Une histoire du vivant** : Évolution et histoire du vivant.
- **Des modèles pour comprendre** : Modélisation et développement durable.

## 3. Épreuves
### Évaluations en terminale
- Matières du tronc commun : contrôle continu et/ou évaluations terminales selon la note de service de la session (coefficients declared_or_null).
- Le **Grand oral** (coefficient 10) s'appuie sur deux questions liées aux spécialités.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/enseignement_scientifique/terminale.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=generale`, `matiere=es`, `statut_enseignement=enseignement_scientifique`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
