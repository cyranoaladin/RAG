# Spécialité SVT — Terminale

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_8_2019-07-25) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **terminale** — voie générale — spécialité.
- Horaire : 6 h/semaine.
- Collection cible : `rag_nexus_svt_terminale_specialite` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_8_2019-07-25)
- **Stabilité et variabilité des génomes et évolution** : Brassage génétique et variabilité, Mécanismes de l'évolution.
- **La procréation** : Sexualisation chez les plantes, Contrôle de la reproduction.
- **L'origine du monde microbien** : Origine du monde microbien et biosphère.
- **Climat et énergies** : Le climat : passé et futur, Énergies : choix rationnels.
- **Comportements, mouvement et système nerveux** : Système nerveux et commande du mouvement.

## 3. Épreuves
### Épreuves terminales de spécialité
- Deux épreuves écrites de **4 h** chacune, **coefficient 16** chacune (une par spécialité conservée).
- S'ajoute le **Grand oral** (coefficient 10) adossé aux spécialités — voir corpus `Referentiels/REF_GRAND_ORAL.md`.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : chercher, modéliser, représenter, raisonner, calculer, communiquer. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/svt/terminale_specialite.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=terminale`, `voie=generale`, `matiere=svt`, `statut_enseignement=specialite`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
