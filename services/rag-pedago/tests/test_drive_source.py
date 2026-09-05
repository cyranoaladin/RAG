"""Tests de la frontière source Google Drive.

Le transport est injecté : aucun test n'ouvre de connexion réseau, et
aucun identifiant réel n'entre dans le dépôt. Ce que ces tests
protègent n'est pas « l'adaptateur marche », mais les quatre propriétés
sans lesquelles une découverte Drive n'est pas gouvernable :

- la découverte est **reprenable** — une panne au milieu d'une
  pagination ne redonne pas deux fois les mêmes objets ;
- une **occurrence logique n'est pas un artefact physique** — un
  raccourci vers un fichier déjà vu ne crée ni artefact ni
  téléchargement supplémentaire ;
- une **réponse partielle est refusée**, jamais complétée en silence ;
- les **exclusions gouvernées sont nommées**, jamais comptées comme des
  erreurs ni oubliées.
"""
from __future__ import annotations

import hashlib
from typing import Any

import pytest

from rag_pedago.governance.drive_source import (
    CONTROL_PLANE_ZONES,
    EXCLUSION_GOVERNED_SOURCE_CLASS,
    EXCLUSION_UNSTABLE_EXPORT,
    NON_INGESTABLE_SUBTREES,
    SOURCE_KIND,
    DriveObject,
    DrivePage,
    DriveSourceAdapter,
    DriveSourceError,
    DriveTransientError,
    taxonomy_hints_from_path,
)

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
NATIVE_DOC = "application/vnd.google-apps.document"
PDF = "application/pdf"

ROOT_ID = "root-folder"
ROOT_NAME = "NEXUS_RAG_GDRIVE_READY"


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FakeTransport:
    """Un Drive en mémoire qui pagine réellement.

    Il enregistre chaque appel : c'est ce journal, et non une assertion
    sur un compteur interne de l'adaptateur, qui prouve qu'un même
    fichier n'a pas été retéléchargé.
    """

    def __init__(
        self,
        entries: dict[str, list[dict[str, Any]]],
        blobs: dict[str, bytes] | None = None,
        *,
        page_size: int = 100,
    ) -> None:
        self.entries = entries
        self.blobs = blobs or {}
        self.page_size = page_size
        self.list_calls: list[tuple[str, str | None]] = []
        self.fetch_calls: list[str] = []
        self.export_calls: list[tuple[str, str]] = []
        self.metadata_calls: list[str] = []
        #: scripts d'échec : (folder_id, numéro d'appel) -> exception
        self.list_failures: dict[tuple[str, int], BaseException] = {}
        #: page renvoyée telle quelle, court-circuitant la pagination
        self.forced_pages: dict[tuple[str, str | None], DrivePage] = {}

    # -- transport ----------------------------------------------------
    def list_children(self, folder_id: str, *, page_token: str | None) -> DrivePage:
        seen = sum(1 for fid, _ in self.list_calls if fid == folder_id)
        self.list_calls.append((folder_id, page_token))
        failure = self.list_failures.pop((folder_id, seen), None)
        if failure is not None:
            raise failure
        forced = self.forced_pages.get((folder_id, page_token))
        if forced is not None:
            return forced
        children = self.entries.get(folder_id, [])
        start = int(page_token) if page_token else 0
        window = children[start : start + self.page_size]
        nxt = start + self.page_size
        return DrivePage(
            entries=tuple(window),
            next_page_token=str(nxt) if nxt < len(children) else None,
        )

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        self.metadata_calls.append(file_id)
        for children in self.entries.values():
            for child in children:
                if child["id"] == file_id:
                    return child
        raise KeyError(file_id)

    def fetch(self, file_id: str) -> bytes:
        self.fetch_calls.append(file_id)
        return self.blobs[file_id]

    def export(self, file_id: str, *, mime_type: str) -> bytes:
        self.export_calls.append((file_id, mime_type))
        return f"export:{file_id}:{mime_type}".encode()


def entry(
    file_id: str,
    name: str,
    mime: str = PDF,
    *,
    size: int | None = None,
    modified: str = "2026-08-05T01:53:07.337Z",
    target: str | None = None,
    target_mime: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "modifiedTime": modified,
    }
    if mime != FOLDER and mime != SHORTCUT:
        record["size"] = str(size if size is not None else 10)
    if target is not None:
        record["shortcutDetails"] = {
            "targetId": target,
            "targetMimeType": target_mime or PDF,
        }
    return record


def adapter(transport: FakeTransport, **kwargs: Any) -> DriveSourceAdapter:
    return DriveSourceAdapter(
        transport,
        root_folder_id=ROOT_ID,
        root_name=ROOT_NAME,
        **kwargs,
    )


def simple_tree() -> FakeTransport:
    """Racine → une zone → deux PDF, plus un dossier vide."""
    blobs = {"f1": b"un", "f2": b"deux-deux"}
    return FakeTransport(
        {
            ROOT_ID: [
                entry("z1", "01_EDUSCOL_OFFICIEL", FOLDER),
                entry("z2", "02_NEXUS_DIAGNOSTICS", FOLDER),
            ],
            "z1": [
                entry("sub", "LYCEE", FOLDER),
            ],
            "sub": [
                entry("f1", "a.pdf", size=len(blobs["f1"])),
                entry("f2", "b.pdf", size=len(blobs["f2"])),
            ],
            "z2": [],
        },
        blobs,
    )


# ---------------------------------------------------------------------
# découverte
# ---------------------------------------------------------------------


def test_la_decouverte_est_recursive_et_porte_le_chemin_complet() -> None:
    transport = simple_tree()
    objects = adapter(transport).discover()

    assert [obj.drive_path for obj in objects] == [
        f"{ROOT_NAME}/01_EDUSCOL_OFFICIEL/LYCEE/a.pdf",
        f"{ROOT_NAME}/01_EDUSCOL_OFFICIEL/LYCEE/b.pdf",
    ]


def test_chaque_objet_porte_le_contrat_de_metadonnees_complet() -> None:
    transport = simple_tree()
    obj = adapter(transport).discover()[0]

    assert obj.source_kind == SOURCE_KIND == "GOOGLE_DRIVE"
    assert obj.source_id == f"GOOGLE_DRIVE:{ROOT_NAME}/01_EDUSCOL_OFFICIEL/LYCEE/a.pdf"
    assert obj.drive_file_id == "f1"
    assert obj.mime_type == PDF
    assert obj.modified_time == "2026-08-05T01:53:07.337Z"
    assert obj.size == 2
    assert obj.zone == "01_EDUSCOL_OFFICIEL"
    assert obj.taxonomy_hints == ("01_EDUSCOL_OFFICIEL", "LYCEE")


def test_les_indices_de_taxonomie_viennent_du_chemin_parent_pas_du_nom() -> None:
    hints = taxonomy_hints_from_path(
        f"{ROOT_NAME}/01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/MATHEMATIQUES/2026/x.pdf",
        root_name=ROOT_NAME,
    )
    assert hints == (
        "01_EDUSCOL_OFFICIEL",
        "LYCEE",
        "TERMINALE",
        "MATHEMATIQUES",
        "2026",
    )


def test_le_chemin_relatif_est_celui_qu_attend_l_acquisition_gouvernee() -> None:
    transport = simple_tree()
    obj = adapter(transport).discover()[0]
    # acquire_corpus indexe par chemin relatif à la racine, sans le nom
    # de la racine : c'est aussi la clé du manifeste livré par la source.
    assert obj.relative_path == "01_EDUSCOL_OFFICIEL/LYCEE/a.pdf"


def test_deux_decouvertes_du_meme_instantane_donnent_les_memes_objets() -> None:
    transport = simple_tree()
    first = adapter(transport).discover()
    second = adapter(transport).discover()
    assert first == second


# ---------------------------------------------------------------------
# pagination réelle
# ---------------------------------------------------------------------


def test_la_pagination_traverse_plusieurs_pages() -> None:
    children = [entry(f"f{i}", f"{i:02d}.pdf") for i in range(7)]
    transport = FakeTransport({ROOT_ID: children}, page_size=3)

    objects = adapter(transport).discover()

    assert len(objects) == 7
    # trois pages : jetons None, "3", "6"
    assert [token for fid, token in transport.list_calls if fid == ROOT_ID] == [
        None,
        "3",
        "6",
    ]


def test_un_jeton_de_page_rejoue_est_refuse_au_lieu_de_boucler() -> None:
    transport = FakeTransport({ROOT_ID: [entry("f1", "a.pdf")]})
    # la source renvoie le jeton qu'elle vient de consommer
    transport.forced_pages[(ROOT_ID, None)] = DrivePage(
        entries=(entry("f1", "a.pdf"),), next_page_token="tok"
    )
    transport.forced_pages[(ROOT_ID, "tok")] = DrivePage(
        entries=(entry("f2", "b.pdf"),), next_page_token="tok"
    )

    with pytest.raises(DriveSourceError, match="jeton de page"):
        adapter(transport).discover()


def test_un_jeton_rejoue_ne_duplique_pas_ce_qui_a_deja_ete_emis() -> None:
    """Le refus doit survenir avant qu'un objet soit émis deux fois."""
    transport = FakeTransport({ROOT_ID: [entry("f1", "a.pdf")]})
    transport.forced_pages[(ROOT_ID, None)] = DrivePage(
        entries=(entry("f1", "a.pdf"),), next_page_token="tok"
    )
    transport.forced_pages[(ROOT_ID, "tok")] = DrivePage(
        entries=(entry("f1", "a.pdf"),), next_page_token="tok"
    )
    with pytest.raises(DriveSourceError):
        adapter(transport).discover()


def test_une_reponse_partielle_est_refusee_pas_completee() -> None:
    transport = FakeTransport({ROOT_ID: []})
    transport.forced_pages[(ROOT_ID, None)] = DrivePage(
        entries=({"id": "f1", "name": "a.pdf"},),  # mimeType manquant
        next_page_token=None,
    )
    with pytest.raises(DriveSourceError, match="mimeType"):
        adapter(transport).discover()


def test_un_fichier_sans_taille_declaree_est_refuse() -> None:
    transport = FakeTransport({ROOT_ID: []})
    transport.forced_pages[(ROOT_ID, None)] = DrivePage(
        entries=(
            {
                "id": "f1",
                "name": "a.pdf",
                "mimeType": PDF,
                "modifiedTime": "2026-01-01T00:00:00.000Z",
            },
        ),
        next_page_token=None,
    )
    with pytest.raises(DriveSourceError, match="size"):
        adapter(transport).discover()


# ---------------------------------------------------------------------
# reprise après panne
# ---------------------------------------------------------------------


def test_une_panne_reseau_laisse_une_decouverte_reprenable_sans_duplication() -> None:
    children = [entry(f"f{i}", f"{i:02d}.pdf") for i in range(6)]
    transport = FakeTransport({ROOT_ID: children}, page_size=2)
    # panne définitive au troisième appel de list sur la racine
    transport.list_failures[(ROOT_ID, 2)] = OSError("connexion perdue")

    src = adapter(transport, max_attempts=1)
    state = src.start()
    collected: list[DriveObject] = []
    with pytest.raises(OSError):
        while not state.exhausted:
            batch, state = src.step(state)
            collected.extend(batch)

    assert [obj.drive_file_id for obj in collected] == ["f0", "f1", "f2", "f3"]

    # reprise depuis l'état conservé : ni perte ni doublon
    resumed: list[DriveObject] = []
    while not state.exhausted:
        batch, state = src.step(state)
        resumed.extend(batch)

    assert [obj.drive_file_id for obj in resumed] == ["f4", "f5"]
    assert len(collected) + len(resumed) == 6


def test_l_etat_n_avance_pas_quand_la_page_echoue() -> None:
    children = [entry(f"f{i}", f"{i:02d}.pdf") for i in range(4)]
    transport = FakeTransport({ROOT_ID: children}, page_size=2)
    transport.list_failures[(ROOT_ID, 1)] = OSError("coupure")

    src = adapter(transport, max_attempts=1)
    state = src.start()
    _, state = src.step(state)
    before = state
    with pytest.raises(OSError):
        src.step(state)
    assert state == before


def test_les_retries_sont_bornes_et_transparents_sur_429() -> None:
    children = [entry("f0", "a.pdf")]
    transport = FakeTransport({ROOT_ID: children})
    transport.list_failures[(ROOT_ID, 0)] = DriveTransientError("429 rate limited")

    slept: list[float] = []
    objects = adapter(
        transport, max_attempts=3, sleep=slept.append
    ).discover()

    assert [obj.drive_file_id for obj in objects] == ["f0"]
    assert len(slept) == 1


def test_les_retries_epuises_remontent_l_erreur_sans_resultat_partiel() -> None:
    transport = FakeTransport({ROOT_ID: [entry("f0", "a.pdf")]})
    for attempt in range(3):
        transport.list_failures[(ROOT_ID, attempt)] = DriveTransientError("503")

    with pytest.raises(DriveTransientError):
        adapter(transport, max_attempts=3, sleep=lambda _: None).discover()


def test_une_erreur_non_transitoire_n_est_pas_reessayee() -> None:
    transport = FakeTransport({ROOT_ID: [entry("f0", "a.pdf")]})
    transport.list_failures[(ROOT_ID, 0)] = PermissionError("403")

    with pytest.raises(PermissionError):
        adapter(transport, max_attempts=5, sleep=lambda _: None).discover()
    assert len(transport.list_calls) == 1


# ---------------------------------------------------------------------
# raccourcis
# ---------------------------------------------------------------------


def shortcut_tree() -> FakeTransport:
    blobs = {"f1": b"contenu-partage"}
    return FakeTransport(
        {
            ROOT_ID: [
                entry("z1", "01_EDUSCOL_OFFICIEL", FOLDER),
                entry("z2", "04_COMPLEMENTS_PEDAGOGIQUES", FOLDER),
            ],
            "z1": [entry("f1", "reel.pdf", size=len(blobs["f1"]))],
            "z2": [entry("sc1", "alias.pdf", SHORTCUT, target="f1")],
        },
        blobs,
    )


def test_un_raccourci_est_resolu_vers_le_fichier_cible() -> None:
    transport = shortcut_tree()
    objects = adapter(transport).discover()
    alias = next(o for o in objects if o.drive_path.endswith("alias.pdf"))

    assert alias.drive_file_id == "f1"
    assert alias.mime_type == PDF
    assert alias.shortcut_id == "sc1"


def test_deux_occurrences_du_meme_fichier_donnent_une_seule_identite() -> None:
    transport = shortcut_tree()
    src = adapter(transport)
    artifacts = src.materialise(src.discover())

    assert len(artifacts) == 1
    only = artifacts[0]
    assert only.content_sha256 == sha(b"contenu-partage")
    assert only.occurrences == (
        "01_EDUSCOL_OFFICIEL/reel.pdf",
        "04_COMPLEMENTS_PEDAGOGIQUES/alias.pdf",
    )


def test_une_occurrence_supplementaire_ne_retelecharge_pas_les_memes_octets() -> None:
    transport = shortcut_tree()
    src = adapter(transport)
    src.materialise(src.discover())

    assert transport.fetch_calls == ["f1"]


def test_un_raccourci_vers_un_dossier_est_traverse_une_seule_fois() -> None:
    transport = FakeTransport(
        {
            ROOT_ID: [
                entry("z1", "01_EDUSCOL_OFFICIEL", FOLDER),
                entry("sc", "raccourci_zone", SHORTCUT, target="z1", target_mime=FOLDER),
            ],
            "z1": [entry("f1", "a.pdf")],
        },
        {"f1": b"x" * 10},
    )
    objects = adapter(transport).discover()
    # le dossier cible n'est visité qu'une fois : pas de second a.pdf
    assert [o.drive_path for o in objects] == [
        f"{ROOT_NAME}/01_EDUSCOL_OFFICIEL/a.pdf"
    ]


def test_un_cycle_de_dossiers_est_refuse_pas_parcouru_indefiniment() -> None:
    transport = FakeTransport(
        {
            ROOT_ID: [entry("z1", "A", FOLDER)],
            "z1": [entry("sc", "retour", SHORTCUT, target=ROOT_ID, target_mime=FOLDER)],
        }
    )
    objects = adapter(transport).discover()
    # le cycle est neutralisé par le suivi des dossiers visités
    assert objects == []
    assert transport.list_calls.count((ROOT_ID, None)) == 1


# ---------------------------------------------------------------------
# exclusions gouvernées
# ---------------------------------------------------------------------


def test_les_sous_arbres_non_ingestibles_sont_exclus_nommement_pas_en_erreur() -> None:
    assert "ARCHIVES_SOURCES_NON_INGESTABLES" in NON_INGESTABLE_SUBTREES
    assert "OUTILS_NEXUS_NON_INGESTABLES" in NON_INGESTABLE_SUBTREES

    transport = FakeTransport(
        {
            ROOT_ID: [
                entry("z1", "01_EDUSCOL_OFFICIEL", FOLDER),
                entry("na", "ARCHIVES_SOURCES_NON_INGESTABLES", FOLDER),
            ],
            "z1": [entry("f1", "a.pdf")],
            "na": [entry("f9", "vieux.pdf")],
        },
        {"f1": b"x" * 10},
    )
    src = adapter(transport)
    objects = src.discover()

    assert [o.drive_file_id for o in objects] == ["f1"]
    assert src.exclusions == (
        (
            f"{ROOT_NAME}/ARCHIVES_SOURCES_NON_INGESTABLES",
            EXCLUSION_GOVERNED_SOURCE_CLASS,
        ),
    )
    # le sous-arbre exclu n'est même pas énuméré
    assert all(fid != "na" for fid, _ in transport.list_calls)


def test_les_zones_de_plan_de_controle_sont_decouvertes_mais_non_servables() -> None:
    assert CONTROL_PLANE_ZONES == frozenset({"00_ADMIN", "00_INDEX_PROVENANCE"})
    transport = FakeTransport(
        {
            ROOT_ID: [
                entry("a", "00_ADMIN", FOLDER),
                entry("z", "01_EDUSCOL_OFFICIEL", FOLDER),
            ],
            "a": [entry("m", "SHA256SUMS.txt", "text/plain")],
            "z": [entry("f1", "a.pdf")],
        }
    )
    objects = {o.drive_file_id: o for o in adapter(transport).discover()}

    assert objects["m"].servable is False
    assert objects["f1"].servable is True


def test_un_objet_google_natif_est_exclu_car_ses_octets_ne_sont_pas_stables() -> None:
    transport = FakeTransport(
        {ROOT_ID: [entry("d1", "note", NATIVE_DOC)]},
    )
    src = adapter(transport)
    objects = src.discover()

    assert objects == []
    assert src.exclusions == (
        (f"{ROOT_NAME}/note", EXCLUSION_UNSTABLE_EXPORT),
    )


def test_l_export_d_un_natif_reste_disponible_hors_acquisition_scellee() -> None:
    transport = FakeTransport({ROOT_ID: [entry("d1", "note", NATIVE_DOC)]})
    src = adapter(transport)
    payload = src.export("d1", mime_type="text/plain")

    assert payload == b"export:d1:text/plain"
    assert transport.export_calls == [("d1", "text/plain")]


# ---------------------------------------------------------------------
# passage à l'acquisition gouvernée
# ---------------------------------------------------------------------


def test_l_adaptateur_produit_les_drive_file_attendus_par_l_acquisition() -> None:
    transport = simple_tree()
    src = adapter(transport)
    objects = src.discover()
    files = src.to_drive_files(objects)

    assert [(f.file_id, f.relative_path, f.mime_type, f.size_bytes) for f in files] == [
        ("f1", "01_EDUSCOL_OFFICIEL/LYCEE/a.pdf", PDF, 2),
        ("f2", "01_EDUSCOL_OFFICIEL/LYCEE/b.pdf", PDF, 9),
    ]


def test_le_telechargement_gouverne_passe_par_le_cache_de_l_adaptateur() -> None:
    transport = simple_tree()
    src = adapter(transport)
    assert src.download("f1") == b"un"
    assert src.download("f1") == b"un"
    assert transport.fetch_calls == ["f1"]


def test_une_taille_annoncee_fausse_est_refusee_a_la_materialisation() -> None:
    transport = FakeTransport(
        {ROOT_ID: [entry("f1", "a.pdf", size=999)]},
        {"f1": b"court"},
    )
    src = adapter(transport)
    with pytest.raises(DriveSourceError, match="999"):
        src.materialise(src.discover())
