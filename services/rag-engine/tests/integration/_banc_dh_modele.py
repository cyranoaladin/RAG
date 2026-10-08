"""Sélection du modèle d'embedding du banc DH — deux modes, jamais confondus.

* **DEBUG** (défaut) : Worker B tourne EN PROCESSUS avec l'adaptateur de test
  ``CallableEmbeddingProvider``. La release du banc doit néanmoins déclarer
  une empreinte d'inventaire : un inventaire FICTIF, sans aucun poids, est
  créé pour cela et marqué comme tel. Ce mode ne qualifie jamais E5.
* **CLI** (``NEXUS_DH_WORKER_B_CLI=1``) : le vrai CLI de Worker B charge le
  modèle fourni par l'opérateur. Son chemin (``RAG_EMBEDDING_MODEL_CACHE_DIR``)
  et son empreinte d'inventaire attendue
  (``RAG_EMBEDDING_MODEL_INVENTORY_SHA256``) sont CONSERVÉS, vérifiés par le
  vérificateur canonique ``verify_embedding_artifact``, et transmis tels quels
  au contexte du banc puis au sous-processus. Absents ou invalides : refus.
  Aucun repli vers DEBUG.

Toute variable modifiée est restaurée à la sortie, exception comprise.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

VARIABLE_MODE = "NEXUS_DH_WORKER_B_CLI"
VARIABLE_RACINE = "RAG_EMBEDDING_MODEL_CACHE_DIR"
VARIABLE_INVENTAIRE = "RAG_EMBEDDING_MODEL_INVENTORY_SHA256"
MODE_DEBUG = "debug"
MODE_CLI = "cli"
MARQUEUR_FICTIF = "INVENTAIRE-FICTIF-AUCUN-POIDS"


class ModeleDuBancRefuse(RuntimeError):
    """Le modèle du banc n'est pas établi ; le banc ne démarre pas."""


@dataclass(frozen=True)
class ModeleDuBanc:
    mode: str
    racine: Path
    inventaire_sha256: str
    #: Vrai seulement en DEBUG : l'inventaire ne décrit aucun poids.
    fictif: bool


def mode_worker_b(environ: MutableMapping[str, str]) -> str:
    valeur = environ.get(VARIABLE_MODE, "").strip()
    if valeur == "1":
        return MODE_CLI
    if valeur in ("", "0"):
        return MODE_DEBUG
    raise ModeleDuBancRefuse(f"{VARIABLE_MODE}={valeur!r} : seules les valeurs 1 ou 0 sont admises")


def _inventaire_fictif(racine: Path) -> ModeleDuBanc:
    racine.mkdir(parents=True, exist_ok=True)
    marqueur = racine / MARQUEUR_FICTIF
    marqueur.write_text("inventaire de banc DH en mode DEBUG — aucun poids de modèle\n", encoding="utf-8")
    inventaire = racine / "SHA256SUMS"
    inventaire.write_text(f"{hashlib.sha256(marqueur.read_bytes()).hexdigest()}  {MARQUEUR_FICTIF}\n", encoding="utf-8")
    return ModeleDuBanc(
        mode=MODE_DEBUG,
        racine=racine,
        inventaire_sha256=hashlib.sha256(inventaire.read_bytes()).hexdigest(),
        fictif=True,
    )


def _modele_operateur(environ: MutableMapping[str, str]) -> ModeleDuBanc:
    from ingestor.embedding_contract import (  # noqa: PLC0415
        EmbeddingContractError,
        verify_embedding_artifact,
    )

    racine = environ.get(VARIABLE_RACINE, "").strip()
    inventaire = environ.get(VARIABLE_INVENTAIRE, "").strip()
    if not racine:
        raise ModeleDuBancRefuse(f"mode CLI : {VARIABLE_RACINE} absent — le chemin du modèle E5 est requis")
    if not inventaire:
        raise ModeleDuBancRefuse(
            f"mode CLI : {VARIABLE_INVENTAIRE} absent — l'empreinte d'inventaire attendue est requise"
        )
    try:
        verifie = verify_embedding_artifact(Path(racine), expected_inventory_sha256=inventaire)
    except EmbeddingContractError as exc:
        raise ModeleDuBancRefuse(f"mode CLI : modèle refusé par le vérificateur canonique ({exc})") from exc
    return ModeleDuBanc(mode=MODE_CLI, racine=verifie, inventaire_sha256=inventaire, fictif=False)


@contextmanager
def modele_du_banc(
    *, racine_fictive: Path, environ: MutableMapping[str, str] | None = None
) -> Iterator[ModeleDuBanc]:
    """Sélectionne le modèle et n'expose au banc QUE celui-là, le temps du bloc."""
    environ = os.environ if environ is None else environ
    mode = mode_worker_b(environ)
    selection = _modele_operateur(environ) if mode == MODE_CLI else _inventaire_fictif(racine_fictive)
    precedent = environ.get(VARIABLE_RACINE)
    try:
        # CLI : la valeur de l'opérateur n'est jamais remplacée.
        if selection.fictif:
            environ[VARIABLE_RACINE] = str(selection.racine)
        yield selection
    finally:
        if precedent is None:
            environ.pop(VARIABLE_RACINE, None)
        else:
            environ[VARIABLE_RACINE] = precedent


def _valeur_d_option(arguments: Sequence[str], option: str) -> str:
    positions = [i for i, valeur in enumerate(arguments) if valeur == option]
    if len(positions) != 1 or positions[0] + 1 >= len(arguments):
        raise ModeleDuBancRefuse(f"{option} absent ou répété dans les arguments de Worker B")
    return arguments[positions[0] + 1]


def exiger_modele_transmis(
    selection: ModeleDuBanc,
    *,
    modele_e5: Path,
    inventaire_sha256: str,
    arguments: Sequence[str] | None = None,
) -> None:
    """Le contexte du banc, puis le CLI, reçoivent le modèle sélectionné — et lui seul."""
    ecarts = []
    if Path(modele_e5).resolve() != selection.racine.resolve():
        ecarts.append(f"contexte : modèle {modele_e5}, sélectionné {selection.racine}")
    if inventaire_sha256 != selection.inventaire_sha256:
        ecarts.append("contexte : empreinte d'inventaire différente de la sélection")
    if arguments is not None:
        if selection.fictif:
            ecarts.append("un inventaire FICTIF ne doit jamais être transmis au CLI de Worker B")
        racine = _valeur_d_option(arguments, "--embedding-artifact-root")
        if Path(racine).resolve() != selection.racine.resolve():
            ecarts.append(f"CLI : --embedding-artifact-root {racine}, sélectionné {selection.racine}")
        if _valeur_d_option(arguments, "--embedding-inventory-sha256") != selection.inventaire_sha256:
            ecarts.append("CLI : --embedding-inventory-sha256 différent de la sélection")
    if ecarts:
        raise ModeleDuBancRefuse("; ".join(ecarts))
