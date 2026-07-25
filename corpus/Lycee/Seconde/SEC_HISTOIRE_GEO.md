# Histoire-Géographie — Seconde

> Fiche corpus. Gabarit : identité × programme × épreuve × spécificité candidat libre × attendus × notes RAG.
> Sources : programme officiel (BOEN_special_1_2019-01-22) ; eduscol ; notes de service de la session (declared_or_null).

## 1. Identité
- Niveau : **seconde** — voie générale — tronc commun.
- Horaire : 3 h/semaine.
- Collection cible : `rag_nexus_hg_seconde_tc` (ADR-0015 — convention rag_nexus_{matiere}_{niveau}_{voie}_{statut}).

## 2. Programme officiel (BOEN_special_1_2019-01-22)
- **Histoire** : Les mondes anciens : cités et empires, Sociétés médiévales : XIe-XVe siècle, Transformations de l'Europe et ouverture atlantique (XVIe-XVIIIe), Révolutions et empires (1770-1815).
- **Géographie** : Sociétés et environnements : équilibres fragiles, Territoires, populations et développement, Mobilités et transhumances.

## 3. Épreuves
### Pas d'examen national en seconde
- Évaluation en contrôle continu ; la classe de seconde prépare le choix des **3 enseignements de spécialité** de première (voie générale) ou de la série technologique.
- Les moyennes de seconde alimentent le contrôle continu du baccalauréat.

## 4. Spécificité candidat libre
Le candidat libre passe les **épreuves ponctuelles** qui se substituent au contrôle continu, dans les mêmes conditions que les scolarisés. Voir `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` pour le cadrage complet du parcours.

## 5. Attendus / compétences évaluées
Compétences mobilisées : analyser, argumenter, mobiliser des références précises, rédiger avec rigueur. La notation valorise la **méthode, la justification et la clarté de la rédaction**.

## 6. Notes RAG / corpus
- Taxonomie : `services/rag-pedago/taxonomy/histoire_geo/seconde_tronc_commun.yml` (thèmes → notions → compétences).
- Indexer par **thème puis notion** ; métadonnées obligatoires : `niveau=seconde`, `voie=generale`, `matiere=hg`, `statut_enseignement=tronc_commun`, `session` (declared_or_null), `audience` (libre/aefe/tous).
- Lier chaque notion aux ressources ingérées par les agents continus (ADR-0016) : eduscol en priorité, Wikipedia/Wikiversité (CC-BY-SA) en complément.
- Tout contenu sans droits établis part en `rag_nexus_quarantine` (non retrievable).
