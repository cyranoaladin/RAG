# Mathématiques — Terminale STMG

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_2_2020-02-13) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie technologique STMG — tronc commun.
- Horaire : 3 h/semaine.
- Collection cible : `rag_nexus_maths_terminale_stmg_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_2_2020-02-13)
- **Évolutions** : Évolutions successives et taux moyen, Suites géométriques et seuils.
- **Fonctions** : Fonction logarithme népérien, Dérivation et étude complète de fonctions.
- **Probabilités et statistiques** : Loi binomiale, Loi normale, Échantillonnage et estimation.

## 3. Épreuves
### Évaluations en terminale
- Matières du tronc commun : contrôle continu et/ou évaluations terminales selon la note de service de la session (coefficients declared_or_null).
- Le **Grand oral** (coefficient 10) s'appuie sur deux questions liées aux spécialités.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/maths/terminale_stmg_tc.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=technologique`, `matiere=maths`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
