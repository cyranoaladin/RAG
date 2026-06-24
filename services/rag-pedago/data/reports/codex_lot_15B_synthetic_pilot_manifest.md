# Rapport Codex — Lot 15B : corpus pilote synthetique metadata-only

## 1. Objectif

Creer un corpus pilote synthetique pour mathematiques terminale specialite afin de
valider uniquement la chaine metadata-only existante :

```text
manifest synthetique -> qualite -> readiness -> coverage -> gate -> review package
```

Aucun document reel, PDF, scraping, reseau, embedding, Qdrant ou ingestion documentaire
n'a ete introduit.

## 2. Point de depart Git

Le lot demarre apres le commit valide :

```text
f6f98a7 docs: map project state and define pilot corpus protocol
```

Le depot etait propre au lancement du lot 15B.

## 3. Fichiers crees ou modifies

Fichiers crees :

- `data/fixtures/pilot_math_terminale/README.md`
- `data/fixtures/pilot_math_terminale/manifests/pilot_math_terminale_specialite.valid.jsonl`
- `data/fixtures/pilot_math_terminale/manifests/pilot_math_terminale_specialite.invalid_missing_rights.jsonl`
- `data/fixtures/pilot_math_terminale/manifests/pilot_math_terminale_specialite.invalid_unknown_rights.jsonl`
- `tests/unit/test_pilot_math_terminale_fixtures.py`
- `data/reports/codex_lot_15B_synthetic_pilot_manifest.md`

Fichiers modifies :

- Aucun fichier existant n'a ete modifie.

## 4. Format des manifests synthetiques

Les manifests sont des JSONL compatibles avec `DocumentMeta`.

Principes retenus :

- `source_uri` utilise uniquement le schema `synthetic://pilot/maths-terminale/...`.
- Aucun fichier source correspondant n'est cree.
- Les SHA-256 sont des valeurs synthetiques valides de 64 caracteres hexadecimaux.
- Les refs officielles sont renseignees pour les documents officiels et d'examen.
- Le profil commun est terminale generale, specialite mathematiques, candidat scolarise,
  contexte d'etablissement AEFE.

## 5. Documents synthetiques couverts

Le manifest valide contient 7 documents metadata-only :

- reference de programme officiel ;
- cours sur les suites et limites ;
- fiche methode sur le raisonnement par recurrence ;
- exercices corriges sur probabilites conditionnelles et loi binomiale ;
- sujet type bac specialite mathematiques ;
- bareme de sujet type bac ;
- ressource algorithmique Python.

## 6. Notions couvertes

Notions prioritaires couvertes :

- `suites`
- `recurrence`
- `limites_de_suites`
- `probabilites_conditionnelles`
- `loi_binomiale`
- `algorithmique_python`

Competences utilisees :

- `chercher`
- `modeliser`
- `raisonner`
- `calculer`
- `communiquer`
- `programmer`

## 7. Droits et visibilite

Le manifest valide couvre :

- `officiel_public` avec `visibility=public` pour les references et documents d'examen publics ;
- `nexus_proprietaire` avec `visibility=internal` pour les ressources internes Nexus ;
- `usage_interne` avec `visibility=internal` pour les fiches et exercices internes.

La fixture `invalid_unknown_rights` valide le cas `rights=unknown`, qui reste stockable au
niveau schema mais non recuperable (`is_retrievable=false`).

## 8. Fixtures invalides

Deux fixtures invalides ou non exploitables ont ete ajoutees :

- `pilot_math_terminale_specialite.invalid_missing_rights.jsonl` : document sans champ
  `rights`, refuse par `DocumentMeta`.
- `pilot_math_terminale_specialite.invalid_unknown_rights.jsonl` : document avec
  `rights=unknown`, valide mais signale comme non recuperable.

## 9. Chaine quality/readiness/coverage/gate/review

La chaine a ete executee dans le test unitaire
`test_pilot_manifest_chain_reaches_review_package` sur une copie temporaire contenant
uniquement le manifest valide.

Resultats observes :

- readiness : `ready` ;
- coverage : `coverage_ok` ;
- gate : `ready_for_controlled_import` ;
- review package : `ready_for_review`.

La chaine n'a pas ete executee sur le dossier complet des fixtures, car ce dossier contient
volontairement des manifests invalides destines aux tests de rejet.

## 10. Tests ajoutes ou modifies

Ajout :

- `tests/unit/test_pilot_math_terminale_fixtures.py`

Les tests verifient :

- existence du manifest valide ;
- minimum de 5 documents ;
- validation `DocumentMeta` ;
- absence de besoin de fichier source reel ;
- couverture des notions prioritaires ;
- rejet d'un document sans `rights` ;
- comportement non recuperable pour `rights=unknown` ;
- absence de chemins interdits ou secrets dans les fixtures ;
- execution de la chaine readiness, coverage, gate et review package sur le manifest valide.

## 11. Tests executes

Commandes executees pendant le lot :

```bash
pytest tests/unit/test_pilot_math_terminale_fixtures.py -q
make doctor
make project-doctor
make test
```

## 12. Resultats

Resultats :

```text
pytest tests/unit/test_pilot_math_terminale_fixtures.py -q : 8 passed
make doctor : OK
make project-doctor : OK
make test : 284 passed
```

## 13. Limites volontaires

- Aucun manifest de production n'a ete cree.
- Aucun dossier de staging documentaire n'a ete cree.
- Aucun PDF ou fichier source reel n'a ete ajoute.
- Aucun `source_uri` n'a ete ouvert.
- Aucun import dans le ledger n'a ete lance hors dry-run de validation.
- Aucune taxonomie officielle n'a ete modifiee.
- `schema/document.py` n'a pas ete modifie.

## 14. Risques restants

- Le corpus reste synthetique : il valide la structure et les controles, pas le contenu
  pedagogique reel.
- Les futures ressources reelles devront etre soumises a review humaine et hashes de manifests.
- Le futur lot 15C devra definir un mode de preparation de manifest reel sans lecture
  automatique de documents sources.

## 15. Incident de contexte corrige

Pendant le lot 15B, un fichier de test a ete cree par erreur comme fichier non suivi
dans le depot interdit `/home/alaeddine/Bureau/rag-local`.

Correction appliquee :

- le fichier accidentel non suivi a ete supprime ;
- le depot interdit a ete verifie par `git status --short --branch` ;
- l'etat restant observe correspond aux fichiers non suivis deja presents avant le lot ;
- toutes les modifications effectives du lot ont ensuite ete reprises avec chemins explicites
  vers `/home/alaeddine/Bureau/rag-pedago`.

Impact :

- aucun fichier suivi du depot interdit n'a ete modifie ;
- aucun fichier du RAG historique n'a ete copie ;
- le lot 15B reste limite a des fixtures synthetiques metadata-only dans `rag-pedago`.

## 16. Verdict

COMMIT_RECOMMANDÉ

## 17. Recommandation pour le lot 15C

Preparer un protocole de manifest pilote reel limite, avec collecte manuelle controlee des
metadonnees, review obligatoire, et toujours sans parsing PDF ni ingestion documentaire tant
qu'un lot dedie n'a pas ete valide.
