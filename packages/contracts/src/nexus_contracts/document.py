from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Niveau(str, Enum):
    troisieme = "troisieme"
    seconde = "seconde"
    premiere = "premiere"
    terminale = "terminale"
    cycle4 = "cycle4"
    lycee_gt = "lycee_gt"
    voie_generale = "voie_generale"
    voie_technologique = "voie_technologique"


class Voie(str, Enum):
    college = "college"
    generale = "generale"
    technologique = "technologique"
    professionnelle = "professionnelle"
    aefe = "aefe"
    unknown = "unknown"


class StatutEnseignement(str, Enum):
    tronc_commun = "tronc_commun"
    enseignement_commun = "enseignement_commun"
    specialite = "specialite"
    eds = "eds"
    option = "option"
    maths_complementaires = "maths_complementaires"
    maths_expertes = "maths_expertes"
    snt = "snt"
    enseignement_scientifique = "enseignement_scientifique"
    emc = "emc"
    atelier = "atelier"
    stage = "stage"
    remediation = "remediation"
    examen = "examen"
    unknown = "unknown"


class TypeDoc(str, Enum):
    programme_officiel = "programme_officiel"
    ressource_officielle = "ressource_officielle"
    cours = "cours"
    fiche_synthese = "fiche_synthese"
    fiche_methode = "fiche_methode"
    td = "td"
    tp = "tp"
    exercice = "exercice"
    exercice_corrige = "exercice_corrige"
    devoir = "devoir"
    devoir_corrige = "devoir_corrige"
    evaluation = "evaluation"
    evaluation_corrigee = "evaluation_corrigee"
    bac_blanc = "bac_blanc"
    brevet_blanc = "brevet_blanc"
    annale = "annale"
    sujet_zero = "sujet_zero"
    corrige = "corrige"
    bareme = "bareme"
    grille_evaluation = "grille_evaluation"
    grille_grand_oral = "grille_grand_oral"
    oral = "oral"
    diaporama = "diaporama"
    latex = "latex"
    notebook = "notebook"
    code = "code"
    image = "image"
    scan = "scan"
    copie = "copie"
    rapport = "rapport"
    referentiel = "referentiel"
    modalite_examen = "modalite_examen"
    autre = "autre"


class Epreuve(str, Enum):
    dnb = "dnb"
    eaf_ecrit = "eaf_ecrit"
    eaf_oral = "eaf_oral"
    anticipee_maths = "anticipee_maths"
    bac_specialite_ecrit = "bac_specialite_ecrit"
    bac_specialite_pratique = "bac_specialite_pratique"
    philosophie = "philosophie"
    grand_oral = "grand_oral"
    controle_continu = "controle_continu"
    epreuve_ponctuelle = "epreuve_ponctuelle"
    epreuve_remplacement = "epreuve_remplacement"
    rattrapage = "rattrapage"
    aucune = "aucune"


class Candidat(str, Enum):
    scolarise = "scolarise"
    individuel = "individuel"
    libre = "libre"
    cned_reglemente = "cned_reglemente"
    cned_libre = "cned_libre"
    aefe = "aefe"
    both = "both"


class SourceType(str, Enum):
    officiel = "officiel"
    eduscol = "eduscol"
    bo = "bo"
    examens = "examens"
    nexus = "nexus"
    upload = "upload"
    scan = "scan"
    generated = "generated"
    unknown = "unknown"


class Rights(str, Enum):
    officiel_public = "officiel_public"
    public_allowed = "public_allowed"
    nexus_proprietaire = "nexus_proprietaire"
    usage_interne = "usage_interne"
    student_private = "student_private"
    parent_private = "parent_private"
    commercial_confidential = "commercial_confidential"
    restricted = "restricted"
    unknown = "unknown"


class AccessContext(str, Enum):
    public = "public"
    internal = "internal"
    enrolled_student = "enrolled_student"
    parent = "parent"
    owner_student = "owner_student"
    teacher = "teacher"
    admin = "admin"


RIGHTS_ALLOWED_CONTEXTS: dict[Rights, tuple[AccessContext, ...]] = {
    Rights.officiel_public: (
        AccessContext.public,
        AccessContext.internal,
        AccessContext.enrolled_student,
        AccessContext.parent,
        AccessContext.owner_student,
        AccessContext.teacher,
        AccessContext.admin,
    ),
    Rights.public_allowed: (
        AccessContext.public,
        AccessContext.internal,
        AccessContext.enrolled_student,
        AccessContext.parent,
        AccessContext.owner_student,
        AccessContext.teacher,
        AccessContext.admin,
    ),
    Rights.nexus_proprietaire: (
        AccessContext.internal,
        AccessContext.enrolled_student,
        AccessContext.teacher,
        AccessContext.admin,
    ),
    Rights.usage_interne: (
        AccessContext.internal,
        AccessContext.teacher,
        AccessContext.admin,
    ),
    Rights.student_private: (
        AccessContext.owner_student,
        AccessContext.admin,
    ),
    Rights.parent_private: (
        AccessContext.parent,
        AccessContext.admin,
    ),
    Rights.commercial_confidential: (
        AccessContext.internal,
        AccessContext.admin,
    ),
    Rights.restricted: (
        AccessContext.admin,
    ),
    Rights.unknown: (),
}


class Modality(str, Enum):
    text = "text"
    pdf_native = "pdf_native"
    pdf_scan = "pdf_scan"
    image = "image"
    table = "table"
    formula = "formula"
    code = "code"
    latex = "latex"
    mixed = "mixed"


def _non_empty_list(values: list[str], field_name: str) -> list[str]:
    cleaned = [value.strip() for value in values]
    if any(not value for value in cleaned):
        raise ValueError(f"{field_name} cannot contain empty values")
    return cleaned


class DocumentMeta(StrictBaseModel):
    schema_version: str = "1.0.0"

    doc_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    source_type: SourceType
    original_filename: str | None = None
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    fetched_at: datetime | None = None
    discovered_at: datetime
    modified_at_source: datetime | None = None

    rights: Rights
    visibility: Literal["public", "internal", "restricted", "private"] = "internal"

    niveau: Niveau | None = None
    voie: Voie = Voie.unknown
    matiere: str = Field(min_length=1)
    statut_enseignement: StatutEnseignement = StatutEnseignement.unknown
    type_doc: TypeDoc
    epreuve: Epreuve = Epreuve.aucune
    candidat: Candidat = Candidat.both

    school_year_start: int | None = Field(default=None, ge=1900, le=2200)
    school_year_end: int | None = Field(default=None, ge=1900, le=2200)
    session: int | None = Field(default=None, ge=1900, le=2200)

    bo_reference: str | None = None
    bo_date: date | None = None
    programme_reference: str | None = None
    programme_version: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    is_current: bool | None = None
    official_level_ref: str | None = None
    official_exam_ref: str | None = None
    official_subject_ref: str | None = None
    candidate_status_ref: str | None = None
    official_source_refs: list[str] = Field(default_factory=list)
    official_claim_refs: list[str] = Field(default_factory=list)
    establishment_context_ref: str | None = None

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    language: str = "fr"

    notions: list[str] = Field(default_factory=list)
    competences: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)

    has_corrige: bool = False
    parent_doc_id: str | None = None
    related_doc_ids: list[str] = Field(default_factory=list)

    difficulty: int | None = Field(default=None, ge=1, le=5)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)

    modality: Modality = Modality.mixed
    pages_count: int | None = Field(default=None, ge=0)

    quality_score: float | None = Field(default=None, ge=0, le=1)
    parse_confidence: float | None = Field(default=None, ge=0, le=1)
    classification_confidence: float | None = Field(default=None, ge=0, le=1)

    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "authors",
        "notions",
        "competences",
        "prerequisites",
        "learning_objectives",
        "related_doc_ids",
        "official_source_refs",
        "official_claim_refs",
    )
    @classmethod
    def validate_string_lists(cls, values: list[str]) -> list[str]:
        return _non_empty_list(values, "list field")

    @model_validator(mode="after")
    def validate_school_year(self) -> DocumentMeta:
        if (
            self.school_year_start is not None
            and self.school_year_end is not None
            and self.school_year_end < self.school_year_start
        ):
            raise ValueError("school_year_end must be greater than or equal to school_year_start")
        return self

    @property
    def is_retrievable(self) -> bool:
        return self.rights is not Rights.unknown

    @property
    def allowed_contexts(self) -> list[AccessContext]:
        return list(RIGHTS_ALLOWED_CONTEXTS[self.rights])

    def is_allowed_in_context(self, context: AccessContext) -> bool:
        return context in RIGHTS_ALLOWED_CONTEXTS[self.rights]


class ChunkMeta(StrictBaseModel):
    schema_version: str = "1.0.0"

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    chunk_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    chunk_index: int = Field(ge=0)
    parent_section: str | None = None
    section_path: list[str] = Field(default_factory=list)

    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None

    chunk_type: Modality
    text: str | None = None
    asset_path: str | None = None

    notions: list[str] = Field(default_factory=list)
    competences: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)

    token_count: int | None = Field(default=None, ge=0)
    char_count: int | None = Field(default=None, ge=0)

    retrieval_title: str | None = None
    citation_label: str | None = None

    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("section_path", "notions", "competences")
    @classmethod
    def validate_string_lists(cls, values: list[str]) -> list[str]:
        return _non_empty_list(values, "list field")

    @model_validator(mode="after")
    def complete_derived_fields(self) -> ChunkMeta:
        if self.page_start is not None and self.page_end is not None and self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if self.text is None and self.asset_path is None:
            raise ValueError("either text or asset_path is required")
        if self.char_count is None and self.text is not None:
            self.char_count = len(self.text)
        return self
