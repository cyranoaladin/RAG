"""Tests du transport Drive réel — sans réseau ni compte de service.

Le service Google est injecté : ce qui est vérifié ici, c'est la requête
émise (filtre, champs, jeton de page, drives partagés), la traduction des
pannes réessayables, et le refus d'une configuration d'identifiants
absente. Rien de tout cela n'a besoin d'un appel sortant, et aucun
identifiant réel n'entre dans le dépôt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rag_pedago.governance.drive_extraction import extract_pdf_pages
from rag_pedago.governance.drive_source import DriveTransientError
from rag_pedago.governance.drive_transport import (
    CREDENTIALS_ENV,
    DRIVE_READONLY_SCOPE,
    GoogleDriveTransport,
    credentials_path,
    is_transient_status,
    page_from_response,
)


class FakeExecutable:
    def __init__(self, result: Any, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error

    def execute(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.result


class FakeFiles:
    def __init__(self) -> None:
        self.list_kwargs: list[dict[str, Any]] = []
        self.get_kwargs: list[dict[str, Any]] = []
        self.response: Any = {"files": [], "nextPageToken": None}
        self.error: BaseException | None = None

    def list(self, **kwargs: Any) -> FakeExecutable:
        self.list_kwargs.append(kwargs)
        return FakeExecutable(self.response, self.error)

    def get(self, **kwargs: Any) -> FakeExecutable:
        self.get_kwargs.append(kwargs)
        return FakeExecutable({"id": kwargs.get("fileId"), "size": "12"})

    def get_media(self, **kwargs: Any) -> FakeExecutable:
        self.get_kwargs.append(kwargs)
        return FakeExecutable(b"octets", self.error)

    def export(self, **kwargs: Any) -> FakeExecutable:
        self.get_kwargs.append(kwargs)
        return FakeExecutable(b"exporte")


class FakeService:
    def __init__(self) -> None:
        self._files = FakeFiles()

    def files(self) -> FakeFiles:
        return self._files


class FakeHttpError(Exception):
    """Imite ``googleapiclient.errors.HttpError`` sans la dépendance."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


class TestCredentials:
    def test_un_chemin_d_identifiants_absent_est_refuse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Aucun repli sur un emplacement conventionnel : deviner le
        compte de service, c'est ne plus savoir avec quels droits on
        énumère."""
        monkeypatch.delenv(CREDENTIALS_ENV, raising=False)
        # Le message doit dire *que la variable manque* : un repli sur un
        # emplacement conventionnel échouerait lui aussi, mais en disant
        # « ce fichier n'existe pas », ce qui laisserait croire qu'il
        # suffirait de le créer.
        with pytest.raises(RuntimeError, match="n'est pas défini"):
            credentials_path()

    def test_un_fichier_d_identifiants_inexistant_est_refuse(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(CREDENTIALS_ENV, str(tmp_path / "absent.json"))
        with pytest.raises(RuntimeError, match="absent.json"):
            credentials_path()

    def test_un_chemin_valide_est_rendu_tel_quel(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        target = tmp_path / "sa.json"
        target.write_text("{}")
        monkeypatch.setenv(CREDENTIALS_ENV, str(target))
        assert credentials_path() == target

    def test_la_portee_demandee_est_en_lecture_seule(self) -> None:
        """Un scope en écriture rendrait possible, par erreur de code, une
        modification de la source de référence."""
        assert DRIVE_READONLY_SCOPE == "https://www.googleapis.com/auth/drive.readonly"
        assert DRIVE_READONLY_SCOPE.endswith(".readonly")


class TestRequestShape:
    def transport(self) -> tuple[GoogleDriveTransport, FakeFiles]:
        service = FakeService()
        return GoogleDriveTransport(service), service.files()

    def test_la_requete_filtre_les_enfants_non_supprimes(self) -> None:
        transport, files = self.transport()
        transport.list_children("abc", page_token=None)
        assert files.list_kwargs[0]["q"] == "'abc' in parents and trashed=false"

    def test_la_requete_demande_les_champs_dont_l_adaptateur_a_besoin(self) -> None:
        transport, files = self.transport()
        transport.list_children("abc", page_token=None)
        fields = files.list_kwargs[0]["fields"]
        for needed in ("size", "shortcutDetails", "modifiedTime", "nextPageToken"):
            assert needed in fields

    def test_le_jeton_de_page_est_transmis(self) -> None:
        transport, files = self.transport()
        transport.list_children("abc", page_token="tok")
        assert files.list_kwargs[0]["pageToken"] == "tok"

    def test_les_drives_partages_sont_inclus(self) -> None:
        """La racine gouvernée vit sur un drive partagé : sans ces deux
        drapeaux, l'énumération rend un arbre vide sans erreur."""
        transport, files = self.transport()
        transport.list_children("abc", page_token=None)
        assert files.list_kwargs[0]["includeItemsFromAllDrives"] is True
        assert files.list_kwargs[0]["supportsAllDrives"] is True

    def test_une_page_est_traduite_en_DrivePage(self) -> None:
        transport, files = self.transport()
        files.response = {"files": [{"id": "a"}], "nextPageToken": "suite"}
        page = transport.list_children("abc", page_token=None)
        assert page.entries == ({"id": "a"},)
        assert page.next_page_token == "suite"


class TestTransientClassification:
    def test_les_statuts_reessayables_sont_ceux_qui_disparaissent_seuls(self) -> None:
        assert all(is_transient_status(code) for code in (429, 500, 502, 503, 504))

    def test_un_refus_de_droits_n_est_pas_reessayable(self) -> None:
        """Une erreur 403 rejouée cinq fois reste une erreur 403 ; la
        réessayer masque un partage manquant derrière une lenteur."""
        assert not is_transient_status(403)
        assert not is_transient_status(404)
        assert not is_transient_status(400)

    def test_une_panne_reessayable_devient_DriveTransientError(self) -> None:
        service = FakeService()
        service.files().error = FakeHttpError(503)
        transport = GoogleDriveTransport(service)
        with pytest.raises(DriveTransientError):
            transport.list_children("abc", page_token=None)

    def test_une_erreur_definitive_traverse_sans_etre_convertie(self) -> None:
        service = FakeService()
        service.files().error = FakeHttpError(403)
        transport = GoogleDriveTransport(service)
        with pytest.raises(FakeHttpError):
            transport.list_children("abc", page_token=None)


class TestResponseShape:
    def test_une_reponse_sans_liste_de_fichiers_est_refusee(self) -> None:
        with pytest.raises(RuntimeError, match="files"):
            page_from_response({"nextPageToken": "x"})

    def test_une_reponse_dont_files_n_est_pas_une_liste_est_refusee(self) -> None:
        with pytest.raises(RuntimeError, match="files"):
            page_from_response({"files": "pas-une-liste"})

    def test_un_jeton_de_page_vide_vaut_fin_de_pagination(self) -> None:
        assert page_from_response({"files": [], "nextPageToken": ""}).next_page_token is None


class TestPdfExtraction:
    def test_le_texte_est_extrait_page_par_page(self, tmp_path: Path) -> None:
        pdf = build_pdf(["alpha", "beta"])
        pages = extract_pdf_pages(pdf)
        assert [p.number for p in pages] == [1, 2]
        assert "alpha" in pages[0].text
        assert "beta" in pages[1].text

    def test_deux_extractions_des_memes_octets_rendent_le_meme_texte(self) -> None:
        pdf = build_pdf(["gamma"])
        assert extract_pdf_pages(pdf) == extract_pdf_pages(pdf)

    def test_des_octets_qui_ne_sont_pas_un_pdf_sont_refuses(self) -> None:
        with pytest.raises(RuntimeError, match="illisible"):
            extract_pdf_pages(b"pas un pdf du tout")


def build_pdf(texts: list[str]) -> bytes:
    """Un PDF minimal, réel, construit sans fichier de fixture."""
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=200, height=200)
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)

        font = DictionaryObject()
        font.update(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = writer._add_object(font)
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestPageSize:
    def test_la_taille_de_page_est_reglable(self) -> None:
        service = FakeService()
        GoogleDriveTransport(service, page_size=10).list_children("abc", page_token=None)
        assert service.files().list_kwargs[0]["pageSize"] == 10

    def test_une_taille_de_page_hors_bornes_drive_est_refusee(self) -> None:
        """Drive plafonne à 1000 : au-delà, l'API rogne en silence et la
        pagination qu'on croit avoir réglée n'est plus celle qui s'exerce."""
        with pytest.raises(RuntimeError, match="hors bornes"):
            GoogleDriveTransport(FakeService(), page_size=1001)
        with pytest.raises(RuntimeError, match="hors bornes"):
            GoogleDriveTransport(FakeService(), page_size=0)
