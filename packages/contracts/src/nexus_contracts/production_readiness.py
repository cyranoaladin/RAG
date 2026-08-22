"""Manifeste de readiness de production signé — `NEXUS-PRODUCTION-READINESS-V1`.

Contrat sérialisé entre **trois** consommateurs qui ne se font pas
confiance mutuellement :

1. le workflow de promotion, qui l'émet et le signe ;
2. le wrapper de déploiement côté serveur, qui refuse de déployer sans
   lui ;
3. le runtime d'ingestion, qui refuse de démarrer et de créer un job de
   mutation sans lui.

C'est parce qu'il traverse ces trois frontières qu'il vit dans
``packages/contracts`` plutôt que dans l'un d'eux : trois parseurs
indépendants finiraient par diverger, et un manifeste interprété
différemment par le vérificateur et par l'exécutant n'est plus une
preuve.

**Ce qu'il lie.** Le manifeste ne dit pas « tout va bien » : il nomme
exactement *quoi* a été vérifié. Le commit de merge déployé, l'arbre Git
complet du HEAD de PR approuvé, les digests OCI des images qui tourneront,
les digests de toutes les preuves de gouvernance, et le verdict du gate.
Un seul de ces champs qui diverge et le déploiement est refusé.

**Identité de l'arbre, pas seulement du chemin gouverné.** Le contrat
exige ``pr_head_tree_sha == merge_tree_sha``. Comparer uniquement
``governance/**`` prouverait que les preuves n'ont pas bougé, mais pas que
le *code déployé* est celui qui a été relu. C'est l'arbre complet ou rien.

**Séparation des clés.** La clé qui signe ce manifeste n'est jamais celle
qui signe les reçus de liaison de revue (ADR-0025/ADR-0035). Les deux
autorités sont distinctes : l'une atteste qu'un humain a relu une
autorisation, l'autre qu'une chaîne de promotion complète a réussi.
Réutiliser une seule clé permettrait à quiconque peut émettre un reçu
d'émettre aussi une autorisation de déploiement. L'ancre de readiness est
donc un fichier distinct, et ce module refuse une ancre dont le
``protocol_version`` n'est pas le sien.

**Ce que le tag de release signifie.** ``release_tag`` est l'identité
immuable d'une version *candidate* au déploiement, créée après le gate et
après la signature, avant le déploiement. Ce n'est **pas** une preuve de
déploiement réussi : celle-ci est portée par le statut de l'Environment
GitHub, l'artifact de preuve final, le journal d'audit et les health
checks. Un tag peut donc légitimement subsister sur un déploiement qui a
échoué, et n'est jamais déplacé ni réutilisé.

Aucune cryptographie artisanale : Ed25519 via ``cryptography``, et la
canonicalisation est celle déjà employée par les autres artefacts
d'autorité (clés triées, indentation fixe, UTF-8, saut de ligne final).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictInt, StrictStr, field_validator, model_validator

from nexus_contracts.document import StrictBaseModel

#: Version de protocole. Absente ou inconnue, le manifeste n'est pas parsé.
PRODUCTION_READINESS_PROTOCOL_VERSION = "NEXUS-PRODUCTION-READINESS-V1"

#: Le manifeste n'existe que pour la production. Un mode répétition ne
#: réutilise pas ce protocole en l'affaiblissant : il utilise ses propres
#: fixtures et sa propre ancre (cf. ADR-0036 § rehearsal).
PRODUCTION_ENVIRONMENT = "production"

_HEX64 = r"^[0-9a-f]{64}$"
_GIT_SHA1 = r"^[0-9a-f]{40}$"
_OCI_DIGEST = r"^sha256:[0-9a-f]{64}$"
_HEX_ED25519 = r"^[0-9a-f]{64}$"
_SIGNATURE_HEX = r"^[0-9a-f]{128}$"
_KEY_ID = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_REPOSITORY = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
_SERVICE_NAME = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_IMAGE_REF = r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
_WORKFLOW_PATH = r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml$"

#: ``release/rag/YYYYMMDD-<merge_sha12>`` — le suffixe est les 12 premiers
#: caractères du merge SHA, ce qui rend le tag vérifiable sans contexte.
_RELEASE_TAG = re.compile(r"^release/rag/(\d{8})-([0-9a-f]{12})$")

_CANONICAL_INDENT = 2


class ProductionReadinessError(ValueError):
    """Le manifeste ne prouve pas ce qu'il prétend — refus explicite.

    Jamais une valeur de repli : un déploiement qui continue sur un
    manifeste douteux est exactement ce que ce contrat existe pour
    empêcher."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _canonical_digest_map(values: dict[str, str]) -> dict[str, str]:
    return {key: values[key] for key in sorted(values)}


class ProductionReadinessManifestV1(StrictBaseModel):
    """Les 26 faits qui autorisent — ou non — un déploiement."""

    protocol_version: Literal["NEXUS-PRODUCTION-READINESS-V1"]

    # — Identité du dépôt et de la revue —
    repository: StrictStr = Field(pattern=_REPOSITORY)
    pr_number: StrictInt = Field(gt=0)
    pr_head_sha: StrictStr = Field(pattern=_GIT_SHA1)
    pr_head_tree_sha: StrictStr = Field(pattern=_GIT_SHA1)
    merge_sha: StrictStr = Field(pattern=_GIT_SHA1)
    merge_tree_sha: StrictStr = Field(pattern=_GIT_SHA1)
    release_tag: StrictStr = Field(min_length=1, max_length=128)
    environment: Literal["production"]

    # — Digests des preuves de gouvernance —
    review_binding_digest: StrictStr = Field(pattern=_HEX64)
    authorization_digest: StrictStr = Field(pattern=_HEX64)
    trust_anchor_digest: StrictStr = Field(pattern=_HEX64)
    revocation_registry_digest: StrictStr = Field(pattern=_HEX64)
    catalog_digest: StrictStr = Field(pattern=_HEX64)
    sealed_manifest_digest: StrictStr = Field(pattern=_HEX64)
    h2b_report_digest: StrictStr = Field(pattern=_HEX64)
    gate_result: Literal["pass"]

    # — Unité de déploiement, immuable par construction —
    application_image_digests: dict[str, str] = Field(min_length=1)
    upstream_image_digests: dict[str, str] = Field(min_length=1)
    compose_digest: StrictStr = Field(pattern=_HEX64)

    # — Provenance de l'émission —
    workflow_path: StrictStr = Field(pattern=_WORKFLOW_PATH)
    workflow_ref: StrictStr = Field(min_length=1, max_length=255)
    run_id: StrictInt = Field(gt=0)
    run_attempt: StrictInt = Field(gt=0)
    issued_at: AwareDatetime
    key_id: StrictStr = Field(pattern=_KEY_ID)

    @field_validator("application_image_digests", "upstream_image_digests")
    @classmethod
    def _image_digests_are_pinned(cls, values: dict[str, str]) -> dict[str, str]:
        """Chaque service nomme une image **par digest**.

        Un tag, même précis, désigne une cible mouvante : c'est
        exactement ce que ``rsync + docker build`` faisait, et ce que
        cette chaîne remplace."""
        for service, reference in values.items():
            if not isinstance(service, str) or re.fullmatch(_SERVICE_NAME, service) is None:
                raise ValueError(
                    f"service name {service!r} must match {_SERVICE_NAME}"
                )
            if not isinstance(reference, str) or re.fullmatch(_IMAGE_REF, reference) is None:
                raise ValueError(
                    f"image reference for {service!r} must be pinned as "
                    f"name@sha256:<64 hex> — a mutable tag is never a deployment unit"
                )
        return _canonical_digest_map(values)

    @field_validator("release_tag")
    @classmethod
    def _tag_is_canonical(cls, value: str) -> str:
        if _RELEASE_TAG.fullmatch(value) is None:
            raise ValueError(
                f"release_tag {value!r} must match release/rag/YYYYMMDD-<merge_sha12>"
            )
        return value

    @model_validator(mode="after")
    def _bindings_hold(self) -> ProductionReadinessManifestV1:
        # Le cœur du contrat : le code déployé est celui qui a été relu.
        if self.pr_head_tree_sha != self.merge_tree_sha:
            raise ValueError(
                "pr_head_tree_sha and merge_tree_sha differ — the merge commit "
                "does not carry the exact tree that was reviewed, so the human "
                "approval does not cover what would be deployed"
            )
        # Le tag doit désigner le commit qu'il prétend désigner.
        match = _RELEASE_TAG.fullmatch(self.release_tag)
        assert match is not None  # noqa: S101 - déjà garanti par le validateur
        if match.group(2) != self.merge_sha[:12]:
            raise ValueError(
                f"release_tag suffix {match.group(2)!r} does not match the first "
                f"12 characters of merge_sha ({self.merge_sha[:12]!r})"
            )
        if self.pr_head_sha == self.merge_sha:
            # Tolérable en fast-forward, mais alors les arbres coïncident
            # nécessairement ; rien à signaler. Aucun refus ici.
            pass
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "application_image_digests": _canonical_digest_map(
                self.application_image_digests
            ),
            "authorization_digest": self.authorization_digest,
            "catalog_digest": self.catalog_digest,
            "compose_digest": self.compose_digest,
            "environment": self.environment,
            "gate_result": self.gate_result,
            "h2b_report_digest": self.h2b_report_digest,
            "issued_at": _canonical_moment(self.issued_at),
            "key_id": self.key_id,
            "merge_sha": self.merge_sha,
            "merge_tree_sha": self.merge_tree_sha,
            "pr_head_sha": self.pr_head_sha,
            "pr_head_tree_sha": self.pr_head_tree_sha,
            "pr_number": self.pr_number,
            "protocol_version": self.protocol_version,
            "release_tag": self.release_tag,
            "repository": self.repository,
            "revocation_registry_digest": self.revocation_registry_digest,
            "review_binding_digest": self.review_binding_digest,
            "run_attempt": self.run_attempt,
            "run_id": self.run_id,
            "sealed_manifest_digest": self.sealed_manifest_digest,
            "trust_anchor_digest": self.trust_anchor_digest,
            "upstream_image_digests": _canonical_digest_map(self.upstream_image_digests),
            "workflow_path": self.workflow_path,
            "workflow_ref": self.workflow_ref,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


#: Version de protocole V2 (ADR-0044). Distincte de V1 : un manifeste V2
#: ne peut jamais être relu comme V1, et réciproquement.
PRODUCTION_READINESS_V2_PROTOCOL_VERSION = "NEXUS-PRODUCTION-READINESS-V2"


class ProductionReadinessManifestV2(StrictBaseModel):
    """`NEXUS-PRODUCTION-READINESS-V2` (ADR-0044) — remplace les deux
    digests parallèles ``authorization_digest``/``review_binding_digest``
    de V1 par une référence unique à un ``AuthorizationSetV1`` gouverné.

    **Pourquoi les deux champs, pas un seul.** PR#127 n'avait signalé que
    ``authorization_digest``. Mais ADR-0035 exige une revue humaine
    distincte *par autorisation* — N autorisations impliquent donc
    structurellement N reçus de revue, jamais un seul couvrant les N.
    ``review_binding_digest`` porte exactement le même problème que
    ``authorization_digest`` et doit changer avec lui.

    **Pourquoi un seul champ agrégé, pas deux listes parallèles.** Le
    détail par-membre (digest d'autorisation + digest de reçu de revue,
    par autorisation) vit déjà dans l'``AuthorizationSetV1`` lui-même —
    le référencer par un seul digest évite l'anti-pattern « N champs qui
    doivent rester synchronisés partout » (ADR-0044 §7).
    """

    protocol_version: Literal["NEXUS-PRODUCTION-READINESS-V2"]

    # — Identité du dépôt et de la revue — (inchangé depuis V1)
    repository: StrictStr = Field(pattern=_REPOSITORY)
    pr_number: StrictInt = Field(gt=0)
    pr_head_sha: StrictStr = Field(pattern=_GIT_SHA1)
    pr_head_tree_sha: StrictStr = Field(pattern=_GIT_SHA1)
    merge_sha: StrictStr = Field(pattern=_GIT_SHA1)
    merge_tree_sha: StrictStr = Field(pattern=_GIT_SHA1)
    release_tag: StrictStr = Field(min_length=1, max_length=128)
    environment: Literal["production"]

    # — Digests des preuves de gouvernance — (multi-scope, ADR-0044) —
    #: Référence l'``AuthorizationSetV1`` complet — remplace
    #: ``authorization_digest`` ET ``review_binding_digest`` de V1, tous
    #: deux structurellement incapables de nommer plus d'une autorisation.
    authorization_set_digest: StrictStr = Field(pattern=_HEX64)
    trust_anchor_digest: StrictStr = Field(pattern=_HEX64)
    revocation_registry_digest: StrictStr = Field(pattern=_HEX64)
    catalog_digest: StrictStr = Field(pattern=_HEX64)
    sealed_manifest_digest: StrictStr = Field(pattern=_HEX64)
    h2b_report_digest: StrictStr = Field(pattern=_HEX64)
    gate_result: Literal["pass"]

    # — Unité de déploiement, immuable par construction — (inchangé)
    application_image_digests: dict[str, str] = Field(min_length=1)
    upstream_image_digests: dict[str, str] = Field(min_length=1)
    compose_digest: StrictStr = Field(pattern=_HEX64)

    # — Provenance de l'émission — (inchangé)
    workflow_path: StrictStr = Field(pattern=_WORKFLOW_PATH)
    workflow_ref: StrictStr = Field(min_length=1, max_length=255)
    run_id: StrictInt = Field(gt=0)
    run_attempt: StrictInt = Field(gt=0)
    issued_at: AwareDatetime
    key_id: StrictStr = Field(pattern=_KEY_ID)

    @field_validator("application_image_digests", "upstream_image_digests")
    @classmethod
    def _image_digests_are_pinned(cls, values: dict[str, str]) -> dict[str, str]:
        return ProductionReadinessManifestV1._image_digests_are_pinned(values)

    @field_validator("release_tag")
    @classmethod
    def _tag_is_canonical(cls, value: str) -> str:
        return ProductionReadinessManifestV1._tag_is_canonical(value)

    @model_validator(mode="after")
    def _bindings_hold(self) -> ProductionReadinessManifestV2:
        if self.pr_head_tree_sha != self.merge_tree_sha:
            raise ValueError(
                "pr_head_tree_sha and merge_tree_sha differ — the merge commit "
                "does not carry the exact tree that was reviewed, so the human "
                "approval does not cover what would be deployed"
            )
        match = _RELEASE_TAG.fullmatch(self.release_tag)
        assert match is not None  # noqa: S101 - déjà garanti par le validateur
        if match.group(2) != self.merge_sha[:12]:
            raise ValueError(
                f"release_tag suffix {match.group(2)!r} does not match the first "
                f"12 characters of merge_sha ({self.merge_sha[:12]!r})"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "application_image_digests": _canonical_digest_map(
                self.application_image_digests
            ),
            "authorization_set_digest": self.authorization_set_digest,
            "catalog_digest": self.catalog_digest,
            "compose_digest": self.compose_digest,
            "environment": self.environment,
            "gate_result": self.gate_result,
            "h2b_report_digest": self.h2b_report_digest,
            "issued_at": _canonical_moment(self.issued_at),
            "key_id": self.key_id,
            "merge_sha": self.merge_sha,
            "merge_tree_sha": self.merge_tree_sha,
            "pr_head_sha": self.pr_head_sha,
            "pr_head_tree_sha": self.pr_head_tree_sha,
            "pr_number": self.pr_number,
            "protocol_version": self.protocol_version,
            "release_tag": self.release_tag,
            "repository": self.repository,
            "revocation_registry_digest": self.revocation_registry_digest,
            "run_attempt": self.run_attempt,
            "run_id": self.run_id,
            "sealed_manifest_digest": self.sealed_manifest_digest,
            "trust_anchor_digest": self.trust_anchor_digest,
            "upstream_image_digests": _canonical_digest_map(self.upstream_image_digests),
            "workflow_path": self.workflow_path,
            "workflow_ref": self.workflow_ref,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


class SignedProductionReadinessManifestV2(StrictBaseModel):
    """Le manifeste V2 tel qu'il est déposé sur l'hôte : faits + digest +
    signature — même structure que ``SignedProductionReadinessManifest``
    (V1), sur ``ProductionReadinessManifestV2``."""

    manifest: ProductionReadinessManifestV2
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    signature_algorithm: Literal["ed25519"]
    key_id: StrictStr = Field(pattern=_KEY_ID)
    signature: StrictStr = Field(pattern=_SIGNATURE_HEX)

    def canonical_document(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "manifest": self.manifest.canonical_document(),
            "manifest_digest": self.manifest_digest,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


def sign_production_readiness_manifest_v2(
    manifest: ProductionReadinessManifestV2,
    *,
    private_key_hex: str,
    key_id: str,
) -> SignedProductionReadinessManifestV2:
    """Même discipline que ``sign_production_readiness_manifest`` (V1)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not isinstance(manifest, ProductionReadinessManifestV2):
        raise TypeError("manifest must be a ProductionReadinessManifestV2")
    if not isinstance(private_key_hex, str) or re.fullmatch(
        _HEX_ED25519, private_key_hex.strip()
    ) is None:
        raise ProductionReadinessError(
            "the production readiness signing key must be 64 lowercase hex "
            "characters (an Ed25519 seed)"
        )
    if re.fullmatch(_KEY_ID, key_id) is None:
        raise ProductionReadinessError(f"key_id {key_id!r} must match {_KEY_ID}")
    if manifest.key_id != key_id:
        raise ProductionReadinessError(
            f"manifest declares key_id {manifest.key_id!r} but is being signed "
            f"with {key_id!r} — a manifest never names a signer other than its own"
        )

    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    payload = manifest.canonical_bytes()
    return SignedProductionReadinessManifestV2(
        manifest=manifest,
        manifest_digest=sha256(payload).hexdigest(),
        signature_algorithm="ed25519",
        key_id=key_id,
        signature=private_key.sign(payload).hex(),
    )


def parse_signed_production_readiness_manifest_v2(
    raw: bytes,
) -> SignedProductionReadinessManifestV2:
    """Même discipline que ``parse_signed_production_readiness_manifest``
    (V1) — parse strict et canonicité **octet à octet**."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionReadinessError(
            f"readiness manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProductionReadinessError("readiness manifest must be a JSON object")
    if document.get("manifest", {}).get("protocol_version") != (
        PRODUCTION_READINESS_V2_PROTOCOL_VERSION
    ):
        raise ProductionReadinessError(
            "readiness manifest protocol_version is not "
            f"{PRODUCTION_READINESS_V2_PROTOCOL_VERSION!r}"
        )
    try:
        parsed = SignedProductionReadinessManifestV2.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ProductionReadinessError(
            f"readiness manifest failed strict validation: {exc}"
        ) from exc
    if parsed.canonical_bytes() != raw:
        raise ProductionReadinessError(
            "readiness manifest bytes are not in canonical form — the signed "
            "bytes and their canonical re-serialization differ"
        )
    return parsed


def verify_production_readiness_manifest_v2(
    raw: bytes,
    *,
    trust_anchor: ProductionReadinessTrustAnchor,
    environment: str = PRODUCTION_ENVIRONMENT,
) -> ProductionReadinessManifestV2:
    """Même discipline que ``verify_production_readiness_manifest`` (V1)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(trust_anchor, ProductionReadinessTrustAnchor):
        raise TypeError(
            "trust_anchor must be a ProductionReadinessTrustAnchor — the review "
            "binding anchor is a different authority and is never accepted here"
        )
    signed = parse_signed_production_readiness_manifest_v2(raw)
    payload = signed.manifest.canonical_bytes()

    if signed.manifest_digest != sha256(payload).hexdigest():
        raise ProductionReadinessError(
            "manifest_digest does not match the canonical manifest bytes"
        )
    if signed.key_id != signed.manifest.key_id:
        raise ProductionReadinessError(
            "the signed envelope and the manifest name different key_id values"
        )

    key = trust_anchor.key(signed.key_id, environment=environment)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key)).verify(
            bytes.fromhex(signed.signature), payload
        )
    except InvalidSignature as exc:
        raise ProductionReadinessError(
            f"readiness manifest signature is invalid under key_id {signed.key_id!r}"
        ) from exc

    if signed.manifest.environment != environment:
        raise ProductionReadinessError(
            f"readiness manifest declares environment "
            f"{signed.manifest.environment!r} but is being verified for "
            f"{environment!r}"
        )
    if signed.manifest.gate_result != "pass":
        raise ProductionReadinessError(
            "readiness manifest carries a non-passing gate result"
        )
    return signed.manifest


class SignedProductionReadinessManifest(StrictBaseModel):
    """Le manifeste tel qu'il est déposé sur l'hôte : faits + digest + signature."""

    manifest: ProductionReadinessManifestV1
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    signature_algorithm: Literal["ed25519"]
    key_id: StrictStr = Field(pattern=_KEY_ID)
    signature: StrictStr = Field(pattern=_SIGNATURE_HEX)

    def canonical_document(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "manifest": self.manifest.canonical_document(),
            "manifest_digest": self.manifest_digest,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


class ProductionReadinessTrustAnchorKey(StrictBaseModel):
    key_id: StrictStr = Field(pattern=_KEY_ID)
    algorithm: Literal["ed25519"]
    public_key: StrictStr = Field(pattern=_HEX_ED25519)
    environment: Literal["production", "test"]
    comment: StrictStr = Field(default="", max_length=512)


class ProductionReadinessTrustAnchor(StrictBaseModel):
    """Ancre **distincte** de celle des reçus de liaison de revue.

    Son ``protocol_version`` lui est propre : une ancre de review binding
    ne peut donc pas être présentée ici, même par erreur de chemin."""

    protocol_version: Literal["NEXUS-PRODUCTION-READINESS-V1"]
    keys: tuple[ProductionReadinessTrustAnchorKey, ...] = Field(min_length=1)

    @field_validator("keys")
    @classmethod
    def _key_ids_are_unique(
        cls, values: tuple[ProductionReadinessTrustAnchorKey, ...]
    ) -> tuple[ProductionReadinessTrustAnchorKey, ...]:
        identifiers = [key.key_id for key in values]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("trust anchor key_id values must be unique")
        return values

    def key(self, key_id: str, *, environment: str) -> ProductionReadinessTrustAnchorKey:
        for candidate in self.keys:
            if candidate.key_id == key_id:
                if candidate.environment != environment:
                    raise ProductionReadinessError(
                        f"key_id {key_id!r} is declared for the "
                        f"{candidate.environment!r} environment and can never be "
                        f"accepted in {environment!r} mode"
                    )
                return candidate
        raise ProductionReadinessError(
            f"key_id {key_id!r} is not declared in the production readiness trust "
            "anchor — an unapproved signer proves nothing"
        )


def parse_production_readiness_trust_anchor(raw: bytes) -> ProductionReadinessTrustAnchor:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionReadinessError(
            f"production readiness trust anchor is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProductionReadinessError(
            "production readiness trust anchor must be a JSON object"
        )
    try:
        return ProductionReadinessTrustAnchor.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ProductionReadinessError(
            f"production readiness trust anchor failed strict validation: {exc}"
        ) from exc


def sign_production_readiness_manifest(
    manifest: ProductionReadinessManifestV1,
    *,
    private_key_hex: str,
    key_id: str,
) -> SignedProductionReadinessManifest:
    """Signe les octets canoniques du manifeste.

    ``private_key_hex`` vient de l'Environment ``production``, jamais d'un
    fichier du dépôt. Cette fonction ne le journalise ni ne le rend."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not isinstance(manifest, ProductionReadinessManifestV1):
        raise TypeError("manifest must be a ProductionReadinessManifestV1")
    if not isinstance(private_key_hex, str) or re.fullmatch(
        _HEX_ED25519, private_key_hex.strip()
    ) is None:
        # Le message ne cite jamais la valeur reçue.
        raise ProductionReadinessError(
            "the production readiness signing key must be 64 lowercase hex "
            "characters (an Ed25519 seed)"
        )
    if re.fullmatch(_KEY_ID, key_id) is None:
        raise ProductionReadinessError(f"key_id {key_id!r} must match {_KEY_ID}")
    if manifest.key_id != key_id:
        raise ProductionReadinessError(
            f"manifest declares key_id {manifest.key_id!r} but is being signed "
            f"with {key_id!r} — a manifest never names a signer other than its own"
        )

    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    payload = manifest.canonical_bytes()
    return SignedProductionReadinessManifest(
        manifest=manifest,
        manifest_digest=sha256(payload).hexdigest(),
        signature_algorithm="ed25519",
        key_id=key_id,
        signature=private_key.sign(payload).hex(),
    )


def public_readiness_key_hex(private_key_hex: str) -> str:
    """Clé publique d'une graine — sert à publier une ancre, jamais à signer."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    if not isinstance(private_key_hex, str) or re.fullmatch(
        _HEX_ED25519, private_key_hex.strip()
    ) is None:
        raise ProductionReadinessError(
            "the production readiness signing key must be 64 lowercase hex characters"
        )
    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    return private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    ).hex()


def parse_signed_production_readiness_manifest(
    raw: bytes,
) -> SignedProductionReadinessManifest:
    """Parse strict + canonicité **octet à octet**.

    Sans l'égalité octet à octet, deux fichiers différents pourraient
    porter la même signature logique — et le wrapper déploierait des
    octets que le vérificateur n'a pas vus."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionReadinessError(
            f"readiness manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProductionReadinessError("readiness manifest must be a JSON object")
    if document.get("manifest", {}).get("protocol_version") != (
        PRODUCTION_READINESS_PROTOCOL_VERSION
    ):
        raise ProductionReadinessError(
            "readiness manifest protocol_version is not "
            f"{PRODUCTION_READINESS_PROTOCOL_VERSION!r}"
        )
    try:
        parsed = SignedProductionReadinessManifest.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ProductionReadinessError(
            f"readiness manifest failed strict validation: {exc}"
        ) from exc
    if parsed.canonical_bytes() != raw:
        raise ProductionReadinessError(
            "readiness manifest bytes are not in canonical form — the signed "
            "bytes and their canonical re-serialization differ"
        )
    return parsed


def verify_production_readiness_manifest(
    raw: bytes,
    *,
    trust_anchor: ProductionReadinessTrustAnchor,
    environment: str = PRODUCTION_ENVIRONMENT,
) -> ProductionReadinessManifestV1:
    """Vérifie signature, ancre, environnement et verdict — hors ligne.

    Ordre délibéré : la signature d'abord. Un manifeste non vérifié n'a le
    droit de rien affirmer, pas même sur lui-même."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(trust_anchor, ProductionReadinessTrustAnchor):
        raise TypeError(
            "trust_anchor must be a ProductionReadinessTrustAnchor — the review "
            "binding anchor is a different authority and is never accepted here"
        )
    signed = parse_signed_production_readiness_manifest(raw)
    payload = signed.manifest.canonical_bytes()

    if signed.manifest_digest != sha256(payload).hexdigest():
        raise ProductionReadinessError(
            "manifest_digest does not match the canonical manifest bytes"
        )
    if signed.key_id != signed.manifest.key_id:
        raise ProductionReadinessError(
            "the signed envelope and the manifest name different key_id values"
        )

    key = trust_anchor.key(signed.key_id, environment=environment)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key)).verify(
            bytes.fromhex(signed.signature), payload
        )
    except InvalidSignature as exc:
        raise ProductionReadinessError(
            f"readiness manifest signature is invalid under key_id {signed.key_id!r}"
        ) from exc

    if signed.manifest.environment != environment:
        raise ProductionReadinessError(
            f"readiness manifest declares environment "
            f"{signed.manifest.environment!r} but is being verified for "
            f"{environment!r}"
        )
    if signed.manifest.gate_result != "pass":
        raise ProductionReadinessError(
            "readiness manifest carries a non-passing gate result"
        )
    return signed.manifest


def require_manifest_matches_release(
    manifest: ProductionReadinessManifestV1,
    *,
    release_sha: str,
    compose_digest: str | None = None,
) -> None:
    """Confronte le manifeste à ce qui est réellement sur le point de tourner.

    ``release_sha`` est le commit que le wrapper — ou le runtime — croit
    déployer. S'il diverge du merge SHA signé, la preuve ne porte pas sur
    cette révision."""
    if re.fullmatch(_GIT_SHA1, release_sha or "") is None:
        raise ProductionReadinessError(
            "release_sha must be a full 40-character Git SHA — a branch name is "
            "mutable and can never identify a release"
        )
    if manifest.merge_sha != release_sha:
        raise ProductionReadinessError(
            f"readiness manifest attests merge_sha {manifest.merge_sha!r} but the "
            f"release being deployed is {release_sha!r}"
        )
    if compose_digest is not None and manifest.compose_digest != compose_digest:
        raise ProductionReadinessError(
            "the resolved compose file does not match the digest signed in the "
            "readiness manifest"
        )


__all__ = [
    "PRODUCTION_ENVIRONMENT",
    "PRODUCTION_READINESS_PROTOCOL_VERSION",
    "PRODUCTION_READINESS_V2_PROTOCOL_VERSION",
    "ProductionReadinessError",
    "ProductionReadinessManifestV1",
    "ProductionReadinessManifestV2",
    "ProductionReadinessTrustAnchor",
    "ProductionReadinessTrustAnchorKey",
    "SignedProductionReadinessManifest",
    "SignedProductionReadinessManifestV2",
    "parse_production_readiness_trust_anchor",
    "parse_signed_production_readiness_manifest",
    "parse_signed_production_readiness_manifest_v2",
    "public_readiness_key_hex",
    "require_manifest_matches_release",
    "sign_production_readiness_manifest",
    "sign_production_readiness_manifest_v2",
    "verify_production_readiness_manifest",
    "verify_production_readiness_manifest_v2",
]
