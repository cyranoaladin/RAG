"""Tests de la tranche verticale Drive → staging gouverné.

Aucun réseau, aucune base : le transport Drive, l'extracteur de pages et
le magasin de staging sont injectés. Ce que ces tests protègent, c'est
l'ordre des autorités — la classification vient du chemin gouverné, les
octets viennent de l'arbre *rehaché* par ``acquire_corpus``, et l'identité
d'un artefact est son empreinte, jamais son identifiant Drive.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from rag_pedago.governance.corpus_acquisition import CorpusAcquisitionError
from rag_pedago.governance.drive_slice import (
    DriveClassificationError,
    InMemoryStagingStore,
    PageText,
    StagedChunk,
    classify_from_hints,
    make_chunks,
    run_slice,
)
from rag_pedago.governance.drive_source import DrivePage, DriveSourceAdapter

FOLDER = "application/vnd.google-apps.folder"
PDF = "application/pdf"
SHORTCUT = "application/vnd.google-apps.shortcut"
ROOT_ID = "root"
ROOT_NAME = "NEXUS_RAG_GDRIVE_READY"

PDF_BYTES = b"%PDF-programme-terminale"
PDF_PATH = (
    "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/MATHEMATIQUES/"
    "01_PROGRAMMES_OFFICIELS/2026/programme.pdf"
)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------
# classification depuis le chemin gouverné
# ---------------------------------------------------------------------


class TestClassification:
    def test_le_chemin_gouverne_porte_toute_la_classification(self) -> None:
        placement = classify_from_hints(
            (
                "01_EDUSCOL_OFFICIEL",
                "LYCEE",
                "TERMINALE",
                "MATHEMATIQUES",
                "01_PROGRAMMES_OFFICIELS",
                "2026",
            )
        )
        assert placement.zone == "01_EDUSCOL_OFFICIEL"
        assert placement.cycle == "lycee"
        assert placement.niveau == "terminale"
        assert placement.matiere == "mathematiques"
        assert placement.nature == "programmes_officiels"
        assert placement.millesime == "2026"
        assert placement.servable is True

    def test_l_ordre_des_segments_n_est_pas_une_autorite(self) -> None:
        """Les segments sont reconnus par leur *nature*, pas leur rang :
        une zone qui insère un dossier intermédiaire ne doit pas décaler
        toute la classification d'un cran."""
        placement = classify_from_hints(
            (
                "02_NEXUS_DIAGNOSTICS",
                "TERMINALE",
                "MATHEMATIQUES",
                "04_EVALUATIONS_EXAMENS",
            )
        )
        assert placement.niveau == "terminale"
        assert placement.matiere == "mathematiques"
        assert placement.nature == "evaluations_examens"
        assert placement.cycle is None
        assert placement.millesime is None

    def test_une_zone_de_plan_de_controle_n_est_pas_servable(self) -> None:
        placement = classify_from_hints(("00_ADMIN",))
        assert placement.servable is False

    def test_une_zone_inconnue_est_refusee(self) -> None:
        with pytest.raises(DriveClassificationError, match="zone"):
            classify_from_hints(("99_ZONE_INVENTEE", "LYCEE"))

    def test_un_statut_empile_sur_une_nature_designe_DEUX_dimensions(self) -> None:
        """``80_A_VERIFIER`` sur ``04_EVALUATIONS_EXAMENS`` n'est pas une
        ambiguïté : c'est une évaluation dont la source doute.

        La source numérote ces deux familles séparément — 01–09 pour ce que
        le document est, 10/20/80/90/99 pour ce qu'elle dit de son actualité.
        Les replier dans un seul seau faisait de ce chemin « deux natures »
        et le refusait, alors qu'il ne portait aucune ambiguïté. Sur l'arbre
        gouverné, ce seul défaut écartait 938 documents."""
        placement = classify_from_hints(
            (
                "01_EDUSCOL_OFFICIEL",
                "LYCEE",
                "TRANSVERSAL_MULTI_NIVEAUX",
                "80_A_VERIFIER",
                "EPS",
                "04_EVALUATIONS_EXAMENS",
                "2022",
            )
        )
        assert placement.nature == "evaluations_examens"
        assert placement.statut_source == "a_verifier"
        assert placement.matiere == "eps"

    def test_deux_natures_reelles_restent_un_refus(self) -> None:
        """Séparer les dimensions ne desserre pas la garde : deux segments
        d'une MÊME dimension restent une ambiguïté que la source ne tranche
        pas."""
        with pytest.raises(DriveClassificationError, match="ambigu"):
            classify_from_hints(
                (
                    "01_EDUSCOL_OFFICIEL",
                    "LYCEE",
                    "TERMINALE",
                    "EPS",
                    "04_EVALUATIONS_EXAMENS",
                    "06_GUIDES",
                )
            )

    def test_deux_statuts_de_source_restent_un_refus(self) -> None:
        with pytest.raises(DriveClassificationError, match="ambigu"):
            classify_from_hints(
                (
                    "01_EDUSCOL_OFFICIEL",
                    "LYCEE",
                    "TERMINALE",
                    "EPS",
                    "80_A_VERIFIER",
                    "90_ARCHIVE_CATALOGUE",
                )
            )

    def test_un_libelle_numerote_inconnu_est_refuse(self) -> None:
        """Le ranger d'après son seul préfixe lui prêterait une dimension
        qu'on ignore — exactement le défaut que la séparation corrige."""
        with pytest.raises(DriveClassificationError, match="inconnu"):
            classify_from_hints(
                ("01_EDUSCOL_OFFICIEL", "LYCEE", "TERMINALE", "EPS", "05_INVENTE")
            )

    def test_deux_segments_libres_rendent_la_matiere_ambigue_donc_refusee(self) -> None:
        with pytest.raises(DriveClassificationError, match="ambigu"):
            classify_from_hints(
                ("01_EDUSCOL_OFFICIEL", "LYCEE", "TERMINALE", "MATHS", "ALGEBRE")
            )

    def test_un_chemin_sans_aucune_dimension_de_routage_est_refuse(self) -> None:
        with pytest.raises(DriveClassificationError, match="routage"):
            classify_from_hints(("01_EDUSCOL_OFFICIEL", "LYCEE", "TERMINALE"))

    def test_un_niveau_abrege_est_canonicalise(self) -> None:
        """``3E`` et ``TROISIEME`` désignent le même niveau. Sans alias,
        l'abréviation retombait dans les segments libres et entrait en
        collision avec la vraie discipline : 44 documents écartés pour une
        orthographe."""
        abrege = classify_from_hints(
            ("01_EDUSCOL_OFFICIEL", "COLLEGE", "3E", "HISTOIRE_GEOGRAPHIE")
        )
        long = classify_from_hints(
            ("01_EDUSCOL_OFFICIEL", "COLLEGE", "TROISIEME", "HISTOIRE_GEOGRAPHIE")
        )
        assert abrege.niveau == long.niveau == "troisieme"
        assert abrege.matiere == "histoire_geographie"

    def test_une_abreviation_de_niveau_inconnue_reste_une_matiere(self) -> None:
        """La canonicalisation est un vocabulaire FERMÉ : ``7E`` n'est pas
        un niveau qu'on devine, et le chemin qui l'emploie à côté d'une
        discipline reste refusé."""
        with pytest.raises(DriveClassificationError, match="ambigu"):
            classify_from_hints(
                ("01_EDUSCOL_OFFICIEL", "COLLEGE", "7E", "HISTOIRE_GEOGRAPHIE")
            )

    def test_une_voie_route_un_document_sans_discipline(self) -> None:
        """Une ressource de série porte de quoi être adressée sans nommer de
        matière. Exiger la discipline seule refusait 87 documents STMG que la
        source place pourtant sans ambiguïté."""
        placement = classify_from_hints(
            ("01_EDUSCOL_OFFICIEL", "STMG", "PREMIERE", "07_DIAPORAMAS_SUPPORTS", "2019")
        )
        assert placement.voie == "technologique"
        assert placement.niveau == "premiere"
        assert placement.matiere is None
        assert placement.servable is True

    def test_une_institution_route_un_test_de_positionnement(self) -> None:
        placement = classify_from_hints(
            (
                "04_COMPLEMENTS_PEDAGOGIQUES",
                "01_SOURCES_INSTITUTIONNELLES",
                "DEPP",
                "SECONDE",
                "TESTS_POSITIONNEMENT",
                "2025",
            )
        )
        assert placement.institution == "depp"
        assert placement.famille_provenance == "sources_institutionnelles"
        assert placement.nature == "tests_positionnement"
        assert placement.niveau == "seconde"


# ---------------------------------------------------------------------
# découpage
# ---------------------------------------------------------------------


class TestChunking:
    def test_un_chunk_par_page_avec_ses_bornes(self) -> None:
        pages = (PageText(1, "premiere page"), PageText(2, "seconde page"))
        chunks = make_chunks("a" * 64, pages)
        assert [(c.chunk_index, c.page_start, c.page_end) for c in chunks] == [
            (0, 1, 1),
            (1, 2, 2),
        ]

    def test_l_identite_d_un_chunk_lie_l_artefact_le_rang_et_le_texte(self) -> None:
        artifact = "b" * 64
        chunks = make_chunks(artifact, (PageText(1, "texte"),))
        text_sha = sha(b"texte")
        assert chunks[0].chunk_sha256 == text_sha
        assert chunks[0].chunk_id == sha(f"{artifact}:0:{text_sha}".encode())

    def test_les_memes_octets_donnent_les_memes_identites_de_chunk(self) -> None:
        first = make_chunks("c" * 64, (PageText(1, "x"), PageText(2, "y")))
        second = make_chunks("c" * 64, (PageText(1, "x"), PageText(2, "y")))
        assert [c.chunk_id for c in first] == [c.chunk_id for c in second]

    def test_une_page_vide_est_ignoree_sans_decaler_les_rangs(self) -> None:
        """Un chunk vide n'enseigne rien ; en revanche son rang doit rester
        celui de sa page, sinon deux découpages du même PDF donneraient des
        identités différentes."""
        pages = (PageText(1, "a"), PageText(2, "   "), PageText(3, "b"))
        chunks = make_chunks("d" * 64, pages)
        assert [(c.chunk_index, c.page_start) for c in chunks] == [(0, 1), (2, 3)]

    def test_un_document_sans_aucun_texte_est_refuse(self) -> None:
        with pytest.raises(CorpusAcquisitionError, match="aucun texte"):
            make_chunks("e" * 64, (PageText(1, ""), PageText(2, "  ")))


# ---------------------------------------------------------------------
# tranche verticale complète
# ---------------------------------------------------------------------


class FakeTransport:
    def __init__(self, entries: dict[str, list[dict[str, Any]]], blobs: dict[str, bytes]):
        self.entries = entries
        self.blobs = blobs
        self.fetch_calls: list[str] = []

    def list_children(self, folder_id: str, *, page_token: str | None) -> DrivePage:
        return DrivePage(entries=tuple(self.entries.get(folder_id, [])), next_page_token=None)

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        for children in self.entries.values():
            for child in children:
                if child["id"] == file_id:
                    return child
        raise KeyError(file_id)

    def fetch(self, file_id: str) -> bytes:
        self.fetch_calls.append(file_id)
        return self.blobs[file_id]

    def export(self, file_id: str, *, mime_type: str) -> bytes:  # pragma: no cover
        raise AssertionError("aucun natif dans cette tranche")


def folder(fid: str, name: str) -> dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "mimeType": FOLDER,
        "modifiedTime": "2026-08-05T01:53:07.337Z",
    }


def pdf(fid: str, name: str, payload: bytes) -> dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "mimeType": PDF,
        "modifiedTime": "2026-08-05T01:53:07.337Z",
        "size": str(len(payload)),
    }


ALIAS_PATH = "04_COMPLEMENTS_PEDAGOGIQUES/alias.pdf"


def build_transport(
    *, with_shortcut: bool = False, declare_shortcut: bool = True
) -> FakeTransport:
    # Le manifeste du producteur décrit les *chemins* du corpus : une
    # occurrence par raccourci y a sa ligne, avec le digest de sa cible.
    declared = {PDF_PATH: sha(PDF_BYTES)}
    if with_shortcut and declare_shortcut:
        declared[ALIAS_PATH] = sha(PDF_BYTES)
    manifest = "".join(
        f"{digest}  {path}\n" for path, digest in sorted(declared.items())
    ).encode()
    blobs = {"pdf1": PDF_BYTES, "man": manifest}
    entries: dict[str, list[dict[str, Any]]] = {
        ROOT_ID: [folder("admin", "00_ADMIN"), folder("z1", "01_EDUSCOL_OFFICIEL")],
        "admin": [
            {
                "id": "man",
                "name": "SHA256SUMS.txt",
                "mimeType": "text/plain",
                "modifiedTime": "2026-08-08T10:42:30.556Z",
                "size": str(len(manifest)),
            }
        ],
        "z1": [folder("cy", "LYCEE")],
        "cy": [folder("ni", "TERMINALE")],
        "ni": [folder("ma", "MATHEMATIQUES")],
        "ma": [folder("na", "01_PROGRAMMES_OFFICIELS")],
        "na": [folder("mi", "2026")],
        "mi": [pdf("pdf1", "programme.pdf", PDF_BYTES)],
    }
    if with_shortcut:
        entries[ROOT_ID].append(folder("z4", "04_COMPLEMENTS_PEDAGOGIQUES"))
        entries["z4"] = [
            {
                "id": "sc1",
                "name": "alias.pdf",
                "mimeType": SHORTCUT,
                "modifiedTime": "2026-08-05T01:53:07.337Z",
                "shortcutDetails": {"targetId": "pdf1", "targetMimeType": PDF},
            }
        ]
    return FakeTransport(entries, blobs)


def fake_extract(content: bytes) -> tuple[PageText, ...]:
    return (PageText(1, content.decode("latin-1")), PageText(2, "seconde page"))


def make_adapter(transport: FakeTransport) -> DriveSourceAdapter:
    return DriveSourceAdapter(transport, root_folder_id=ROOT_ID, root_name=ROOT_NAME)


class TestVerticalSlice:
    def test_la_tranche_traverse_acquisition_classification_et_staging(
        self, tmp_path: Path
    ) -> None:
        transport = build_transport()
        store = InMemoryStagingStore()
        report = run_slice(
            make_adapter(transport),
            scope={PDF_PATH},
            destination=tmp_path / "tree",
            store=store,
            extract_pages=fake_extract,
        )

        assert report.new_artifacts == 1
        assert report.new_chunks == 2
        assert report.duplicate_chunks == 0
        # l'arbre matérialisé et rehaché par acquire_corpus existe
        assert (tmp_path / "tree" / PDF_PATH).read_bytes() == PDF_BYTES

        staged = store.artifacts[sha(PDF_BYTES)]
        assert staged.artifact_id == sha(PDF_BYTES)
        assert staged.placement.matiere == "mathematiques"
        assert staged.placement.niveau == "terminale"
        assert staged.review_status == "needs_review"

    def test_les_chunks_stages_sont_interrogeables_par_leur_placement(
        self, tmp_path: Path
    ) -> None:
        transport = build_transport()
        store = InMemoryStagingStore()
        run_slice(
            make_adapter(transport),
            scope={PDF_PATH},
            destination=tmp_path / "tree",
            store=store,
            extract_pages=fake_extract,
        )
        found = store.query(matiere="mathematiques", niveau="terminale", motif="programme")
        assert [c.chunk_index for c in found] == [0]
        assert found[0].text.startswith("%PDF-programme")

    def test_le_meme_instantane_deux_fois_n_ajoute_rien(self, tmp_path: Path) -> None:
        transport = build_transport()
        store = InMemoryStagingStore()
        first = run_slice(
            make_adapter(transport),
            scope={PDF_PATH},
            destination=tmp_path / "run1",
            store=store,
            extract_pages=fake_extract,
        )
        second = run_slice(
            make_adapter(transport),
            scope={PDF_PATH},
            destination=tmp_path / "run2",
            store=store,
            extract_pages=fake_extract,
        )

        assert first.new_artifacts == 1
        assert second.new_artifacts == 0
        assert second.duplicate_chunks == first.new_chunks
        assert second.new_chunks == 0
        assert len(store.chunks) == first.new_chunks

    def test_deux_acquisitions_des_memes_octets_donnent_le_meme_artifact_id(
        self, tmp_path: Path
    ) -> None:
        store = InMemoryStagingStore()
        run_slice(
            make_adapter(build_transport()),
            scope={PDF_PATH},
            destination=tmp_path / "a",
            store=store,
            extract_pages=fake_extract,
        )
        assert list(store.artifacts) == [sha(PDF_BYTES)]

    def test_un_raccourci_ajoute_une_provenance_pas_un_artefact(
        self, tmp_path: Path
    ) -> None:
        transport = build_transport(with_shortcut=True)
        store = InMemoryStagingStore()
        report = run_slice(
            make_adapter(transport),
            scope={PDF_PATH, ALIAS_PATH},
            destination=tmp_path / "tree",
            store=store,
            extract_pages=fake_extract,
        )

        assert report.new_artifacts == 1
        assert report.new_provenances == 2
        assert report.new_chunks == 2
        assert transport.fetch_calls.count("pdf1") == 1
        assert store.provenances[sha(PDF_BYTES)] == (PDF_PATH, ALIAS_PATH)

    def test_un_perimetre_non_declare_par_le_producteur_est_refuse(
        self, tmp_path: Path
    ) -> None:
        transport = build_transport(with_shortcut=True, declare_shortcut=False)
        with pytest.raises(CorpusAcquisitionError, match="never declared"):
            run_slice(
                make_adapter(transport),
                scope={PDF_PATH, ALIAS_PATH},
                destination=tmp_path / "tree",
                store=InMemoryStagingStore(),
                extract_pages=fake_extract,
            )

    def test_un_perimetre_absent_de_la_source_est_refuse(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusAcquisitionError, match="not present in the source"):
            run_slice(
                make_adapter(build_transport()),
                scope={PDF_PATH, "01_EDUSCOL_OFFICIEL/fantome.pdf"},
                destination=tmp_path / "tree",
                store=InMemoryStagingStore(),
                extract_pages=fake_extract,
            )

    def test_le_staging_n_est_jamais_marque_relu(self, tmp_path: Path) -> None:
        """Rien de ce qui sort d'ici n'est servable : la revue humaine est
        en aval, et un défaut « reviewed » la court-circuiterait."""
        store = InMemoryStagingStore()
        run_slice(
            make_adapter(build_transport()),
            scope={PDF_PATH},
            destination=tmp_path / "tree",
            store=store,
            extract_pages=fake_extract,
        )
        assert all(a.review_status == "needs_review" for a in store.artifacts.values())


def test_un_chunk_stage_expose_ce_qu_il_faut_pour_le_relire() -> None:
    chunk = StagedChunk(
        chunk_id="x", artifact_id="y", chunk_index=0, chunk_sha256="z",
        page_start=1, page_end=1, text="t",
    )
    assert chunk.page_start == 1
