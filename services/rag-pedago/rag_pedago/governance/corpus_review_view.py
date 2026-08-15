"""Vue de revue humaine — ``NEXUS-CORPUS-REVIEW-VIEW-V1``.

**Une aide à la décision, pas une autorité.** C'est la propriété la plus
importante de ce module, et celle qu'un lecteur pressé confondra le plus
facilement. Un humain ne peut pas relire 2 451 PDF ; il relit un diff. Mais
ce qu'il approuve n'est jamais le diff — c'est le couple de digests que la
campagne épingle. Si la vue et les digests divergeaient, ce sont les
digests qui font foi et la campagne qui doit être refusée.

Le champ ``authoritative`` vaut donc ``False`` et est sérialisé, pas
seulement documenté : un consommateur lit le JSON, pas cette docstring.
Rien dans le gate H2 ne doit accepter cette vue comme preuve.

**Déterminisme.** Deux exécutions sur les mêmes catalogues doivent produire
les mêmes octets. Sans cela, la vue ne peut pas entrer dans le bundle H2 —
son digest cesserait d'identifier un contenu pour identifier une
exécution. Tout ce qui varie (horloge, ordre de dictionnaire, chemin de
travail) est donc exclu du contenu canonique. L'horodatage vit dans une
enveloppe séparée, jamais dans les octets hachés.

**Ce que la vue doit rendre visible.** Un diff qui ne montre que les
ajouts et les suppressions cache précisément les changements dangereux :
un fichier remplacé au même chemin, une disposition qui passe de
``QUARANTINE`` à ``INGEST``, un scope élargi, une catégorie de droits
assouplie. Ces transitions-là changent ce qui sera publié sans changer le
nombre d'objets, et c'est pourquoi elles sont comptées séparément.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from rag_pedago.imports.artifact_placement_model import (
    Disposition,
    SealedCorpusCatalog,
)

#: Identifiant de protocole. Versionné : une évolution du contenu de la
#: vue doit changer ce nom, sinon deux formats partageraient une identité.
REVIEW_VIEW_PROTOCOL = "NEXUS-CORPUS-REVIEW-VIEW-V1"

#: Zones de preuve. Leur contenu documente le corpus ; il ne l'enseigne
#: pas. Les transformer en chunks de retrieval ferait remonter des sommes
#: de contrôle dans les réponses aux élèves.
EVIDENCE_ONLY_ZONES = ("00_ADMIN", "00_INDEX_PROVENANCE")

#: Extensions sans extracteur gouverné à ce jour. Listées explicitement :
#: un format non supporté doit être *compté*, jamais disparaître.
UNSUPPORTED_EXTENSIONS = (".ggb",)

#: Statuts de diagnostic qui interdisent la publication. Un brouillon qui
#: se publie est pire qu'un brouillon absent.
DRAFT_STATUSES = ("DRAFT", "BROUILLON", "WIP", "UNVALIDATED", "NON_VALIDE")


class ReviewViewError(ValueError):
    """La vue ne peut pas être construite de façon fiable — refus.

    Une vue partielle serait pire qu'aucune vue : elle donnerait à un
    relecteur l'impression d'avoir tout vu."""


@dataclass(frozen=True)
class PathChange:
    """Un objet ajouté ou supprimé, identifié par chemin *et* contenu."""

    path: str
    content_sha256: str
    zone: str
    disposition: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "content_sha256": self.content_sha256,
            "zone": self.zone,
            "disposition": self.disposition,
        }


@dataclass(frozen=True)
class ContentReplacement:
    """Même chemin, octets différents.

    Le cas le plus dangereux du diff : la liste des chemins est identique,
    donc un compteur d'objets ne bouge pas, mais ce qui sera ingéré a
    changé."""

    path: str
    previous_sha256: str
    current_sha256: str
    zone: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "previous_sha256": self.previous_sha256,
            "current_sha256": self.current_sha256,
            "zone": self.zone,
        }


@dataclass(frozen=True)
class PathMove:
    """Mêmes octets, chemin différent.

    Distingué d'un ajout + une suppression : un déplacement ne change pas
    le contenu ingéré, mais il change la zone — donc potentiellement la
    disposition et les droits."""

    content_sha256: str
    previous_path: str
    current_path: str
    previous_zone: str
    current_zone: str

    def to_dict(self) -> dict[str, str]:
        return {
            "content_sha256": self.content_sha256,
            "previous_path": self.previous_path,
            "current_path": self.current_path,
            "previous_zone": self.previous_zone,
            "current_zone": self.current_zone,
        }


@dataclass(frozen=True)
class AttributeChange:
    """Une transition d'attribut gouverné sur un objet inchangé.

    ``escalation`` marque les transitions qui *élargissent* ce qui sera
    publié. C'est le seul champ que le relecteur doit lire en priorité :
    une campagne qui n'en contient aucune ne peut rien publier de plus
    qu'avant."""

    subject: str  # chemin, ou content_sha256 pour un attribut de contenu
    attribute: str
    previous: str
    current: str
    escalation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "attribute": self.attribute,
            "previous": self.previous,
            "current": self.current,
            "escalation": self.escalation,
        }


@dataclass(frozen=True)
class Anomaly:
    """Un constat qui doit bloquer ou au moins interrompre la revue."""

    code: str
    subject: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass
class ReviewView:
    """Diff gouverné entre deux catalogues scellés."""

    campaign_id: str
    source_oci_digest: str
    source_tree_digest: str
    manifest_sha256: str
    catalog_sha256: str
    baseline_manifest_sha256: str | None

    added: list[PathChange] = field(default_factory=list)
    removed: list[PathChange] = field(default_factory=list)
    replaced: list[ContentReplacement] = field(default_factory=list)
    moved: list[PathMove] = field(default_factory=list)
    attribute_changes: list[AttributeChange] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)

    counts: dict[str, int] = field(default_factory=dict)
    dispositions: dict[str, int] = field(default_factory=dict)
    zones: dict[str, int] = field(default_factory=dict)
    uncovered_scopes: list[str] = field(default_factory=list)

    @property
    def escalations(self) -> list[AttributeChange]:
        """Les seules transitions capables d'élargir la publication."""
        return [change for change in self.attribute_changes if change.escalation]

    @property
    def is_first_campaign(self) -> bool:
        return self.baseline_manifest_sha256 is None

    def to_canonical_dict(self) -> dict[str, Any]:
        """Contenu canonique — aucune valeur volatile.

        ``authoritative`` est sérialisé pour que le refus de faire foi
        voyage avec la donnée."""
        return {
            "protocol": REVIEW_VIEW_PROTOCOL,
            "authoritative": False,
            "campaign_id": self.campaign_id,
            "source_oci_digest": self.source_oci_digest,
            "source_tree_digest": self.source_tree_digest,
            "manifest_sha256": self.manifest_sha256,
            "catalog_sha256": self.catalog_sha256,
            "baseline_manifest_sha256": self.baseline_manifest_sha256,
            "is_first_campaign": self.is_first_campaign,
            "added": [item.to_dict() for item in self.added],
            "removed": [item.to_dict() for item in self.removed],
            "replaced": [item.to_dict() for item in self.replaced],
            "moved": [item.to_dict() for item in self.moved],
            "attribute_changes": [item.to_dict() for item in self.attribute_changes],
            "escalation_count": len(self.escalations),
            "anomalies": [item.to_dict() for item in self.anomalies],
            "counts": dict(sorted(self.counts.items())),
            "dispositions": dict(sorted(self.dispositions.items())),
            "zones": dict(sorted(self.zones.items())),
            "uncovered_scopes": sorted(self.uncovered_scopes),
        }

    def to_canonical_json(self) -> bytes:
        """Octets canoniques : clés triées, indentation fixe, LF final."""
        payload = json.dumps(
            self.to_canonical_dict(), ensure_ascii=False, sort_keys=True, indent=2
        )
        return (payload + "\n").encode("utf-8")

    @property
    def view_sha256(self) -> str:
        return hashlib.sha256(self.to_canonical_json()).hexdigest()


def _zone_of(path: str) -> str:
    head, _, _ = path.partition("/")
    return head


def _is_evidence_only(path: str) -> bool:
    return _zone_of(path) in EVIDENCE_ONLY_ZONES


def _plain(value: Any) -> str:
    """Rend une valeur comparable, qu'elle soit ``StrEnum`` ou ``str``.

    Le modèle mélange les deux ; comparer un Enum à une chaîne renverrait
    silencieusement ``False`` et masquerait une transition."""
    if value is None:
        return ""
    return getattr(value, "value", value)


def _index_physical(catalog: SealedCorpusCatalog) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for item in catalog.physical_objects:
        if item.path in index:
            raise ReviewViewError(
                f"catalog declares {item.path!r} twice — a diff over an ambiguous "
                "catalog would silently show only one of the two"
            )
        index[item.path] = item
    return index


def _paths_by_content(index: Mapping[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for path, item in index.items():
        grouped.setdefault(item.content_sha256, []).append(path)
    for paths in grouped.values():
        paths.sort()
    return grouped


#: Ordre de sévérité décroissante. Une transition vers une disposition
#: *moins* bloquante est une escalade : elle publie ce qui était retenu.
_DISPOSITION_SEVERITY = {
    Disposition.EXCLUDE.value: 0,
    Disposition.QUARANTINE.value: 1,
    Disposition.UNSUPPORTED.value: 2,
    Disposition.ARCHIVE_ONLY.value: 3,
    Disposition.REVIEW_REQUIRED.value: 4,
    Disposition.INGEST.value: 5,
}


def _is_disposition_escalation(previous: str, current: str) -> bool:
    before = _DISPOSITION_SEVERITY.get(previous)
    after = _DISPOSITION_SEVERITY.get(current)
    if before is None or after is None:
        # Une disposition inconnue est traitée comme une escalade : on ne
        # peut pas prouver qu'elle restreint.
        return True
    return after > before


def _diff_attributes(
    path: str, previous: Any, current: Any
) -> list[AttributeChange]:
    """Transitions d'attributs gouvernés sur un chemin présent des deux côtés."""
    changes: list[AttributeChange] = []

    before = _plain(previous.disposition)
    after = _plain(current.disposition)
    if before != after:
        changes.append(
            AttributeChange(
                subject=path,
                attribute="disposition",
                previous=before,
                current=after,
                escalation=_is_disposition_escalation(before, after),
            )
        )

    for attribute in ("zone", "currentness", "rights_category_candidate",
                      "provenance_status"):
        before = _plain(getattr(previous, attribute, None))
        after = _plain(getattr(current, attribute, None))
        if before != after:
            changes.append(
                AttributeChange(
                    subject=path,
                    attribute=attribute,
                    previous=before,
                    current=after,
                    # Toute évolution de droits ou de provenance élargit
                    # potentiellement la publication : on ne prétend pas
                    # savoir laquelle restreint.
                    escalation=attribute in ("rights_category_candidate",
                                             "provenance_status"),
                )
            )
    return changes


#: Attributs de placement dont un changement modifie l'audience atteinte.
_PLACEMENT_ATTRIBUTES = ("scope", "family", "subject", "level", "status", "year")


def _diff_placements(
    baseline: SealedCorpusCatalog | None, current: SealedCorpusCatalog
) -> list[AttributeChange]:
    """Transitions d'audience, clé par contenu.

    Les placements sont attachés au contenu, pas au chemin : c'est ce qui
    permet aux 2 956 affectations logiques de partager 2 451 objets
    physiques. Le diff suit donc la même clé."""
    if baseline is None:
        return []

    def by_key(catalog: SealedCorpusCatalog) -> dict[tuple[str, str], Any]:
        mapping: dict[tuple[str, str], Any] = {}
        for artifact in catalog.artifacts.values():
            for placement in artifact.pedagogical_placements:
                # ``scope_path`` désambiguïse deux placements du même
                # contenu vers deux audiences distinctes. Peut être
                # ``None`` pour un placement dérivé du schéma technique
                # réel (aucune notion de portée pédagogique dans ce
                # schéma) -- normalisé comme le reste du fichier via
                # ``_plain`` plutôt que de fuiter ``str | None`` dans une
                # clé typée ``tuple[str, str]``.
                mapping[(placement.content_sha256, _plain(placement.scope_path))] = placement
        return mapping

    previous_map = by_key(baseline)
    current_map = by_key(current)

    changes: list[AttributeChange] = []
    for key in sorted(set(previous_map) & set(current_map)):
        previous, current_placement = previous_map[key], current_map[key]
        for attribute in _PLACEMENT_ATTRIBUTES:
            before = _plain(getattr(previous, attribute, ""))
            after = _plain(getattr(current_placement, attribute, ""))
            if before != after:
                changes.append(
                    AttributeChange(
                        subject=f"{key[0]}@{key[1]}",
                        attribute=f"placement.{attribute}",
                        previous=before,
                        current=after,
                        # Changer de niveau ou de scope déplace le contenu
                        # vers une autre audience : toujours à relire.
                        escalation=attribute in ("scope", "level", "family"),
                    )
                )

    for key in sorted(set(current_map) - set(previous_map)):
        placement = current_map[key]
        changes.append(
            AttributeChange(
                subject=f"{key[0]}@{key[1]}",
                attribute="placement.added",
                previous="",
                current=_plain(placement.scope),
                escalation=True,
            )
        )
    for key in sorted(set(previous_map) - set(current_map)):
        placement = previous_map[key]
        changes.append(
            AttributeChange(
                subject=f"{key[0]}@{key[1]}",
                attribute="placement.removed",
                previous=_plain(placement.scope),
                current="",
                escalation=False,
            )
        )
    return changes


def _collect_anomalies(
    catalog: SealedCorpusCatalog, *, authorized_scopes: frozenset[str] | None
) -> tuple[list[Anomaly], list[str]]:
    """Constats qui doivent interrompre la revue, et scopes non couverts."""
    anomalies: list[Anomaly] = []
    uncovered: set[str] = set()

    for item in sorted(catalog.physical_objects, key=lambda o: o.path):
        disposition = _plain(item.disposition)
        path = item.path

        if _is_evidence_only(path) and disposition == Disposition.INGEST.value:
            anomalies.append(
                Anomaly(
                    code="EVIDENCE_ZONE_MARKED_FOR_INGEST",
                    subject=path,
                    detail=(
                        "an evidence zone documents the corpus; ingesting it would "
                        "surface checksums as pedagogical content"
                    ),
                )
            )

        if path.lower().endswith(UNSUPPORTED_EXTENSIONS):
            if disposition == Disposition.INGEST.value:
                anomalies.append(
                    Anomaly(
                        code="UNSUPPORTED_FORMAT_MARKED_FOR_INGEST",
                        subject=path,
                        detail=(
                            "GeoGebra archives are binary; no governed extractor "
                            "exists, so ingesting would index container bytes"
                        ),
                    )
                )

        if disposition == Disposition.INGEST.value and not item.rights_category_candidate:
            anomalies.append(
                Anomaly(
                    code="INGEST_WITHOUT_RIGHTS_CATEGORY",
                    subject=path,
                    detail="no rights category was resolved for an ingested object",
                )
            )

        if _plain(item.provenance_status) not in ("VERIFIED", ""):
            anomalies.append(
                Anomaly(
                    code="UNVERIFIED_PROVENANCE",
                    subject=path,
                    detail=f"provenance status is {_plain(item.provenance_status)!r}",
                )
            )

    for sha in sorted(catalog.artifacts):
        artifact = catalog.artifacts[sha]
        for placement in sorted(
            artifact.pedagogical_placements, key=lambda p: _plain(p.scope_path)
        ):
            status = _plain(placement.status).upper()
            if any(marker in status for marker in DRAFT_STATUSES):
                anomalies.append(
                    Anomaly(
                        code="DRAFT_PLACEMENT_PUBLISHED",
                        subject=f"{sha}@{placement.scope_path}",
                        detail=f"placement status is {status!r}",
                    )
                )
            scope = _plain(placement.scope)
            if authorized_scopes is not None and scope and scope not in authorized_scopes:
                uncovered.add(scope)

        if not artifact.physical_objects:
            anomalies.append(
                Anomaly(
                    code="PLACEMENT_WITHOUT_PHYSICAL_OBJECT",
                    subject=sha,
                    detail=(
                        "a logical assignment points at content that is absent from "
                        "the sealed manifest"
                    ),
                )
            )

    return anomalies, sorted(uncovered)


def build_review_view(
    *,
    campaign_id: str,
    source_oci_digest: str,
    source_tree_digest: str,
    manifest_sha256: str,
    catalog_sha256: str,
    current: SealedCorpusCatalog,
    baseline: SealedCorpusCatalog | None = None,
    authorized_scopes: Iterable[str] | None = None,
) -> ReviewView:
    """Construit la vue de revue entre ``baseline`` et ``current``.

    ``baseline`` vaut ``None`` pour la première campagne : tout est alors
    un ajout, et la vue le dit explicitement plutôt que de présenter un
    diff vide qui se lirait comme « rien n'a changé »."""
    if not campaign_id:
        raise ReviewViewError("campaign_id is required to identify what is reviewed")

    current_index = _index_physical(current)
    baseline_index = _index_physical(baseline) if baseline is not None else {}

    current_paths = set(current_index)
    baseline_paths = set(baseline_index)

    added_paths = current_paths - baseline_paths
    removed_paths = baseline_paths - current_paths

    # Déplacements d'abord : ils consomment un ajout et une suppression
    # qui, pris isolément, se liraient comme un changement de contenu.
    current_by_content = _paths_by_content(current_index)
    baseline_by_content = _paths_by_content(baseline_index)

    moved: list[PathMove] = []
    for sha in sorted(set(current_by_content) & set(baseline_by_content)):
        gone = [p for p in baseline_by_content[sha] if p in removed_paths]
        arrived = [p for p in current_by_content[sha] if p in added_paths]
        for previous_path, current_path in zip(gone, arrived, strict=False):
            moved.append(
                PathMove(
                    content_sha256=sha,
                    previous_path=previous_path,
                    current_path=current_path,
                    previous_zone=_zone_of(previous_path),
                    current_zone=_zone_of(current_path),
                )
            )
            removed_paths.discard(previous_path)
            added_paths.discard(current_path)

    added = [
        PathChange(
            path=path,
            content_sha256=current_index[path].content_sha256,
            zone=_zone_of(path),
            disposition=_plain(current_index[path].disposition),
        )
        for path in sorted(added_paths)
    ]
    removed = [
        PathChange(
            path=path,
            content_sha256=baseline_index[path].content_sha256,
            zone=_zone_of(path),
            disposition=_plain(baseline_index[path].disposition),
        )
        for path in sorted(removed_paths)
    ]

    replaced: list[ContentReplacement] = []
    attribute_changes: list[AttributeChange] = []
    for path in sorted(current_paths & baseline_paths):
        previous, current_item = baseline_index[path], current_index[path]
        if previous.content_sha256 != current_item.content_sha256:
            replaced.append(
                ContentReplacement(
                    path=path,
                    previous_sha256=previous.content_sha256,
                    current_sha256=current_item.content_sha256,
                    zone=_zone_of(path),
                )
            )
        attribute_changes.extend(_diff_attributes(path, previous, current_item))

    attribute_changes.extend(_diff_placements(baseline, current))
    attribute_changes.sort(key=lambda c: (c.subject, c.attribute))

    scopes = frozenset(authorized_scopes) if authorized_scopes is not None else None
    anomalies, uncovered = _collect_anomalies(current, authorized_scopes=scopes)

    # ``Counter`` et non ``set`` : deux objets partageant une disposition
    # doivent compter deux fois. Un ``set`` rendrait 6 quel que soit le
    # corpus.
    dispositions = Counter(
        _plain(item.disposition) for item in current.physical_objects
    )
    zones = Counter(_zone_of(item.path) for item in current.physical_objects)

    placement_total = sum(
        len(artifact.pedagogical_placements) for artifact in current.artifacts.values()
    )

    counts = {
        "physical_objects": len(current.physical_objects),
        "content_artifacts": len(current.artifacts),
        "logical_placements": placement_total,
        "added": len(added),
        "removed": len(removed),
        "replaced": len(replaced),
        "moved": len(moved),
        "attribute_changes": len(attribute_changes),
        "anomalies": len(anomalies),
        "unsupported_format_objects": sum(
            1
            for item in current.physical_objects
            if item.path.lower().endswith(UNSUPPORTED_EXTENSIONS)
        ),
        "evidence_only_objects": sum(
            1 for item in current.physical_objects if _is_evidence_only(item.path)
        ),
        "objects_without_rights_category": sum(
            1 for item in current.physical_objects if not item.rights_category_candidate
        ),
    }

    return ReviewView(
        campaign_id=campaign_id,
        source_oci_digest=source_oci_digest,
        source_tree_digest=source_tree_digest,
        manifest_sha256=manifest_sha256,
        catalog_sha256=catalog_sha256,
        baseline_manifest_sha256=(
            baseline.manifest_sha256 if baseline is not None else None
        ),
        added=added,
        removed=removed,
        replaced=replaced,
        moved=moved,
        attribute_changes=attribute_changes,
        anomalies=anomalies,
        counts=counts,
        dispositions=dict(dispositions),
        zones=dict(zones),
        uncovered_scopes=uncovered,
    )


def render_markdown(view: ReviewView) -> str:
    """Rendu lisible — déterministe, borné, et honnête sur son statut.

    Les listes sont tronquées : un diff de 2 451 lignes n'est pas relu, il
    est parcouru. Ce qui est tronqué est annoncé, jamais coupé en
    silence."""
    limit = 50
    lines: list[str] = [
        f"# Vue de revue — {view.campaign_id}",
        "",
        "> **Cette vue ne fait pas autorité.** Elle aide à relire ; elle ne",
        "> décide pas. L'objet approuvé est le couple de digests ci-dessous.",
        "",
        "## Source immuable",
        "",
        f"- Digest OCI : `{view.source_oci_digest}`",
        f"- Digest de l'arbre : `{view.source_tree_digest}`",
        f"- Manifeste scellé : `{view.manifest_sha256}`",
        f"- Catalogue : `{view.catalog_sha256}`",
        f"- Référence précédente : "
        f"`{view.baseline_manifest_sha256 or 'aucune (première campagne)'}`",
        "",
        "## Compteurs",
        "",
    ]
    for key in sorted(view.counts):
        lines.append(f"- {key} : {view.counts[key]}")

    lines += ["", "## Dispositions", ""]
    for key in sorted(view.dispositions):
        lines.append(f"- {key} : {view.dispositions[key]}")

    lines += ["", "## Zones", ""]
    for key in sorted(view.zones):
        lines.append(f"- {key} : {view.zones[key]}")

    def section(title: str, items: list[Any], render: Any) -> None:
        lines.extend(["", f"## {title} ({len(items)})", ""])
        if not items:
            lines.append("_aucun_")
            return
        for item in items[:limit]:
            lines.append(f"- {render(item)}")
        if len(items) > limit:
            lines.append(f"- … {len(items) - limit} de plus (tronqué à {limit})")

    section("Ajouts", view.added, lambda i: f"`{i.path}` → {i.disposition}")
    section("Suppressions", view.removed, lambda i: f"`{i.path}` ({i.disposition})")
    section(
        "Remplacements au même chemin",
        view.replaced,
        lambda i: f"`{i.path}` : {i.previous_sha256[:12]}… → {i.current_sha256[:12]}…",
    )
    section(
        "Déplacements",
        view.moved,
        lambda i: f"`{i.previous_path}` → `{i.current_path}`",
    )
    section(
        "Escalades (élargissent la publication)",
        view.escalations,
        lambda i: f"`{i.subject}` — {i.attribute} : {i.previous!r} → {i.current!r}",
    )
    section(
        "Autres transitions",
        [c for c in view.attribute_changes if not c.escalation],
        lambda i: f"`{i.subject}` — {i.attribute} : {i.previous!r} → {i.current!r}",
    )
    section(
        "Anomalies",
        view.anomalies,
        lambda i: f"**{i.code}** — `{i.subject}` : {i.detail}",
    )

    lines.extend(["", "## Couverture d'autorisation", ""])
    if view.uncovered_scopes:
        lines.append("Scopes présents dans le catalogue mais **non autorisés** :")
        for scope in view.uncovered_scopes:
            lines.append(f"- `{scope}`")
    else:
        lines.append("_tous les scopes du catalogue sont couverts_")

    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DRAFT_STATUSES",
    "EVIDENCE_ONLY_ZONES",
    "REVIEW_VIEW_PROTOCOL",
    "UNSUPPORTED_EXTENSIONS",
    "Anomaly",
    "AttributeChange",
    "ContentReplacement",
    "PathChange",
    "PathMove",
    "ReviewView",
    "ReviewViewError",
    "build_review_view",
    "render_markdown",
]
