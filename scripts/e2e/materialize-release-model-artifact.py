#!/usr/bin/env python3
"""Matérialiser l'artefact modèle runtime à partir d'une release scellée.

═══ POURQUOI CET OUTIL EXISTE ═══════════════════════════════════════════════

Trois métiers distincts produisent ou consomment un inventaire d'artefact modèle,
et les confondre a coûté une soirée (ADR-0051, dette n°19) :

1. `scripts/e2e/prepare-embedding-model-artifact.sh` fabrique un artefact
   **candidat**, destiné à devenir l'entrée d'une release *future*. Son
   `manifest.json` porte dix clés de provenance (`revision_requested`,
   `generated_at`, `repo_commit`, versions d'outillage…).

2. `services/rag-pedago/scripts/build_production_profile_release.py` **scelle**
   la release. Son `_model_inventory` écrit son propre `manifest.json`, à trois
   clés (`model_id`, `revision`, `canonical_dim`), et cet inventaire fait
   autorité.

3. **Cet outil** matérialise l'artefact runtime *depuis* une release déjà
   scellée.

Les inventaires de (1) et (2) portent des `manifest.json` différents, donc des
empreintes irréconciliables — mêmes fichiers, mêmes poids, deux valeurs. Servir
une release scellée avec un artefact produit par (1) est structurellement
impossible : `_validate_release_model_attestations` échoue en
`release model inventory mismatch`.

═══ CE QUE CET OUTIL FAIT, ET NE FAIT PAS ═══════════════════════════════════

Il **copie**. Il ne recalcule aucun `manifest.json`, ne régénère aucun
`SHA256SUMS`, ne dérive aucune empreinte : il prend ceux de la release, y joint
les fichiers de poids issus du snapshot, et assemble.

Tout recalcul le ferait retomber dans le défaut qu'il existe pour éviter.

Son test d'acceptation est **intrinsèque** : l'empreinte d'inventaire du
répertoire produit — `sha256(SHA256SUMS)` — doit être exactement celle scellée
par la release. Aucun ajustement n'est prévu, et aucun ne doit l'être : si les
valeurs divergent, l'outil ou l'entrée est en faute, et il le signale au lieu de
corriger.

═══ USAGE ═══════════════════════════════════════════════════════════════════

    python3 scripts/e2e/materialize-release-model-artifact.py \\
        --release-models-dir services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/models/embedding \\
        --snapshot ~/sauvegardes-rag/hub-snapshots/e5-large/<revision> \\
        --output ~/rag-model-artifacts/e5-large-<horodatage>

L'empreinte imprimée est celle à reporter dans
`RAG_EMBEDDING_MODEL_INVENTORY_SHA256`.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

INVENTORY_LINE_SEPARATOR = "  "


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_inventory(inventory: bytes) -> dict[str, str]:
    """Lire l'inventaire scellé : chemin relatif -> empreinte attendue."""
    entries: dict[str, str] = {}
    for line in inventory.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition(INVENTORY_LINE_SEPARATOR)
        if len(digest) != 64 or not relative:
            raise SystemExit(f"MATERIALIZE_INVENTORY_MALFORMED: {line[:80]}")
        candidate = Path(relative)
        if candidate.is_absolute() or any(
            part in ("", ".", "..") for part in candidate.parts
        ):
            raise SystemExit(f"MATERIALIZE_INVENTORY_UNSAFE_PATH: {relative}")
        if relative in entries:
            raise SystemExit(f"MATERIALIZE_INVENTORY_DUPLICATE: {relative}")
        entries[relative] = digest
    if not entries:
        raise SystemExit("MATERIALIZE_INVENTORY_EMPTY")
    return entries


def materialize(*, release_models_dir: Path, snapshot: Path, output: Path) -> str:
    release_inventory_path = release_models_dir / "SHA256SUMS"
    release_manifest_path = release_models_dir / "manifest.json"
    for required in (release_inventory_path, release_manifest_path):
        if not required.is_file():
            raise SystemExit(f"MATERIALIZE_RELEASE_INCOMPLETE: {required}")
    if not snapshot.is_dir():
        raise SystemExit(f"MATERIALIZE_SNAPSHOT_MISSING: {snapshot}")
    if output.exists():
        raise SystemExit(
            f"MATERIALIZE_OUTPUT_EXISTS: {output} — ne jamais écraser un artefact, "
            "en produire un nouveau et ne changer que les lignes de .env"
        )

    inventory_bytes = release_inventory_path.read_bytes()
    expected = _parse_inventory(inventory_bytes)

    output.mkdir(parents=True)
    for relative in sorted(expected):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == "manifest.json":
            # Le manifeste vient de la RELEASE, jamais du snapshot : c'est la
            # première ligne de l'inventaire, donc ce qui distingue les deux
            # producteurs.
            source = release_manifest_path
        else:
            source = snapshot / relative
            if not source.is_file():
                raise SystemExit(
                    f"MATERIALIZE_SNAPSHOT_INCOMPLETE: {relative} absent de {snapshot}"
                )
        # `copyfile` suit les liens : un snapshot de cache hub est fait de liens
        # vers ../../blobs, et le vérificateur runtime refuse tout lien.
        shutil.copyfile(source, destination)
        shutil.copymode(source, destination)

    # Le sceau est celui de la release, recopié tel quel — jamais régénéré.
    (output / "SHA256SUMS").write_bytes(inventory_bytes)

    # Contrôle intrinsèque, dans cet ordre : contenu d'abord, empreinte ensuite.
    for relative, digest in sorted(expected.items()):
        actual = _sha256_file(output / relative)
        if actual != digest:
            raise SystemExit(
                f"MATERIALIZE_CONTENT_MISMATCH: {relative} "
                f"attendu={digest} obtenu={actual}"
            )

    produced = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    } - {"SHA256SUMS"}
    if produced != set(expected):
        raise SystemExit(
            "MATERIALIZE_SET_MISMATCH: "
            f"en trop={sorted(produced - set(expected))} "
            f"manquants={sorted(set(expected) - produced)}"
        )

    return hashlib.sha256(inventory_bytes).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-models-dir", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--expected-inventory-sha256",
        help=(
            "Empreinte attendue. Fournie, elle est comparée et toute divergence "
            "est fatale : l'outil ne rattrape jamais un écart."
        ),
    )
    args = parser.parse_args(argv)

    inventory_sha256 = materialize(
        release_models_dir=args.release_models_dir.resolve(),
        snapshot=args.snapshot.resolve(),
        output=args.output.resolve(),
    )

    if (
        args.expected_inventory_sha256
        and args.expected_inventory_sha256 != inventory_sha256
    ):
        raise SystemExit(
            "MATERIALIZE_INVENTORY_MISMATCH: "
            f"attendu={args.expected_inventory_sha256} obtenu={inventory_sha256}"
        )

    print(f"MATERIALIZED_ARTIFACT_DIR={args.output.resolve()}")
    print(f"MATERIALIZED_INVENTORY_SHA256={inventory_sha256}")
    print("Reporter cette empreinte dans RAG_EMBEDDING_MODEL_INVENTORY_SHA256.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
