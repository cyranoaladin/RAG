# Rapport Codex — Lot 15C : kit de preparation manifest reel metadata-only

## 1. Objectif

Creer un kit de preparation pour un futur manifest pilote reel de mathematiques
terminale specialite, sans document reel, sans PDF, sans ingestion, sans parsing,
sans scraping, sans reseau et sans Qdrant.

Le lot fournit :

- des templates a remplir manuellement ;
- une checklist de validation humaine ;
- un validateur offline de brouillon ;
- des tests unitaires ;
- une cible Makefile non destructive.

## 2. Point de depart Git

Le lot demarre apres le commit valide :

```text
9b44fb4 test: add metadata-only pilot math corpus fixtures
```

Le depot etait propre au debut du lot.

## 3. Fichiers crees ou modifies

Fichiers crees :

- `docs/templates/pilot_math_terminale/README.md`
- `docs/templates/pilot_math_terminale/pilot_manifest.template.yml`
- `docs/templates/pilot_math_terminale/pilot_manifest.template.jsonl`
- `docs/templates/pilot_math_terminale/human_review_checklist.md`
- `docs/templates/pilot_math_terminale/metadata_collection_sheet.csv`
- `rag_pedago/imports/pilot_manifest_template.py`
- `tests/unit/test_pilot_manifest_template.py`
- `data/reports/codex_lot_15C_real_manifest_preparation_kit.md`

Fichiers modifies :

- `Makefile`

## 4. Templates crees

Le template YAML contient 7 blocs d'exemple :

- programme ou reference officielle ;
- cours sur les suites ;
- fiche methode sur recurrence ;
- exercice corrige sur probabilites conditionnelles et loi binomiale ;
- annale ou sujet type bac ;
- bareme ;
- ressource algorithmique Python.

Le template JSONL fournit les memes familles de documents sous une forme proche du
format final attendu par l'import manifest.

Les templates utilisent uniquement des placeholders explicites :

- `A_REMPLIR_*`
- `A_CONFIRMER`

Ils ne pointent vers aucun document reel et ne sont pas des manifests de production.

## 5. Checklist humaine

La checklist `human_review_checklist.md` couvre :

- l'identite du batch ;
- l'origine des fichiers ;
- les droits et visibilites ;
- les metadonnees pedagogiques ;
- les references officielles ;
- la distinction candidat scolarise / AEFE / candidat individuel ;
- les controles avant import futur.

## 6. Validateur offline

Le module `rag_pedago.imports.pilot_manifest_template` fournit :

- `load_pilot_manifest_template(path)` ;
- `iter_template_items(data)` ;
- `validate_template_item_shape(item)` ;
- `find_unfilled_placeholders(item)` ;
- `validate_no_real_source_access(item)` ;
- `validate_manual_metadata_rules(item)` ;
- `build_template_validation_report(path)`.

La commande :

```bash
python -m rag_pedago.imports.pilot_manifest_template docs/templates/pilot_math_terminale/pilot_manifest.template.yml
```

affiche un rapport texte non destructif. Elle ne lit aucun `source_uri`, ne verifie
pas l'existence de fichier source et ne calcule aucun hash.

## 7. Regles controlees

Le validateur signale :

- champs obligatoires absents ;
- placeholders `A_REMPLIR` ou `A_CONFIRMER` ;
- `rights=unknown` ;
- `source_uri` pointant vers `/srv/nexusreussite/rag-ui` ;
- `source_uri` pointant vers `/home/alaeddine/Bureau/rag-local` ;
- `source_uri` contenant un marqueur de secret ou credential ;
- incoherence `candidat=scolarise` avec `candidate_status_ref` different ;
- incoherence AEFE Tunisie sans `establishment_context_ref=aefe` ;
- incoherence `establishment_context_ref=aefe` sans `extra.zone=aefe_tunisie`.

## 8. Tests ajoutes ou modifies

Ajout :

- `tests/unit/test_pilot_manifest_template.py`

Les tests couvrent :

- presence des templates ;
- lecture YAML ;
- detection des placeholders ;
- absence d'ouverture de `source_uri` ;
- signalement de `rights=unknown` ;
- signalement des chemins interdits ;
- signalement des chemins de type secret ;
- incoherences AEFE ;
- incoherences candidat ;
- execution CLI ;
- absence de PDF et absence de creation `data/staging`.

## 9. Tests executes

Commandes deja executees pendant le lot :

```bash
pytest tests/unit/test_pilot_manifest_template.py -q
make pilot-template-check
make doctor
make project-doctor
make test
```

## 10. Resultats

Resultats intermediaires :

```text
pytest tests/unit/test_pilot_manifest_template.py -q : 16 passed
make pilot-template-check : status needs_completion, 7 items, 49 issues attendues de placeholders
make doctor : OK
make project-doctor : OK
make test : 300 passed
```

## 11. Limites volontaires

- Aucun document reel n'a ete ajoute.
- Aucun PDF n'a ete cree ou copie.
- Aucun dossier `data/staging` n'a ete cree.
- Aucun `source_uri` n'a ete ouvert.
- Aucun hash de document source n'a ete calcule.
- Aucun manifest de production n'a ete cree.
- Aucune ingestion documentaire n'a ete lancee.
- Aucune taxonomie officielle et aucun schema documentaire n'ont ete modifies.

## 12. Risques restants

- Le kit ne valide pas encore un manifest reel rempli.
- Le calcul des SHA-256 et la collecte des droits restent des actions humaines futures.
- Les documents reels devront passer par gate, review package et approbation avant import.
- Tout parsing PDF doit rester interdit tant qu'un lot dedie n'est pas valide.

## 13. Controles renforces avant commit

Le micro-lot 15C-hardening ajoute les controles suivants :

- chargement reel du template JSONL par le validateur offline ;
- scan de tous les fichiers de `docs/templates/pilot_math_terminale/` contre les chemins
  interdits et marqueurs de secrets ;
- verification que le CLI ne cree aucun artefact dans le dossier de templates ;
- verification que les templates YAML et JSONL restent `needs_completion` et ne peuvent pas
  etre confondus avec un manifest pret ;
- verification en lecture seule que le depot interdit `/home/alaeddine/Bureau/rag-local`
  ne contient ni le test de template ni le dossier de templates accidentel.

## 14. Verdict

COMMIT_RECOMMANDÉ

## 15. Recommandation pour le lot 15D

Creer un brouillon de manifest metadata-only rempli manuellement a partir de ce kit,
sur un tres petit nombre de ressources autorisees, puis le soumettre uniquement aux
validateurs offline, readiness, coverage, gate et review package, sans lecture de PDF
ni ingestion documentaire.
