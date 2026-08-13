"""Tests de la vue de revue ``NEXUS-CORPUS-REVIEW-VIEW-V1``.

Les tests construisent de vrais catalogues et lisent la vue produite. Ils
n'inspectent jamais le texte du code : une assertion sur une docstring
prouve qu'un commentaire existe, pas qu'un mécanisme fonctionne.
"""
from __future__ import annotations

import json

import pytest

from rag_pedago.governance.corpus_review_view import (
    REVIEW_VIEW_PROTOCOL,
    ReviewViewError,
    build_review_view,
    render_markdown,
)
from rag_pedago.imports.artifact_placement_model import (
    ContentArtifact,
    Disposition,
    PedagogicalPlacement,
    PhysicalCorpusObject,
    SealedCorpusCatalog,
)


def make_object(
    path: str,
    sha: str,
    *,
    disposition: Disposition = Disposition.INGEST,
    rights: str | None = "PUBLIC_INSTITUTIONAL",
    provenance: str = "VERIFIED",
    currentness: str | None = "actuel",
) -> PhysicalCorpusObject:
    return PhysicalCorpusObject(
        content_sha256=sha,
        path=path,
        base_disposition=disposition,
        disposition=disposition,
        disposition_reason="test",
        zone=path.partition("/")[0],
        currentness=currentness,
        rights_category_candidate=rights,
        provenance_status=provenance,
    )


def make_placement(
    sha: str,
    *,
    scope: str = "libre_terminale",
    level: str = "terminale",
    status: str = "10_ACTUEL_CONFIRME",
    scope_path: str = "maths/terminale",
    subject: str = "mathematiques",
) -> PedagogicalPlacement:
    return PedagogicalPlacement(
        content_sha256=sha,
        scope=scope,
        family="lycee",
        subject=subject,
        level=level,
        document_type="programme",
        year="2026",
        status=status,
        title="Titre",
        source_url="https://eduscol.education.fr/x",
        source_object="x.pdf",
        technical_path="t",
        level_path=level,
        scope_path=scope_path,
    )


def make_catalog(
    objects: list[PhysicalCorpusObject],
    placements: dict[str, list[PedagogicalPlacement]] | None = None,
    *,
    manifest_sha256: str = "m" * 64,
) -> SealedCorpusCatalog:
    artifacts: dict[str, ContentArtifact] = {}
    for item in objects:
        artifact = artifacts.setdefault(
            item.content_sha256, ContentArtifact(sha256=item.content_sha256)
        )
        artifact.physical_objects.append(item)
    for sha, items in (placements or {}).items():
        artifacts.setdefault(sha, ContentArtifact(sha256=sha)).pedagogical_placements.extend(
            items
        )
    return SealedCorpusCatalog(
        config_id="test",
        manifest_path="00_ADMIN/SHA256SUMS.txt",
        manifest_sha256=manifest_sha256,
        placement_catalog_path="p.tsv",
        placement_catalog_sha256="p" * 64,
        compiled_at="2026-01-01T00:00:00Z",
        manifest_entries=len(objects),
        physical_objects=objects,
        artifacts=artifacts,
        verification_passed=True,
    )


def build(current, baseline=None, **kwargs):
    return build_review_view(
        campaign_id="2026-08-corpus-public",
        source_oci_digest="sha256:" + "0" * 64,
        source_tree_digest="1" * 64,
        manifest_sha256=current.manifest_sha256,
        catalog_sha256="c" * 64,
        current=current,
        baseline=baseline,
        **kwargs,
    )


class TestNonAuthority:
    def test_the_view_serialises_its_own_lack_of_authority(self) -> None:
        """Le refus de faire foi doit voyager avec la donnée, pas rester
        dans une docstring que le consommateur ne lit jamais."""
        view = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        payload = json.loads(view.to_canonical_json())
        assert payload["authoritative"] is False
        assert payload["protocol"] == REVIEW_VIEW_PROTOCOL

    def test_the_view_carries_the_digests_that_do_decide(self) -> None:
        view = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        payload = json.loads(view.to_canonical_json())
        assert payload["source_oci_digest"] == "sha256:" + "0" * 64
        assert payload["manifest_sha256"] == "m" * 64


class TestDeterminism:
    def test_two_runs_produce_identical_bytes(self) -> None:
        """Sans cela la vue ne peut pas entrer dans le bundle H2 : son
        digest identifierait une exécution, pas un contenu."""
        objects = [
            make_object("01_EDUSCOL_OFFICIEL/b.pdf", "b" * 64),
            make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64),
        ]
        first = build(make_catalog(list(objects))).to_canonical_json()
        second = build(make_catalog(list(reversed(objects)))).to_canonical_json()
        assert first == second

    def test_the_canonical_content_carries_no_timestamp(self) -> None:
        view = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        raw = view.to_canonical_json().decode()
        assert "generated_at" not in raw
        assert "2026-01-01" not in raw

    def test_the_digest_changes_when_the_content_changes(self) -> None:
        one = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        two = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "e" * 64)]))
        assert one.view_sha256 != two.view_sha256


class TestDiffSemantics:
    def test_the_first_campaign_says_so_instead_of_showing_an_empty_diff(self) -> None:
        """Un diff vide se lirait « rien n'a changé » alors que tout est
        nouveau."""
        view = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        assert view.is_first_campaign is True
        assert len(view.added) == 1

    def test_a_replacement_at_the_same_path_is_not_an_add_plus_a_remove(self) -> None:
        """Le cas le plus dangereux : le nombre d'objets ne bouge pas,
        mais ce qui sera ingéré a changé."""
        baseline = make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)])
        current = make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "f" * 64)])
        view = build(current, baseline)
        assert len(view.replaced) == 1
        assert view.replaced[0].previous_sha256 == "a" * 64
        assert view.replaced[0].current_sha256 == "f" * 64
        assert view.added == [] and view.removed == []

    def test_a_move_is_not_reported_as_a_content_change(self) -> None:
        baseline = make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)])
        current = make_catalog([make_object("04_COMPLEMENTS_PEDAGOGIQUES/a.pdf", "a" * 64)])
        view = build(current, baseline)
        assert len(view.moved) == 1
        assert view.moved[0].previous_zone == "01_EDUSCOL_OFFICIEL"
        assert view.moved[0].current_zone == "04_COMPLEMENTS_PEDAGOGIQUES"
        assert view.added == [] and view.removed == []

    def test_a_genuine_addition_is_still_an_addition(self) -> None:
        baseline = make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)])
        current = make_catalog(
            [
                make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64),
                make_object("01_EDUSCOL_OFFICIEL/b.pdf", "b" * 64),
            ]
        )
        view = build(current, baseline)
        assert [item.path for item in view.added] == ["01_EDUSCOL_OFFICIEL/b.pdf"]
        assert view.moved == []

    def test_a_duplicate_path_is_refused_rather_than_shown_once(self) -> None:
        catalog = make_catalog(
            [
                make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64),
                make_object("01_EDUSCOL_OFFICIEL/a.pdf", "b" * 64),
            ]
        )
        with pytest.raises(ReviewViewError, match="twice"):
            build(catalog)


class TestEscalations:
    def test_quarantine_to_ingest_is_flagged_as_an_escalation(self) -> None:
        """La transition qui publie ce qui était retenu."""
        baseline = make_catalog(
            [make_object("02_NEXUS_DIAGNOSTICS/d.pdf", "d" * 64,
                         disposition=Disposition.QUARANTINE)]
        )
        current = make_catalog(
            [make_object("02_NEXUS_DIAGNOSTICS/d.pdf", "d" * 64,
                         disposition=Disposition.INGEST)]
        )
        view = build(current, baseline)
        escalations = [c for c in view.escalations if c.attribute == "disposition"]
        assert len(escalations) == 1
        assert escalations[0].previous == "QUARANTINE"
        assert escalations[0].current == "INGEST"

    def test_ingest_to_quarantine_is_not_an_escalation(self) -> None:
        baseline = make_catalog(
            [make_object("02_NEXUS_DIAGNOSTICS/d.pdf", "d" * 64,
                         disposition=Disposition.INGEST)]
        )
        current = make_catalog(
            [make_object("02_NEXUS_DIAGNOSTICS/d.pdf", "d" * 64,
                         disposition=Disposition.QUARANTINE)]
        )
        view = build(current, baseline)
        changes = [c for c in view.attribute_changes if c.attribute == "disposition"]
        assert len(changes) == 1
        assert changes[0].escalation is False

    def test_a_rights_category_change_is_always_flagged(self) -> None:
        baseline = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64, rights="RESTRICTED")]
        )
        current = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64,
                         rights="PUBLIC_INSTITUTIONAL")]
        )
        view = build(current, baseline)
        assert any(
            c.attribute == "rights_category_candidate" and c.escalation
            for c in view.escalations
        )

    def test_a_scope_change_reaches_a_different_audience_and_is_flagged(self) -> None:
        sha = "a" * 64
        baseline = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", sha)],
            {sha: [make_placement(sha, scope="libre_seconde", level="seconde")]},
        )
        current = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", sha)],
            {sha: [make_placement(sha, scope="libre_terminale", level="terminale")]},
        )
        view = build(current, baseline)
        assert any(c.attribute == "placement.scope" and c.escalation
                   for c in view.escalations)
        assert any(c.attribute == "placement.level" for c in view.attribute_changes)


class TestAnomalies:
    def test_an_evidence_zone_marked_for_ingest_is_an_anomaly(self) -> None:
        """00_ADMIN documente le corpus ; l'ingérer ferait remonter des
        sommes de contrôle dans les réponses aux élèves."""
        view = build(
            make_catalog([make_object("00_ADMIN/SHA256SUMS.txt", "a" * 64)])
        )
        assert any(a.code == "EVIDENCE_ZONE_MARKED_FOR_INGEST" for a in view.anomalies)

    def test_a_ggb_marked_for_ingest_is_an_anomaly(self) -> None:
        view = build(
            make_catalog([make_object("03_RESSOURCES_INTERACTIVES/f.ggb", "a" * 64)])
        )
        assert any(
            a.code == "UNSUPPORTED_FORMAT_MARKED_FOR_INGEST" for a in view.anomalies
        )

    def test_a_ggb_marked_unsupported_is_counted_not_dropped(self) -> None:
        """« Aucun fichier ne doit disparaître silencieusement. »"""
        view = build(
            make_catalog(
                [
                    make_object(
                        "03_RESSOURCES_INTERACTIVES/f.ggb",
                        "a" * 64,
                        disposition=Disposition.UNSUPPORTED,
                    )
                ]
            )
        )
        assert view.anomalies == []
        assert view.counts["unsupported_format_objects"] == 1
        assert view.dispositions["UNSUPPORTED"] == 1

    def test_ingest_without_a_rights_category_is_an_anomaly(self) -> None:
        view = build(
            make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64, rights=None)])
        )
        assert any(a.code == "INGEST_WITHOUT_RIGHTS_CATEGORY" for a in view.anomalies)

    def test_a_draft_placement_is_an_anomaly(self) -> None:
        sha = "a" * 64
        view = build(
            make_catalog(
                [make_object("02_NEXUS_DIAGNOSTICS/d.pdf", sha)],
                {sha: [make_placement(sha, status="DRAFT")]},
            )
        )
        assert any(a.code == "DRAFT_PLACEMENT_PUBLISHED" for a in view.anomalies)

    def test_unverified_provenance_is_an_anomaly(self) -> None:
        view = build(
            make_catalog(
                [make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64,
                             provenance="UNVERIFIED")]
            )
        )
        assert any(a.code == "UNVERIFIED_PROVENANCE" for a in view.anomalies)

    def test_a_placement_without_physical_bytes_is_an_anomaly(self) -> None:
        """Une affectation logique qui pointe vers un contenu absent du
        manifeste scellé."""
        catalog = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)],
            {"z" * 64: [make_placement("z" * 64)]},
        )
        view = build(catalog)
        assert any(
            a.code == "PLACEMENT_WITHOUT_PHYSICAL_OBJECT" for a in view.anomalies
        )


class TestCardinalities:
    def test_logical_placements_exceed_physical_objects_without_duplication(self) -> None:
        """Le cas réel : 2 956 affectations pour 2 451 objets. Le modèle
        doit compter les deux séparément, sinon la duplication logique
        ressemblerait à une duplication d'octets."""
        sha = "a" * 64
        catalog = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", sha)],
            {
                sha: [
                    make_placement(sha, scope_path="maths/seconde", level="seconde"),
                    make_placement(sha, scope_path="maths/premiere", level="premiere"),
                    make_placement(sha, scope_path="maths/terminale"),
                ]
            },
        )
        view = build(catalog)
        assert view.counts["physical_objects"] == 1
        assert view.counts["content_artifacts"] == 1
        assert view.counts["logical_placements"] == 3

    def test_dispositions_are_counted_as_a_multiset(self) -> None:
        """Preuve de mutation dirigée : avec un ``set``, ce compteur
        vaudrait 1 quel que soit le nombre d'objets."""
        catalog = make_catalog(
            [
                make_object(f"01_EDUSCOL_OFFICIEL/{i}.pdf", chr(97 + i) * 64)
                for i in range(5)
            ]
        )
        view = build(catalog)
        assert view.dispositions["INGEST"] == 5
        assert view.counts["physical_objects"] == 5


class TestAuthorizationCoverage:
    def test_an_unauthorized_scope_is_reported(self) -> None:
        sha = "a" * 64
        catalog = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", sha)],
            {sha: [make_placement(sha, scope="aefe_seconde")]},
        )
        view = build(catalog, authorized_scopes=["libre_terminale"])
        assert view.uncovered_scopes == ["aefe_seconde"]

    def test_a_covered_scope_is_not_reported(self) -> None:
        sha = "a" * 64
        catalog = make_catalog(
            [make_object("01_EDUSCOL_OFFICIEL/a.pdf", sha)],
            {sha: [make_placement(sha, scope="libre_terminale")]},
        )
        view = build(catalog, authorized_scopes=["libre_terminale"])
        assert view.uncovered_scopes == []


class TestRendering:
    def test_the_markdown_states_the_lack_of_authority_up_front(self) -> None:
        view = build(make_catalog([make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]))
        rendered = render_markdown(view)
        assert "ne fait pas autorité" in rendered
        assert view.source_oci_digest in rendered

    def test_truncation_is_announced_never_silent(self) -> None:
        catalog = make_catalog(
            [
                make_object(f"01_EDUSCOL_OFFICIEL/{i:04d}.pdf", f"{i:064d}")
                for i in range(120)
            ]
        )
        rendered = render_markdown(build(catalog))
        assert "de plus (tronqué à 50)" in rendered

    def test_the_rendering_is_deterministic(self) -> None:
        catalog = make_catalog(
            [make_object(f"01_EDUSCOL_OFFICIEL/{i}.pdf", chr(97 + i) * 64)
             for i in range(4)]
        )
        assert render_markdown(build(catalog)) == render_markdown(build(catalog))


class TestRefusals:
    def test_an_empty_campaign_id_is_refused(self) -> None:
        with pytest.raises(ReviewViewError, match="campaign_id"):
            build_review_view(
                campaign_id="",
                source_oci_digest="sha256:" + "0" * 64,
                source_tree_digest="1" * 64,
                manifest_sha256="m" * 64,
                catalog_sha256="c" * 64,
                current=make_catalog(
                    [make_object("01_EDUSCOL_OFFICIEL/a.pdf", "a" * 64)]
                ),
            )
