# ADR-0048 — Périmètre produit du GO-LIVE : collège, lycée général, STMG

- **Statut** : **Accepté** — décision opérateur du 2026-08-27
- **Date** : 2026-08-27
- **Décideur** : Nexus Réussite (opérateur)
- **Supersède, pour le seul verdict `GO_LIVE_READY`** : le vertical pilote de
  `docs/ROADMAP.md` (« Candidat libre — Terminale générale, spécialités
  Maths + NSI »)
- **S'appuie sur** : ADR-0013, ADR-0015, ADR-0039, ADR-0040, ADR-0041

## Contexte

Le périmètre produit était jusqu'ici lu depuis `docs/ROADMAP.md`, qui fixait un
vertical pilote — Terminale générale, spécialités Maths et NSI — et renvoyait
le reste à une Phase 5 « Mise à l'échelle » postérieure. Un audit du 2026-08-26
en a tiré, correctement au regard des sources d'alors, que
`GO_LIVE_READY` n'exigeait la couverture que de deux collections.

Ce n'est pas ce que l'opérateur attend du produit. La lecture était fidèle aux
documents ; les documents ne décrivaient plus l'intention.

Deux erreurs de raisonnement ont accompagné cette lecture et doivent être
nommées, parce qu'elles se reproduiraient sinon :

1. le **référentiel scolaire** (`docs/referentiel_scolaire_3e_terminale.md`) a
   été pris pour une autorité de périmètre produit. Il décrit le système
   éducatif français ; il ne dit rien de ce que Nexus vend ;
2. l'**absence de ressources dans le Drive** a été traitée comme une raison de
   retirer un niveau du périmètre. La 6e, sans aucun fichier, a été déclarée
   « pas une collection à créer ». C'est confondre la structure et le contenu.

## Décision

Le périmètre obligatoire du verdict `GO_LIVE_READY` devient :

```
GO_LIVE_REQUIRED_SCOPE = college + lycee_general + stmg
```

- **Collège** — 6e, 5e, 4e, 3e, et les disciplines pour lesquelles Nexus
  possède ou peut identifier des ressources ;
- **Lycée général** — Seconde, Première, Terminale : enseignements communs,
  spécialités, options, enseignements facultatifs, ressources transversales et
  liées au baccalauréat ;
- **STMG** — Première et Terminale : enseignements communs, spécialités,
  enseignements spécifiques et ressources liées aux épreuves.

Les autres séries technologiques (ST2S, STI2D, STL, STD2A, STHR, S2TMD) et la
voie professionnelle restent hors périmètre. C'est la seule exclusion admise,
et elle est explicite.

### Deux axes indépendants

La décision sépare définitivement deux notions que le projet confondait :

| Axe | Signification | Dépend du Drive |
| --- | --- | :-: |
| `CURRICULUM_STRUCTURE_COMPLETE` | le modèle — contrats, taxonomie, catalogue — représente tous les programmes du périmètre | **non** |
| `PEDAGOGICAL_CONTENT_COVERAGE` | il existe assez de matière exploitable pour chaque programme requis | oui |

**Une absence de ressources ne retire jamais une entrée du périmètre
structurel.** Elle produit `COVERAGE_GAP_NO_SOURCE_MATERIAL`, qui est une
disposition honnête — et qui n'est pas une couverture.

Le cas de la 6e le fixe :

```
6E_REQUIRED_BY_PRODUCT_SCOPE = YES
6E_SUPPORTED_BY_CONTRACT     = NO      (enum Niveau incomplet)
6E_DRIVE_SOURCE_FILES        = 0
6E_CONTENT_COVERAGE          = COVERAGE_GAP_NO_SOURCE_MATERIAL
```

L'entrée existe au catalogue cible ; elle n'est pas instanciée physiquement
tant qu'aucune ressource ne la justifie ; et le jour où des ressources 6e
arrivent, aucune décision d'architecture n'est à reprendre.

### Deux verdicts distincts

`GO_LIVE_READY` ne peut plus être rendu par un seul chiffre :

- `STRUCTURAL_GO_LIVE_READINESS` — le modèle couvre le périmètre ;
- `CONTENT_GO_LIVE_READINESS` — la matière existe et est ingérée.

Si le Drive ne contient réellement rien pour une partie obligatoire, le verdict
est `STRUCTURE_READY = YES / CONTENT_READY = NO / BLOCKER =
SOURCE_MATERIAL_MISSING`. Rien n'est fabriqué pour combler.

### Le catalogue actuel n'est pas l'autorité

Les 62 collections de `rag_collections.yml` sont un état historique. Le
périmètre se dérive dans ce sens, et jamais dans l'autre :

```
OFFICIAL_CURRICULUM_SCOPE → EXPECTED_LOGICAL_COLLECTIONS → GDRIVE_RESOURCES
    → PLACEMENTS → ACTIVATED / RETRIEVABLE COLLECTIONS
```

Une collection n'est créée ni parce qu'une matière existe en théorie, ni parce
qu'un dossier porte son nom dans le Drive. Le Drive est une source
documentaire, pas l'autorité de définition du système scolaire.

### Multi-niveaux : le cycle ne remplace pas le niveau

73 % du corpus Drive est transversal — 862 fichiers Cycle 4, 938 fichiers
lycée multi-niveaux. Ces ressources doivent emprunter le modèle de placement
multiple (`rag_artifact_placements`, migration 004) :

```
1 artefact  →  placement 5e  +  placement 4e  +  placement 3e
```

sans duplication physique du document. `cycle4` reste utile comme métadonnée
de provenance ou de classification transversale ; il ne se substitue jamais à
`cinquieme`, `quatrieme` ou `troisieme`, sous peine de détruire le routage par
niveau.

## Conséquences

- **Blocker structurel ouvert** : l'enum `Niveau` de `nexus-contracts` ne
  connaît ni `sixieme` ni `cinquieme`. Une évolution SemVer et son ADR sont
  requises. Aucun alias `sixieme → cycle4` n'est acceptable.
- **Catalogue incomplet** : aucune collection 6e ni 5e ; aucune collection
  d'enseignement commun STMG, alors que le Drive porte déjà 8 fichiers
  `STMG/COMMUN`.
- Un chantier distinct `FULL_CURRICULUM_COVERAGE` est ouvert. Il se ferme
  quand la matrice de programmes prouve la couverture structurelle des neuf
  couples niveau×voie du périmètre.
- Les releases intermédiaires restent permises et utiles.
  **`FIRST_SERVABLE_RELEASE` n'est pas `GO_LIVE_READY`** : son membership
  porte `release_type: intermediate` et `go_live_complete: false`, et un test
  interdit qu'un rapport en dérive un verdict final.
- `docs/ROADMAP.md` n'est plus l'autorité de périmètre pour ce verdict. Son
  vertical pilote survit dans `go_live_scope.yml` sous `historical_pilot`,
  marqué `superseded_for_go_live_verdict`.

## Ce que cette ADR n'autorise pas

Elle ne rend aucune collection instanciée, n'autorise aucune ingestion,
n'active aucun scope et ne lève aucun verrou de gouvernance. Chaque activation
continue d'exiger sa propre autorité nommée, conformément à
`activation_authorities.yml`.
