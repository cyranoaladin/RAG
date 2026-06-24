"""nexus-contracts — Shared retrieval contract for the Nexus RAG platform."""

from nexus_contracts.chunk import (
    Audience,
    ChunkMetadata,
)
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
)
from nexus_contracts.retrieval import (
    Citation,
    RetrievalNeed,
    RetrievalOptions,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
)
from nexus_contracts.student_profile import (
    StatusDetail,
    StudentProfile,
)

__all__ = [
    "AccessContext",
    "Audience",
    "Candidat",
    "ChunkMeta",
    "ChunkMetadata",
    "Citation",
    "DocumentMeta",
    "Epreuve",
    "Modality",
    "Niveau",
    "RIGHTS_ALLOWED_CONTEXTS",
    "RetrievalNeed",
    "RetrievalOptions",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalResult",
    "Rights",
    "SourceType",
    "StatusDetail",
    "StatutEnseignement",
    "StrictBaseModel",
    "StudentProfile",
    "TypeDoc",
    "Voie",
]
