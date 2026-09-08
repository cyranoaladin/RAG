"""Tests de l'acquisition Drive → arbre vérifié.

Le client Drive est injecté : aucun test n'a besoin d'un compte de
service, et aucun identifiant réel n'entre dans le dépôt.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rag_pedago.governance.corpus_acquisition import (
    GOOGLE_FOLDER_MIME,
    AcquisitionReport,
    CorpusAcquisitionError,
    DriveFile,
    acquire_corpus,
    parse_declared_manifest,
    require_reconciled,
    require_scoped_reconciled,
    summarise,
    verify_expected_inventory,
    zone_counts,
)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FakeDrive:
    """Un Drive en lecture seule, entièrement en mémoire."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.downloads: list[str] = []

    def download(self, file_id: str) -> bytes:
        self.downloads.append(file_id)
        return self.blobs[file_id]


def build_source(
    objects: dict[str, bytes],
    *,
    manifest_paths: dict[str, str] | None = None,
    include_manifest: bool = True,
) -> tuple[list[DriveFile], FakeDrive]:
    """Construit une source cohérente : octets + manifeste GNU livré."""
    blobs = {f"id-{path}": payload for path, payload in objects.items()}
    files = [
        DriveFile(
            file_id=f"id-{path}",
            relative_path=path,
            mime_type="application/pdf",
            size_bytes=len(payload),
        )
        for path, payload in objects.items()
    ]
    if include_manifest:
        declared = manifest_paths or {
            path: sha(payload) for path, payload in objects.items()
        }
        content = "".join(
            f"{digest}  {path}\n" for path, digest in sorted(declared.items())
        ).encode()
        blobs["id-manifest"] = content
        files.append(
            DriveFile(
                file_id="id-manifest",
                relative_path="00_ADMIN/SHA256SUMS.txt",
                mime_type="text/plain",
                size_bytes=len(content),
            )
        )
    return files, FakeDrive(blobs)


NOMINAL = {
    "01_EDUSCOL_OFFICIEL/a.pdf": b"%PDF-a",
    "01_EDUSCOL_OFFICIEL/b.pdf": b"%PDF-b",
    "04_COMPLEMENTS_PEDAGOGIQUES/c.pdf": b"%PDF-c",
}


def acquire(files, drive, tmp_path) -> AcquisitionReport:
    return acquire_corpus(files, destination=tmp_path / "tree", download=drive.download)


class TestNominalAcquisition:
    def test_a_consistent_source_reconciles(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        report = require_reconciled(acquire(files, drive, tmp_path))
        assert report.file_count == 3
        assert report.reconciled is True

    def test_the_manifest_is_recomputed_not_copied(self, tmp_path: Path) -> None:
        """C'est le recalcul qui fait passer le corpus d'un contenu
        déclaré à un contenu prouvé."""
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        expected = "".join(
            f"{sha(payload)}  {path}\n" for path, payload in sorted(NOMINAL.items())
        ).encode()
        assert report.manifest.content == expected
        assert report.manifest.manifest_sha256 == sha(expected)

    def test_the_self_object_is_never_written_into_the_tree(
        self, tmp_path: Path
    ) -> None:
        """Le manifeste régénéré ne se contient jamais."""
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        assert not (report.root / "00_ADMIN" / "SHA256SUMS.txt").exists()
        assert all(path != "00_ADMIN/SHA256SUMS.txt"
                   for _digest, path in report.manifest.entries)

    def test_two_acquisitions_produce_identical_bytes(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        first = acquire(files, drive, tmp_path / "one")
        files2, drive2 = build_source(NOMINAL)
        second = acquire(list(reversed(files2)), drive2, tmp_path / "two")
        assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256


class TestReconciliation:
    def test_a_tampered_object_is_refused(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        drive.blobs["id-01_EDUSCOL_OFFICIEL/a.pdf"] = b"%PDF-x"
        # La taille annoncée reste celle de l'original : le contrôle de
        # taille passe, seul le digest attrape l'altération.
        with pytest.raises(CorpusAcquisitionError, match="digest mismatch"):
            require_reconciled(acquire(files, drive, tmp_path))

    def test_a_missing_object_is_named_as_incomplete(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        files = [f for f in files if not f.relative_path.endswith("b.pdf")]
        with pytest.raises(CorpusAcquisitionError, match="declared but not acquired"):
            require_reconciled(acquire(files, drive, tmp_path))

    def test_an_extra_object_says_the_source_moved(self, tmp_path: Path) -> None:
        declared = {p: sha(v) for p, v in NOMINAL.items()}
        del declared["01_EDUSCOL_OFFICIEL/b.pdf"]
        files, drive = build_source(NOMINAL, manifest_paths=declared)
        with pytest.raises(CorpusAcquisitionError, match="acquired but not declared"):
            require_reconciled(acquire(files, drive, tmp_path))

    def test_a_source_without_a_manifest_is_refused(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL, include_manifest=False)
        with pytest.raises(CorpusAcquisitionError, match="nothing to cross-check"):
            require_reconciled(acquire(files, drive, tmp_path))

    def test_reconciliation_errors_are_readable_not_a_bare_count(
        self, tmp_path: Path
    ) -> None:
        declared = {p: sha(v) for p, v in NOMINAL.items()}
        declared["01_EDUSCOL_OFFICIEL/ghost.pdf"] = "0" * 64
        files, drive = build_source(NOMINAL, manifest_paths=declared)
        with pytest.raises(CorpusAcquisitionError) as excinfo:
            require_reconciled(acquire(files, drive, tmp_path))
        assert "ghost.pdf" in str(excinfo.value)


class TestTruncationAndBounds:
    def test_a_truncated_download_is_refused(self, tmp_path: Path) -> None:
        """Un téléchargement tronqué se hacherait sans erreur."""
        files, drive = build_source(NOMINAL)
        drive.blobs["id-01_EDUSCOL_OFFICIEL/a.pdf"] = b"%PD"
        with pytest.raises(CorpusAcquisitionError, match="truncated download"):
            acquire(files, drive, tmp_path)

    def test_an_oversized_object_is_refused_before_download(
        self, tmp_path: Path
    ) -> None:
        files, drive = build_source(NOMINAL)
        files[0] = DriveFile(
            file_id=files[0].file_id,
            relative_path=files[0].relative_path,
            mime_type="application/pdf",
            size_bytes=10**12,
        )
        with pytest.raises(CorpusAcquisitionError, match="above the"):
            acquire(files, drive, tmp_path)
        assert files[0].file_id not in drive.downloads

    def test_an_empty_acquisition_is_refused(self, tmp_path: Path) -> None:
        files, drive = build_source({}, include_manifest=False)
        with pytest.raises(CorpusAcquisitionError, match="no regular object"):
            acquire(files, drive, tmp_path)


class TestPathSafety:
    def _with_path(self, path: str) -> tuple[list[DriveFile], FakeDrive]:
        return (
            [DriveFile("id-x", path, "application/pdf", 3)],
            FakeDrive({"id-x": b"abc"}),
        )

    def test_a_traversal_path_is_refused(self, tmp_path: Path) -> None:
        files, drive = self._with_path("01_EDUSCOL_OFFICIEL/../../etc/passwd")
        with pytest.raises(CorpusAcquisitionError, match="escapes"):
            acquire(files, drive, tmp_path)

    def test_an_absolute_path_is_refused(self, tmp_path: Path) -> None:
        files, drive = self._with_path("/etc/passwd")
        with pytest.raises(CorpusAcquisitionError, match="absolute path"):
            acquire(files, drive, tmp_path)

    def test_an_overlong_path_is_refused(self, tmp_path: Path) -> None:
        files, drive = self._with_path("01_EDUSCOL_OFFICIEL/" + "x" * 2000 + ".pdf")
        with pytest.raises(CorpusAcquisitionError, match="path bound"):
            acquire(files, drive, tmp_path)

    def test_a_duplicated_path_is_refused(self, tmp_path: Path) -> None:
        files = [
            DriveFile("id-1", "01_EDUSCOL_OFFICIEL/a.pdf", "application/pdf", 3),
            DriveFile("id-2", "01_EDUSCOL_OFFICIEL/a.pdf", "application/pdf", 3),
        ]
        drive = FakeDrive({"id-1": b"abc", "id-2": b"xyz"})
        with pytest.raises(CorpusAcquisitionError, match="listed twice"):
            acquire(files, drive, tmp_path)


class TestNativeGoogleObjects:
    def test_a_google_doc_is_excluded_and_named(self, tmp_path: Path) -> None:
        """Un Google Doc n'a pas d'octets : il a des exports, et deux
        exports du même document peuvent différer."""
        files, drive = build_source(NOMINAL)
        files.append(
            DriveFile(
                "id-doc",
                "04_COMPLEMENTS_PEDAGOGIQUES/note",
                "application/vnd.google-apps.document",
                0,
            )
        )
        report = acquire(files, drive, tmp_path)
        assert report.skipped_native == ["04_COMPLEMENTS_PEDAGOGIQUES/note"]
        assert "id-doc" not in drive.downloads

    def test_an_excluded_object_appears_in_the_summary(self, tmp_path: Path) -> None:
        """« Aucun fichier ne doit disparaître silencieusement. »"""
        files, drive = build_source(NOMINAL)
        files.append(
            DriveFile("id-doc", "04_COMPLEMENTS_PEDAGOGIQUES/note",
                      "application/vnd.google-apps.document", 0)
        )
        rendered = "\n".join(summarise(acquire(files, drive, tmp_path)))
        assert "04_COMPLEMENTS_PEDAGOGIQUES/note" in rendered

    def test_folders_are_counted_not_downloaded(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        files.append(DriveFile("id-f", "01_EDUSCOL_OFFICIEL", GOOGLE_FOLDER_MIME, 0))
        report = acquire(files, drive, tmp_path)
        assert report.skipped_folders == 1
        assert "id-f" not in drive.downloads


class TestDeclaredManifestParsing:
    def test_a_single_space_separator_is_refused(self) -> None:
        with pytest.raises(CorpusAcquisitionError, match="GNU sha256sum format"):
            parse_declared_manifest(b"%s 01_EDUSCOL_OFFICIEL/a.pdf\n" % (b"a" * 64))

    def test_an_uppercase_digest_is_refused(self) -> None:
        with pytest.raises(CorpusAcquisitionError, match="GNU sha256sum format"):
            parse_declared_manifest(b"%s  a.pdf\n" % (b"A" * 64))

    def test_a_duplicated_declaration_is_refused(self) -> None:
        raw = b"%s  a.pdf\n%s  a.pdf\n" % (b"a" * 64, b"b" * 64)
        with pytest.raises(CorpusAcquisitionError, match="twice"):
            parse_declared_manifest(raw)

    def test_an_empty_manifest_is_refused(self) -> None:
        with pytest.raises(CorpusAcquisitionError, match="empty"):
            parse_declared_manifest(b"")

    def test_non_utf8_is_refused(self) -> None:
        with pytest.raises(CorpusAcquisitionError, match="UTF-8"):
            parse_declared_manifest(b"\xff\xfe")

    def test_a_nominal_manifest_parses(self) -> None:
        raw = b"%s  01_EDUSCOL_OFFICIEL/a.pdf\n" % (b"a" * 64)
        assert parse_declared_manifest(raw) == {
            "01_EDUSCOL_OFFICIEL/a.pdf": "a" * 64
        }


class TestInventoryVerification:
    def test_matching_zone_counts_pass(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        verify_expected_inventory(
            report,
            expected_counts={
                "01_EDUSCOL_OFFICIEL": 2,
                "04_COMPLEMENTS_PEDAGOGIQUES": 1,
            },
        )

    def test_a_compensating_pair_of_errors_is_still_caught(
        self, tmp_path: Path
    ) -> None:
        """Un total global juste peut masquer deux erreurs opposées : la
        comparaison est par zone, précisément pour cela."""
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError) as excinfo:
            verify_expected_inventory(
                report,
                expected_counts={
                    "01_EDUSCOL_OFFICIEL": 1,
                    "04_COMPLEMENTS_PEDAGOGIQUES": 2,
                },
            )
        message = str(excinfo.value)
        assert "01_EDUSCOL_OFFICIEL: expected 1, acquired 2" in message
        assert "04_COMPLEMENTS_PEDAGOGIQUES: expected 2, acquired 1" in message

    def test_an_unexpected_zone_is_reported(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="none expected"):
            verify_expected_inventory(
                report, expected_counts={"01_EDUSCOL_OFFICIEL": 2}
            )

    def test_zone_counts_are_a_multiset(self, tmp_path: Path) -> None:
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        assert zone_counts(report.manifest) == {
            "01_EDUSCOL_OFFICIEL": 2,
            "04_COMPLEMENTS_PEDAGOGIQUES": 1,
        }


class TestRealCorpusShape:
    """Les cardinalités réelles de la source, telles que
    ``00_ADMIN/VALIDATION_FINAL.json`` les scelle."""

    def test_the_expected_zone_inventory_shape_is_enforceable(
        self, tmp_path: Path
    ) -> None:
        objects = {
            **{f"01_EDUSCOL_OFFICIEL/{i:04d}.pdf": f"%PDF-{i}".encode()
               for i in range(5)},
            **{f"02_NEXUS_DIAGNOSTICS/{i}.pdf": f"%PDF-d{i}".encode()
               for i in range(2)},
            "03_RESSOURCES_INTERACTIVES/x.ggb": b"PK\x03\x04ggb",
            "04_COMPLEMENTS_PEDAGOGIQUES/c.pdf": b"%PDF-c",
        }
        files, drive = build_source(objects)
        report = require_reconciled(acquire(files, drive, tmp_path))
        verify_expected_inventory(
            report,
            expected_counts={
                "01_EDUSCOL_OFFICIEL": 5,
                "02_NEXUS_DIAGNOSTICS": 2,
                "03_RESSOURCES_INTERACTIVES": 1,
                "04_COMPLEMENTS_PEDAGOGIQUES": 1,
            },
        )
        assert report.file_count == 9

    def test_a_ggb_is_acquired_never_dropped(self, tmp_path: Path) -> None:
        """L'exclusion des ``.ggb`` est une décision de *disposition*, pas
        d'acquisition : le fichier doit exister dans le manifeste scellé
        pour que le catalogue puisse le classer."""
        objects = {
            "01_EDUSCOL_OFFICIEL/a.pdf": b"%PDF-a",
            "03_RESSOURCES_INTERACTIVES/x.ggb": b"PK\x03\x04ggb",
        }
        files, drive = build_source(objects)
        report = require_reconciled(acquire(files, drive, tmp_path))
        assert any(
            path.endswith(".ggb") for _digest, path in report.manifest.entries
        )


class TestScopedReconciliation:
    """Une tranche du corpus se recoupe *sur son périmètre*, pas moins.

    Acquérir un sous-ensemble et exiger le recoupement global refuserait
    toute tranche ; se contenter de « ce qui est arrivé concorde avec
    lui-même » accepterait un périmètre silencieusement rétréci. Le
    périmètre demandé est donc l'entrée du contrôle, et il est vérifié
    dans les deux sens contre la déclaration du producteur.
    """

    def full_manifest(self) -> dict[str, str]:
        return {path: sha(payload) for path, payload in NOMINAL.items()}

    def test_a_slice_reconciles_against_the_full_producer_manifest(
        self, tmp_path: Path
    ) -> None:
        subset = {"01_EDUSCOL_OFFICIEL/a.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/a.pdf"]}
        files, drive = build_source(subset, manifest_paths=self.full_manifest())
        report = acquire(files, drive, tmp_path)

        # le recoupement global échoue : deux objets déclarés manquent
        assert report.reconciled is False
        with pytest.raises(CorpusAcquisitionError, match="declared but not acquired"):
            require_reconciled(report)

        # le recoupement de périmètre passe, et prouve le digest acquis
        scoped = require_scoped_reconciled(
            report, requested={"01_EDUSCOL_OFFICIEL/a.pdf"}
        )
        assert scoped is report

    def test_a_requested_object_absent_from_the_tree_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Un périmètre demandé plus large que l'acquisition est un
        téléchargement incomplet, pas une tranche."""
        subset = {"01_EDUSCOL_OFFICIEL/a.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/a.pdf"]}
        files, drive = build_source(subset, manifest_paths=self.full_manifest())
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="requested but not acquired"):
            require_scoped_reconciled(
                report,
                requested={
                    "01_EDUSCOL_OFFICIEL/a.pdf",
                    "01_EDUSCOL_OFFICIEL/b.pdf",
                },
            )

    def test_an_object_acquired_outside_the_requested_scope_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Un objet arrivé sans avoir été demandé est une source qui a
        bougé sous l'acquisition."""
        subset = {
            "01_EDUSCOL_OFFICIEL/a.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/a.pdf"],
            "01_EDUSCOL_OFFICIEL/b.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/b.pdf"],
        }
        files, drive = build_source(subset, manifest_paths=self.full_manifest())
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="acquired outside"):
            require_scoped_reconciled(
                report, requested={"01_EDUSCOL_OFFICIEL/a.pdf"}
            )

    def test_a_requested_object_the_producer_never_declared_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Sans ligne dans le manifeste livré, il n'y a rien à recouper :
        le digest recalculé ne serait comparé qu'à lui-même."""
        objects = {"01_EDUSCOL_OFFICIEL/z.pdf": b"%PDF-z"}
        files, drive = build_source(objects, manifest_paths=self.full_manifest())
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="never declared"):
            require_scoped_reconciled(
                report, requested={"01_EDUSCOL_OFFICIEL/z.pdf"}
            )

    def test_a_tampered_object_inside_the_scope_is_refused(
        self, tmp_path: Path
    ) -> None:
        subset = {"01_EDUSCOL_OFFICIEL/a.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/a.pdf"]}
        files, drive = build_source(subset, manifest_paths=self.full_manifest())
        drive.blobs["id-01_EDUSCOL_OFFICIEL/a.pdf"] = b"%PDF-X"
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="digest mismatch"):
            require_scoped_reconciled(
                report, requested={"01_EDUSCOL_OFFICIEL/a.pdf"}
            )

    def test_an_empty_scope_is_refused(self, tmp_path: Path) -> None:
        """Un périmètre vide passerait tous les contrôles sans rien
        prouver."""
        files, drive = build_source(NOMINAL)
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="empty scope"):
            require_scoped_reconciled(report, requested=set())

    def test_a_source_without_a_delivered_manifest_is_refused(
        self, tmp_path: Path
    ) -> None:
        subset = {"01_EDUSCOL_OFFICIEL/a.pdf": NOMINAL["01_EDUSCOL_OFFICIEL/a.pdf"]}
        files, drive = build_source(subset, include_manifest=False)
        report = acquire(files, drive, tmp_path)
        with pytest.raises(CorpusAcquisitionError, match="SHA256SUMS"):
            require_scoped_reconciled(
                report, requested={"01_EDUSCOL_OFFICIEL/a.pdf"}
            )
