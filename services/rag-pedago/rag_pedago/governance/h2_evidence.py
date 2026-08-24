"""Bundle de preuves H2 — ``NEXUS-H2-EVIDENCE-V1`` et son résolveur.

**Ce que le bundle est.** Un objet unique qui lie, en un seul digest,
tout ce qu'une promotion doit pouvoir prouver : le code fusionné, le
corpus immuable, le catalogue, la revue, l'autorisation, les ancres, et
le verdict du gate. Sans lui, une promotion vérifierait dix preuves
indépendantes et rien ne garantirait qu'elles parlent du même objet.

**Pourquoi ``run_id`` appartient au contenu et pas l'horodatage.** Les
deux varient d'une exécution à l'autre, mais pas pour la même raison. Le
``run_id`` *identifie* l'exécution qui a produit la preuve : deux runs
sont deux preuves distinctes, et c'est exactement ce que le résolveur doit
pouvoir départager. L'horodatage, lui, varie sans rien identifier — deux
lectures d'horloge dans le même run donneraient deux digests pour une
seule preuve. Il vit donc dans une enveloppe non hachée.

La règle qui en découle : *le digest de contenu doit être reproductible à
partir du contenu seul*. Si régénérer le bundle depuis les mêmes entrées
donnait un autre digest, la preuve identifierait une exécution plutôt
qu'un fait.

**Strict par construction.** Un champ inconnu est un refus, pas un champ
ignoré. Un producteur qui ajoute une clé sans faire évoluer le protocole
produit une preuve qu'un consommateur plus ancien lirait partiellement,
en croyant l'avoir lue entièrement.

**Le résolveur ne choisit jamais.** Zéro candidat est un refus ; deux
candidats sont un refus. Sélectionner « le plus récent » ou « le dernier
disponible » transformerait une ambiguïté — donc un défaut de gouvernance
— en succès silencieux.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any

from nexus_contracts.authorization_set import parse_authorization_set
from nexus_contracts.h2_coverage_evidence import parse_h2_coverage_evidence_v2
from nexus_contracts.release_evidence import (
    H2_EVIDENCE_V2_PROTOCOL_VERSION,
    H2EvidenceBundleV2,
    ReleaseEvidenceError,
)

from rag_pedago.governance.corpus_campaign import parse_corpus_campaign_v2

#: Identifiant de protocole. Toute évolution du jeu de champs doit le
#: changer : deux formats ne peuvent pas partager une identité.
H2_EVIDENCE_PROTOCOL = "NEXUS-H2-EVIDENCE-V1"

#: Nom exact de l'artefact publié. Le résolveur ne fait aucun préfixe ni
#: aucune correspondance approximative.
ARTIFACT_NAME_TEMPLATE = "h2-evidence-{merge_sha}-{campaign_id}"

#: Seul environnement dont les preuves peuvent promouvoir.
PRODUCTION_ENVIRONMENT = "production"

#: Durée de validité du reçu exact-head. Une approbation humaine n'est
#: pas un blanc-seing permanent : au-delà, l'arbre approuvé et l'arbre
#: promu ont eu le temps de diverger dans l'esprit du relecteur, même
#: si les digests coïncident encore.
EXACT_HEAD_RECEIPT_MAX_AGE = timedelta(days=7)

_SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")
_OCI_DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
_CAMPAIGN_ID = re.compile(r"\A[a-z0-9][a-z0-9._-]{2,63}\Z")


class H2EvidenceError(ValueError):
    """La preuve ne se tient pas — refus explicite.

    Jamais dégradée en avertissement : une preuve incomplète qui promeut
    est pire qu'une promotion bloquée."""


def _require_hex(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.match(value):
        raise H2EvidenceError(
            f"{field_name} must be a lowercase 64-hex SHA-256, got {value!r}"
        )
    return value


def _require_oci(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _OCI_DIGEST.match(value):
        raise H2EvidenceError(
            f"{field_name} must be a 'sha256:<64 hex>' OCI digest, got {value!r}"
        )
    return value


def _require_git_sha(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.match(value):
        raise H2EvidenceError(
            f"{field_name} must be a full 40-hex git object id, got {value!r} — an "
            "abbreviated SHA is ambiguous and cannot pin an immutable tree"
        )
    return value


@dataclass(frozen=True)
class H2EvidenceBundle:
    """Preuve H2 canonique liant code, corpus, revue et verdict.

    Tous les champs sont obligatoires. Un champ optionnel serait un champ
    qu'un producteur peut omettre en silence, donc une preuve dont
    l'absence ressemblerait à une preuve."""

    # ── Identité du code fusionné ──────────────────────────────────────
    repository: str
    pull_request_number: int
    pr_head_sha: str
    pr_head_tree_sha: str
    merge_sha: str
    merge_tree_sha: str

    # ── Identité du corpus immuable ────────────────────────────────────
    campaign_id: str
    campaign_sha256: str
    source_oci_digest: str
    source_archive_sha256: str
    source_tree_digest: str
    manifest_sha256: str
    catalog_sha256: str
    review_view_sha256: str

    # ── Autorité de gouvernance ────────────────────────────────────────
    authorization_sha256: str
    revocation_registry_sha256: str
    trust_anchor_sha256: str
    exact_head_receipt_sha256: str
    exact_head_receipt_issued_at: str

    # ── Configurations gouvernées ──────────────────────────────────────
    routing_config_sha256: str
    rights_config_sha256: str
    pii_config_sha256: str
    golden_config_sha256: str

    # ── Verdict du gate ────────────────────────────────────────────────
    h2_report_sha256: str
    h2_coverage_gate_pass: bool
    authority_revocations_checked: bool
    coverage_complete: bool

    # ── Identité de l'exécution productrice ────────────────────────────
    environment: str
    workflow_path: str
    run_id: str
    run_attempt: int

    def __post_init__(self) -> None:
        _require_git_sha(self.pr_head_sha, field_name="pr_head_sha")
        _require_git_sha(self.pr_head_tree_sha, field_name="pr_head_tree_sha")
        _require_git_sha(self.merge_sha, field_name="merge_sha")
        _require_git_sha(self.merge_tree_sha, field_name="merge_tree_sha")
        _require_oci(self.source_oci_digest, field_name="source_oci_digest")

        for field_name in (
            "campaign_sha256",
            "source_archive_sha256",
            "source_tree_digest",
            "manifest_sha256",
            "catalog_sha256",
            "review_view_sha256",
            "authorization_sha256",
            "revocation_registry_sha256",
            "trust_anchor_sha256",
            "exact_head_receipt_sha256",
            "routing_config_sha256",
            "rights_config_sha256",
            "pii_config_sha256",
            "golden_config_sha256",
            "h2_report_sha256",
        ):
            _require_hex(getattr(self, field_name), field_name=field_name)

        if not _CAMPAIGN_ID.match(self.campaign_id):
            raise H2EvidenceError(
                f"campaign_id {self.campaign_id!r} is not a canonical identifier"
            )
        if "/" not in self.repository:
            raise H2EvidenceError(
                f"repository {self.repository!r} must be '<owner>/<name>'"
            )
        if self.pull_request_number <= 0:
            raise H2EvidenceError("pull_request_number must be a positive integer")
        if self.run_attempt <= 0:
            raise H2EvidenceError("run_attempt must be a positive integer")
        if not self.run_id:
            raise H2EvidenceError("run_id is required to attribute the evidence")
        if not self.workflow_path:
            raise H2EvidenceError("workflow_path is required to attribute the evidence")

        # Le cœur de la garantie exact-head : ce qu'un humain a relu et ce
        # qui a été fusionné doivent être le *même arbre*, pas seulement
        # deux commits reliés. Deux SHA de commit diffèrent toujours (le
        # merge a un parent de plus) ; les arbres, eux, doivent coïncider.
        if self.pr_head_tree_sha != self.merge_tree_sha:
            raise H2EvidenceError(
                "pr_head_tree_sha does not equal merge_tree_sha — the merged tree "
                "is not the tree a human approved, so the review does not cover "
                "what would be promoted"
            )

    # ── Contenu canonique ──────────────────────────────────────────────

    def to_content_dict(self) -> dict[str, Any]:
        """Le contenu haché. Aucune lecture d'horloge n'y entre."""
        return {
            name.name: getattr(self, name.name) for name in fields(self)
        }

    def to_canonical_json(self) -> bytes:
        payload = json.dumps(
            {"protocol": H2_EVIDENCE_PROTOCOL, "content": self.to_content_dict()},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        return (payload + "\n").encode("utf-8")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.to_canonical_json()).hexdigest()

    @property
    def artifact_name(self) -> str:
        return ARTIFACT_NAME_TEMPLATE.format(
            merge_sha=self.merge_sha, campaign_id=self.campaign_id
        )

    def to_envelope(self, *, produced_at: str) -> dict[str, Any]:
        """Enveloppe publiée : contenu + horodatage **hors** du digest.

        ``produced_at`` est passé, jamais lu depuis l'horloge : une
        fonction qui lit l'heure ne peut pas être testée pour son
        déterminisme."""
        return {
            "protocol": H2_EVIDENCE_PROTOCOL,
            "content": self.to_content_dict(),
            "content_sha256": self.content_sha256,
            "produced_at": produced_at,
        }

    # ── Reconstruction stricte ─────────────────────────────────────────

    @classmethod
    def from_content_dict(cls, payload: Mapping[str, Any]) -> H2EvidenceBundle:
        """Reconstruit depuis un contenu, en refusant tout champ inconnu.

        Un champ ignoré serait une preuve lue partiellement par un
        consommateur convaincu de l'avoir lue entièrement."""
        expected = {item.name for item in fields(cls)}
        received = set(payload)
        unknown = received - expected
        if unknown:
            raise H2EvidenceError(
                f"unknown field(s) {sorted(unknown)} — the producer emitted evidence "
                f"this consumer cannot interpret; {H2_EVIDENCE_PROTOCOL} is strict "
                "so that a partially-read bundle never looks fully read"
            )
        missing = expected - received
        if missing:
            raise H2EvidenceError(
                f"missing required field(s) {sorted(missing)} — an absent proof must "
                "never resemble a satisfied one"
            )
        return cls(**dict(payload))

    @classmethod
    def from_envelope(cls, payload: Mapping[str, Any]) -> H2EvidenceBundle:
        """Relit une enveloppe et **revérifie** son digest annoncé."""
        if payload.get("protocol") != H2_EVIDENCE_PROTOCOL:
            raise H2EvidenceError(
                f"expected protocol {H2_EVIDENCE_PROTOCOL!r}, got "
                f"{payload.get('protocol')!r}"
            )
        content = payload.get("content")
        if not isinstance(content, Mapping):
            raise H2EvidenceError("envelope carries no content mapping")
        bundle = cls.from_content_dict(content)
        announced = payload.get("content_sha256")
        if announced != bundle.content_sha256:
            raise H2EvidenceError(
                "content_sha256 does not match the recomputed digest — the envelope "
                "announces an identity its own content does not have"
            )
        return bundle


def verify_gate_outcome(bundle: H2EvidenceBundle) -> None:
    """Refuse une preuve dont le verdict n'est pas un succès complet.

    Les trois drapeaux sont vérifiés séparément parce qu'ils prouvent
    trois choses différentes : que le gate a conclu, que la non-révocation
    a été *prouvée* contre un registre plutôt que supposée faute de
    registre, et que la couverture porte sur tout le périmètre."""
    if not bundle.h2_coverage_gate_pass:
        raise H2EvidenceError("h2_coverage_gate_pass is false — the gate did not pass")
    if not bundle.authority_revocations_checked:
        raise H2EvidenceError(
            "authority_revocations_checked is false — non-revocation was assumed "
            "for want of a registry, not proven against one"
        )
    if not bundle.coverage_complete:
        raise H2EvidenceError(
            "coverage_complete is false — a gate that is green on a sample is not "
            "green on its perimeter"
        )
    if bundle.environment != PRODUCTION_ENVIRONMENT:
        raise H2EvidenceError(
            f"environment is {bundle.environment!r}, not {PRODUCTION_ENVIRONMENT!r} — "
            "evidence produced outside the protected environment cannot promote"
        )


def verify_receipt_freshness(bundle: H2EvidenceBundle, *, now: datetime) -> None:
    """Refuse un reçu exact-head périmé.

    ``now`` est injecté : une vérification qui lit l'horloge ne peut pas
    être testée aux bornes."""
    try:
        issued = datetime.fromisoformat(bundle.exact_head_receipt_issued_at)
    except ValueError as exc:
        raise H2EvidenceError(
            f"exact_head_receipt_issued_at {bundle.exact_head_receipt_issued_at!r} "
            "is not an ISO-8601 instant"
        ) from exc
    if issued.tzinfo is None:
        raise H2EvidenceError(
            "exact_head_receipt_issued_at must carry an explicit timezone — a naive "
            "instant is ambiguous by up to a day"
        )
    issued = issued.astimezone(UTC)
    reference = now.astimezone(UTC)
    if issued > reference:
        raise H2EvidenceError(
            "exact_head_receipt_issued_at is in the future — refusing rather than "
            "trusting a clock that disagrees with the producer's"
        )
    if reference - issued > EXACT_HEAD_RECEIPT_MAX_AGE:
        raise H2EvidenceError(
            f"exact-head receipt is older than {EXACT_HEAD_RECEIPT_MAX_AGE.days} days "
            "— a human approval is not a permanent blank cheque"
        )


def cross_check_review_view(
    bundle: H2EvidenceBundle,
    *,
    review_view_sha256: str,
    manifest_sha256: str,
    catalog_sha256: str,
    source_oci_digest: str,
) -> None:
    """Vérifie que la vue de revue parle bien du corpus promu.

    Sans ce contrôle, un bundle pourrait référencer une vue relue par un
    humain *et* un corpus différent : chaque digest serait valide
    isolément, et l'ensemble ne prouverait rien."""
    mismatches = []
    if bundle.review_view_sha256 != review_view_sha256:
        mismatches.append("review_view_sha256")
    if bundle.manifest_sha256 != manifest_sha256:
        mismatches.append("manifest_sha256")
    if bundle.catalog_sha256 != catalog_sha256:
        mismatches.append("catalog_sha256")
    if bundle.source_oci_digest != source_oci_digest:
        mismatches.append("source_oci_digest")
    if mismatches:
        raise H2EvidenceError(
            f"bundle disagrees with the produced evidence on {sorted(mismatches)} — "
            "the reviewed corpus and the promoted corpus are not the same object"
        )


def build_h2_evidence_bundle_v2(
    *,
    campaign_raw: bytes,
    authorization_set_raw: bytes,
    h2_coverage_evidence_raw: bytes,
    review_view_sha256: str,
    repository: str,
    pull_request_number: int,
    pr_head_sha: str,
    pr_head_tree_sha: str,
    merge_sha: str,
    merge_tree_sha: str,
    workflow_path: str,
    run_id: str,
    run_attempt: int,
) -> H2EvidenceBundleV2:
    """Assemble V2 depuis les trois documents canoniques, jamais des flags libres.

    Les digests de configuration, d'autorité, de révocation et de placement
    proviennent de la preuve H2 structurée. La campagne et le set sont relus et
    rehachés ici, puis chaque identité dupliquée est confrontée.
    """
    try:
        campaign = parse_corpus_campaign_v2(campaign_raw)
    except ValueError as exc:
        raise ReleaseEvidenceError(f"campaign V2 is invalid: {exc}") from exc
    try:
        authorization_set = parse_authorization_set(authorization_set_raw)
    except ValueError as exc:
        raise ReleaseEvidenceError(f"authorization set is invalid: {exc}") from exc
    try:
        h2_coverage = parse_h2_coverage_evidence_v2(h2_coverage_evidence_raw)
    except ValueError as exc:
        raise ReleaseEvidenceError(f"H2 coverage V2 is invalid: {exc}") from exc

    authorization_set_digest = hashlib.sha256(authorization_set_raw).hexdigest()
    h2_coverage_digest = hashlib.sha256(h2_coverage_evidence_raw).hexdigest()
    campaign_digest = hashlib.sha256(campaign_raw).hexdigest()
    comparisons = {
        "authorization_set_digest": (
            authorization_set_digest,
            campaign.authorization_set_digest,
            h2_coverage.authorization_set_digest,
        ),
        "corpus_manifest_sha256": (
            authorization_set.corpus_manifest_sha256,
            campaign.expected_manifest_sha256,
            h2_coverage.corpus_manifest_sha256,
        ),
        "profile_manifest_digest": (
            authorization_set.profile_manifest_digest,
            campaign.profile_manifest_digest,
            h2_coverage.profile_manifest_digest,
        ),
        "release_scope_placement_digest": (
            authorization_set.release_scope_placement_digest,
            campaign.release_scope_placement_digest,
            h2_coverage.release_scope_placement_digest,
        ),
        "authority_required_count": (
            authorization_set.authority_required_count,
            campaign.authority_required_count,
            h2_coverage.authority_required_count,
            h2_coverage.authority_covered_count,
        ),
        "authority_required_set_sha256": (
            authorization_set.authority_required_set_sha256,
            campaign.authority_required_set_sha256,
            h2_coverage.authority_required_set_sha256,
        ),
        "authorization_count": (
            authorization_set.authorization_count,
            h2_coverage.authorization_count,
        ),
        "authorizations_effective_valid_until": (
            authorization_set.authorizations_effective_valid_until,
            h2_coverage.authorizations_effective_valid_until,
        ),
        "catalog": (
            campaign.expected_catalog_digest,
            h2_coverage.input_file_digests["catalog"],
        ),
        "routing": (
            campaign.routing_config_digest,
            h2_coverage.input_file_digests["routing"],
        ),
        "rights": (
            campaign.rights_config_digest,
            h2_coverage.input_file_digests["rights"],
        ),
        "pii": (
            campaign.pii_config_digest,
            h2_coverage.input_file_digests["pii"],
        ),
        "golden": (
            campaign.golden_spec_digest,
            h2_coverage.input_file_digests["golden"],
        ),
    }
    for label, values in comparisons.items():
        if len(set(values)) != 1:
            raise ReleaseEvidenceError(f"{label} differs across release evidence")
    if campaign.environment != "production":
        raise ReleaseEvidenceError("campaign V2 is not a production campaign")
    if h2_coverage.git_commit != merge_sha:
        raise ReleaseEvidenceError("H2 coverage git_commit does not match merge_sha")
    if h2_coverage.release_scope_source_tree_sha != merge_tree_sha:
        raise ReleaseEvidenceError(
            "H2 coverage release_scope_source_tree_sha does not match merge_tree_sha"
        )

    try:
        return H2EvidenceBundleV2.model_validate(
            {
                "protocol_version": H2_EVIDENCE_V2_PROTOCOL_VERSION,
                "repository": repository,
                "pull_request_number": pull_request_number,
                "pr_head_sha": pr_head_sha,
                "pr_head_tree_sha": pr_head_tree_sha,
                "merge_sha": merge_sha,
                "merge_tree_sha": merge_tree_sha,
                "campaign_id": campaign.campaign_id,
                "campaign_digest": campaign_digest,
                "source_oci_digest": campaign.source_oci_digest,
                "source_archive_sha256": campaign.source_archive_sha256,
                "source_tree_digest": campaign.source_tree_digest,
                "corpus_manifest_sha256": h2_coverage.corpus_manifest_sha256,
                "catalog_sha256": h2_coverage.input_file_digests["catalog"],
                "review_view_sha256": review_view_sha256,
                "profile_manifest_digest": h2_coverage.profile_manifest_digest,
                "authorization_set_digest": authorization_set_digest,
                "authorization_count": authorization_set.authorization_count,
                "authority_required_count": authorization_set.authority_required_count,
                "authority_required_set_sha256": (
                    authorization_set.authority_required_set_sha256
                ),
                "release_scope_source_tree_sha": (
                    h2_coverage.release_scope_source_tree_sha
                ),
                "release_scope_placement_digest": (
                    h2_coverage.release_scope_placement_digest
                ),
                "release_scope_source_blob_digests": (
                    h2_coverage.release_scope_source_blob_digests
                ),
                "revocation_registry_sha256": h2_coverage.input_file_digests[
                    "authority_revocations"
                ],
                "review_binding_trust_anchor_sha256": (
                    h2_coverage.input_file_digests["review_binding_trust_anchor"]
                ),
                "trusted_reviewers_sha256": h2_coverage.input_file_digests[
                    "trusted_reviewers"
                ],
                "input_file_digests": h2_coverage.input_file_digests,
                "authorization_set_verified_at": (
                    h2_coverage.authorization_set_verified_at
                ),
                "earliest_review_submitted_at": (
                    h2_coverage.earliest_review_submitted_at
                ),
                "earliest_review_binding_verified_at": (
                    h2_coverage.earliest_review_binding_verified_at
                ),
                "earliest_review_binding_expires_at": (
                    h2_coverage.earliest_review_binding_expires_at
                ),
                "authorizations_effective_valid_from": (
                    authorization_set.authorizations_effective_valid_from
                ),
                "authorizations_effective_valid_until": (
                    h2_coverage.authorizations_effective_valid_until
                ),
                "h2_coverage_generated_at": h2_coverage.generated_at,
                "h2_coverage_evidence_sha256": h2_coverage_digest,
                "h2_coverage_gate_pass": h2_coverage.h2_coverage_gate_pass,
                "authority_revocations_checked": (
                    h2_coverage.authority_revocations_checked
                ),
                "authority_review_bindings_verified": (
                    h2_coverage.authority_review_bindings_verified
                ),
                "coverage_complete": h2_coverage.coverage_complete,
                "authority_covered_count": h2_coverage.authority_covered_count,
                "authorization_overlap_count": (
                    h2_coverage.authorization_overlap_count
                ),
                "authorization_gap_count": h2_coverage.authorization_gap_count,
                "authorization_extra_count": h2_coverage.authorization_extra_count,
                "environment": h2_coverage.environment,
                "workflow_path": workflow_path,
                "run_id": run_id,
                "run_attempt": run_attempt,
            }
        )
    except Exception as exc:  # noqa: BLE001 - frontière de contrat stricte
        raise ReleaseEvidenceError(f"H2 evidence V2 bundle is invalid: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────
# Résolution — §5.3
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceCandidate:
    """Un artefact candidat, tel que l'API GitHub le décrit.

    Volontairement pauvre : le résolveur ne doit disposer d'aucun champ
    qui l'inciterait à *choisir*. Il n'y a ni date de création ni taille,
    parce qu'un résolveur qui les connaît finit par les utiliser pour
    départager, et « le plus récent » n'est pas une preuve."""

    artifact_name: str
    workflow_path: str
    run_id: str
    run_attempt: int
    conclusion: str
    head_sha: str
    expired: bool


def resolve_evidence_artifact(
    candidates: Iterable[EvidenceCandidate],
    *,
    expected_workflow_path: str,
    expected_merge_sha: str,
    expected_campaign_id: str,
    expected_run_id: str,
    expected_run_attempt: int,
) -> EvidenceCandidate:
    """Retourne l'unique candidat admissible, ou refuse.

    Aucune sélection par date, aucun « latest », aucun repli. Le filtrage
    est exhaustif *puis* l'unicité est exigée — l'inverse laisserait
    passer le premier candidat trouvé."""
    expected_name = ARTIFACT_NAME_TEMPLATE.format(
        merge_sha=expected_merge_sha, campaign_id=expected_campaign_id
    )

    admissible: list[EvidenceCandidate] = []
    for candidate in candidates:
        if candidate.artifact_name != expected_name:
            continue
        if candidate.workflow_path != expected_workflow_path:
            continue
        if candidate.run_id != expected_run_id:
            continue
        if candidate.run_attempt != expected_run_attempt:
            continue
        if candidate.conclusion != "success":
            continue
        if candidate.head_sha != expected_merge_sha:
            continue
        if candidate.expired:
            continue
        admissible.append(candidate)

    if not admissible:
        raise H2EvidenceError(
            f"no admissible evidence artifact named {expected_name!r} produced by "
            f"{expected_workflow_path!r} at run {expected_run_id}/"
            f"{expected_run_attempt} — refusing rather than promoting unproven code"
        )
    if len(admissible) > 1:
        raise H2EvidenceError(
            f"{len(admissible)} admissible artifacts named {expected_name!r} — "
            "ambiguity is a governance defect, not something to break by picking "
            "the most recent one"
        )
    return admissible[0]


def verify_promotion_inputs(
    bundle: H2EvidenceBundle,
    candidate: EvidenceCandidate,
    *,
    now: datetime,
    expected_workflow_path: str,
) -> None:
    """Contrôle final avant promotion : le bundle et son artefact concordent."""
    verify_gate_outcome(bundle)
    verify_receipt_freshness(bundle, now=now)

    if bundle.workflow_path != expected_workflow_path:
        raise H2EvidenceError(
            f"bundle claims workflow {bundle.workflow_path!r} but promotion expects "
            f"{expected_workflow_path!r}"
        )
    if bundle.run_id != candidate.run_id or bundle.run_attempt != candidate.run_attempt:
        raise H2EvidenceError(
            "bundle run identity does not match the artifact that carried it — the "
            "evidence was produced by a different execution than the one resolved"
        )
    if bundle.merge_sha != candidate.head_sha:
        raise H2EvidenceError(
            "bundle merge_sha does not match the artifact head SHA"
        )
    if bundle.artifact_name != candidate.artifact_name:
        raise H2EvidenceError(
            "bundle does not derive the artifact name it was published under"
        )


def build_evidence_index(bundles: Sequence[H2EvidenceBundle]) -> dict[str, str]:
    """Index non auto-référentiel des preuves connues.

    L'index ne se contient jamais : un index dont le digest couvrirait
    son propre digest serait insoluble, et un index qui s'exclut sans le
    dire laisserait croire qu'il couvre tout."""
    index: dict[str, str] = {}
    for bundle in bundles:
        key = bundle.artifact_name
        if key in index and index[key] != bundle.content_sha256:
            raise H2EvidenceError(
                f"two distinct bundles share the artifact name {key!r} — the later "
                "would silently shadow the earlier"
            )
        index[key] = bundle.content_sha256
    return dict(sorted(index.items()))


__all__ = [
    "ARTIFACT_NAME_TEMPLATE",
    "EXACT_HEAD_RECEIPT_MAX_AGE",
    "H2_EVIDENCE_PROTOCOL",
    "PRODUCTION_ENVIRONMENT",
    "EvidenceCandidate",
    "H2EvidenceBundle",
    "H2EvidenceError",
    "build_h2_evidence_bundle_v2",
    "build_evidence_index",
    "cross_check_review_view",
    "resolve_evidence_artifact",
    "verify_gate_outcome",
    "verify_promotion_inputs",
    "verify_receipt_freshness",
]
