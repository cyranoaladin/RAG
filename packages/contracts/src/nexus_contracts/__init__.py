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
from nexus_contracts.chat import (
    ChatCitation,
    ChatMessage,
    ChatPayload,
    ChatRequest,
    ChatResponse,
    SearchPayload,
)
from nexus_contracts.student_profile import (
    StatusDetail,
    StudentProfile,
)
from nexus_contracts.identity import (
    InternalIdentity,
    InternalIdentityEnvelope,
    PedagogicalProfile,
)
from nexus_contracts.scope import (
    PILOT_RETRIEVAL_SCOPE_DIGEST,
    PilotRetrievalScopeArtifact,
    PilotScopeIdentity,
    PilotScopeSubject,
    load_pilot_retrieval_scope,
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
    "ChatCitation",
    "ChatMessage",
    "ChatPayload",
    "ChatRequest",
    "ChatResponse",
    "SearchPayload",
    "Rights",
    "SourceType",
    "StatusDetail",
    "StatutEnseignement",
    "StrictBaseModel",
    "StudentProfile",
    "InternalIdentity",
    "InternalIdentityEnvelope",
    "PedagogicalProfile",
    "PILOT_RETRIEVAL_SCOPE_DIGEST",
    "PilotRetrievalScopeArtifact",
    "PilotScopeIdentity",
    "PilotScopeSubject",
    "TypeDoc",
    "Voie",
    "load_pilot_retrieval_scope",
]
