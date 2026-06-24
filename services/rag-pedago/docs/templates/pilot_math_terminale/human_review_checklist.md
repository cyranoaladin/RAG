# Checklist humaine — manifest pilote mathematiques terminale

Cette checklist doit etre remplie avant de transformer un brouillon en manifest JSONL
reel. Elle ne remplace pas le gate, le review package ou l'approbation humaine.

## Identite du lot

- [ ] Batch id defini.
- [ ] Perimetre confirme : terminale generale, specialite mathematiques.
- [ ] Zone confirmee : AEFE Tunisie.
- [ ] Statut candidat confirme : scolarise.

## Sources et fichiers

- [ ] Aucun document ne vient du RAG historique.
- [ ] Aucun fichier secret, credential, fichier d'environnement, export prive ou upload sensible.
- [ ] Les fichiers sources reels seront places dans un dossier de staging dedie plus tard.
- [ ] Aucun PDF n'est ajoute dans ce dossier de templates.
- [ ] Le SHA-256 de chaque fichier sera calcule manuellement au moment autorise.

## Droits et visibilite

- [ ] Chaque document a un `rights` explicite.
- [ ] Aucun document `rights=unknown` n'est marque recuperable.
- [ ] Les ressources Nexus proprietaires sont `visibility=internal`.
- [ ] Les ressources officielles publiques sont `rights=officiel_public`.

## Metadonnees pedagogiques

- [ ] `niveau=terminale`.
- [ ] `voie=generale`.
- [ ] `matiere=mathematiques`.
- [ ] `statut_enseignement=specialite`.
- [ ] Notions controlees contre `taxonomy/maths/terminale_specialite.yml`.
- [ ] Competences controlees contre la taxonomie commune.

## References officielles

- [ ] `official_level_ref=terminale_generale`.
- [ ] `official_subject_ref=mathematiques`.
- [ ] `official_exam_ref=bac_specialite_ecrit` pour les documents d'examen.
- [ ] Les documents officiels citent une source ou claim verifiee.
- [ ] Aucune source `pending` ne soutient seule une decision reglementaire.

## AEFE et candidat

- [ ] `candidat=scolarise`.
- [ ] `candidate_status_ref=scolarise`.
- [ ] `establishment_context_ref=aefe`.
- [ ] `extra.zone=aefe_tunisie`.
- [ ] Aucun document candidat individuel n'est melange au batch.

## Validation avant import futur

- [ ] Validateur offline du template execute.
- [ ] Manifest JSONL futur valide contre `DocumentMeta`.
- [ ] Readiness executee.
- [ ] Coverage executee avec notions prioritaires.
- [ ] Gate execute.
- [ ] Review package genere.
- [ ] Approbation humaine obtenue.
