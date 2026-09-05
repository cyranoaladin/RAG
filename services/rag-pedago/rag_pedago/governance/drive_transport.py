"""Transport Google Drive réel — le seul endroit qui parle au réseau.

Il est délibérément mince. Toute la logique gouvernable — pagination,
cycles, raccourcis, exclusions, retries — vit dans ``drive_source`` et
reste donc testable sans compte de service. Ici, on ne trouve que la
forme de la requête, la traduction des pannes, et le refus d'une
configuration d'identifiants absente.

**Aucun chemin d'identifiants en dur, aucun repli.** Le compte de service
vient d'une variable d'environnement, et son absence est un refus. Un
repli sur un emplacement conventionnel — ``~/.credentials/…`` — ferait
qu'on énumérerait la source de référence sans plus savoir avec quels
droits, ni au nom de qui.

**Portée en lecture seule, écrite une fois.** La racine gouvernée est la
matière première de tout le corpus ; un scope en écriture rendrait une
altération possible par simple erreur de code.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rag_pedago.governance.drive_source import (
    LIST_FIELDS,
    DrivePage,
    DriveSourceError,
    DriveTransientError,
)

#: Emplacement du compte de service, par variable d'environnement. Jamais
#: de valeur par défaut : un chemin deviné est un compte de service qu'on
#: ne peut plus nommer dans une preuve.
CREDENTIALS_ENV = "NEXUS_GDRIVE_SERVICE_ACCOUNT_FILE"

#: Identifiant de la racine gouvernée, par variable d'environnement.
ROOT_FOLDER_ENV = "NEXUS_GDRIVE_ROOT_FOLDER_ID"

#: Nom de la racine gouvernée, tel qu'il préfixe les chemins.
ROOT_NAME_ENV = "NEXUS_GDRIVE_ROOT_NAME"

DEFAULT_ROOT_NAME = "NEXUS_RAG_GDRIVE_READY"

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

#: Statuts qui disparaissent d'eux-mêmes. Les autres ne sont pas
#: réessayés : rejouer un 403 masque un partage manquant derrière une
#: lenteur apparente.
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})

#: Champs de métadonnées à demander pour un objet isolé (cible d'un
#: raccourci : sa taille et sa date ne sont pas dans le raccourci).
METADATA_FIELDS = "id, name, mimeType, modifiedTime, size, md5Checksum"

#: Taille de page. Réglable par l'environnement pour qu'une pagination
#: réelle puisse être exercée sur un dossier donné, plutôt que d'être
#: seulement simulée : la borne de l'API n'est pas la borne du code.
PAGE_SIZE_ENV = "NEXUS_GDRIVE_PAGE_SIZE"
DEFAULT_PAGE_SIZE = 200


def is_transient_status(status: int) -> bool:
    return status in TRANSIENT_STATUS


def credentials_path() -> Path:
    """Le compte de service, ou un refus nommé."""
    raw = os.environ.get(CREDENTIALS_ENV)
    if not raw:
        raise DriveSourceError(
            f"{CREDENTIALS_ENV} n'est pas défini — refus d'énumérer la racine "
            "gouvernée avec des droits qu'on ne saurait pas nommer"
        )
    path = Path(raw)
    if not path.is_file():
        raise DriveSourceError(
            f"{CREDENTIALS_ENV} désigne {path} qui n'existe pas"
        )
    return path


def root_folder_id() -> str:
    raw = os.environ.get(ROOT_FOLDER_ENV)
    if not raw:
        raise DriveSourceError(
            f"{ROOT_FOLDER_ENV} n'est pas défini — la racine gouvernée n'est "
            "pas codée en dur, elle est désignée"
        )
    return raw


def root_name() -> str:
    return os.environ.get(ROOT_NAME_ENV) or DEFAULT_ROOT_NAME


def page_from_response(response: Mapping[str, Any]) -> DrivePage:
    """Traduit une réponse ``files.list``, ou refuse de l'interpréter."""
    entries = response.get("files")
    if not isinstance(entries, list):
        raise DriveSourceError(
            "réponse Drive sans liste 'files' exploitable — la traiter comme "
            f"une page vide ferait passer une panne pour un dossier vide : {response!r}"
        )
    token = response.get("nextPageToken") or None
    return DrivePage(entries=tuple(entries), next_page_token=token)


def _status_of(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "resp", None)
    candidate = getattr(response, "status", None)
    if isinstance(candidate, int):
        return candidate
    return None


class GoogleDriveTransport:
    """``DriveTransport`` adossé à ``googleapiclient``.

    Le service est injecté pour que la forme des requêtes soit vérifiable
    sans réseau ; ``from_environment`` le construit pour l'usage réel."""

    def __init__(self, service: Any, *, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        if not 1 <= page_size <= 1000:
            raise DriveSourceError(
                f"taille de page hors bornes Drive (1..1000) : {page_size}"
            )
        self._service = service
        self._page_size = page_size

    @classmethod
    def from_environment(cls) -> GoogleDriveTransport:
        # Import tardif : le paquet Google n'est pas une dépendance de
        # base du service, et rien de ce qui est testé ne l'exige.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path()), scopes=[DRIVE_READONLY_SCOPE]
        )
        return cls(
            build("drive", "v3", credentials=credentials, cache_discovery=False),
            page_size=int(os.environ.get(PAGE_SIZE_ENV) or DEFAULT_PAGE_SIZE),
        )

    # -- DriveTransport ------------------------------------------------
    def list_children(self, folder_id: str, *, page_token: str | None) -> DrivePage:
        response = self._call(
            lambda: self._service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields=LIST_FIELDS,
                pageToken=page_token,
                pageSize=self._page_size,
                orderBy="name",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        return page_from_response(response)

    def get_metadata(self, file_id: str) -> Mapping[str, Any]:
        result = self._call(
            lambda: self._service.files()
            .get(fileId=file_id, fields=METADATA_FIELDS, supportsAllDrives=True)
            .execute()
        )
        if not isinstance(result, Mapping):
            raise DriveSourceError(f"métadonnées Drive inexploitables : {result!r}")
        return result

    def fetch(self, file_id: str) -> bytes:
        payload = self._call(
            lambda: self._service.files()
            .get_media(fileId=file_id, supportsAllDrives=True)
            .execute()
        )
        if not isinstance(payload, bytes):
            raise DriveSourceError(
                f"le téléchargement de {file_id!r} n'a pas rendu d'octets"
            )
        return payload

    def export(self, file_id: str, *, mime_type: str) -> bytes:
        payload = self._call(
            lambda: self._service.files()
            .export(fileId=file_id, mimeType=mime_type)
            .execute()
        )
        if not isinstance(payload, bytes):
            raise DriveSourceError(f"l'export de {file_id!r} n'a pas rendu d'octets")
        return payload

    def _call(self, action: Any) -> Any:
        """Traduit les pannes réessayables ; laisse tout le reste passer."""
        try:
            return action()
        except Exception as error:
            status = _status_of(error)
            if status is not None and is_transient_status(status):
                raise DriveTransientError(f"Drive a répondu {status}") from error
            raise


def real_sleep(seconds: float) -> None:
    """Attente réelle du backoff, injectée par l'usage en production."""
    time.sleep(seconds)


__all__ = [
    "CREDENTIALS_ENV",
    "DEFAULT_PAGE_SIZE",
    "PAGE_SIZE_ENV",
    "DEFAULT_ROOT_NAME",
    "DRIVE_READONLY_SCOPE",
    "METADATA_FIELDS",
    "ROOT_FOLDER_ENV",
    "ROOT_NAME_ENV",
    "TRANSIENT_STATUS",
    "GoogleDriveTransport",
    "credentials_path",
    "is_transient_status",
    "page_from_response",
    "real_sleep",
    "root_folder_id",
    "root_name",
]
