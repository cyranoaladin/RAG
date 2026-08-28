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
