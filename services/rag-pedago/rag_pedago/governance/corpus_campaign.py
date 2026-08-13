"""Descripteur de campagne de corpus — `NEXUS-CORPUS-CAMPAIGN-V1`.

**Le problème résolu ici.** Le gate H2-B/H2-F recevait ses huit preuves
sous forme de chemins choisis par l'opérateur : catalogue, manifeste,
droits, PII, routage, golden, autorisation, reçu. Chacun était donc
substituable au moment de l'exécution, et rien ne reliait ce que le gate
mesurait à ce qu'un humain avait relu dans une PR. Une chaîne de promotion
bâtie sur ces chemins n'aurait prouvé que la bonne volonté de l'opérateur.

Le descripteur ferme cet écart en déplaçant l'identité du corpus **dans
l'arbre Git approuvé**. Il ne contient pas les octets — plusieurs milliers
de PDF n'ont rien à faire dans l'historique — mais il nomme leur identité
cryptographique de trois manières indépendantes :

``source_oci_digest``
    le digest de l'objet OCI tel que le registre le renvoie ;
``source_archive_sha256``
    le SHA-256 des octets de l'archive canonique qu'il transporte ;
``source_tree_digest``
    le digest de l'arbre *après* extraction, régénéré par le producteur.

Les trois doivent concorder. Le premier prouve qu'on a tiré le bon objet,
le second que son contenu n'a pas changé en transit, le troisième que ce
qui a été matérialisé est bien ce qui a été scellé — un packer défaillant
ou une extraction créative ne peuvent pas passer.

**Ce que la revue humaine approuve réellement.** Personne ne relit des
PDF binaires. Ce qu'un relecteur approuve dans la PR, ce sont ces digests
et ``expected_manifest_sha256`` — l'identité exacte du corpus. Le
producteur, après fusion, régénère et exige l'égalité. Il ne peut donc
jamais introduire une identité de corpus que la revue n'a pas vue.

**Registre et propriétaire ne sont pas des paramètres.** Ils sont figés
dans ce module. Les rendre configurables reviendrait à laisser une
campagne désigner son propre registre de confiance — le défaut exact que
la gouvernance des ancres a déjà fermé ailleurs.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from nexus_contracts.document import StrictBaseModel
from nexus_contracts.ingestion import ResourceScope
from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

#: Version de protocole. Absente ou inconnue, le descripteur n'est pas parsé.
CORPUS_CAMPAIGN_PROTOCOL_VERSION = "NEXUS-CORPUS-CAMPAIGN-V1"

#: Protocole de la source OCI, distinct : il pourra évoluer sans changer
#: la structure de la campagne.
CORPUS_SOURCE_OCI_PROTOCOL_VERSION = "NEXUS-CORPUS-SOURCE-OCI-V1"

#: Registre et dépôt **gouvernés**, non substituables. Un champ libre ici
#: laisserait une campagne désigner son propre registre de confiance.
CANONICAL_CORPUS_REGISTRY = "ghcr.io"
CANONICAL_CORPUS_REPOSITORY = "cyranoaladin/rag-corpus"

#: Seul format d'archive accepté. Le packer le produit de façon
#: déterministe (cf. ``sealed_corpus.py``).
CANONICAL_ARCHIVE_FORMAT = "tar.zst"

#: Racine canonique des campagnes, versionnée dans Git.
CAMPAIGNS_DIR = "governance/corpus-campaigns"

#: Répertoire canonique des autorisations de scope (ADR-0032/0034).
AUTHORIZATIONS_DIR = "governance/authorizations"

#: Nom canonique du manifeste scellé, à l'intérieur d'une campagne comme
#: dans le corpus lui-même.
SEALED_MANIFEST_NAME = "SHA256SUMS.txt"

#: Chemin du self-object, tel que le gate l'attend dans le catalogue.
MANIFEST_SELF_PATH = "00_ADMIN/SHA256SUMS.txt"

_HEX64 = r"^[0-9a-f]{64}$"
_OCI_DIGEST = r"^sha256:[0-9a-f]{64}$"
_CAMPAIGN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_AUTHORIZATION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SOURCE_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")

_CANONICAL_INDENT = 2


class CorpusCampaignError(ValueError):
    """Le descripteur ne décrit pas une identité de corpus vérifiable —
    refus explicite, jamais une valeur devinée."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _plain(value: Any) -> str:
    """Valeur scalaire canonique d'un champ de scope.

    ``ResourceScope`` mélange des Enum (``niveau``, ``voie``, ``candidat``,
    ``audience``) et des chaînes ou ``Literal`` (``visibility``, ``tenant``…).
    Cette fonction unifie les deux sans supposer lequel est lequel — une
    hypothèse qui casserait silencieusement si le contrat évoluait.
    """
    return value.value if hasattr(value, "value") else str(value)


class CorpusCampaignV1(StrictBaseModel):
    """Identité approuvée d'un corpus, versionnée dans la PR."""

    protocol_version: Literal["NEXUS-CORPUS-CAMPAIGN-V1"]
    campaign_id: StrictStr = Field(min_length=1, max_length=64)

    #: Scope gouverné complet — le modèle canonique, jamais une
    #: représentation parallèle qui divergerait des dix dimensions.
    scope: ResourceScope

    # — Identité immuable des octets —
    source_kind: Literal["ghcr-oci"]
    source_registry: Literal["ghcr.io"]
    source_repository: Literal["cyranoaladin/rag-corpus"]
    source_oci_digest: StrictStr = Field(pattern=_OCI_DIGEST)

    #: SHA-256 du **tar canonique non compressé**, jamais du blob
    #: transporté. La compression zstd n'est pas déterministe d'une
    #: version ou d'un niveau à l'autre : hacher le blob compressé ferait
    #: dépendre l'identité du corpus de la build du compresseur, et une
    #: campagne approuvée cesserait de se vérifier après une mise à jour
    #: de zstd. ``archive_format`` décrit l'encodage de transport ; le
    #: résolveur décompresse, puis vérifie ce digest.
    source_archive_sha256: StrictStr = Field(pattern=_HEX64)

    source_tree_digest: StrictStr = Field(pattern=_HEX64)
    archive_format: Literal["tar.zst"]
    source_root: StrictStr = Field(min_length=1, max_length=255)

    # — Identité attendue des preuves dérivées —
    expected_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    expected_catalog_digest: StrictStr = Field(pattern=_HEX64)

    # — Autorité et règles de compilation —
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    compiler_version: StrictStr = Field(min_length=1, max_length=64)
    routing_config_digest: StrictStr = Field(pattern=_HEX64)
    rights_config_digest: StrictStr = Field(pattern=_HEX64)
    pii_config_digest: StrictStr = Field(pattern=_HEX64)
    golden_spec_digest: StrictStr = Field(pattern=_HEX64)

    environment: Literal["production", "rehearsal"]
    retention_days: StrictInt = Field(ge=1, le=400)

    @field_validator("campaign_id")
    @classmethod
    def _campaign_id_is_canonical(cls, value: str) -> str:
        if _CAMPAIGN_ID.fullmatch(value) is None:
            raise ValueError(
                f"campaign_id {value!r} must match {_CAMPAIGN_ID.pattern} — the "
                "identifier becomes a directory name and must never carry a path "
                "separator, an uppercase letter or a traversal segment"
            )
        return value

    @field_validator("authorization_id")
    @classmethod
    def _authorization_id_is_canonical(cls, value: str) -> str:
        if _AUTHORIZATION_ID.fullmatch(value) is None:
            raise ValueError(
                f"authorization_id {value!r} must match {_AUTHORIZATION_ID.pattern}"
            )
        return value

    @field_validator("source_root")
    @classmethod
    def _source_root_is_confined(cls, value: str) -> str:
        """La racine du corpus dans l'archive : relative, sans évasion.

        Un ``..`` ou un chemin absolu ici sortirait du répertoire
        d'extraction avant même que le résolveur ne regarde les entrées de
        l'archive."""
        if value.startswith("/") or ".." in Path(value).parts:
            raise ValueError(
                f"source_root {value!r} must be a relative path without '..'"
            )
        if _SOURCE_ROOT.fullmatch(value) is None:
            raise ValueError(f"source_root {value!r} must match {_SOURCE_ROOT.pattern}")
        return value

    @model_validator(mode="after")
    def _identities_are_distinct(self) -> CorpusCampaignV1:
        """Défense en profondeur — **pas** la preuve d'indépendance.

        L'inégalité de trois chaînes ne prouve rien sur le plan
        cryptographique : trois valeurs distinctes peuvent parfaitement
        provenir du même calcul. La propriété de sécurité réelle est
        ailleurs, et elle est portée par ``corpus_source_resolver`` :

        * chaque digest a un **domaine** propre — descripteur OCI, octets
          du tar canonique, arbre matérialisé — et ces domaines ne se
          recouvrent pas ;
        * chacun est **recalculé depuis son propre objet**, jamais recopié
          d'un autre champ ;
        * les **trois** comparaisons sont obligatoires, dans cet ordre, et
          une seule qui manque est un refus.

        Ce validateur ne fait qu'attraper tôt le cas dégénéré où un auteur
        de campagne aurait recopié une valeur dans deux champs. Le prendre
        pour la garantie principale serait exactement l'erreur que ce
        commentaire existe pour empêcher."""
        oci_hex = self.source_oci_digest.split(":", 1)[1]
        if len({oci_hex, self.source_archive_sha256, self.source_tree_digest}) != 3:
            raise ValueError(
                "source_oci_digest, source_archive_sha256 and source_tree_digest "
                "must be three distinct values — three digests over three "
                "different domains never coincide in practice, so equality here "
                "means a value was copied from one field into another. This is a "
                "cheap early check, not the independence proof: that proof is the "
                "three mandatory recomputations performed by the resolver."
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "archive_format": self.archive_format,
            "authorization_id": self.authorization_id,
            "campaign_id": self.campaign_id,
            "compiler_version": self.compiler_version,
            "environment": self.environment,
            "expected_catalog_digest": self.expected_catalog_digest,
            "expected_manifest_sha256": self.expected_manifest_sha256,
            "golden_spec_digest": self.golden_spec_digest,
            "pii_config_digest": self.pii_config_digest,
            "protocol_version": self.protocol_version,
            "retention_days": self.retention_days,
            "rights_config_digest": self.rights_config_digest,
            "routing_config_digest": self.routing_config_digest,
            "scope": {
                "audience": sorted(_plain(a) for a in self.scope.audience),
                "candidat": _plain(self.scope.candidat),
                "collection": _plain(self.scope.collection),
                "matiere": _plain(self.scope.matiere),
                "niveau": _plain(self.scope.niveau),
                "programme_version": _plain(self.scope.programme_version),
                "school_year": _plain(self.scope.school_year),
                "tenant": _plain(self.scope.tenant),
                "visibility": _plain(self.scope.visibility),
                "voie": _plain(self.scope.voie),
            },
            "source_archive_sha256": self.source_archive_sha256,
            "source_kind": self.source_kind,
            "source_oci_digest": self.source_oci_digest,
            "source_registry": self.source_registry,
            "source_repository": self.source_repository,
            "source_root": self.source_root,
            "source_tree_digest": self.source_tree_digest,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    def canonical_dir(self) -> str:
        return f"{CAMPAIGNS_DIR}/{self.campaign_id}"

    def canonical_path(self) -> str:
        return f"{self.canonical_dir()}/campaign.json"

    def sealed_manifest_path(self) -> str:
        return f"{self.canonical_dir()}/{SEALED_MANIFEST_NAME}"

    def catalog_digest_path(self) -> str:
        return f"{self.canonical_dir()}/catalog.digest.json"

    def review_view_path(self) -> str:
        return f"{self.canonical_dir()}/review-view.json"

    def authorization_path(self) -> str:
        return f"{AUTHORIZATIONS_DIR}/{self.authorization_id}.json"

    def oci_reference(self) -> str:
        """Référence complète, **toujours par digest**.

        Aucune surcharge par tag n'est représentable : le champ tag
        n'existe pas dans ce modèle."""
        return (
            f"{self.source_registry}/{self.source_repository}@{self.source_oci_digest}"
        )


def parse_corpus_campaign(raw: bytes) -> CorpusCampaignV1:
    """Parse strict + exigence de canonicité **octet à octet**.

    L'égalité octet à octet est ce qui rend la revue humaine utile : le
    fichier que le relecteur voit dans le diff est exactement celui dont
    le digest est calculé. Sans elle, deux fichiers différents pourraient
    porter la même campagne logique."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CorpusCampaignError(
            f"campaign descriptor is not valid UTF-8: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CorpusCampaignError(
            f"campaign descriptor is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise CorpusCampaignError("campaign descriptor must be a JSON object")
    if document.get("protocol_version") != CORPUS_CAMPAIGN_PROTOCOL_VERSION:
        raise CorpusCampaignError(
            f"campaign protocol_version is not {CORPUS_CAMPAIGN_PROTOCOL_VERSION!r}"
        )
    try:
        parsed = CorpusCampaignV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise CorpusCampaignError(
            f"campaign descriptor failed strict validation: {exc}"
        ) from exc
    if parsed.canonical_bytes() != raw:
        raise CorpusCampaignError(
            "campaign descriptor bytes are not in canonical form — the reviewed "
            "bytes and their canonical re-serialization differ, so the human "
            "review cannot be bound to this content. Commit the canonical form."
        )
    return parsed


def discover_promoted_campaign(changed_paths: list[str]) -> str:
    """Détermine l'unique campagne promue par un ensemble de chemins modifiés.

    L'opérateur ne fournit jamais ``campaign_id`` : il est **dérivé** du
    diff entre la base et le head de PR. Zéro campagne ne promeut rien ;
    plus d'une est une ambiguïté, et choisir « la première » ou « la plus
    récente » reviendrait à laisser le hasard décider de ce qui part en
    production.
    """
    campaigns: set[str] = set()
    prefix = f"{CAMPAIGNS_DIR}/"
    for raw in changed_paths:
        path = raw.strip()
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        segments = remainder.split("/")
        if len(segments) < 2 or not segments[0]:
            raise CorpusCampaignError(
                f"changed path {path!r} sits directly under {CAMPAIGNS_DIR} without "
                "naming a campaign directory"
            )
        campaigns.add(segments[0])

    if not campaigns:
        raise CorpusCampaignError(
            f"no campaign under {CAMPAIGNS_DIR} was modified — a promotion always "
            "carries the corpus identity it promotes"
        )
    if len(campaigns) > 1:
        raise CorpusCampaignError(
            f"{len(campaigns)} campaigns were modified ({sorted(campaigns)!r}) — "
            "exactly one campaign is promoted at a time, and picking one of them "
            "automatically would let chance decide what reaches production"
        )
    (campaign_id,) = campaigns
    if _CAMPAIGN_ID.fullmatch(campaign_id) is None:
        raise CorpusCampaignError(
            f"discovered campaign_id {campaign_id!r} is not canonical"
        )
    return campaign_id


__all__ = [
    "AUTHORIZATIONS_DIR",
    "CAMPAIGNS_DIR",
    "CANONICAL_ARCHIVE_FORMAT",
    "CANONICAL_CORPUS_REGISTRY",
    "CANONICAL_CORPUS_REPOSITORY",
    "CORPUS_CAMPAIGN_PROTOCOL_VERSION",
    "CORPUS_SOURCE_OCI_PROTOCOL_VERSION",
    "MANIFEST_SELF_PATH",
    "SEALED_MANIFEST_NAME",
    "CorpusCampaignError",
    "CorpusCampaignV1",
    "discover_promoted_campaign",
    "parse_corpus_campaign",
]
