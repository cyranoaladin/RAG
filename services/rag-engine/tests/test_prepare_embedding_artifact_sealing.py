"""Contrat de scellement de prepare-embedding-model-artifact.sh.

Le script se compose de deux étages distincts :

- l'**acquisition**, qui récupère les fichiers du modèle ;
- le **scellement**, qui produit `SHA256SUMS` puis l'empreinte d'inventaire.

Le scellement est l'autorité du script : c'est lui qui fait foi lorsqu'un
opérateur reporte `RAG_EMBEDDING_MODEL_INVENTORY_SHA256` dans `.env`. Le
28/08/2026, l'acquisition a dû être modifiée pour résoudre depuis le cache hub
local en mode `HF_HUB_OFFLINE=1` — `snapshot_download` contournant ce cache dès
qu'un `local_dir` est passé. La frontière posée à cette modification était :
toucher l'acquisition, jamais le scellement.

Ces tests pincent le comportement du scellement sur des entrées connues. Ils
échouent si une évolution de l'acquisition, ou toute autre, altère ce que le
script scelle ou l'empreinte qu'il en dérive.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "prepare-embedding-model-artifact.sh"

#: Contenu de la fixture : un répertoire plat plus deux niveaux de
#: sous-répertoires. `1_Pooling/config.json` reproduit le cas réel qui a motivé
#: ces garde-fous — un artefact embedding scellé sans son module de pooling est
#: conforme à son empreinte et incapable de se charger.
_FIXTURE: dict[str, str] = {
    "manifest.json": '{"id":"t"}\n',
    "model.safetensors": "poids\n",
    "config.json": '{"a":1}\n',
    "modules.json": "[]\n",
    "1_Pooling/config.json": '{"m":true}\n',
    "nested/deep/f.txt": "x\n",
}


def _extract_sealing_stage() -> str:
    """Isoler l'étage de scellement, du premier écho au calcul d'empreinte."""
    source = PREPARE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'^echo "Generating SHA256SUMS\.\.\."$.*?^INVENTORY_SHA256=.*?$',
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "étage de scellement introuvable dans le script"
    return match.group(0)


def _seal(artifact: Path) -> tuple[str, str]:
    """Exécuter l'étage de scellement réel du script sur un répertoire donné."""
    for relative, content in _FIXTURE.items():
        target = artifact / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    script = _extract_sealing_stage() + '\nprintf "%s" "$INVENTORY_SHA256"\n'
    completed = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin", "MODEL_ARTIFACT_DIR": str(artifact)},
        capture_output=True,
        text=True,
        check=True,
    )
    inventory_sha256 = completed.stdout.strip().splitlines()[-1]
    return (artifact / "SHA256SUMS").read_text(encoding="utf-8"), inventory_sha256


def test_sealing_covers_every_file_including_subdirectories(tmp_path: Path) -> None:
    """Le sceau couvre tout l'arbre, `manifest.json` compris.

    Deux propriétés distinctes, toutes deux acquises de haute lutte :

    - les sous-répertoires sont scellés (`find . -type f` est récursif), ce qui
      manquait au producteur `_model_inventory` de `rag-pedago` ;
    - `manifest.json` est scellé. Le commit `374b231` (03/08/2026) l'a ajouté —
      « The manifest carries the canonical identity and must itself be
      authenticated ». Les artefacts produits avant portent un sceau que le
      vérificateur du runtime rejette aujourd'hui.
    """
    inventory, _ = _seal(tmp_path / "artifact")

    sealed = {line.split("  ", 1)[1] for line in inventory.splitlines() if line}

    assert sealed == set(_FIXTURE), sorted(sealed)
    assert "1_Pooling/config.json" in sealed
    assert "nested/deep/f.txt" in sealed
    assert "manifest.json" in sealed
    assert "SHA256SUMS" not in sealed


def test_sealing_is_byte_stable_for_a_known_input(tmp_path: Path) -> None:
    """Empreintes d'or : toute dérive du scellement casse ce test.

    Les valeurs ci-dessous ont été relevées sur l'implémentation en vigueur
    avant la modification d'acquisition du 28/08/2026, puis reproduites à
    l'identique après. Elles pincent l'ordre de tri, le format des lignes et le
    mode de calcul de l'empreinte — c'est-à-dire tout ce dont dépend la valeur
    qu'un opérateur reporte dans `.env`.
    """
    inventory, inventory_sha256 = _seal(tmp_path / "artifact")

    expected_inventory = (
        "3a50e09ad4449ca639fe3c8227a18da5b06f9dd554917c5ea0497db2af24308b"
        "  1_Pooling/config.json\n"
        "e346432021b04179518d9614f3560ccd71354a4ee101ddcb893d6959a9d6301c"
        "  config.json\n"
        "23c4a43e0742276829eec6b929f0bcf83d8d4045074b3c23cd188a41b8bbbd46"
        "  manifest.json\n"
        "c2544c4f42a1631593373fe495abbdd926256ba1614fb694a1a62937b4480179"
        "  model.safetensors\n"
        "37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"
        "  modules.json\n"
        "73cb3858a687a8494ca3323053016282f3dad39d42cf62ca4e79dda2aac7d9ac"
        "  nested/deep/f.txt\n"
    )

    assert inventory == expected_inventory
    assert inventory_sha256 == (
        "9369fa315ad9818635923184dd6bf7e939f253edef59d0cd76267bb5285a0805"
    )
    assert (
        hashlib.sha256(inventory.encode("utf-8")).hexdigest() == inventory_sha256
    ), "l'empreinte doit rester le sha256 du fichier SHA256SUMS lui-même"


def test_offline_acquisition_never_passes_local_dir() -> None:
    """Le chemin hors ligne doit résoudre sans `local_dir`.

    `snapshot_download` contourne le cache hub partagé dès qu'un `local_dir` est
    fourni — la documentation de `huggingface_hub` est explicite. Repasser
    `local_dir` sur le chemin hors ligne ramènerait le `LocalEntryNotFoundError`
    que cette branche existe pour éviter, alors même que la révision épinglée
    est intégralement en cache.
    """
    source = PREPARE_SCRIPT.read_text(encoding="utf-8")

    offline_branch = source[source.index("offline = os.environ.get") :]
    offline_branch = offline_branch[: offline_branch.index("Copied {copied} files")]

    assert "snapshot_download(repo_id=model_id, revision=revision)" in offline_branch
    assert "local_dir" not in offline_branch.split("if not offline:")[-1].split(
        "sys.exit(0)"
    )[-1]
    assert "revision=revision" in offline_branch
