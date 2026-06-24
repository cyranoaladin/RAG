"""Re-export from nexus-contracts (source of truth)."""

from nexus_contracts.document import *  # noqa: F401,F403
from nexus_contracts.document import (
    AccessContext,
    Candidat,
    ChunkMeta,
    DocumentMeta,
    Epreuve,
    Modality,
    Niveau,
    Rights,
    RIGHTS_ALLOWED_CONTEXTS,
    SourceType,
    StatutEnseignement,
    StrictBaseModel,
    TypeDoc,
    Voie,
    _non_empty_list,
)

__all__ = [
    "AccessContext",
    "Candidat",
    "ChunkMeta",
    "DocumentMeta",
    "Epreuve",
    "Modality",
    "Niveau",
    "RIGHTS_ALLOWED_CONTEXTS",
    "Rights",
    "SourceType",
    "StatutEnseignement",
    "StrictBaseModel",
    "TypeDoc",
    "Voie",
    "_non_empty_list",
]
