"""Chargement du périmètre de validation réel, encore dormant."""

from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

_EXPECTED_SCOPE_ID = "libre_terminale_maths_nsi_real_v1"
_DORMANT_STATUS = "eligible_for_promotion"
_EXPECTED_SCHOOL_YEAR = "2026-2027"
_EXPECTED_IDENTITY = {
    "tenant": "libre_terminale",
    "level": "terminale",
    "track": "generale",
    "teaching_status": "specialite",
    "audience": "libre",
    "candidates": ("cned_libre", "individuel", "libre"),
}
_EXPECTED_COLLECTIONS = (
    "rag_nexus_maths_terminale_gen_specialite",
    "rag_nexus_nsi_terminale_specialite",
)
_EXPECTED_SUBJECTS = {
    "maths": {
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "taxonomy_path": "taxonomy/maths/terminale_gen_specialite.yml",
        "taxonomy_sha256": "4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6",
        "programme_version": "BOEN_special_8_2019-07-25",
    },
    "nsi": {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "taxonomy_path": "taxonomy/nsi/terminale.yml",
        "taxonomy_sha256": "b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f",
        "programme_version": "BOEN_special_8_2019-07-25",
    },
}


class PilotIdentity(BaseModel):
    """Identité contractuelle admise par le pilote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str
    level: str
    track: str
    teaching_status: str
    audience: str
    candidates: tuple[str, ...]


class PilotSubject(BaseModel):
    """Matière, collection et taxonomie immuables du pilote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str
    collection: str
    taxonomy_path: str
    taxonomy_sha256: str
    programme_version: str
    notions: tuple[str, ...]


class PilotValidationScope(BaseModel):
    """Périmètre canonique du pilote Mathématiques + NSI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str
    status: str
    school_year: str
    identity: PilotIdentity
    subjects: tuple[PilotSubject, ...]

    @property
    def collections(self) -> tuple[str, ...]:
        return tuple(subject.collection for subject in self.subjects)


def load_scope(path: Path) -> PilotValidationScope:
    """Charge un document de scope strict depuis le disque local."""

    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PilotValidationScope.model_validate(payload)


def _taxonomy_notions(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()

    notions: list[str] = []
    themes = payload.get("themes", ())
    if not isinstance(themes, list):
        return ()
    for theme in themes:
        if not isinstance(theme, dict):
            continue
        theme_notions = theme.get("notions", ())
        if not isinstance(theme_notions, list):
            continue
        for notion in theme_notions:
            if isinstance(notion, dict) and isinstance(notion.get("id"), str):
                notions.append(notion["id"])
    return tuple(notions)


def _is_confined_taxonomy_path(path: str, *, taxonomy_root: Path) -> bool:
    relative_path = Path(path)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or relative_path.parts[0] != "taxonomy"
        or ".." in relative_path.parts
    ):
        return False

    resolved_path = (taxonomy_root.parent / relative_path).resolve()
    return resolved_path.is_relative_to(taxonomy_root)


def _scope_metadata_reasons(
    scope: PilotValidationScope,
    *,
    taxonomy_root: Path,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if scope.scope_id != _EXPECTED_SCOPE_ID:
        reasons.append("scope.id_mismatch")
    if scope.status != _DORMANT_STATUS:
        reasons.append("scope.status_not_dormant")
    if scope.school_year != _EXPECTED_SCHOOL_YEAR:
        reasons.append("scope.school_year_mismatch")

    for field, expected in _EXPECTED_IDENTITY.items():
        if getattr(scope.identity, field) != expected:
            reasons.append(f"scope.identity_mismatch:{field}")

    if tuple(sorted(scope.collections)) != _EXPECTED_COLLECTIONS:
        reasons.append("scope.collections_mismatch")
        return tuple(reasons)

    if tuple(sorted(subject.subject for subject in scope.subjects)) != tuple(
        sorted(_EXPECTED_SUBJECTS)
    ):
        reasons.append("scope.subjects_mismatch")
        return tuple(reasons)

    for subject in scope.subjects:
        if not _is_confined_taxonomy_path(subject.taxonomy_path, taxonomy_root=taxonomy_root):
            reasons.append(f"scope.taxonomy_path_not_confined:{subject.subject}")
            continue

        expected_subject = _EXPECTED_SUBJECTS[subject.subject]
        for field in ("collection", "taxonomy_path", "programme_version"):
            if getattr(subject, field) != expected_subject[field]:
                reasons.append(f"scope.{field}_mismatch:{subject.subject}")
        if subject.taxonomy_sha256 != expected_subject["taxonomy_sha256"]:
            reasons.append(f"scope.taxonomy_sha256_mismatch:{subject.subject}")

    return tuple(reasons)


def validate_scope_integrity(
    scope: PilotValidationScope,
    *,
    service_root: Path | None = None,
) -> tuple[str, ...]:
    """Vérifie l'adressage brut et les notions déclarées par matière."""

    root = (service_root or Path(__file__).resolve().parents[2]).resolve()
    taxonomy_root = (root / "taxonomy").resolve()
    metadata_reasons = _scope_metadata_reasons(scope, taxonomy_root=taxonomy_root)
    if metadata_reasons:
        return metadata_reasons

    reasons: list[str] = []
    for subject in scope.subjects:
        taxonomy = root / subject.taxonomy_path
        try:
            raw_taxonomy = taxonomy.read_bytes()
        except OSError:
            reasons.append(f"scope.taxonomy_unreadable:{subject.subject}")
            continue
        if sha256(raw_taxonomy).hexdigest() != subject.taxonomy_sha256:
            reasons.append(f"scope.taxonomy_sha256_mismatch:{subject.subject}")
            continue
        try:
            taxonomy_payload = yaml.safe_load(raw_taxonomy)
        except yaml.YAMLError:
            reasons.append(f"scope.taxonomy_invalid:{subject.subject}")
            continue
        taxonomy_notions = _taxonomy_notions(taxonomy_payload)
        if taxonomy_notions != subject.notions or len(taxonomy_notions) != len(
            set(taxonomy_notions)
        ):
            reasons.append(f"scope.notions_mismatch:{subject.subject}")
    return tuple(reasons)
