# Runbook Ré-émission — Release de production `profile_gate`

## Quand déclencher une ré-émission

- Une **autorité liée** change de contenu : inventaire modèle, mapping, politique
  PII, registre de droits, manifeste de profils.
- Une autorité scellée s'avère **sans référent utilisable** — c'est le cas qui a
  motivé ce runbook : la release scelle
  `embedding_inventory_sha256 = e15ab71b…`, empreinte d'un artefact embedding
  amputé de `1_Pooling/`, structurellement inchargeable (ADR-0051 §7bis).
- **Jamais** pour « rafraîchir » une release. Une ré-émission modifie 34 fichiers
  d'autorité ; sans cause identifiée, elle détruit de la traçabilité sans rien
  produire.

## 0. Préalables — vérifier AVANT toute exécution

La ré-émission est **impossible** si l'un de ces éléments manque. Contrôler les
trois, sans quoi le script échoue à mi-course sur un arbre partiellement réécrit.

```bash
cd services/rag-pedago

# a. Miroir PDF : 26 fichiers nommés <content_sha256>.pdf.
#    `validate_pdf_mirror` relit chaque octet et refuse toute divergence.
#    Racine par défaut : $NEXUS_SEALED_CORPUS_ROOT
#    (défaut ~/Téléchargements/NEXUS_RAG_GDRIVE_READY)
python3 - <<'PY'
import json, pathlib, os
root = pathlib.Path(
    os.environ.get("NEXUS_PDF_MIRROR", "")
    or pathlib.Path.home() / "Téléchargements/NEXUS_RAG_GDRIVE_READY"
)
agg = json.loads(pathlib.Path(
    "data/releases/prerentree_2026_2027/profile_gate/"
    "production-profile-gate.release.json").read_text())
shas = set()
def walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "content_sha256" and isinstance(v, str): shas.add(v)
            walk(v)
    elif isinstance(x, list):
        for i in x: walk(i)
walk(agg)
missing = sorted(s for s in shas if not (root / f"{s}.pdf").is_file())
print(f"attendus={len(shas)} manquants={len(missing)}")
for s in missing[:5]: print("  ", s)
PY

# b. Artefacts modèles embedding + reranker, complets et scellés.
MODEL_ARTIFACT_DIR=<embedding> MODEL_ARTIFACT_INVENTORY_SHA256=<inv> \
  ../../scripts/e2e/verify-embedding-model-artifact.sh

# c. Arbre git propre. Une ré-émission sur un arbre sale rend le diff illisible.
git status --porcelain
```

> **Si le miroir PDF est absent, s'arrêter ici.** Il n'existe aucun chemin de
> substitution : les empreintes de contenu sont vérifiées octet par octet.

### Le miroir est une pièce d'archive, pas un cache

`fetch_artifact_bytes` (`canonical_release_corpus_ingestion.py`) sait reconstruire
le miroir en téléchargeant chaque `source_url` et en refusant toute empreinte
divergente. Cela n'en fait pas une ressource régénérable à volonté.

Les 26 contenus proviennent d'`eduscol.education.gouv.fr` (24) et de
`www.education.gouv.fr` (2). **Si l'un de ces PDF est réédité en amont, son
empreinte cesse de correspondre à celle scellée par la release** : le
téléchargement échouera — comportement correct — et le miroir local deviendra la
**seule source des octets exacts sur lesquels l'index a été construit**.

Conséquences opératoires :

- conserver le miroir sur **deux supports physiques distincts**, au même titre
  que les dumps PostgreSQL ; emplacement de référence
  `~/sauvegardes-rag/corpus-pdf-mirror`, surchargeable par
  `NEXUS_CORPUS_PDF_MIRROR` ;
- **ne jamais le placer sous `/tmp`** — deux incidents y sont déjà imputables
  (dette n°18) ;
- le vérifier contre l'autorité de la release, jamais contre lui-même :
  `sha256sum -c` avec un manifeste dérivé des `content_sha256` des manifests-sujets ;
- une reconstruction depuis Drive reste possible et **traçable** : le mapping
  `docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json`
  donne pour chaque contenu son `drive_file_id`, son `canonical_path` et sa
  taille. La structure du corpus source est documentée dans
  `docs/corpus/README_GDRIVE_IMPORT.md`.

## 1. Discipline TDD — les tests d'abord

Reprise du plan `docs/superpowers/plans/2026-08-25-production-profile-gate.md`,
qui a présidé à la création du producteur. La ré-émission suit la même
discipline : **le test qui échoue précède le code qui répare**.

1. Écrire ou activer un test **RED** qui exprime la cause de la ré-émission —
   par exemple « l'inventaire embedding scellé doit désigner un artefact dont
   chaque module de `modules.json` est couvert par le sceau ». Le test doit
   échouer sur l'état courant, et cet échec doit être constaté, pas supposé.
2. Corriger la cause **en amont** (artefact, mapping, politique), jamais en
   éditant un manifeste à la main.
3. Vérifier le test au vert **avant** de régénérer quoi que ce soit.
4. Conserver les **mutation tests** sur chaque digest de `authority_bindings.json` :
   toute liaison doit nommer un chemin source réel et refuser un digest de forme
   seule. Un binding qui ne casse pas quand sa source change ne prouve rien.

## 2. Rejeu à blanc — hors du dépôt

**Jamais de première exécution dans le dépôt.** Le script réécrit 34 fichiers
sans sauvegarde.

```bash
BLANC=$(mktemp -d /tmp/reseal-blanc.XXXXXX)
rsync -a --exclude '.git' --exclude '.venv' --exclude '.worktrees' \
      --exclude 'node_modules' /chemin/vers/RAG/ "$BLANC/RAG/"

cd "$BLANC/RAG/services/rag-pedago"
python3 scripts/build_production_profile_release.py \
    --pdf-root "$NEXUS_PDF_MIRROR" \
    --embedding-snapshot "$EMBEDDING_ARTIFACT" \
    --reranker-snapshot "$RERANKER_ARTIFACT"
```

`REPOSITORY_ROOT` dérive de l'emplacement du script : exécuter la copie écrit
dans la copie.

### 2.1 Reproductibilité — deux rejeux doivent coïncider

```bash
BLANC2=$(mktemp -d /tmp/reseal-blanc2.XXXXXX)
rsync -a --exclude '.git' --exclude '.venv' --exclude '.worktrees' \
      --exclude 'node_modules' /chemin/vers/RAG/ "$BLANC2/RAG/"
cd "$BLANC2/RAG/services/rag-pedago" && python3 scripts/build_production_profile_release.py …

diff -r "$BLANC/RAG/services/rag-pedago/data/releases/prerentree_2026_2027" \
        "$BLANC2/RAG/services/rag-pedago/data/releases/prerentree_2026_2027"
```

**Toute différence entre deux rejeux est un défaut bloquant.** Une release non
reproductible ne peut pas être auditée : on ne saurait plus distinguer une
correction voulue d'une dérive du producteur. Traiter ce défaut **avant** la
ré-émission, jamais après.

### 2.2 Diff attendu — le contrôle qui décide

```bash
diff -r /chemin/vers/RAG/services/rag-pedago/data/releases/prerentree_2026_2027 \
        "$BLANC/RAG/services/rag-pedago/data/releases/prerentree_2026_2027"
```

**Critère d'acceptation** : chaque différence doit se rattacher à la cause
déclarée en §1, ou à un digest qui en dérive. La cascade attendue pour un
changement d'inventaire embedding :

| Rang | Fichier | Raison |
|---|---|---|
| 1 | `models/embedding/SHA256SUMS`, `manifest.json` | la cause elle-même |
| 2 | `authority_bindings.json` | `embedding_inventory_sha256` lie ce fichier |
| 3 | 18 × `subjects/*.release.json` | chacun recopie le bloc `authorities` |
| 4 | `production-profile-gate.release.json` | agrège les sujets |
| 5 | `release-registry.json` | `expected_manifest_sha256` suit l'agrégat |

**Doit rester identique** : `candidate_inventory`, `catalog_delta`,
`corpus_manifest_authority`, `currentness_*`, `pii_evidence`,
`preflight_evidence`, `programme_registry`, `models/reranker/*`, et les trois
rapports sous `docs/reports/`.

> **Arrêter et escalader** si un champ bouge sans rattachement : horodatage
> mouvant, réordonnancement de sérialisation, contenu sans rapport. Ce serait un
> défaut de reproductibilité, distinct et plus grave que la cause traitée.

`multilevel/` n'est **pas** réécrit par le script. Ses manifests déclarent une
empreinte embedding (`e2c7384b…`) sans artefact correspondant : anomalie inerte
tant que `release-registry.json` ne les référence pas, bloquante le jour de leur
activation. À traiter séparément.

### 2.3 La cascade sort du bundle — balayage inverse obligatoire

**Un diff d'écriture n'est pas un diff d'impact.** Le §2.2 établit ce que le
script *réécrit*. Il ne dit rien de ce qui, ailleurs dans le dépôt, *épingle* les
valeurs qu'il vient de changer.

Cette confusion a coûté deux découvertes par collision : d'abord
`packages/contracts`, heurté au démarrage du runtime
(`scope source SHA differs from subject release`), alors que le diff du bundle
était déclaré propre et complet.

Quand une valeur change, la question n'est pas « quels fichiers ai-je réécrits »
mais **« qui référence cette valeur, où que ce soit »**.

#### Méthode

```bash
# 1. Extraire les valeurs DISPARUES : présentes avant, absentes après.
#    Une valeur des deux côtés n'a pas changé et ne doit pas être cherchée.
git diff -U0 services/rag-pedago/data/releases/ \
  | grep '^-' | grep -oE '[0-9a-f]{64}' | sort -u > /tmp/anciennes.txt
git diff -U0 services/rag-pedago/data/releases/ \
  | grep '^+' | grep -oE '[0-9a-f]{64}' | sort -u > /tmp/nouvelles.txt
comm -23 /tmp/anciennes.txt /tmp/nouvelles.txt > /tmp/a-chercher.txt

# 2. Chercher chaque ancienne valeur dans TOUT le dépôt.
#    Aucun filtre d'extension : un épinglage peut vivre dans un JSON de
#    contrat, un test, une fixture, un snapshot cockpit, un verrou, la CI.
while read -r v; do
  grep -rl "$v" . 2>/dev/null \
    | grep -v '^\./\.git/\|/\.venv/\|/\.worktrees/\|node_modules\|__pycache__\|/\.next/' \
    | sed "s|^|$v\t|"
done < /tmp/a-chercher.txt
```

> **Nommer le périmètre exclu.** Un balayage qui établit un négatif doit
> justifier son domaine aussi rigoureusement que son résultat.
> `find /home /mnt` prouve l'absence dans `/home` et `/mnt`, pas l'absence.
> Écrire dans le rapport de lot ce qui a été exclu et pourquoi.

#### Classer chaque site — la distinction qui décide de tout

| Nature | Reconnaissance | Traitement |
|---|---|---|
| **Généré** | un outil du dépôt l'écrit | se régénère |
| **Manuscrit** | aucun outil ne l'écrit | se modifie et **s'audite** |
| **Historique** | rapport daté, trace d'un état passé | **ne pas toucher** |

Un rapport de lot qui cite l'ancienne empreinte n'est pas un épinglage à
corriger : c'est un enregistrement de ce qui était vrai à sa date. Le réécrire
détruirait de la traçabilité.

#### Sites connus après le rescellement du 28/08/2026

| Site | Valeurs | Nature | Traitement |
|---|---|---|---|
| 18 × `packages/contracts/…/retrieval-scope-prod-*-v1.json` | `source_sha256` | manuscrit | **ni régénérer ni modifier** — ADR-0045 impose de nouveaux `_v2` (ADR-0052) |
| `packages/contracts/tests/test_production_profile_scope_registry.py` | 18 | manuscrit | étendre aux nouveaux IDs |
| `packages/contracts/pyproject.toml` + `tests/test_schema_export.py` | version | manuscrit | bump SemVer mineur, additif |
| `tests/test_multilevel_scope_registry.py`, `tests/test_retrieval_scope_registry_v2.py` | compte du registre | manuscrit | suivre l'ajout — la préservation est garantie par les assertions de sous-ensemble |
| `docs/reports/master_go_live_state_20260815.json`, `docs/reports/lot_production_profiles_20260825.md` | agrégat | **historique** | **inchangés** |

Vérifié sans occurrence : `services/cockpit/` (y compris `collections.json`),
`services/rag-pedago/tests/golden_queries/`, `scripts/governance-locks.baseline`,
`.github/workflows/`, `scripts/ci-local.sh`.

> Un épinglage de **version** — et non de digest — échappe au balayage par
> empreinte. Vérifier séparément `grep -rn '<ancienne version>'` après tout bump
> de `nexus-contracts`.

#### Trois familles de dépendance, trois méthodes

| Famille | Exemple | Détection |
|---|---|---|
| Épinglage de **valeur** | `source_sha256` d'un scope | balayage inverse, deux modes d'empreinte |
| Épinglage de **version** | `test_schema_export.py` | `grep` de l'ancienne version après bump |
| Invariant de **cardinalité** ou de **nom** | `len(registry) == 31`, une fixture nommant `prod_*_v1` | **aucune recherche de valeur ne les révèle** |

La troisième famille n'est atteignable que par la CI. **La CI complète des trois
paquets fait donc partie du balayage, elle n'en est pas la validation finale.**

Sur la cardinalité : une assertion de compte accompagne presque toujours une
assertion de sous-ensemble, qui porte l'intention réelle du test. Mettre le
compte à jour est légitime quand le sous-ensemble passe inchangé ; ce n'est pas
« ajuster un test pour qu'il passe ».

Sur les noms : après une seconde émission, une fixture qui nomme un scope `_v1`
peut devenir **vacante sans devenir rouge** — le scope existe toujours, il n'est
simplement plus lié à la release active. Auditer les fixtures qui nomment un
scope pour distinguer celles qui veulent « le scope actif » de celles qui veulent
« ce scope historique précis ». Seule une lecture humaine tranche.

> **Limite connue de l'outil de fermeture.** Il couvre deux formes d'empreinte :
> octets, et JSON canonique compact. `nexus-contracts` en emploie au moins cinq,
> plus des empreintes calculées sur une *projection de champs*
> (`canonical_document()`), qu'aucune fonction générique appliquée au fichier ne
> peut reproduire. La carte est complète **sous ces deux modes**, pas
> absolument (dettes n°23 et n°24).

#### Contrôle d'unicité avant publication

ADR-0045 sélectionne un scope par le couple exact `(collection, subject_sha256)`,
et **zéro comme plusieurs correspondances sont des refus**. Avant de publier de
nouveaux scopes, prouver l'unicité du couple sur l'ensemble du registre : une
collision n'exposerait pas un mauvais scope, elle empêcherait le démarrage.

```bash
PYTHONPATH=packages/contracts/src python3 -c "
from collections import Counter
from nexus_contracts import load_retrieval_scope_registry, RetrievalScopeArtifactV2
pairs = [(a.evidence_subject.collection, a.source_sha256)
         for a in load_retrieval_scope_registry().values()
         if isinstance(a, RetrievalScopeArtifactV2)]
dup = {k: n for k, n in Counter(pairs).items() if n > 1}
print(f'couples={len(pairs)} distincts={len(set(pairs))} collisions={len(dup)}')
"
```

## 3. Ce que la ré-émission ne touche pas — vérification obligatoire

Les 18 **ReviewBindings Ed25519** de `governance/review-bindings/` lient des
autorisations d'ingestion sous `governance/authorizations/`, et non le bundle de
release. Les 19 chemins de `authority_bindings.json` n'ont **aucune
intersection** avec ces deux arborescences. Une ré-émission ne devrait donc pas
les invalider, et la clé privée opérateur ne devrait pas être requise.

Cette disjonction est un raisonnement sur les chemins, **pas une preuve
cryptographique**. La lever :

```bash
# Après ré-émission, revérifier les 18 bindings contre l'ancre de confiance.
# `nexus_contracts` doit être importable : utiliser un interpréteur de service
# ou exporter PYTHONPATH=packages/contracts/src.
PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python \
  scripts/review_binding_bundle_manager.py verify-bundle \
    --bundle-dir governance/review-bindings/prerentree-2026-2027 \
    --trust-anchor governance/trust-anchors/review-binding-v1.json
```

Les défauts `--expected-head` (`140b157f…`) et `--expected-key-id`
(`review-binding-v1-2026-08-25`) désignent l'état de revue de la PR #134 : ne
les surcharger que si l'ancre a effectivement tourné. La sous-commande
`sign-all` **ré-émet** les bindings et exige la clé privée : elle n'a aucune
place dans une ré-émission de release.

**Relever la même sortie AVANT la ré-émission** : sans référence antérieure, un
`PASS` postérieur ne prouve rien. Base établie le 28/08/2026, bundle intact :

```
EXPECTED_HEAD_MATCH=18
CHALLENGE_VALID=18
AUTHORIZATION_BYTES_MATCH=18
AUTHORIZATION_SHA256_MATCH=18
REVIEW_BINDING_BUNDLE_VERIFICATION=PASS
```

**Les 18 doivent rester valides.** Si un seul échoue, la ré-émission touche une
autorité signée : c'est un gate opérateur de catégorie B, la clé privée devient
nécessaire, et la décision change de nature. Restaurer par §5 et escalader.

## 4. Application et report des ancres

```bash
cd services/rag-pedago
python3 scripts/build_production_profile_release.py \
    --pdf-root "$NEXUS_PDF_MIRROR" \
    --embedding-snapshot "$EMBEDDING_ARTIFACT" \
    --reranker-snapshot "$RERANKER_ARTIFACT"
```

Le script imprime `PRODUCTION_PROFILE_RELEASE_SHA256=…` et revalide lui-même les
liaisons d'autorité.

Deux ancres vivent **hors** du bundle, dans `services/rag-engine/infra/.env`, et
ne sont pas mises à jour par le script :

```bash
# a. Empreinte du registre de release.
sha256sum services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json
# -> reporter dans RAG_RELEASE_REGISTRY_SHA256

# b. Empreinte d'inventaire de l'artefact embedding, si l'artefact a changé.
sha256sum "$EMBEDDING_ARTIFACT/SHA256SUMS"
# -> reporter dans RAG_EMBEDDING_MODEL_INVENTORY_SHA256
#    et RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR vers le nouvel artefact
```

Oublier l'un des deux se manifeste au démarrage par
`release model inventory mismatch` ou un refus de lecture du registre. `.env`
n'est pas versionné : sauvegarder avant édition
(`cp -a .env .env.bak_$(date +%Y%m%d_%H%M%S)`).

Redémarrer sans `-p` (ADR-0051) :

```bash
cd services/rag-engine/infra && ./scripts/rag-stack.sh up -d ingestor
```

Critère de succès : `GET /health` à 200, `schema_head = 004_artifact_placements`,
et aucun `release model inventory mismatch` au journal.

## 4bis. Matérialiser l'artefact runtime — étape obligatoire après toute ré-émission

**Une ré-émission seule ne suffit jamais à faire redémarrer le runtime.**
L'inventaire scellé change ; l'artefact monté doit changer avec lui, et porter
*exactement* la nouvelle empreinte.

### Ne pas se tromper d'outil

| Outil | Métier | À utiliser ici ? |
|---|---|---|
| `prepare-embedding-model-artifact.sh` | fabrique un artefact **candidat** pour une release *future* | **non** |
| `build_production_profile_release.py` | **scelle** la release, fait autorité | non (c'est le §4) |
| `materialize-release-model-artifact.py` | **matérialise** l'artefact runtime depuis la release scellée | **oui** |

Les deux premiers écrivent chacun leur `manifest.json` — dix clés contre trois —
première ligne de l'inventaire, donc empreintes irréconciliables pour les mêmes
poids. Servir une release scellée avec un artefact du premier échoue en
`release model inventory mismatch` (dette n°19).

### Exécution

```bash
python3 scripts/e2e/materialize-release-model-artifact.py \
    --release-models-dir services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/models/embedding \
    --snapshot "$EMBEDDING_SNAPSHOT" \
    --output ~/rag-model-artifacts/e5-large-prerentree-2026-2027-$(date +%Y%m%d) \
    --expected-inventory-sha256 "$(sha256sum services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/models/embedding/SHA256SUMS | cut -d' ' -f1)"
```

L'outil **copie** : il reprend le `manifest.json` et le `SHA256SUMS` de la
release, y joint les fichiers de poids du snapshot, vérifie chaque empreinte, et
refuse tout écart. Il ne recalcule rien.

> **Si l'empreinte produite ne coïncide pas, ne rien ajuster.** L'outil ou son
> entrée est en faute. Un ajustement recréerait précisément le défaut des deux
> producteurs.

Il refuse d'écraser un répertoire existant : toujours produire un artefact
**nouveau et horodaté**, pour que le retour arrière reste deux lignes de `.env`.

### Contrôles

```bash
MODEL_ARTIFACT_DIR=<nouvel artefact> MODEL_ARTIFACT_INVENTORY_SHA256=<empreinte> \
  scripts/e2e/verify-embedding-model-artifact.sh
```

Attendu : `runtime artifact contract verified` (contrôle de complétude compris)
et `model loaded offline, dimension=1024`.

Puis **preuve de non-dérive du retrieval**, sur l'artefact final et non sur un
cache : ré-encoder le texte de chunks existants avec la convention d'ingestion
(`format_passage` → `"passage: "`, `normalize_embeddings=True`) et comparer aux
vecteurs stockés. Trois collections distinctes au minimum.

**Seuil d'arrêt : écart à 1 supérieur à 10⁻⁷.** L'écart normal est de l'ordre de
10⁻⁹, plancher imposé par la sérialisation à huit décimales à l'ingestion. Au-delà
du seuil, ne pas poursuivre : ce serait le signe que le modèle de requête n'est
pas le modèle d'index.

## 4ter. Ré-émettre le placement de scope — EN DERNIER

Le rescellement change `release-registry.json`, qui est une **entrée du
producteur** du placement de scope. `docs/reports/release_scope_placement_20260825.jsonl`
et sa provenance doivent donc être ré-émis.

`test_current_head_has_no_drift_in_any_producer_input_blob` le signale, et il a
raison de le faire : un document qui atteste « projeté depuis cet état du dépôt »
doit être réémis quand cet état change. Le figer en sachant l'entrée périmée
reproduirait le défaut de l'empreinte sans référent, deux couches plus haut.

### Règle de séquencement — le piège

> **Produire la provenance en DERNIER — et surtout APRÈS LE COMMIT.**

`produce_release_scope_placement_from_git` lit ses entrées depuis un **arbre
git nommé**, jamais depuis le répertoire de travail. Une ré-émission non commitée
est donc invisible pour lui : produire la provenance avant de commiter
enregistrerait l'ancien contenu, et le document serait faux dès son écriture —
sans qu'aucun test ne le signale, puisqu'il serait cohérent avec l'arbre qu'il
nomme.

Constaté le 28/08/2026 : le registre valait `2a963bd9…` dans l'arbre HEAD et
`585099bc…` dans le répertoire de travail. Seul le premier serait entré dans la
provenance.

L'ordre est donc : **CI verte → commit → production de la provenance depuis le
nouveau HEAD → second commit → rejeu du test de dérive.**

La provenance scelle 36 empreintes de blobs d'entrée sous un `source_tree_sha`.
La produire puis modifier un autre fichier du lot la périme **à la naissance** :
elle attesterait un état du dépôt qui n'existe plus.

Après **toute** édition ultérieure, si tardive soit-elle — une correction de
test, une coquille de documentation — rejouer :

```bash
cd services/rag-pedago && .venv/bin/python -m pytest -q \
  tests/test_production_release_scope_placement.py
```

### Production

```bash
python3 scripts/produce_release_scope_placement.py --check   # sans écrire
python3 scripts/produce_release_scope_placement.py           # écrit
```

Le CLI est une **enveloppe mince** autour de
`nexus_contracts.produce_release_scope_placement_from_git`. Il n'ordonne rien, ne
reformate rien, n'ajoute aucune clé de son cru : deux producteurs du même
artefact qui divergent d'un détail de sérialisation produisent deux empreintes
irréconciliables (dette n°19).

`test_cli_output_is_byte_identical_to_the_committed_documents` l'établit au sens
fort — rejoué sur l'arbre enregistré, le CLI reproduit les documents versionnés
octet pour octet. Les tests passent par le CLI, jamais par un appel parallèle :
**un producteur, un chemin**.

### Enchaînement complet d'une ré-émission

| Ordre | Étape | Référence |
|---|---|---|
| 1 | Préalables : miroir PDF, artefacts modèles, arbre propre | §0 |
| 2 | Test RED exprimant la cause | §1 |
| 3 | Rejeu à blanc, reproductibilité, diff | §2, §2.2 |
| 4 | **Balayage inverse de fermeture** | §2.3 |
| 5 | Ré-émission réelle | §4 |
| 6 | Matérialisation de l'artefact runtime | §4bis |
| 7 | Report des ancres `.env` | §4 |
| 8 | Vérification des 18 bindings Ed25519 | §3 |
| 9 | CI complète des trois paquets | §2.3 |
| 10 | **Commit** — la provenance a besoin d'un arbre git | §4ter |
| 11 | **Placement de scope et provenance, depuis le nouveau HEAD** | §4ter |
| 12 | Second commit, puis rejeu du test de dérive | §4ter |

Les étapes 9 à 12 forment une boucle : toute correction exigée par la CI après
l'étape 11 modifie l'arbre, donc périme la provenance. Dans ce cas, **reprendre à
l'étape 9** — CI, commit, provenance, commit — jusqu'à ce que la CI et le test de
dérive soient verts ensemble sur le même arbre.

C'est le seul point de la procédure où l'ordre ne peut pas être relâché : une
provenance produite hors séquence est fausse **sans être détectable**, puisqu'elle
reste cohérente avec l'arbre périmé qu'elle nomme.

## 5. Rollback

Le bundle est **entièrement versionné** : le retour arrière est un `git checkout`,
sans manipulation de fichier.

```bash
git checkout -- services/rag-pedago/data/releases/prerentree_2026_2027 \
                docs/reports/final_production_eligible_set_20260825.txt \
                docs/reports/production_profile_accepted_placements_20260825.json \
                docs/reports/verified_production_profiles_20260825.json

# Restaurer les deux ancres hors bundle.
cp -a services/rag-engine/infra/.env.bak_<horodatage> services/rag-engine/infra/.env

git status --porcelain   # doit être vide
```

Les artefacts modèles étant hors dépôt, **ne jamais écraser un artefact
existant** : en produire un nouveau, horodaté, et ne changer que les deux lignes
de `.env`. Le retour arrière reste alors trivial et l'artefact précédent
disponible pour investigation.

## 6. Traçabilité

Un lot = une branche = une PR. Le commit doit nommer la cause déclarée en §1,
joindre le diff attendu du §2.2, et consigner le résultat de la vérification des
18 bindings du §3. Une ré-émission sans cause écrite est indistinguable d'une
dérive.
