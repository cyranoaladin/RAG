# LOT — Registre des URL sources (`URL_SOURCE_REGISTRY`)

Branche `glr/url-registry`. Périmètre : les 150 artefacts scellés de
`services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml`
et l'univers d'URL découvert dans les autorités de gouvernance.

## 1. Le problème

L'évidence de fraîcheur portait 150 artefacts dont **12 seulement** avaient une
`current_download_url`. Les 138 autres l'avaient à `null` : aucune URL, donc
aucune manière de rejouer le téléchargement, donc aucune manière de répondre à
« ce document est-il encore celui que le ministère publie ? ».

Le catalogue de moisson, lui, connaît pour chaque document l'URL de la **page qui
le référence** — jamais l'URL du document. Et ces pages de navigation répondent
**403** : protection anti-robot du fournisseur, qui n'est pas contournée.

## 2. Recherche de la relation `navigation → document direct`

**Question mesurée :** cette relation existe-t-elle quelque part dans les
autorités disponibles ?

### 2.1 Plan de contrôle Drive — fouillé en entier

37 fichiers textuels du plan de contrôle téléchargés et fouillés :
`EDUSCOL_CATALOGUES/` (catalogue complet TSV + CSV, par-scope, par-niveau, 7
index), `EDUSCOL_MANIFESTES/` (par-scope, par-niveau, `corpus.sha256`,
`metadonnees-exports.sha256`), `EDUSCOL_META/`, `EDUSCOL_RUN/`,
`EDUSCOL_RAPPORTS_TECHNIQUES/`, `EDUSCOL_README/`, et l'intégralité de
`00_ADMIN/` (`eduscol_affectations.tsv`, `eduscol_catalogue_unique.tsv`,
`eduscol_duplicates_content.tsv`, `geogebra_index.tsv`, `duplicates.tsv`,
`copy_events.tsv`, `TREE.txt`, `SHA256SUMS.txt`, `BUILD_INFO.json`, …).

| Mesure | Valeur |
|---|---|
| Fichiers d'autorité fouillés | 37 |
| Occurrences de `sites/default/files` (motif d'URL directe) | **0** |
| URL présentes, toutes de navigation | 111 distinctes, dans 4 fichiers seulement |
| Colonne `objet_source` du catalogue | `objects/sha256/…` — adresse locale, pas une URL |

### 2.2 Métadonnées Drive des objets

Sondées sur 15 PDF de `01_EDUSCOL_OFFICIEL` et 15 hors zone :
`description`, `properties`, `appProperties`, `contentHints`. La `description`
répète le nom de fichier. **Aucune URL source.**

### 2.3 Le porteur réel de la relation — identifié, puis constaté absent

Le moissonneur qui a produit le corpus est `eduscol-pdf-harvester v1.10.0`. Son
schéma SQLite (lu dans l'archive de release
`eduscol-pdf-harvester-v1.10.0.tar.gz`) **contient bien la relation** :

```sql
CREATE TABLE urls (url PRIMARY KEY, canonical_url, final_url, status_code,
                   content_type, etag, last_modified, sha256, kind, transport, …);
CREATE TABLE references_ (source_url NOT NULL, target_url NOT NULL,
                          scope, anchor_text, section_path, …);
```

`references_(source_url → target_url)` joint à `urls(kind='pdf', sha256)` puis à
`documents(sha256)` **est** exactement la relation cherchée. Le rapport technique
`synthese-sqlite.txt` versé au plan de contrôle la chiffre :
**2 738 lignes `urls` (dont 2 463 `pdf`) et 6 622 lignes `references_`**.

Mais :

- la base qui les porte, `.../full-20260804T230753+0100/01-corpus-technique/catalog.sqlite3`,
  **n'a pas été versée au plan de contrôle Drive** (0 objet SQLite dans les 3 871
  objets inventoriés) ;
- son répertoire de run local **n'existe plus** ;
- l'export vers le catalogue **a laissé tomber la colonne** : `document_scopes.source_url`
  (navigation) est exporté en `url_source`, `urls.url` (direct) ne l'est pas.

La seule base survivante, `archives-eduscol-avant-v1.4-20260804-063641/catalog.sqlite3`,
est un run avorté : 46 URL, **toutes de navigation, toutes en erreur 403**,
`references_` et `documents` **vides**.

### 2.4 Réponse

**La relation `navigation → document direct` a existé et n'existe plus dans
aucune autorité accessible.** Ce n'est pas une supposition : c'est la conjonction
de trois mesures — 0 occurrence sur 37 autorités, schéma du porteur identifié,
porteur absent du plan de contrôle et supprimé localement.

## 3. Tentative réseau réelle — 123 URL, aucun contournement

Sonde avec agent identifié portant une adresse de contact, et le
`Crawl-delay: 10` que `robots.txt` d'Éduscol déclare pour `User-agent: *`.

| Constat | Valeur |
|---|---|
| URL sondées | 123 (12 documents directs + 111 pages de navigation) |
| HTTP 200 | 13 |
| HTTP 403 | 110 |

`robots.txt` (récupéré, HTTP 200) **n'exclut pas** les chemins de navigation pour
`User-agent: *` et **autorise explicitement** `/sites/default/files/` et `*.pdf`.
Le 403 est donc une protection anti-robot applicative, pas une exclusion robots —
et elle est **enregistrée telle quelle**. Aucun proxy, aucun agent trompeur,
aucune session de navigateur détournée.

Une seule page de navigation répond 200 :
`https://sti.eduscol.education.fr/domaines/technologie-au-college` — autre hôte,
hors du périmètre des 150 artefacts. Elle est classée `EN_ATTENTE`, pas
`IRRECUPERABLE`.

## 4. Ce qui a été livré

### `URL_SOURCE_REGISTRY_V1`

`services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/url_source_registry.json`
— 123 entrées, une par URL distincte, portant `source_role`, `navigation_url`,
`direct_url`, `resolved_url`, `status`, `content_type`, `etag`, `last_modified`,
`retrieved_at`, `content_sha256`, `artifact_id`, l'empreinte scellée et les
artefacts du périmètre dont l'URL porte la provenance.

**Le gain principal :** la jointure par `sha256` entre l'évidence et le catalogue
couvre **150/150** artefacts. Les 138 qui n'avaient aucune URL portent désormais
une provenance de navigation nommée. Aucun artefact scellé n'est sans origine.

### Le module et ses gardes

`rag_pedago/governance/url_source_registry.py`. Chaque URL finit dans un état
**nommé** — `RESOLUE`, `IRRECUPERABLE` (avec raison codée **et** preuve),
`EN_ATTENTE` (avec motif). Ce qui n'entre dans aucun état est compté
`URL_UNACCOUNTED`, et le registre est refusé.

`IRRECUPERABLE` exige une preuve précisément pour ne pas devenir la case où l'on
range ce qu'on n'a pas cherché : sans cette contrainte, `URL_UNACCOUNTED = 0`
s'obtiendrait par déplacement plutôt que par travail.

Un document direct ayant répondu 200 **sans** empreinte servie est refusé : « une
URL répond » n'est pas « le contenu n'a pas dérivé ».

### Audit et cible make

`make url-source-registry-audit` (`scripts/url_source_registry_audit.py`) —
hors ligne, déterministe. Il recalcule les compteurs, refuse ceux publiés s'ils
divergent, et refuse un registre qui laisserait un artefact scellé sans
provenance. Cible classée `SAFE_DIAGNOSTIC` dans `configs/make_target_safety.yml`.

## 5. Compteurs mesurés

| Compteur | Valeur |
|---|---|
| `URL_DISCOVERED` | **123** |
| `URL_DIRECT_RESOLVED` | **12** |
| `URL_DIRECT_UNRESOLVED` | **111** |
| `URL_UNRECOVERABLE` | **110** (⊆ unresolved, chacune avec raison + preuve) |
| `URL_FETCHED` | **13** |
| `URL_ERRORS` | **110** |
| `URL_UNACCOUNTED` | **0** |
| `CURRENTNESS_VERIFIED` | **12** |
| `CURRENTNESS_DRIFTED` | **0** |

Les 12 URL de document direct ont été rejouées : les 12 empreintes servies
aujourd'hui sont **identiques** aux empreintes scellées. Aucune dérive.

La 111ᵉ URL non résolue est celle qui répond 200 (`EN_ATTENTE`), les 110 autres
sont `IRRECUPERABLE` avec, chacune, le statut observé, l'horodatage, la politique
`robots.txt` du fournisseur, le compte des autorités fouillées et le nom du
porteur manquant.

## 6. Gardes prouvées par mutation

Chaque garde a été cassée dans le code ou la donnée, le rouge constaté, puis
restaurée et le vert reconstaté.

| Mutation | Effet |
|---|---|
| `_est_comptee` accepte tout | 2 tests rouges |
| Garde `PREUVE_IRRECUPERABILITE` retirée | 1 rouge |
| Garde `EMPREINTE_SERVIE` retirée | 1 rouge |
| Garde `URL_EN_DOUBLE` retirée | 1 rouge |
| Garde `SONDE_RESEAU_ABSENTE` retirée | 1 rouge |
| Une preuve d'irrécupérabilité effacée dans le registre | 2 rouges + audit `REGISTRE_REFUSE` |
| Un compteur publié falsifié (110 → 111) | 1 rouge + audit `COMPTEURS_PUBLIES_DIVERGENTS` |
| Provenance des 150 artefacts effacée | 1 rouge + audit `ARTEFACTS_SANS_PROVENANCE 138` |
| Une empreinte servie falsifiée | 1 rouge + `CURRENTNESS_DRIFTED 0 → 1` |

État initial et final : `15 passed`.

## 7. Chemin de réparation (hors périmètre de ce lot)

Les 110 URL irrécupérables le sont **par perte d'artefact**, pas par
impossibilité de principe. Les résoudre demande de rejouer
`eduscol-pdf-harvester v1.10.0`, dont le transport `chrome-devtools` est la
méthode sanctionnée — le collecteur applique `robots.txt`, le délai déclaré, un
agent identifié avec adresse de contact, et ne contourne aucune authentification.
La base reconstruite reverserait `urls`/`references_`, et le registre passerait de
110 `IRRECUPERABLE` à autant de `RESOLUE`.

**Correctif d'export à porter dans le même mouvement :** le catalogue doit
exporter `urls.url` (direct) à côté de `document_scopes.source_url`
(navigation). Sans ce correctif, la prochaine moisson reperdra la relation à
l'export exactement comme celle-ci.

C'est une remoisson : elle sort du périmètre de ce lot et est signalée ici sans
être entreprise.

## 8. Qualité

- `make lint` : `All checks passed!`
- `make typecheck` : `Success: no issues found in 98 source files`
- `make test` : **3 119 passed, 4 skipped, 0 failed** (5 min 06 s) ; aucun test vert n'est passé au rouge. Les 15 échecs
  transitoires provoqués par l'ajout de la cible make ont été corrigés à la
  source (classification dans `configs/make_target_safety.yml`), pas contournés.
- `make url-source-registry-audit` : `VERDICT : REGISTRE DES URL SOURCES
  COHÉRENT, AUCUNE URL NON COMPTÉE`

---

# Dispositions de fraîcheur — 2026-09-06

`URL_UNACCOUNTED=0` répondait d'une question : chaque URL a un état. Elle n'en
répondait pas d'une autre : **chaque artefact gouverné a-t-il une
disposition ?** Un artefact couvert par une URL comptée peut rester, lui, sans
réponse — et c'était le cas, faute qu'on le lui demande.

## Le registre

`rag_pedago/governance/currentness_disposition.py` +
`data/releases/prerentree_2026_2027/multilevel/currentness_disposition.json`,
produit par `scripts/build_currentness_disposition.py` (mode `--check`
disponible, dérive refusée).

Il est **dérivé** de deux autorités déjà scellées — l'évidence de fraîcheur et
le registre d'URL — et de rien d'autre. Une disposition saisie à la main serait
un avis, pas une mesure.

```
CURRENTNESS_ACCOUNTED=150
CURRENTNESS_UNACCOUNTED=0

VERIFIED_CURRENT=12
UNRECOVERABLE_WITH_EVIDENCE=138
NON_URL_STATIC_SOURCE=0
INTERACTIVE_RESOURCE_VERIFIED=0
```

## Ce que chaque disposition exige

| Disposition | Ce qui doit être vrai |
|---|---|
| `VERIFIED_CURRENT` | une URL directe rejouée dont l'**empreinte servie** est identique à l'empreinte scellée |
| `UNRECOVERABLE_WITH_EVIDENCE` | **toutes** les provenances irrécupérables, chacune avec sa raison codée **et** sa preuve |
| `NON_URL_STATIC_SOURCE` | aucune provenance URL — source statique du plan de contrôle |
| `INTERACTIVE_RESOURCE_VERIFIED` | ressource dont l'identité n'est pas un fichier téléchargeable |

Un artefact qui n'entre dans aucune case **n'est pas rangé d'office** : le
producteur échoue en nommant le cas. C'est ce qui empêche
`CURRENTNESS_UNACCOUNTED=0` de s'obtenir par déplacement.

## Refus prouvés

Douze épreuves, chacune sur le défaut qu'elle vise :

- une URL qui répond **sans empreinte servie** ne vérifie rien — un 200 est un
  ping, pas une vérification ;
- une empreinte servie **différente** de l'empreinte scellée ne vérifie rien —
  c'est même le cas qui compte, le contenu a dérivé ;
- un `IRRECUPERABLE` **sans preuve** est refusé ;
- un artefact **partiellement** résolu (une provenance irrécupérable, une en
  attente) est nommé, pas classé ;
- un compte publié faux, une disposition sans appui, un artefact dispositionné
  deux fois, un périmètre vide : tous refusés.

Le périmètre vide est refusé nommément, parce que zéro artefact rendrait
`UNACCOUNTED=0` trivialement vrai.

---

## Addendum — remédiation des neuf refus P1 de revue — 2026-09-06

La revue de la PR a soulevé 20 constats non résolus (3 `chatgpt-codex-connector`
et 17 `cubic-dev-ai`) sur le HEAD rebasé `e43acbf0`. Neuf d'entre eux, tous de
sévérité P1, désignaient le même défaut sous des angles différents : une
affirmation gouvernée (raison codée, preuve, disposition, empreinte) était
acceptée sur sa seule **présence**, jamais sur son **contenu**. Les onze
constats P2/P3 restants sont reportés à un lot séparé.

Corrections apportées, chacune prouvée par un test qui échouait avant et passe
après :

- **Raison irrécupérable hors liste connue** — `raison_irrecuperabilite`
  n'est plus une chaîne libre : elle doit appartenir à
  `RAISONS_IRRECUPERABILITE_CONNUES` (les deux codes réellement émis par le
  producteur), sans quoi `verifier_registre` refuse
  `RAISON_IRRECUPERABILITE_INCONNUE`.
- **Preuve irrécupérable non structurée** — `preuve_irrecuperabilite` doit
  faire au moins 40 caractères, citer `robots.txt`, et citer l'horodatage
  exact (`retrieved_at`) de la sonde qu'elle prétend documenter. `raison="x"`,
  `preuve="x"` — la fraude minimale que la revue signalait — est maintenant
  refusée.
- **Registre sans autorités scellées** — `verifier_registre` exige exactement
  les deux autorités dont ce registre est censé dériver (catalogue + évidence
  de fraîcheur), chacune porteuse de son empreinte.
- **`VERIFIED_CURRENT` sur coïncidence d'empreintes** — la disposition exige
  maintenant `source_role == DOCUMENT_DIRECT`, `status == 200` et un
  `direct_url` présent, en plus de l'égalité des empreintes : un `RESOLUE` qui
  ne serait pas un téléchargement direct réussi ne peut plus produire
  `VERIFIED_CURRENT` par accident.
- **Preuve d'irrécupérabilité perdue à la disposition** — l'`appui` d'un
  `UNRECOVERABLE_WITH_EVIDENCE` porte désormais un condensé SHA-256 vérifiable
  des preuves sources (`; preuve=<64 hex>`), et `verifier_registre` refuse
  toute disposition irrécupérable qui ne le porte pas.
- **`NON_URL_STATIC_SOURCE` sur silence, pas sur preuve** — un artefact sans
  aucune entrée d'URL n'est plus classé source statique par défaut : l'autorité
  de l'artefact doit le déclarer explicitement
  (`non_url_static_source`), sans quoi le registre est refusé nommément. Une
  régression de jointure dans le registre d'URL ne peut plus se faire passer
  pour une disposition mesurée. Aucun des 150 artefacts réels n'emprunte
  aujourd'hui cette voie (tous portent au moins une entrée) — la garde protège
  contre une régression future, elle ne change aucun compte actuel.
- **Sonde directe incohérente écrite quand même** — `build_url_source_registry.py`
  refuse maintenant la construction (`SystemExit: EMPREINTE_DERIVEE …`) dès
  qu'une sonde directe réussie (`status=200`) rend une empreinte différente de
  l'empreinte scellée, au lieu d'écrire un `RESOLUE` qui aurait fait échouer la
  disposition trois étapes plus loin avec un message sans rapport.
- **Erreurs transitoires classées irrécupérables** — 429, 5xx et échec réseau
  sans statut restent `EN_ATTENTE` (motif : sonde à reprendre) au lieu de
  `IRRECUPERABLE` ; seul un statut qui démontre une impossibilité (403, ou une
  absence de relation dans les autorités) reste irrécupérable. Sans effet sur
  le registre réel : ses 110 entrées irrécupérables sont toutes en 403.
- **Dérive de la disposition non détectée** — `make url-source-registry-audit`
  vérifiait le registre d'URL mais rien ne vérifiait que
  `currentness_disposition.json` committé correspondait encore à sa
  dérivation. Nouvelle cible `make currentness-disposition-check`
  (`build_currentness_disposition.py --check`), câblée dans
  `scripts/ci-local.sh` au même point que `source-evidence-check`, et
  classifiée `SAFE_METADATA_ONLY` dans `make_target_safety.yml`. Le fichier
  committé a été régénéré (le format d'`appui` a changé avec l'ajout du
  condensé de preuve) ; les comptes qu'il porte sont inchangés
  (`VERIFIED_CURRENT=12`, `UNRECOVERABLE_WITH_EVIDENCE=138`,
  `CURRENTNESS_UNACCOUNTED=0`).

**Preuve d'absence de régression** — comparaison nom par nom (pas seulement
par cardinalité) des échecs `make test` avant/après, sur le même interpréteur
emprunté (voir la dette d'environnement plus haut) :

```
avant (e43acbf0, stash)   141 failed, 2905 passed, 3 skipped
après (avec les fixes)    141 failed, 2923 passed, 3 skipped

NOUVEAUX ÉCHECS = 0   (comm -13 baseline branche → vide)
ÉCHECS RÉPARÉS  = 0   (comm -23 baseline branche → vide)
```

L'écart `+18 passed` est le total des épreuves ajoutées par ce correctif (9
gardes nouvelles en `url_source_registry.py`/`currentness_disposition.py`,
plus un nouveau fichier `tests/test_build_url_source_registry.py` couvrant les
deux défauts des scripts producteurs). Un correctif intermédiaire au Makefile
avait d'abord fait régresser 15 épreuves de la famille
`make-target-safety-audit` (cible non classifiée) ; corrigé en ajoutant
`currentness-disposition-check` à `SAFE_METADATA_ONLY`, revérifié à zéro
régression ci-dessus.
