# Review-binding Atomic Rotation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer atomiquement l'ancre review-binding perdue avant premier usage par une nouvelle clé opérateur sauvegardée, restaurée et vérifiée, sans exposer de matière privée.

**Architecture:** Le privé reste exclusivement hors dépôt dans le répertoire opérateur `0700`; le dépôt ne reçoit que l'entrée publique canonique, l'ADR, les tests et le rapport. Le contrat existant reste inchangé : la vraie clé est exercée par nonce et restauration, tandis que le round-trip producteur utilise exclusivement une graine et une ancre `environment=test`. Le round-trip synthétique production-format exécuté avant cette correction est une déviation historique non reproductible, jamais persistée ni liée à une autorisation réelle.

**Tech Stack:** Python 3.11+, `cryptography`, Pydantic/nexus-contracts, pytest, GnuPG 2.4, Git/GitHub CLI, gitleaks.

---

## Précondition exécutée : génération sûre

La génération a été exécutée avant ce plan avec `umask(0o077)`, création des
répertoires `0700`, ouverture `O_CREAT|O_EXCL`, écriture directe de la graine
Raw hexadécimale dans le privé `0600`, puis dérivation du public séparé en
`0644`. La commande n'a imprimé que chemins, permissions, tailles, empreinte
publique et verdict nonce ; jamais la graine. Elle n'a placé la graine ni en
argument ni dans une variable shell.

Le primaire existe déjà. Toute étape suivante doit refuser sa régénération,
son écrasement ou sa troncature. Preuve observée : répertoire `0700`, privé
`0600` de 64 octets, public `0644`, nonce vérifié.

## Chunk 1: Ancre gouvernée et documentation

### Task 1: Verrouiller l'état attendu de l'ancre

**Files:**
- Modify: `packages/contracts/tests/test_review_binding_contract.py`
- Test: `packages/contracts/tests/test_review_binding_contract.py`

- [x] **Step 1: Ajouter le test rouge de l'ancre canonique**

Le test dérive la racine depuis `__file__`, charge
`governance/trust-anchors/review-binding-v1.json` avec `parse_trust_anchor` et
affirme : protocole V1, exactement une clé, nouvel identifiant, algorithme
Ed25519, environnement production, nouvelle clé publique et ancien identifiant
absent.

```python
def test_governed_production_anchor_is_the_atomic_replacement() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    raw = (
        repository_root / "governance/trust-anchors/review-binding-v1.json"
    ).read_bytes()
    anchor = parse_trust_anchor(raw)
    assert anchor.protocol_version == REVIEW_BINDING_PROTOCOL_VERSION
    assert len(anchor.keys) == 1
    key = anchor.key("review-binding-v1-2026-08-25", environment="production")
    assert key.algorithm == "ed25519"
    assert key.public_key == "1f34648789fe7ebdfde6c64197039c0ffa0cd36b98317ce7cad4836a26a058d8"
    with pytest.raises(ReviewBindingError, match="not declared"):
        anchor.key("review-binding-v1-2026-08-13", environment="production")
```

- [x] **Step 2: Exécuter le test et vérifier le rouge attendu**

```bash
PYTHONPATH=packages/contracts/src python3 -m pytest -q \
  packages/contracts/tests/test_review_binding_contract.py \
  -k governed_production_anchor
```

Expected rouge précis : le lookup du nouvel identifiant lève
`ReviewBindingError: ... is not declared ...`. Après Task 2, le nouveau lookup
passe et celui de l'ancien identifiant lève ce refus attendu : c'est le vert.

### Task 2: Remplacer atomiquement l'entrée publique

**Files:**
- Modify: `governance/trust-anchors/review-binding-v1.json`
- Test: `packages/contracts/tests/test_review_binding_contract.py`

- [x] **Step 1: Remplacer l'entrée complète**

Conserver le protocole et une seule entrée :

```text
key_id=review-binding-v1-2026-08-25
algorithm=ed25519
environment=production
public_key=1f34648789fe7ebdfde6c64197039c0ffa0cd36b98317ce7cad4836a26a058d8
```

Le commentaire public indique une clé opérateur créée le 2026-08-25, privée
hors Git/CI/serveur/build et sauvegarde chiffrée requise. Il ne cite aucun
emplacement machine-local.

- [x] **Step 2: Rejouer le test rouge et vérifier le vert**

Run: même commande que Task 1. Expected: `PASS`.

- [x] **Step 3: Exécuter toute la suite contractuelle review-binding**

```bash
PYTHONPATH=packages/contracts/src python3 -m pytest -q \
  packages/contracts/tests/test_review_binding_contract.py
```

Expected: 0 échec.

### Task 3: Adapter le producteur et l'ADR

**Files:**
- Modify: `services/rag-engine/tests/test_review_binding_producer.py`
- Modify: `docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md`
- Test: `services/rag-engine/tests/test_review_binding_producer.py`

- [x] **Step 1: Aligner la fixture du producteur**

Nommer la fixture d'après la génération 2026-08-25 sans utiliser le privé
réel. Conserver `environment=test` et les graines factices. Affirmer que le
reçu nominal transporte ce `key_id` avec `assert signed.key_id == KEY_ID`.
Aucun rouge n'est attendu pour ce renommage : il ne crée pas de comportement
de production et constitue le refactor suivant le cycle rouge/vert de l'ancre.

- [x] **Step 2: Amendement ADR exact**

Documenter l'ancien identifiant et l'ancienne empreinte publique complète avec
`LOST_BEFORE_FIRST_USE`, hors confiance active. Documenter le remplacement
atomique, zéro chevauchement, la nouvelle empreinte publique, la possession
opérateur hors Git/CI/serveur/build, la signature locale transitoire et la
séparation avec le registre de révocation des autorisations. Corriger les
anciens paragraphes « secret CI », « ancre non provisionnée »,
`Provisioning ready` et « rotation non traitée ».

- [x] **Step 3: Exécuter la suite producteur**

```bash
PYTHONPATH=packages/contracts/src:services/rag-engine/src \
  python3 -m pytest -q services/rag-engine/tests/test_review_binding_producer.py
```

Expected: 0 échec.

- [x] **Step 4: Commit du chunk**

```bash
git add governance/trust-anchors/review-binding-v1.json \
  packages/contracts/tests/test_review_binding_contract.py \
  services/rag-engine/tests/test_review_binding_producer.py \
  docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md
git commit -m "governance: remplacer l'ancre review-binding perdue"
```

## Chunk 2: Preuves opérateur hors dépôt

### Task 4: Sauvegarder, restaurer et exercer la nouvelle clé

**Files:**
- Runtime only: `~/.local/share/nexus-rag/operator-keys/review-binding-v1-2026-08-25/`
- Runtime only: `${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}/nexus-rag/operator-keys/review-binding-v1-2026-08-25/`
- Temporary only: répertoire produit par `mktemp -d`

> **Recette initiale supersédée — ne pas exécuter les Steps 1–8 ci-dessous.**
> Leur première rédaction reposait sur des `assert`, n'assurait pas les
> écritures complètes ni `fsync`, et le round-trip Step 7 utilisait à tort la
> clé de production pour un reçu synthétique. L'exécution finale a utilisé un
> script opérateur hors Git audité : refus de `PYTHONOPTIMIZE`, verrou exclusif,
> contrôles explicites, fichiers temporaires privés, publication sans
> écrasement par identité device/inode, rollback borné, écriture complète,
> relecture et `fsync`. Le producteur est désormais exercé uniquement par la
> fixture `environment=test`; la vraie clé ne sert qu'au nonce et à la preuve
> de restauration. Ce helper local consomme
> `NEXUS_REVIEW_BINDING_BACKUP_ROOT` ; l'exécution probante a utilisé sa valeur
> par défaut. Il exige une racine absolue et refuse avant GPG tout support dont
> le `st_dev` est identique à celui de la clé primaire.

- [x] **Step 0: Exécuter la recette opérateur durcie hors Git**

Résultats observés : backup GPG chiffré, checksum relu, restauration publique
égale à l'ancre, nonce vérifié, temporaires supprimés. Un premier essai du
round-trip Step 7 avait produit en mémoire un reçu synthétique au format
production avant cette correction ; il n'a jamais été écrit ni lié à une
autorisation réelle et ne doit pas être reproduit.

- [ ] **Step 1 supersédée: Vérifier le primaire existant**

Vérifier propriétaire, répertoire `0700`, privé `0600`, public `0644` maximum,
taille privée 64 octets et forme hexadécimale sans jamais afficher la valeur.

```bash
python3 - <<'PY'
import os, re, stat
from pathlib import Path
data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
p = data_home / 'nexus-rag/operator-keys/review-binding-v1-2026-08-25'
private = p / 'review-binding-v1-2026-08-25.seed.hex'
public = p / 'review-binding-v1-2026-08-25.public.json'
for component in (data_home / 'nexus-rag', data_home / 'nexus-rag/operator-keys', p):
    meta = component.lstat()
    assert stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
    assert meta.st_uid == os.getuid() and meta.st_mode & 0o777 == 0o700
for path, mode in ((private, 0o600), (public, 0o644)):
    meta = path.lstat()
    assert stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
    assert meta.st_uid == os.getuid() and meta.st_mode & 0o777 <= mode
fd = os.open(private, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    raw = os.read(fd, 65)
finally:
    os.close(fd)
assert len(raw) == 64 and re.fullmatch(rb'[0-9a-f]{64}', raw)
print('PRIMARY_KEY_STRUCTURE_VALID=true')
PY
```

- [ ] **Step 2 supersédée: Préflight du support de sauvegarde**

```bash
NEXUS_KEY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
NEXUS_REVIEW_BINDING_BACKUP_ROOT="${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}"
BACKUP_DIR="$NEXUS_REVIEW_BINDING_BACKUP_ROOT/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
test "$(findmnt -rn -T "$NEXUS_REVIEW_BINDING_BACKUP_ROOT" -o TARGET)" = "$NEXUS_REVIEW_BINDING_BACKUP_ROOT"
test "$(findmnt -rn -T "$NEXUS_REVIEW_BINDING_BACKUP_ROOT" -o SOURCE)" != "$(findmnt -rn -T / -o SOURCE)"
test "$(df -Pk "$NEXUS_REVIEW_BINDING_BACKUP_ROOT" | awk 'NR==2 {print $4}')" -gt 1024
export NEXUS_REVIEW_BINDING_BACKUP_ROOT BACKUP_DIR
python3 - <<'PY'
import os
import stat
from pathlib import Path

root = Path(os.environ["BACKUP_DIR"])
backup_root = Path(os.environ["NEXUS_REVIEW_BINDING_BACKUP_ROOT"])
for component in (
    backup_root,
    backup_root / "nexus-rag",
    backup_root / "nexus-rag/operator-keys",
    root,
):
    meta = component.lstat()
    assert stat.S_ISDIR(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
    assert meta.st_uid == os.getuid()
    if component == backup_root:
        assert meta.st_mode & 0o022 == 0
    else:
        assert meta.st_mode & 0o777 == 0o700
ciphertext = root / "review-binding-v1-2026-08-25.seed.hex.gpg"
assert not ciphertext.exists() and not ciphertext.is_symlink()
print("BACKUP_TARGET_STRUCTURE_VALID=true")
PY
```

Expected: exit 0 ; montage distinct actif, chemin non symbolique, propriétaire
correct et au moins 1 MiB disponible.

- [ ] **Step 3 supersédée: Gate humain unique et création GPG**

Action humaine unique : saisir puis confirmer localement une phrase secrète
forte dans `pinentry`; lors du restore, la ressaisir dans la même interface si
GPG le demande. Ne rien saisir dans la conversation.

```bash
set -euo pipefail
set -C
NEXUS_KEY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
NEXUS_REVIEW_BINDING_BACKUP_ROOT="${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}"
BACKUP_DIR="$NEXUS_REVIEW_BINDING_BACKUP_ROOT/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
CIPHERTEXT="$BACKUP_DIR/review-binding-v1-2026-08-25.seed.hex.gpg"
test ! -e "$CIPHERTEXT"
test ! -L "$CIPHERTEXT"
gpg --no-symkey-cache --pinentry-mode ask --symmetric \
  --cipher-algo AES256 --s2k-mode 3 --s2k-digest-algo SHA512 \
  --output - "$NEXUS_KEY_ROOT/review-binding-v1-2026-08-25.seed.hex" \
  > "$CIPHERTEXT"
chmod 0600 "$CIPHERTEXT"
```

Succès : GPG exit 0, ciphertext régulier non vide en `0600`, aucune copie
claire sous `NEXUS_REVIEW_BINDING_BACKUP_ROOT`.

- [ ] **Step 4 supersédée: Vérifier le ciphertext**

```bash
NEXUS_REVIEW_BINDING_BACKUP_ROOT="${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}"
BACKUP_DIR="$NEXUS_REVIEW_BINDING_BACKUP_ROOT/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
export NEXUS_REVIEW_BINDING_BACKUP_ROOT BACKUP_DIR
python3 - <<'PY'
import os
import stat
from pathlib import Path

path = Path(os.environ["BACKUP_DIR"]) / "review-binding-v1-2026-08-25.seed.hex.gpg"
meta = path.lstat()
assert stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode)
assert meta.st_uid == os.getuid() and meta.st_mode & 0o777 == 0o600
assert meta.st_size > 0
print("BACKUP_CIPHERTEXT_STRUCTURE_VALID=true")
PY
python3 - <<'PY'
import hashlib
import os
from pathlib import Path

root = Path(os.environ["BACKUP_DIR"])
ciphertext = root / "review-binding-v1-2026-08-25.seed.hex.gpg"
checksum = root / "review-binding-v1-2026-08-25.seed.hex.gpg.sha256"
assert not checksum.exists() and not checksum.is_symlink()
digest = hashlib.sha256(ciphertext.read_bytes()).hexdigest()
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
fd = os.open(checksum, flags, 0o600)
try:
    os.write(fd, f"{digest}  {ciphertext.name}\n".encode("ascii"))
finally:
    os.close(fd)
if hashlib.sha256(ciphertext.read_bytes()).hexdigest() != digest:
    raise SystemExit("BACKUP_CHECKSUM_MISMATCH")
print(f"BACKUP_CIPHERTEXT_SHA256={digest}")
print("BACKUP_CHECKSUM_VERIFIED=true")
PY
```

Expected : structure et checksum du ciphertext vérifiés. Aucun hash du privé
n'est calculé.

- [ ] **Step 5 supersédée: Restaurer dans un temporaire `0700`**

Les Steps 5 à 8 s'exécutent dans une seule session PTY shell persistante. La
session est ouverte ici avec `set -euo pipefail` et ne doit être rendue/fermée
qu'après Step 8 ; les blocs suivants sont envoyés à cette même session. Ainsi,
variables et traps persistent et le cleanup `EXIT` ne court pas prématurément.

```bash
set -euo pipefail
umask 077
NEXUS_KEY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
NEXUS_REVIEW_BINDING_BACKUP_ROOT="${NEXUS_REVIEW_BINDING_BACKUP_ROOT:-/mnt/sauvegardes}"
BACKUP_DIR="$NEXUS_REVIEW_BINDING_BACKUP_ROOT/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
RESTORE_DIR="$(mktemp -d /tmp/nexus-review-binding-restore-20260825.XXXXXX)"
case "$RESTORE_DIR" in /tmp/nexus-review-binding-restore-20260825.*) ;; *) exit 2;; esac
cleanup_restore() {
  python3 - "$RESTORE_DIR" <<'PY'
import os
import shutil
import stat
import sys
from pathlib import Path

target = Path(sys.argv[1])
expected_parent = Path("/tmp")
if not target.exists():
    raise SystemExit(0)
if target.parent != expected_parent or not target.name.startswith(
    "nexus-review-binding-restore-20260825."
):
    raise SystemExit("REFUSING_UNSAFE_TEMP_CLEANUP")
meta = target.lstat()
if not stat.S_ISDIR(meta.st_mode) or stat.S_ISLNK(meta.st_mode):
    raise SystemExit("REFUSING_NON_DIRECTORY_TEMP_CLEANUP")
if meta.st_uid != os.getuid():
    raise SystemExit("REFUSING_FOREIGN_TEMP_CLEANUP")
shutil.rmtree(target)
PY
}
trap cleanup_restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
gpg --no-symkey-cache --pinentry-mode ask \
  --output "$RESTORE_DIR/restored.seed.hex" --decrypt \
  "$BACKUP_DIR/review-binding-v1-2026-08-25.seed.hex.gpg"
chmod 0600 "$RESTORE_DIR/restored.seed.hex"
```

Expected: GPG exit 0 et fichier restauré de 64 octets ; aucune sortie privée.

- [ ] **Step 6 supersédée: Vérifier primaire/restauration/ancre et nonce**

Depuis la racine du worktree, exécuter le script complet suivant. Les octets
privés ne sont ni convertis en texte pour affichage, ni inclus dans une erreur.

```bash
export NEXUS_KEY_ROOT RESTORE_DIR
PYTHONPATH=packages/contracts/src python3 - <<'PY'
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from nexus_contracts.review_binding import parse_trust_anchor

def read_seed(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 65)
    finally:
        os.close(fd)
    if len(raw) != 64 or re.fullmatch(rb"[0-9a-f]{64}", raw) is None:
        raise SystemExit("INVALID_SEED_STRUCTURE")
    return bytes.fromhex(raw.decode("ascii"))

primary_seed = read_seed(
    Path(os.environ["NEXUS_KEY_ROOT"])
    / "review-binding-v1-2026-08-25.seed.hex"
)
restored_seed = read_seed(Path(os.environ["RESTORE_DIR"]) / "restored.seed.hex")
primary = Ed25519PrivateKey.from_private_bytes(primary_seed)
restored = Ed25519PrivateKey.from_private_bytes(restored_seed)
primary_public = primary.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
restored_public = restored.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
anchor = parse_trust_anchor(
    Path("governance/trust-anchors/review-binding-v1.json").read_bytes()
)
anchor_public = bytes.fromhex(
    anchor.key(
        "review-binding-v1-2026-08-25", environment="production"
    ).public_key
)
if not primary_public == restored_public == anchor_public:
    raise SystemExit("PUBLIC_KEY_MISMATCH")
print("PRIMARY_RESTORE_ANCHOR_PUBLIC_MATCH=true")
nonce = os.urandom(32)
signature = primary.sign(nonce)
Ed25519PublicKey.from_public_bytes(anchor_public).verify(signature, nonce)
print("NONCE_SIGNATURE_VERIFIED=true")
del signature, nonce, primary_seed, restored_seed
PY
```

Sorties uniques attendues :

```text
PRIMARY_RESTORE_ANCHOR_PUBLIC_MATCH=true
NONCE_SIGNATURE_VERIFIED=true
```

- [ ] **Step 7 supersédée: Faire le round-trip factice réel**

Créer exclusivement dans le temporaire privé le script ci-dessous. Le fichier
est refusé s'il existe déjà ou s'il est symbolique ; aucune matière privée
n'est embarquée dans son source.

```bash
export RESTORE_DIR NEXUS_KEY_ROOT
python3 - <<'PY'
import os
from pathlib import Path

target = Path(os.environ["RESTORE_DIR"]) / "roundtrip.py"
source = r'''from __future__ import annotations
import argparse
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.review_binding import (
    expected_challenge_digest,
    parse_trust_anchor,
    require_challenge_is_bound,
    require_matches_authorization,
    verify_review_binding,
)
import ingestor.ingestion_worker.issue_review_binding_cli as producer
from ingestor.ingestion_control.github_authority import (
    GitHubBlob,
    PullRequestActorContext,
    ReviewVerification,
)

REPOSITORY = "cyranoaladin/RAG"
PULL_REQUEST = 1
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REVIEWER = "abenrhouma"
AUTHOR = "rotation-roundtrip"
AUTHORIZATION_ID = "rotation-roundtrip-v1"
NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
SCOPE: dict[str, Any] = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}
artifact = ScopeAuthorizationArtifactV2.model_validate({
    "protocol_version": "LOT41A-V2",
    "authorization_id": AUTHORIZATION_ID,
    "decision": "AUTHORIZE_INGESTION_SCOPE",
    "scope": SCOPE,
    "manifest_digest": "c" * 64,
    "profile_id": SCOPE["collection"],
    "profile_version": "v1",
    "profile_fingerprint": "d" * 64,
    "allowed_domains": ["eduscol.education.fr"],
    "rights_categories": ["officiel_public"],
    "exclusions": [],
    "allowed_content_sha256": ["e" * 64],
    "pii_absence_attested": True,
    "pii_absence_evidence": "Artefact factice jetable, aucune donnee personnelle.",
    "valid_from": "2026-08-25T00:00:00.000000Z",
    "valid_until": "2026-12-31T23:59:59.999999Z",
})
authorization_raw = artifact.canonical_bytes()
challenge = "NEXUS-TRUSTED-REVIEW-V1:" + expected_challenge_digest(
    repository=REPOSITORY, pull_request=PULL_REQUEST, base_ref="main",
    base_sha=BASE_SHA, head_sha=HEAD_SHA, author=AUTHOR, reviewer=REVIEWER,
)

def fake_review(**_kwargs: Any) -> ReviewVerification:
    return ReviewVerification(
        approved=True, reason="approved", repository=REPOSITORY,
        pull_request=PULL_REQUEST, base_sha=BASE_SHA, head_sha=HEAD_SHA,
        reviewer=REVIEWER, review_id=1, submitted_at="2026-08-25T11:59:00Z",
        challenge=challenge,
    )

def fake_context(**_kwargs: Any) -> PullRequestActorContext:
    return PullRequestActorContext(
        repository=REPOSITORY, pull_request=PULL_REQUEST, author=AUTHOR,
        base_ref="main", reviewer=REVIEWER, reviewer_permission="admin",
        reviewer_role_name="admin",
    )

def fake_blob(**_kwargs: Any) -> GitHubBlob:
    return GitHubBlob(
        repository=REPOSITORY,
        path=canonical_authorization_path(AUTHORIZATION_ID), ref=HEAD_SHA,
        blob_sha=git_blob_sha1(authorization_raw), content=authorization_raw,
    )

producer.verify_review = fake_review
producer.pull_request_actor_context = fake_context
producer.fetch_blob_at_ref = fake_blob
seed_path = (
    Path(os.environ["NEXUS_KEY_ROOT"])
    / "review-binding-v1-2026-08-25.seed.hex"
)
fd = os.open(seed_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    seed_text = os.read(fd, 65).decode("ascii")
finally:
    os.close(fd)
try:
    os.environ[producer.SIGNING_KEY_ENV] = seed_text
    raw = producer._issue_binding(
        argparse.Namespace(
            repository=REPOSITORY, pull_request=PULL_REQUEST,
            expected_head=HEAD_SHA, authorization_id=AUTHORIZATION_ID,
            validity_days=30, key_id="review-binding-v1-2026-08-25",
        ),
        now=NOW,
    )
finally:
    os.environ.pop(producer.SIGNING_KEY_ENV, None)
    seed_text = ""
anchor = parse_trust_anchor(
    Path("governance/trust-anchors/review-binding-v1.json").read_bytes()
)
binding = verify_review_binding(
    raw, trust_anchor=anchor, environment="production", now=NOW
)
print("FAKE_PRODUCER_ROUNDTRIP_VERIFIED=true")
require_challenge_is_bound(binding)
require_matches_authorization(
    binding, authorization_id=AUTHORIZATION_ID,
    authorization_bytes=authorization_raw,
    authorization_git_blob_sha1=git_blob_sha1(authorization_raw),
    expected_repository=REPOSITORY, accepted_reviewers=(REVIEWER,),
)
print("FAKE_AUTHORIZATION_BINDING_VERIFIED=true")
if producer.SIGNING_KEY_ENV in os.environ:
    raise SystemExit("SIGNING_ENV_NOT_CLEARED")
print("SIGNING_ENV_CLEARED=true")
'''
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
fd = os.open(target, flags, 0o700)
try:
    os.write(fd, source.encode("utf-8"))
finally:
    os.close(fd)
PY
PYTHONPATH=packages/contracts/src:services/rag-engine/src \
  python3 "$RESTORE_DIR/roundtrip.py"
```

Le script appelle exactement
`ingestor.ingestion_worker.issue_review_binding_cli._issue_binding`. Il remplace
uniquement `verify_review`, `pull_request_actor_context` et
`fetch_blob_at_ref` par des fonctions retournant `ReviewVerification`,
`PullRequestActorContext` et `GitHubBlob` réels sur une autorisation LOT41A-V2
factice canonique. Il lit le primaire, affecte
`os.environ[SIGNING_KEY_ENV]` dans le processus courant, puis le supprime dans
un `finally`. Il passe les octets retournés à `parse_trust_anchor` sur le fichier
gouverné, `verify_review_binding(..., environment="production")`,
`require_challenge_is_bound` et `require_matches_authorization`.

Sorties uniques attendues :

```text
FAKE_PRODUCER_ROUNDTRIP_VERIFIED=true
FAKE_AUTHORIZATION_BINDING_VERIFIED=true
SIGNING_ENV_CLEARED=true
```

- [ ] **Step 8 supersédée: Détruire les temporaires**

Le `trap` de Step 5 valide puis supprime le répertoire complet, y compris la
restauration et le script. Après les vérifications, l'appeler explicitement,
désarmer le trap seulement si le répertoire a disparu, puis vérifier son
absence. Conserver le primaire et le ciphertext.

```bash
cleanup_restore
test ! -e "$RESTORE_DIR"
trap - EXIT INT TERM
```

## Chunk 3: Rapport, contrôles et PR

### Task 5: Prouver l'absence de fuite privée

**Files:**
- Create: `docs/reports/lot_1_review_binding_rotation_20260825.md`

- [x] **Step 1: Scanner fichiers suivis, diff et processus**

Lire la graine depuis le primaire uniquement en mémoire ; comparer sans
l'afficher à chaque blob suivi, au diff, aux artefacts générés, aux historiques
et logs locaux pertinents créés pendant le lot, aux arguments et aux
environnements `/proc/<pid>/environ` des processus du même utilisateur. Vérifier
séparément que `NEXUS_REVIEW_BINDING_SIGNING_KEY` est absent après le test.

Le script complet ci-dessous utilise `git ls-files -z`, chaque blob du range Git,
le diff depuis la base, les non-suivis, les artefacts ignorés hors dépendances et
caches, les historiques shell/agent datés depuis le début du lot et `/proc` du
même UID. Il compare la représentation hexadécimale et les 32 octets Raw sans
jamais imprimer la valeur recherchée ou le contenu lu. Il ne suit aucun symlink,
lit chaque fichier en flux et impose un délai global de cinq minutes. Les
dépendances/caches exclus sont comptés en fichiers et octets.

```bash
NEXUS_KEY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/nexus-rag/operator-keys/review-binding-v1-2026-08-25"
export NEXUS_KEY_ROOT
python3 - <<'PY'
from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path

BASE = "3566cafb44138d6a7f00296dc0654257f9bf0ad6"
root = Path.cwd().resolve()
deadline = time.monotonic() + 300.0
private = (
    Path(os.environ["NEXUS_KEY_ROOT"])
    / "review-binding-v1-2026-08-25.seed.hex"
)
fd = os.open(private, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    seed_hex = os.read(fd, 65)
finally:
    os.close(fd)
if len(seed_hex) != 64 or re.fullmatch(rb"[0-9a-f]{64}", seed_hex) is None:
    raise SystemExit("INVALID_SEED_STRUCTURE")
needles = (seed_hex, seed_hex.upper(), bytes.fromhex(seed_hex.decode("ascii")))

def contains_private(data: bytes) -> bool:
    return any(needle in data for needle in needles)

def check_deadline() -> None:
    if time.monotonic() >= deadline:
        raise SystemExit("PRIVATE_SCAN_TIMEOUT")

def scan_reader(read: object) -> bool:
    overlap = b""
    while True:
        check_deadline()
        chunk = read(1024 * 1024)  # type: ignore[attr-defined]
        if not chunk:
            return False
        data = overlap + chunk
        if contains_private(data):
            return True
        overlap = data[-127:]

def scan_regular(path: Path) -> bool:
    check_deadline()
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return False
    except PermissionError as exc:
        raise SystemExit("PRIVATE_SCAN_PERMISSION_DENIED") from exc
    if not stat.S_ISREG(meta.st_mode) or stat.S_ISLNK(meta.st_mode):
        return False
    try:
        handle = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    except (OSError, PermissionError) as exc:
        raise SystemExit("PRIVATE_SCAN_OPEN_FAILED") from exc
    try:
        with os.fdopen(handle, "rb", closefd=False) as stream:
            return scan_reader(stream.read)
    finally:
        os.close(handle)

def git_paths(*args: str) -> list[Path]:
    raw = subprocess.run(
        ["git", *args, "-z"], cwd=root, check=True, stdout=subprocess.PIPE,
        timeout=120,
    ).stdout
    return [root / os.fsdecode(item) for item in raw.split(b"\0") if item]

tracked_matches = sum(scan_regular(path) for path in git_paths("ls-files"))
untracked_matches = sum(
    scan_regular(path)
    for path in git_paths("ls-files", "--others", "--exclude-standard")
)
diff = subprocess.run(
    ["git", "diff", "--binary", BASE, "--", "."],
    cwd=root, check=True, stdout=subprocess.PIPE,
).stdout
diff_matches = int(contains_private(diff))

history_matches = 0
objects = subprocess.run(
    ["git", "rev-list", "--objects", f"{BASE}..HEAD"], cwd=root, check=True,
    stdout=subprocess.PIPE, timeout=120,
).stdout.splitlines()
for item in objects:
    check_deadline()
    oid = item.split(b" ", 1)[0].decode("ascii")
    kind = subprocess.run(
        ["git", "cat-file", "-t", oid], cwd=root, check=True,
        stdout=subprocess.PIPE, timeout=30,
    ).stdout.strip()
    if kind != b"blob":
        continue
    process = subprocess.Popen(
        ["git", "cat-file", "blob", oid], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    found = scan_reader(process.stdout.read)
    if found:
        history_matches += 1
        process.kill()
    if process.wait(timeout=30) not in (0, -9):
        raise SystemExit("GIT_BLOB_SCAN_FAILED")

excluded_names = {
    "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "Cache", "CachedData",
}
artifact_matches = 0
artifact_excluded_files = 0
artifact_excluded_bytes = 0
for path in git_paths("ls-files", "--others", "--ignored", "--exclude-standard"):
    check_deadline()
    relative_parts = path.relative_to(root).parts
    if any(part in excluded_names for part in relative_parts):
        try:
            meta = path.lstat()
        except (FileNotFoundError, PermissionError):
            continue
        if stat.S_ISREG(meta.st_mode) and not stat.S_ISLNK(meta.st_mode):
            artifact_excluded_files += 1
            artifact_excluded_bytes += meta.st_size
        continue
    artifact_matches += int(scan_regular(path))

lot_start_epoch = 1787608800  # 2026-08-25T00:00:00+01:00
log_candidates: set[Path] = set()
for fixed in (Path.home() / ".bash_history", Path.home() / ".zsh_history"):
    log_candidates.add(fixed)
for log_root in (
    Path.home() / ".codex", Path.home() / ".cursor", Path.home() / ".claude"
):
    if not log_root.is_dir() or log_root.is_symlink():
        continue
    for dirpath, dirnames, filenames in os.walk(log_root, followlinks=False):
        dirnames[:] = [
            name for name in dirnames
            if name not in {"Cache", "CachedData", "node_modules", ".git"}
        ]
        for name in filenames:
            candidate = Path(dirpath) / name
            try:
                if candidate.lstat().st_mtime >= lot_start_epoch:
                    log_candidates.add(candidate)
            except (FileNotFoundError, PermissionError):
                pass
local_log_matches = sum(scan_regular(path) for path in log_candidates)

arg_matches = 0
env_matches = 0
process_unreadable = 0
uid = os.getuid()
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    try:
        if proc.stat().st_uid != uid:
            continue
        cmdline = (proc / "cmdline").read_bytes()
        environ = (proc / "environ").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        continue
    except PermissionError:
        process_unreadable += 1
        continue
    arg_matches += int(contains_private(cmdline))
    env_matches += int(contains_private(environ))

print(f"TRACKED_PRIVATE_MATCHES={tracked_matches}")
print(f"UNTRACKED_PRIVATE_MATCHES={untracked_matches}")
print(f"DIFF_PRIVATE_MATCHES={diff_matches}")
print(f"GIT_HISTORY_PRIVATE_MATCHES={history_matches}")
print(f"IGNORED_ARTIFACT_PRIVATE_MATCHES={artifact_matches}")
print(f"ARTIFACT_EXCLUDED_FILES={artifact_excluded_files}")
print(f"ARTIFACT_EXCLUDED_BYTES={artifact_excluded_bytes}")
print(f"LOCAL_LOG_PRIVATE_MATCHES={local_log_matches}")
print(f"PROCESS_ARG_PRIVATE_MATCHES={arg_matches}")
print(f"PROCESS_ENV_PRIVATE_MATCHES={env_matches}")
print(f"PROCESS_UNREADABLE={process_unreadable}")
print(
    "SIGNING_ENV_PRESENT_AFTER_TEST="
    + str("NEXUS_REVIEW_BINDING_SIGNING_KEY" in os.environ).lower()
)
if any((tracked_matches, untracked_matches, diff_matches, history_matches,
        artifact_matches, local_log_matches, arg_matches, env_matches)):
    raise SystemExit("PRIVATE_MATERIAL_MATCH_DETECTED")
PY
```

Sortie attendue :

```text
TRACKED_PRIVATE_MATCHES=0
UNTRACKED_PRIVATE_MATCHES=0
DIFF_PRIVATE_MATCHES=0
GIT_HISTORY_PRIVATE_MATCHES=0
IGNORED_ARTIFACT_PRIVATE_MATCHES=0
ARTIFACT_EXCLUDED_FILES=<compte documenté>
ARTIFACT_EXCLUDED_BYTES=<volume documenté>
LOCAL_LOG_PRIVATE_MATCHES=0
PROCESS_ARG_PRIVATE_MATCHES=0
PROCESS_ENV_PRIVATE_MATCHES=0
PROCESS_UNREADABLE=<compte documenté>
SIGNING_ENV_PRESENT_AFTER_TEST=false
```

- [x] **Step 2: Exécuter gitleaks avec redaction totale**

```bash
gitleaks git --redact=100 --log-opts="3566cafb44138d6a7f00296dc0654257f9bf0ad6..HEAD"
gitleaks dir --redact=100 .
```

Expected : le scan différentiel ne remonte aucune fuite introduite par le lot.
Le scan complet est conservé comme mesure de dette : toute alerte préexistante
est rapprochée de la baseline du Lot 0 (190 constats au SHA de base), sans être
présentée comme verte ; les fichiers modifiés par ce lot doivent avoir zéro
constat.

- [x] **Step 3: Écrire le rapport assaini**

Rapporter SHA de base/head, identifiants et empreintes publiques, permissions,
checksum du ciphertext, restauration, nonce, round-trip factice, tests, scans,
limites et rollback. Ne jamais inclure graine, signature, nonce, phrase ou hash
du privé.

### Task 6: Vérification complète du lot

**Files:**
- Test: `packages/contracts/tests/test_review_binding_contract.py`
- Test: `services/rag-engine/tests/test_review_binding_producer.py`
- Test: repository governance and hygiene scripts

- [x] **Step 1: Exécuter les suites ciblées ensemble**

```bash
PYTHONPATH=packages/contracts/src:services/rag-engine/src \
  python3 -m pytest -q \
  packages/contracts/tests/test_review_binding_contract.py \
  services/rag-engine/tests/test_review_binding_producer.py
```

- [x] **Step 2: Exécuter lint, types et contrôles repository**

```bash
ruff check packages/contracts/src packages/contracts/tests \
  services/rag-engine/src/ingestor/ingestion_worker/issue_review_binding_cli.py \
  services/rag-engine/tests/test_review_binding_producer.py
(cd services/rag-engine && \
  python3 -m mypy src/ingestor/ingestion_worker/issue_review_binding_cli.py)
(cd packages/contracts && \
  python3 -m mypy src/nexus_contracts/review_binding.py)
bash scripts/check-governance-locks.sh
bash scripts/check-repository-hygiene.sh
```

Expected : producteur sans erreur. Le contrat conserve au SHA de base une
erreur connue de typage du `Literal['ed25519']`; l'exécution du lot doit être
identique à la base et ne pas ajouter d'erreur.

- [x] **Step 3: Vérifier diff et statut**

```bash
git diff --check 3566cafb44138d6a7f00296dc0654257f9bf0ad6..HEAD
git status --short --branch
```

- [ ] **Step 4: Revue conformité puis revue qualité**

Faire relire le diff exact par deux agents indépendants. Corriger et refaire
les revues jusqu'à approbation sans P0/P1/P2.

- [ ] **Step 5: Committer chaque correction et refaire les revues**

Après chaque correction : tests ciblés, commit impératif scopé, nouvelle revue
de conformité du nouveau HEAD, puis nouvelle revue qualité. Aucune correction
non commitée ne peut faire partie du résultat final.

### Task 7: Finaliser le rapport et la branche

**Files:**
- Modify: `docs/reports/lot_1_review_binding_rotation_20260825.md`
- Modify: `docs/superpowers/plans/2026-08-25-review-binding-atomic-rotation.md`

- [x] **Step 1: Mettre le rapport à jour après Task 6**

Inscrire uniquement les commandes réellement exécutées, leurs résultats, le
SHA de code revu, les preuves backup/restore, le round-trip et les limites.

- [ ] **Step 2: Commit final de tous les fichiers du lot**

```bash
git add governance/trust-anchors/review-binding-v1.json \
  packages/contracts/tests/test_review_binding_contract.py \
  services/rag-engine/tests/test_review_binding_producer.py \
  docs/adr/ADR-0035-liaison-revue-scellee-autorisation-de-scope.md \
  docs/reports/lot_1_review_binding_rotation_20260825.md \
  docs/superpowers/plans/2026-08-25-review-binding-atomic-rotation.md
git commit -m "docs: consigner la rotation review-binding"
```

- [ ] **Step 3: Vérification fraîche après commit**

Répéter les suites ciblées, scans de seed et gitleaks, `git diff --check` et
statut. Refaire les deux revues sur ce HEAD exact et inchangé.

- [ ] **Step 4: Push et PR**

Pousser `ops/review-binding-rotation-20260825`, ouvrir une PR vers `main`,
consigner base/head exacts et suivre la CI. Ne jamais fusionner.

- [ ] **Step 5: Gate humain**

Une fois CI verte et threads résolus, présenter le challenge
trusted-human-review pour le HEAD exact. Attendre l'identité GitHub prescrite.
Tout push suivant invalide ce gate et impose une nouvelle revue.

Tout constat d'une revue ou échec CI ramène à la correction : modifier, rejouer
les tests et scans, committer, puis obtenir deux nouvelles revues indépendantes
sur le nouveau HEAD. La CI et le trusted-human-review ne portent jamais sur un
HEAD remplacé.
