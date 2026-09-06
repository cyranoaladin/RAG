# LOT — C1 : couvrir la lignée COURANTE, pas seulement la revue passée

## Le défaut

`Corpus CAS reproducibility (C1)` confronte le store adressable par contenu à
l'ensemble de **320 objets** que la revue humaine du 2026-09-03 a scellé
(`pii_review_index_20260903.json`, `content_set_sha256=77f01c82…`,
`counts.scanned=320`).

Cette épreuve prouve que le store est celui d'une lignée **figée**. Elle ne
demande jamais si l'ensemble que la lignée **promeut aujourd'hui** y est
couvert. Une lignée régénérée après la revue servirait donc des documents
irreproductibles hors poste, et C1 resterait vert : il vérifierait toujours,
fidèlement, un corpus qui n'est plus celui qu'on sert.

L'écart n'est pas théorique. L'index a été produit à `21:53:59Z`, trois
minutes après `a4b1f96` — le dernier changement de la lignée à cette date. Rien
n'empêche le prochain changement de rompre l'inclusion, et rien ne le dirait.

## La preuve rouge

Sur les données réelles, avant correctif :

```
python scripts/qualification/verify_corpus_cas.py --cas-root … \
  --expect-content-set-sha256 77f01c82… --expect-count 320
→ RC=0
```

vert, sans qu'aucune assertion ne porte sur les contenus servis aujourd'hui.

Le premier correctif — celui de la contribution entrante — introduisait
`--promoted-content-set`. Il portait toutefois la faille qu'il prétendait
fermer :

```python
verify(cas_root, digest, count, promoted=set())
→ code = 0
→ PROMOTED_CAS_COVERAGE_MISSING=0
```

Un ensemble promu **vide** ne manque jamais de rien. C'est la manière exacte
dont un gate devient vert en *perdant* ses données : moins on en sait, plus le
compte est bon.

## L'autorité lue — une seule, celle du runtime

Le producteur ne décide **rien** de la structure des releases. Natures
supportées, sceaux, comptes déclarés, autorités, partitions de pages,
collisions de collection et d'artefact : tout appartient à
`nexus_release_chain.release_readiness`, le module que le **runtime de
production consomme déjà** via `load_release_registry_file`.

Une première version réimplémentait ces règles. C'était un second runtime, et
il en a le coût exact : chaque règle omise devenait un faux vert, chaque règle
ajoutée en amont demandait d'être redécouverte ici. Onze rondes de revue l'ont
mesuré — dix-neuf constats, tous légitimes, tous des variantes du même défaut.
La douzième aurait porté sur `WAVE0_AGGREGATE_RELEASE_V1`, que le registre et
le runtime acceptent et que le qualificateur refusait.

Ce fichier ne fait donc plus que deux choses que le chargeur ne peut pas faire
à sa place :

1. **borner le chemin du registre** à la racine gouvernée — une autorité
   d'entrée extérieure au périmètre qu'elle prétend gouverner ne le gouverne
   pas, et ses empreintes internes fussent-elles cohérentes ne prouveraient
   que la lecture du fichier désigné ;
2. **réduire** ce que le chargeur rend à l'ensemble des `content_sha256`
   distincts, avec la formule d'empreinte du vérificateur CAS.

`--release-registry` accepte un registre figé et `--release-registry-sha256`
son empreinte externe : la qualification du `FULL_GO_LIVE_CANDIDATE`
réutilisera ce script tel quel, sans réécriture.

### Le gate anti-divergence

Pour **chaque** lignée versionnée du dépôt, découverte par parcours et non
nommée en dur, une épreuve confronte ce que C1 rend à ce que le chargeur
runtime rend — ensemble d'artefacts et ensemble de collections. L'égalité est
structurelle, puisqu'il s'agit du même appel ; l'épreuve existe pour qu'elle
le reste.

Une seconde épreuve interdit que C1 nomme la moindre nature de release dans
son source : un `if kind == …` dupliqué dans deux modules diverge le jour où
l'un des deux gagne une nature. **Wave0 est ainsi couvert sans que ce fichier
n'ait jamais à le nommer.**

Les sabotages que la version manuelle gardait sont refusés par le chargeur
canonique, par ses propres règles :

```
V2, artefact retiré + registre et agrégat rescellés
  → ReleaseReadinessError: artifact registry.expected_counts mismatch
V1, sujet retiré + comptes et sceaux refaits
  → ReleaseReadinessError: expected_counts mismatch
```

## Le compte mesuré

```
Occurrences d'artefact (11 sujets)   486
Contenus DISTINCTS promus            319
Partages multi-sujets                167
PROMOTED_CONTENT_SET_SHA256          d06d6051e7037372acf4dca4675a1c999c198129433d68491221a9d03bb821cd
```

Les 167 partages sont exactement ce que la PR #146 a légitimé. Le compte de
319 est corroboré par deux chemins indépendants : la déduplication des
`content_sha256`, et `expected_counts.artifacts = 486` que la release déclare.

## Sémantique de la couverture

« Couvert » ne veut pas dire « déclaré au manifeste du store ». Un contenu peut
y figurer sans qu'aucun octet lisible ne lui corresponde. Quatre compteurs
distinguent désormais ce que l'on sait :

| Compteur | Ce qu'il compte |
|---|---|
| `PROMOTED_CAS_DECLARATION_MISSING` | promu, absent du manifeste du store |
| `PROMOTED_CAS_BLOB_MISSING` | déclaré, mais aucun objet sur disque |
| `PROMOTED_CAS_SIZE_MISMATCH` | octets corrects, taille déclarée fausse |
| `PROMOTED_CAS_HASH_MISMATCH` | octets hachant ailleurs, ou localisateur hors store |
| `PROMOTED_CAS_COVERAGE_MISSING` | promu **sans objet CAS vérifié** — l'union des quatre |

Taille et empreinte sont deux propriétés distinctes : les confondre priverait
l'exploitant de l'information qui dit *quoi* réparer.

Seul `COVERAGE_MISSING` fait échouer le gate, et c'est lui qui porte la
question : *ce document servi, sait-on le relire hors du poste ?*

Un cinquième compteur est publié sans jamais bloquer :

| Compteur | Ce qu'il compte |
|---|---|
| `PROMOTED_CAS_COVERAGE_EXTRA` | contenus du store **qui ne sont plus promus** |

Il n'est pas un défaut, et c'est délibéré. **Le store peut être un
sur-ensemble ; jamais un sous-ensemble.** Un candidat retiré, un contenu
remplacé par une version plus récente, un artefact rendu non servable par une
décision de gouvernance : tous restent légitimement dans le store, où ils
continuent de rendre reproductible ce qu'une lignée antérieure a servi.
Effacer le store à chaque changement de lignée détruirait cette propriété.
`EXTRA` est donc une mesure de l'écart, pas une alarme — et sa valeur non
nulle est l'état normal d'un store qui a vécu.

### Le fichier d'ensemble promu se prouve lui-même

Il porte `count` et `content_set_sha256`. Les ignorer laissait un fichier
**tronqué mais non vide** passer pour complet : la couverture était alors
calculée contre moins de contenus qu'il n'y en a de promus, et « 0 manquant »
cessait de vouloir dire quelque chose. Les deux champs sont désormais
confrontés à la liste avant tout usage.

Un `content_sha256` qui n'est pas un sha256 minuscule de 64 caractères est
refusé à la source. Sans cela, `str()` d'une valeur quelconque devenait un
identifiant promu que le store ne pouvait par construction jamais contenir :
la couverture échouait plus tard, sur un défaut dont l'origine était perdue.

## Les mutants

Chaque garde est prouvée par la mutation qu'elle refuse.

| Mutation | Attendu | Observé |
|---|---|---|
| ensemble promu vide | refus | « la couverture serait vraie par vacuité » |
| registre sans release active | refus | « aucune release active » |
| release sans sujet | refus | « aucun sujet » |
| sujet sans artefact | refus | « aucun artefact » |
| manifeste de sujet réécrit sans son sceau | refus | déclare `5f4af613…`, vaut `dbe72c70…` |
| manifeste de release réécrit sans son sceau | refus | « l'autorité déclare » |
| `expected_counts.artifacts` absent, `"4"`, `0`, `-1`, `True` | refus | « expected_counts » |
| occurrences lues ≠ déclarées | refus | « contre 9 déclarées » |
| registre hors racine gouvernée | refus | « hors de la racine gouvernée » |
| `manifest_path` en `../` | refus | « hors de la racine gouvernée » |
| lien symbolique **interne** sur un composant | refus | « est un lien symbolique » |
| registre / release / entrée valant `[]`, `"x"`, `42`, `null` | refus | « pas un objet » |
| taille déclarée fausse, octets justes | refus | `SIZE_MISMATCH=1`, `HASH_MISMATCH=0` |
| JSON malformé | `RC=2` | `PROMOTED_CONTENT_SET_INVALID` |
| blob supprimé | refus | `BLOB_MISSING=1`, `COVERAGE_MISSING=1` |
| octets remplacés | refus | `HASH_MISMATCH=1`, `COVERAGE_MISSING=1` |

Sur l'arbre réel, la mutation d'un sujet sans mise à jour de son sceau rend
`RC=2` en nommant le sujet, l'empreinte déclarée et l'empreinte mesurée.

**Le garde symlink est éprouvé sur le cas qu'il est SEUL à attraper.** Un lien
vers l'extérieur est déjà refusé par la borne « le chemin résolu est dans la
racine » ; un lien **interne** ne l'est pas — la résolution reste à
l'intérieur, et le sceau du fichier atteint est parfaitement correct. Mutant
appliqué (`if courant.is_symlink()` neutralisé) : **exactement une épreuve
rouge**, celle du lien interne. C'est ce qui en fait une épreuve du garde et
non de la borne voisine.

## Une seule primitive pour toutes les entrées

`_lire_gouverne` borne le registre, les manifestes de release et les
manifestes de sujet. Trois implémentations de la même borne divergeraient :
celle qu'on oublie de durcir devient le chemin d'entrée.

Le **registre lui-même** y est soumis. Une autorité d'entrée extérieure au
périmètre qu'elle prétend gouverner ne le gouverne pas : un faux registre dont
toutes les empreintes seraient cohérentes prouverait seulement qu'on a bien lu
le fichier qu'on a désigné.

Un JSON parfaitement valide peut n'être pas un objet — `[]`, `"registry"`,
`42`, `null`. `_charge_objet` l'exige à chaque étage : appeler `.get()` dessus
rendrait une trace Python là où le gate doit nommer le défaut.

## Déclenchement

Le filtre de chemins du workflow est volontairement **large** plutôt qu'une
allowlist. L'ensemble servi dépend du registre, des manifestes qu'il désigne
et des sujets joignables depuis eux : les énumérer un par un laisserait un
changement de registre seul, ou une release nouvellement désignée, éviter C1
sans que rien ne le dise.

Depuis la délégation, il couvre aussi **l'autorité canonique elle-même** —
`packages/release-chain/**` et les deux paquets dont elle dépend. Un
changement de la sémantique de release change le périmètre servi : ne pas
déclencher C1 dessus laisserait le chargeur évoluer sans que le store privé
soit reconfronté, c'est-à-dire un C1 vert sur un périmètre qu'il ne décrit
plus.

## La frontière de la clé privée

Le workflow C1 refuse de se déclencher sur `pull_request`, et c'est la bonne
décision : il porte la clé d'accès au corpus privé, qu'un job de PR — donc du
code que personne n'a encore revu — pourrait exfiltrer en une étape ajoutée.

Conséquence non voulue : ses épreuves **unitaires**, qui n'ont besoin d'aucun
secret, ne tournaient nulle part avant la fusion. Le job `scripts/qualification`
de `ci.yml` les exécute désormais sur les PR, sur données publiques
uniquement. La séparation reste stricte :

```
PR CI            → données publiques seules, jamais la clé CAS
main post-merge  → clé CAS, confrontation au store privé
```

Les deux jobs installent la même chaîne de paquets locaux — `contracts`,
`pdf-page-policy`, `release-chain` — aucun n'étant publié. Vérifié dans un
venv vierge : installation, 25 épreuves vertes, 319 contenus rendus.

## Ce qui reste à prouver après la fusion

Ce lot rend le gate **capable** de poser la question. La réponse exige le job
privilégié post-fusion, sur le commit exact de `main` :

```
CURRENT_PROMOTED_CONTENTS=<mesuré>
PROMOTED_CAS_DECLARATION_MISSING=0
PROMOTED_CAS_BLOB_MISSING=0
PROMOTED_CAS_SIZE_MISMATCH=0
PROMOTED_CAS_HASH_MISMATCH=0
PROMOTED_CAS_COVERAGE_MISSING=0
```

Alors seulement `C1_CURRENT_LINEAGE=PASS`.

`C1_FULL_GO_LIVE_CORPUS` reste **ouvert** : il sera prouvé contre le
`FULL_GO_LIVE_CANDIDATE`, dont le CAS devra recevoir chaque source promue —
PDF, binaire Drive, document d'URL matérialisé, et GeoGebra s'il est servi
comme artefact. Le store peut être sur-ensemble ; jamais sous-ensemble.

## Provenance de ce lot

La contribution initiale vient d'une autre instance (PR #153, `d8e8415`). Elle
n'a été ni fusionnée par confiance, ni rejetée pour son origine : le défaut
qu'elle vise a été confirmé par mesure, son correctif adopté, et les trous
qu'il laissait — vacuité, sceaux non confrontés, compte déclaré facultatif,
chemins non bornés, sémantique de couverture — fermés au-dessus.
