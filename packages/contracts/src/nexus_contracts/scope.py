"""Artefact canonique du scope de retrieval pilote."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from types import MappingProxyType
from typing import Annotated, Literal, Mapping, TypeAlias

from pydantic import Field, StrictStr, StringConstraints, field_validator, model_validator

from nexus_contracts.document import (
    Candidat,
    Niveau,
    Rights,
    StatutEnseignement,
    StrictBaseModel,
    Voie,
)
from nexus_contracts.identity import (
    BoundedSlug,
    CollectionName,
    InternalIdentityEnvelope,
    SchoolYear,
    Sha256Digest,
)

ARTIFACT_RESOURCE = "artifacts/pilot-retrieval-scope-v1.json"
PILOT_RETRIEVAL_SCOPE_DIGEST = (
    "a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24"
)
ProgrammeVersion = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]


class PilotScopeIdentity(StrictBaseModel):
    """Projection non personnelle de l'identité autorisée par LOT38."""

    tenant: BoundedSlug
    niveau: Niveau
    voie: Voie
    statut_enseignement: StatutEnseignement
    audience: Literal["libre", "aefe", "tous"]
    candidates: list[Candidat] = Field(
        min_length=1,
        max_length=16,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("candidates")
    @classmethod
    def validate_candidates(cls, values: list[Candidat]) -> list[Candidat]:
        if len(values) != len(set(values)):
            raise ValueError("candidates cannot contain duplicates")
        return values


class PilotScopeSubject(StrictBaseModel):
    """Matière, collection et version de programme liées au scope."""

    matiere: BoundedSlug
    collection: CollectionName
    programme_version: ProgrammeVersion


class PilotRetrievalScopeArtifact(StrictBaseModel):
    """Projection adressée par contenu du scope dormant issu de LOT38."""

    artifact_version: Literal["1"]
    scope_id: BoundedSlug
    status: Literal["eligible_for_promotion"]
    source_sha256: Sha256Digest
    school_year: SchoolYear
    identity: PilotScopeIdentity
    subjects: list[PilotScopeSubject] = Field(
        min_length=1,
        max_length=16,
        json_schema_extra={"uniqueItems": True},
    )

    @model_validator(mode="after")
    def validate_subjects(self) -> PilotRetrievalScopeArtifact:
        matieres = [subject.matiere for subject in self.subjects]
        collections = [subject.collection for subject in self.subjects]
        if len(matieres) != len(set(matieres)):
            raise ValueError("subjects cannot contain duplicate matieres")
        if len(collections) != len(set(collections)):
            raise ValueError("subjects cannot contain duplicate collections")
        return self

    def canonical_bytes(self) -> bytes:
        """Sérialiser l'artefact selon la forme utilisée pour son digest."""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def sha256_digest(self) -> str:
        """Retourner le SHA-256 des octets JSON canoniques."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def validate_envelope(self, envelope: InternalIdentityEnvelope) -> None:
        """Refuser toute enveloppe qui diverge du scope adressé."""
        if envelope.scope_id != self.scope_id:
            raise ValueError("scope_id does not match the artifact")
        if envelope.scope_digest != self.sha256_digest():
            raise ValueError("scope_digest does not match the artifact")

        collections = [subject.collection for subject in self.subjects]
        if envelope.allowed_collections != collections:
            raise ValueError("allowed_collections do not match the artifact")

        identity = envelope.identity
        profile = identity.pedagogical_profile
        expected = self.identity
        if identity.tenant != expected.tenant:
            raise ValueError("identity.tenant does not match the artifact")
        if identity.niveau != expected.niveau:
            raise ValueError("identity.niveau does not match the artifact")
        if identity.school_year != self.school_year:
            raise ValueError("identity.school_year does not match the artifact")
        if profile.voie != expected.voie:
            raise ValueError("identity.voie does not match the artifact")
        if profile.statut_enseignement != expected.statut_enseignement:
            raise ValueError("identity.statut_enseignement does not match the artifact")
        if profile.audience != expected.audience:
            raise ValueError("identity.audience does not match the artifact")
        if profile.candidat not in expected.candidates:
            raise ValueError("identity.candidat does not match the artifact")

        matieres = {subject.matiere for subject in self.subjects}
        if not set(profile.matieres).issubset(matieres):
            raise ValueError("identity.matieres do not match the artifact")


class RetrievalScopeTargetIdentity(StrictBaseModel):
    """Cible élève exacte portée par un scope de retrieval V2."""

    tenant: BoundedSlug
    niveau: Niveau
    voie: Voie
    matiere: BoundedSlug
    statut_enseignement: StatutEnseignement
    audience: Literal["libre", "aefe", "tous"]
    candidates: list[Candidat] = Field(
        min_length=1,
        max_length=16,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("candidates")
    @classmethod
    def validate_candidates(cls, values: list[Candidat]) -> list[Candidat]:
        if len(values) != len(set(values)):
            raise ValueError("candidates cannot contain duplicates")
        return values


class RetrievalScopeEvidenceSubject(StrictBaseModel):
    """Dimensions SQL autoritatives de la preuve curriculaire V2."""

    collection: CollectionName
    tenant: BoundedSlug
    niveau: Niveau
    voie: Voie
    matiere: BoundedSlug
    statut_enseignement: StatutEnseignement
    candidat: Candidat
    audiences: list[Literal["libre", "aefe", "tous"]] = Field(
        min_length=1,
        max_length=3,
        json_schema_extra={"uniqueItems": True},
    )
    visibility: Literal["public", "internal", "restricted", "private"]
    rights: list[Rights] = Field(
        min_length=1,
        max_length=16,
        json_schema_extra={"uniqueItems": True},
    )
    school_year: SchoolYear
    programme_version: ProgrammeVersion

    @field_validator("audiences", "rights")
    @classmethod
    def validate_unique_values(cls, values: list[object]) -> list[object]:
        if len(values) != len(set(values)):
            raise ValueError("evidence values cannot contain duplicates")
        return values


class RetrievalScopeArtifactV2(StrictBaseModel):
    """Scope étroit séparant identité cible et preuve pédagogique."""

    artifact_version: Literal["2"]
    scope_id: BoundedSlug
    status: Literal["eligible_for_promotion"]
    source_sha256: Sha256Digest
    target_identity: RetrievalScopeTargetIdentity
    evidence_subject: RetrievalScopeEvidenceSubject

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def sha256_digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def validate_envelope(self, envelope: InternalIdentityEnvelope) -> None:
        if envelope.scope_id != self.scope_id:
            raise ValueError("scope_id does not match the artifact")
        if envelope.scope_digest != self.sha256_digest():
            raise ValueError("scope_digest does not match the artifact")
        if envelope.allowed_collections != [self.evidence_subject.collection]:
            raise ValueError("allowed_collections do not match the artifact")

        identity = envelope.identity
        profile = identity.pedagogical_profile
        expected = self.target_identity
        if identity.tenant != expected.tenant:
            raise ValueError("identity.tenant does not match the artifact")
        if identity.niveau != expected.niveau:
            raise ValueError("identity.niveau does not match the artifact")
        if identity.school_year != self.evidence_subject.school_year:
            raise ValueError("identity.school_year does not match the artifact")
        if profile.voie != expected.voie:
            raise ValueError("identity.voie does not match the artifact")
        if profile.matieres != [expected.matiere]:
            raise ValueError("identity.matieres do not match the artifact")
        if profile.statut_enseignement != expected.statut_enseignement:
            raise ValueError("identity.statut_enseignement does not match the artifact")
        if profile.candidat not in expected.candidates:
            raise ValueError("identity.candidat does not match the artifact")
        if profile.audience != expected.audience:
            raise ValueError("identity.audience does not match the artifact")


RetrievalScopeArtifact: TypeAlias = (
    PilotRetrievalScopeArtifact | RetrievalScopeArtifactV2
)

_RETRIEVAL_SCOPE_RESOURCES: Mapping[str, tuple[str, str, Literal["1", "2"]]] = (
    MappingProxyType(
        {
            "libre_terminale_maths_nsi_real_v1": (
                ARTIFACT_RESOURCE,
                PILOT_RETRIEVAL_SCOPE_DIGEST,
                "1",
            ),
            "entree_seconde_maths_v1": (
                "artifacts/retrieval-scope-entree-seconde-maths-v1.json",
                "b6d8af23df88bd62c2ae601352a9591d2a97b16cca2a5723470679c2b547ce7b",
                "2",
            ),
            "entree_seconde_francais_v1": (
                "artifacts/retrieval-scope-entree-seconde-francais-v1.json",
                "1793ae29067f6f499f73e2d2dfdfc6b5bef5a7f809b75bc6165010165860b983",
                "2",
            ),
            "entree_premiere_maths_v1": (
                "artifacts/retrieval-scope-entree-premiere-maths-v1.json",
                "ea588c50397e720174f45d4ae85d851d49ad743e81899fc7b28a15cb8f890831",
                "2",
            ),
            "entree_premiere_francais_v1": (
                "artifacts/retrieval-scope-entree-premiere-francais-v1.json",
                "f983959892ec90ca68de8d6bf7649f76b76a52c449171cd59073305e2302cfb4",
                "2",
            ),
            "entree_troisieme_maths_v1": (
                "artifacts/retrieval-scope-entree-troisieme-maths-v1.json",
                "f2bf84333a33cf4408e95901805066870a1e38cc361db0fd472943e5a4f3cbdf",
                "2",
            ),
            "entree_troisieme_francais_v1": (
                "artifacts/retrieval-scope-entree-troisieme-francais-v1.json",
                "f2a483dfe490ea07bf13f30a907a54f05cf235a62fde05e832ffdbb708037b5f",
                "2",
            ),
            "entree_terminale_maths_v1": (
                "artifacts/retrieval-scope-entree-terminale-maths-v1.json",
                "17bb7b8accfc1c738dc3cf75a424808c39900100a771e71d29cb0bcb5fdceee1",
                "2",
            ),
            "entree_terminale_nsi_v1": (
                "artifacts/retrieval-scope-entree-terminale-nsi-v1.json",
                "a5e311149bba4863125a9ca8c8e28b0400a27dc855b2cd37c329ebf56f104a93",
                "2",
            ),
            "eaf_premiere_francais_v1": (
                "artifacts/retrieval-scope-eaf-premiere-francais-v1.json",
                "d674858bbe13c6c82a6b688a9444af8d7d1521b7fb5dd8763eb551a694fa2fb2",
                "2",
            ),
            "terminale_maths_v1": (
                "artifacts/retrieval-scope-terminale-maths-v1.json",
                "3ea4cc2898f590bc0377f751b2e52a2a81f8878975eff0cb3b08382ec5bb3c63",
                "2",
            ),
            "terminale_nsi_v1": (
                "artifacts/retrieval-scope-terminale-nsi-v1.json",
                "22b4dd4be1e6c1eb52603a8f0f88a1e362b2b7c7ec2b291b34c5166d1175113b",
                "2",
            ),
            "terminale_physique_chimie_v1": (
                "artifacts/retrieval-scope-terminale-physique-chimie-v1.json",
                "16ffcc4090f5e04531668ceaa66c19fad9eeb13e6d076b2793d607aefb9079f5",
                "2",
            ),
            "prod_dgemc_terminale_option_v1": (
                "artifacts/retrieval-scope-prod-dgemc-terminale-option-v1.json",
                "ab2da910d50abed9c030dc9eba2520b31cf430a1f89610988b529657a9903b5c",
                "2",
            ),
            "prod_francais_premiere_tc_v1": (
                "artifacts/retrieval-scope-prod-francais-premiere-tc-v1.json",
                "3dfb9da4f92d38c566eda0b0dba57d4881e4c63429c04c1ef6bb656b68669bb9",
                "2",
            ),
            "prod_francais_quatrieme_tc_v1": (
                "artifacts/retrieval-scope-prod-francais-quatrieme-tc-v1.json",
                "409f2256169fbed99273e690c3d36a0718787e91b37159bf03ef7ab75d19c670",
                "2",
            ),
            "prod_francais_seconde_tc_v1": (
                "artifacts/retrieval-scope-prod-francais-seconde-tc-v1.json",
                "8ea7e3e62ea93e3ccdb4eec2be3b6564f4cdd4a024a7ec1828234ecb186f81dc",
                "2",
            ),
            "prod_hlp_premiere_specialite_v1": (
                "artifacts/retrieval-scope-prod-hlp-premiere-specialite-v1.json",
                "abc0a93328455ecb1673420c5620175b5db487db8edb0a57bc4dc2876f24a6ba",
                "2",
            ),
            "prod_maths_premiere_gen_specialite_v1": (
                "artifacts/retrieval-scope-prod-maths-premiere-gen-specialite-v1.json",
                "0235f1c56462b4834f1c57eaf88119807055f533a22e0a5f25f86e772c42b34a",
                "2",
            ),
            "prod_maths_quatrieme_tc_v1": (
                "artifacts/retrieval-scope-prod-maths-quatrieme-tc-v1.json",
                "18da5383c0bb8173fc28189646580788425d079a1d0fbb4dc3674b8a086ea44d",
                "2",
            ),
            "prod_maths_seconde_tc_v1": (
                "artifacts/retrieval-scope-prod-maths-seconde-tc-v1.json",
                "a01dfb8a9463199aeb9838aa0c1e84cf7b85aefc4135edf5af11166ca3a5df41",
                "2",
            ),
            "prod_maths_terminale_gen_specialite_v1": (
                "artifacts/retrieval-scope-prod-maths-terminale-gen-specialite-v1.json",
                "5aea0f29bb2993700f462321f5d781557f73fa83c84ff1cf02c7d093ec2af9c3",
                "2",
            ),
            "prod_nsi_premiere_specialite_v1": (
                "artifacts/retrieval-scope-prod-nsi-premiere-specialite-v1.json",
                "06665cc215419fa597bf475d281f8c0d7f2b45232e0819960fedb065f845f231",
                "2",
            ),
            "prod_nsi_terminale_specialite_v1": (
                "artifacts/retrieval-scope-prod-nsi-terminale-specialite-v1.json",
                "a1bd4723de03a7a75903ba907d60687dc8140416d28f9707afbf6a2f4d46a5b8",
                "2",
            ),
            "prod_pc_premiere_specialite_v1": (
                "artifacts/retrieval-scope-prod-pc-premiere-specialite-v1.json",
                "9d04d5843ccc6d1630a4f8f34418ad46a52c8c8cddcc1a6ce9796a22a01d585c",
                "2",
            ),
            "prod_pc_terminale_specialite_v1": (
                "artifacts/retrieval-scope-prod-pc-terminale-specialite-v1.json",
                "fcaf1430f51c1f5ccb8067ec875cc8675be1ed2b9bba84752c32a96f6f08e66c",
                "2",
            ),
            "prod_philo_terminale_tc_v1": (
                "artifacts/retrieval-scope-prod-philo-terminale-tc-v1.json",
                "16798b67cca720b38813b8e811efc17d2317f03a9bfeb752749b7a6ad51f1a5f",
                "2",
            ),
            "prod_ses_premiere_specialite_v1": (
                "artifacts/retrieval-scope-prod-ses-premiere-specialite-v1.json",
                "d722374f719d070a18b374772cdb336e7eda0422a80360f70b16fea24e022e13",
                "2",
            ),
            "prod_ses_terminale_specialite_v1": (
                "artifacts/retrieval-scope-prod-ses-terminale-specialite-v1.json",
                "9b9763f5afe249d2a3ae1fa2ed1bdb3de16136fe69e869760e32f95c0e97175b",
                "2",
            ),
            "prod_svt_premiere_specialite_v1": (
                "artifacts/retrieval-scope-prod-svt-premiere-specialite-v1.json",
                "49a4618951ed114103c5c77c029597b81555f2b459cd80c6b7ccd7788cbd6646",
                "2",
            ),
            "prod_svt_terminale_specialite_v1": (
                "artifacts/retrieval-scope-prod-svt-terminale-specialite-v1.json",
                "8256a1a8b2c7f83fd601e0fd312f0dfb94c49416b42e779ffcff12a06e023256",
                "2",
            ),
        }
    )
)


def load_retrieval_scope_artifact(scope_id: str) -> RetrievalScopeArtifact:
    """Charger un scope explicitement nommé, sans découverte ni fallback."""
    try:
        resource_name, expected_digest, version = _RETRIEVAL_SCOPE_RESOURCES[scope_id]
    except KeyError as exc:
        raise ValueError("unknown retrieval scope") from exc
    resource = files("nexus_contracts").joinpath(resource_name)
    if version == "1":
        artifact: RetrievalScopeArtifact = (
            PilotRetrievalScopeArtifact.model_validate_json(resource.read_bytes())
        )
    else:
        artifact = RetrievalScopeArtifactV2.model_validate_json(resource.read_bytes())
    if artifact.scope_id != scope_id or artifact.sha256_digest() != expected_digest:
        raise ValueError("retrieval scope artifact digest mismatch")
    return artifact


def load_retrieval_scope_registry() -> Mapping[str, RetrievalScopeArtifact]:
    """Retourner le registre fermé de scopes packagés et vérifiés."""
    return MappingProxyType(
        {
            scope_id: load_retrieval_scope_artifact(scope_id)
            for scope_id in _RETRIEVAL_SCOPE_RESOURCES
        }
    )


def load_pilot_retrieval_scope() -> PilotRetrievalScopeArtifact:
    """Charger l'artefact dormant livré dans le package nexus-contracts."""
    artifact = load_retrieval_scope_artifact("libre_terminale_maths_nsi_real_v1")
    if not isinstance(artifact, PilotRetrievalScopeArtifact):
        raise ValueError("pilot retrieval scope artifact version mismatch")
    return artifact


__all__ = [
    "PilotRetrievalScopeArtifact",
    "PILOT_RETRIEVAL_SCOPE_DIGEST",
    "PilotScopeIdentity",
    "PilotScopeSubject",
    "RetrievalScopeArtifact",
    "RetrievalScopeArtifactV2",
    "RetrievalScopeEvidenceSubject",
    "RetrievalScopeTargetIdentity",
    "load_retrieval_scope_artifact",
    "load_retrieval_scope_registry",
    "load_pilot_retrieval_scope",
]
