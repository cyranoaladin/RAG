#!/usr/bin/env python3
"""Dériver, sur l'hôte staging, un fichier d'environnement PAR RÔLE (lot DC).

Aucun nouveau secret : chaque DSN est assemblé à partir des mots de passe DÉJÀ
présents dans ``staging.env`` et ``ingestion_control.env``. Ces valeurs
n'arrivent que par l'ENVIRONNEMENT du processus (l'appelant source les deux
fichiers) — jamais par les arguments, jamais sur la sortie : seuls des noms de
fichiers et de variables y paraissent.

Écriture atomique (fichier temporaire 0600 dans le répertoire cible, fsync,
``os.replace``), répertoire 0700. Un fichier existant au contenu identique est
laissé tel quel ; au contenu différent, c'est un refus — rien n'est écrasé.

Les DSN sont au format libpq à mots-clés (``conninfo_to_dict`` les lit), ce
qui évite tout encodage d'URL du mot de passe ; les fichiers sont lus par
``docker --env-file``, qui prend la valeur littéralement.

    set -a; . staging.env; . ingestion_control.env; set +a
    python3 staging_v4_role_env.py --database ragdb_profile_gate_v4 \\
        --out-dir /srv/nexus-staging/secrets/v4-roles
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

HOTE = "127.0.0.1"

#: fichier → (variable lue par la CLI, rôle PostgreSQL, variable source du mot de passe)
FICHIERS: dict[str, tuple[str, str, str]] = {
    "ingestion-control-app.env": (
        "PG_INGESTION_CONTROL_DSN", "ingestion_control_app", "INGESTION_CONTROL_APP_PASSWORD",
    ),
    "ingestion-control-attestor.env": (
        "PG_INGESTION_CONTROL_ATTESTOR_DSN", "ingestion_control_attestor", "INGESTION_CONTROL_ATTESTOR_PASSWORD",
    ),
    "ingestion-control-authority.env": (
        "PG_INGESTION_CONTROL_AUTHORITY_DSN", "ingestion_control_authority", "INGESTION_CONTROL_AUTHORITY_PASSWORD",
    ),
    "rag-publisher.env": ("PG_RAG_DSN", "rag_publisher", "PGVECTOR_PUBLISHER_PASSWORD"),
    "rag-reader.env": ("PG_RAG_DSN", "rag_reader", "PGVECTOR_RETRIEVAL_PASSWORD"),
}
NOM_BASE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class DerivationRefusee(RuntimeError):
    """Une précondition n'est pas satisfaite ; rien n'est écrit."""


def _valeur_libpq(valeur: str) -> str:
    return "'" + valeur.replace("\\", "\\\\").replace("'", "\\'") + "'"


def contenus(environ: Mapping[str, str], *, database: str) -> dict[str, str]:
    """Le contenu de chaque fichier, sans rien écrire."""
    if not NOM_BASE.match(database) or database == "ragdb":
        raise DerivationRefusee(f"base cible invalide ou historique : {database!r}")
    port = environ.get("PGVECTOR_PORT", "").strip()
    if not port.isdigit():
        raise DerivationRefusee("PGVECTOR_PORT absent ou non numérique")
    sortie: dict[str, str] = {}
    for fichier, (variable, role, source) in FICHIERS.items():
        secret = environ.get(source, "")
        if not secret:
            raise DerivationRefusee(f"{source} absent : {fichier} ne peut être dérivé")
        if any(c in secret for c in "\n\r\0"):
            raise DerivationRefusee(f"{source} contient un caractère de contrôle")
        dsn = (
            f"host={HOTE} port={port} dbname={database} user={role} "
            f"password={_valeur_libpq(secret)}"
        )
        sortie[fichier] = f"{variable}={dsn}\n"
    return sortie


def _repertoire(dossier: Path) -> None:
    if dossier.exists():
        etat = dossier.lstat()
        if not stat.S_ISDIR(etat.st_mode) or stat.S_ISLNK(etat.st_mode):
            raise DerivationRefusee(f"{dossier} n'est pas un répertoire")
        if etat.st_uid != os.getuid() or stat.S_IMODE(etat.st_mode) != 0o700:
            raise DerivationRefusee(f"{dossier} doit appartenir à l'appelant et être en 0700")
        return
    dossier.mkdir(mode=0o700)
    os.chmod(dossier, 0o700)


def ecrire(contenu: Mapping[str, str], *, dossier: Path) -> dict[str, str]:
    """Écrit chaque fichier atomiquement ; rend fichier → WRITTEN|UNCHANGED."""
    _repertoire(dossier)
    # Tout est vérifié AVANT la première écriture : un refus n'écrit rien.
    for nom, texte in contenu.items():
        cible = dossier / nom
        if cible.is_symlink() or (cible.exists() and not cible.is_file()):
            raise DerivationRefusee(f"{nom} existe et n'est pas un fichier ordinaire")
        if cible.exists() and cible.read_text(encoding="utf-8") != texte:
            raise DerivationRefusee(f"{nom} existe avec un autre contenu : rien n'est écrasé")
    etats: dict[str, str] = {}
    for nom, texte in contenu.items():
        cible = dossier / nom
        if cible.exists():
            os.chmod(cible, 0o600)
            etats[nom] = "UNCHANGED"
            continue
        descripteur, temporaire = tempfile.mkstemp(prefix=f".{nom}.", dir=dossier)
        try:
            os.fchmod(descripteur, 0o600)
            with os.fdopen(descripteur, "w", encoding="utf-8") as flux:
                flux.write(texte)
                flux.flush()
                os.fsync(flux.fileno())
            os.replace(temporaire, cible)
        except BaseException:
            Path(temporaire).unlink(missing_ok=True)
            raise
        etats[nom] = "WRITTEN"
    repertoire = os.open(dossier, os.O_RDONLY)
    try:
        os.fsync(repertoire)
    finally:
        os.close(repertoire)
    return etats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        etats = ecrire(contenus(os.environ, database=args.database), dossier=args.out_dir)
    except DerivationRefusee as exc:
        print(f"ROLE_ENV_REFUSED: {exc}", file=sys.stderr)
        return 2
    for nom, etat in etats.items():
        variable, role, _source = FICHIERS[nom]
        print(f"ROLE_ENV {etat} {nom} variable={variable} role={role} mode=0600")
    print(f"ROLE_ENV_DONE count={len(etats)} dir_mode=0700")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
