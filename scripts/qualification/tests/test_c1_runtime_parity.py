"""C1 sélectionne les releases EXACTEMENT comme le runtime — P2 ASTRA-PR153-P2-001.

Le runtime reconnaît trois mécanismes de désignation des releases et refuse
qu'ils parlent à deux. C1 n'en connaissait qu'un : sous un manifest Wave 0
(``RAG_RELEASE_MANIFEST_PATH``/``_SHA256``) ou une liste explicite
(``RAG_RELEASE_MANIFESTS_JSON``), il retombait sur le registre par défaut du
dépôt et certifiait 319 contenus là où le service en servait 2 ; sous un
registre ET un manifest, il acceptait ce que le service refuse comme ambigu.

Ces épreuves confrontent ``main`` à l'autorité du contrat —
``select_release_authority`` puis ``load_selected_release_registry`` —, celle
que le runtime consomme désormais lui aussi. L'égalité porte sur les ENSEMBLES
et sur les couples (manifest, empreinte) réellement liés, jamais sur un compte.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_promoted_content_set import (  # noqa: E402
    DEFAULT_REGISTRY,
    GOVERNED_ROOT_ENV,
    MODE_DEFAULT,
    main,
)
from nexus_release_chain.deployment_binding import (  # noqa: E402
    MANIFEST_PATH_ENV,
    MANIFEST_SHA256_ENV,
    MANIFESTS_JSON_ENV,
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    RELEASE_AUTHORITY_LEGACY_MANIFEST,
    RELEASE_AUTHORITY_MANIFEST_LIST,
    RELEASE_AUTHORITY_REGISTRY_FILE,
    load_selected_release_registry,
    select_release_authority,
)
from verify_corpus_cas import content_set_digest  # noqa: E402

TOUTES_LES_VARIABLES = (
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    MANIFESTS_JSON_ENV,
    MANIFEST_PATH_ENV,
    MANIFEST_SHA256_ENV,
    GOVERNED_ROOT_ENV,
)

RELEASES = DEFAULT_REGISTRY.parent
WAVE0 = RELEASES / "wave0" / "wave0.release.json"
MULTILEVEL = RELEASES / "multilevel" / "multilevel.release.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _aucune_liaison_heritee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le verdict ne doit dépendre d'aucune variable du shell qui lance."""
    for variable in TOUTES_LES_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def _runtime(env: dict[str, str]) -> tuple[list[list[str]], set[str]]:
    """Ce que le runtime tient en main pour cette configuration : les couples
    liés et l'ensemble des contenus — par l'autorité du contrat."""
    selection = select_release_authority(env)
    assert selection is not None
    registre = load_selected_release_registry(selection)
    liaisons = sorted([str(m.path), m.expected_sha256] for m in registre.manifests)
    contenus = {a.content_sha256 for m in registre.manifests for a in m.expectation.artifacts}
    return liaisons, contenus


def _c1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str], argv: tuple[str, ...] = ()
) -> tuple[int, dict | None, str]:
    for cle, valeur in env.items():
        monkeypatch.setenv(cle, valeur)
    sortie = tmp_path / "promoted.json"
    code = main([*argv, "--output", str(sortie)])
    charge = json.loads(sortie.read_text(encoding="utf-8")) if sortie.exists() else None
    return code, charge, ""


def _cas_wave0_legacy() -> dict[str, str]:
    return {MANIFEST_PATH_ENV: str(WAVE0), MANIFEST_SHA256_ENV: _sha(WAVE0)}


def _cas_wave0_liste() -> dict[str, str]:
    return {MANIFESTS_JSON_ENV: json.dumps([{"path": str(WAVE0), "sha256": _sha(WAVE0)}])}


def _cas_wave0_et_multilevel() -> dict[str, str]:
    return {
        MANIFESTS_JSON_ENV: json.dumps(
            [
                {"path": str(WAVE0), "sha256": _sha(WAVE0)},
                {"path": str(MULTILEVEL), "sha256": _sha(MULTILEVEL)},
            ]
        )
    }


def _cas_registre() -> dict[str, str]:
    return {REGISTRY_PATH_ENV: str(DEFAULT_REGISTRY), REGISTRY_SHA256_ENV: _sha(DEFAULT_REGISTRY)}


# --- P2 : le manifest Wave 0 sélectionné est celui que C1 qualifie ----------


@pytest.mark.parametrize(
    ("configuration", "mecanisme"),
    [
        (_cas_wave0_legacy, RELEASE_AUTHORITY_LEGACY_MANIFEST),
        (_cas_wave0_liste, RELEASE_AUTHORITY_MANIFEST_LIST),
        (_cas_wave0_et_multilevel, RELEASE_AUTHORITY_MANIFEST_LIST),
        (_cas_registre, RELEASE_AUTHORITY_REGISTRY_FILE),
    ],
)
def test_c1_rend_exactement_l_ensemble_que_le_runtime_selectionne(
    configuration, mecanisme: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Le cas Astra : Wave 0 seul, runtime 2 contenus, C1 319 sur son défaut."""
    env = configuration()
    liaisons_runtime, contenus_runtime = _runtime(env)
    assert contenus_runtime, "la configuration doit désigner des contenus"

    code, charge, _ = _c1(monkeypatch, tmp_path, env)

    assert code == 0
    assert charge is not None
    assert charge["release_registry_source"] != MODE_DEFAULT, (
        "un déploiement parle : C1 ne retombe jamais sur le défaut du dépôt"
    )
    assert set(charge["content_sha256"]) == contenus_runtime
    assert charge["count"] == len(contenus_runtime)
    assert charge["content_set_sha256"] == content_set_digest(contenus_runtime)
    assert charge["release_authority"]["mechanism"] == mecanisme
    assert charge["release_authority"]["bindings"] == liaisons_runtime


def test_le_manifest_wave0_seul_ne_donne_pas_le_registre_par_defaut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Le contre-exemple exact : deux ensembles DIFFÉRENTS, pas deux comptes."""
    _liaisons, wave0 = _runtime(_cas_wave0_legacy())
    _liaisons, registre = _runtime(_cas_registre())
    assert wave0 != registre
    assert wave0 - registre, "Wave 0 porte des contenus que le registre ne porte pas"

    code, charge, _ = _c1(monkeypatch, tmp_path, _cas_wave0_legacy())

    assert code == 0 and charge is not None
    assert set(charge["content_sha256"]) == wave0
    assert set(charge["content_sha256"]) != registre
    # Le mode est une valeur PUBLIÉE de la preuve : on l'affirme en toutes lettres.
    assert charge["release_registry_source"] == "DEPLOYMENT_MANIFESTS"


# --- P2 : ce que le runtime refuse, C1 le refuse aussi ----------------------


@pytest.mark.parametrize(
    "configuration",
    [
        {**_cas_registre(), **_cas_wave0_legacy()},
        {**_cas_registre(), **_cas_wave0_liste()},
        {**_cas_wave0_legacy(), **_cas_wave0_liste()},
        {**_cas_registre(), **_cas_wave0_legacy(), **_cas_wave0_liste()},
        {**_cas_registre(), MANIFESTS_JSON_ENV: "[]"},
    ],
    ids=["registre+legacy", "registre+liste", "legacy+liste", "les trois", "registre+liste vide"],
)
def test_une_configuration_ambigue_est_refusee_comme_par_le_runtime(
    configuration: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, charge, _ = _c1(monkeypatch, tmp_path, configuration)
    assert code == 2
    assert charge is None
    assert "ambiguous" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("configuration", "motif"),
    [
        ({MANIFEST_PATH_ENV: str(WAVE0)}, "incomplete"),
        ({MANIFEST_SHA256_ENV: "a" * 64}, "incomplete"),
        ({MANIFEST_PATH_ENV: "", MANIFEST_SHA256_ENV: "a" * 64}, "incomplete"),
        ({MANIFEST_PATH_ENV: str(WAVE0), MANIFEST_SHA256_ENV: ""}, "incomplete"),
        ({MANIFESTS_JSON_ENV: ""}, "not valid JSON"),
        ({MANIFESTS_JSON_ENV: "{nope"}, "not valid JSON"),
        ({MANIFESTS_JSON_ENV: "{}"}, "must be an array"),
        ({MANIFESTS_JSON_ENV: json.dumps([{"path": str(WAVE0)}])}, "entry 0 is invalid"),
        ({MANIFESTS_JSON_ENV: json.dumps([{"path": "  ", "sha256": "a" * 64}])}, "entry 0 is invalid"),
        ({MANIFESTS_JSON_ENV: "[]"}, "must not be empty"),
        ({MANIFEST_PATH_ENV: str(WAVE0), MANIFEST_SHA256_ENV: "0" * 64}, "digest mismatch"),
    ],
    ids=[
        "legacy chemin seul", "legacy empreinte seule", "legacy chemin vide", "legacy empreinte vide",
        "liste vide (chaîne)", "liste JSON invalide", "liste objet", "entrée sans sha256",
        "entrée chemin blanc", "liste []", "legacy mauvaise empreinte",
    ],
)
def test_une_liaison_par_manifests_invalide_est_un_refus_nomme(
    configuration: dict[str, str],
    motif: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Le runtime refuse ; C1 refusait… en rendant 319 contenus, code 0."""
    code, charge, _ = _c1(monkeypatch, tmp_path, configuration)
    assert code == 2, "un déploiement qui parle de travers n'est jamais un repli sur le défaut"
    assert charge is None
    erreur = capsys.readouterr().err
    assert "PROMOTED_CONTENT_SET_INVALID" in erreur
    assert motif in erreur


# --- la matrice de précédence connaît la liaison par manifests --------------


def test_une_candidate_explicite_et_une_liaison_par_manifests_sont_deux_autorites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _c1(
        monkeypatch,
        tmp_path,
        _cas_wave0_legacy(),
        ("--release-registry", str(DEFAULT_REGISTRY), "--release-registry-sha256", _sha(DEFAULT_REGISTRY)),
    )
    assert code == 2
    assert "deux autorités" in capsys.readouterr().err


def test_une_empreinte_de_registre_ne_scelle_pas_une_liaison_par_manifests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _c1(monkeypatch, tmp_path, _cas_wave0_legacy(), ("--release-registry-sha256", "b" * 64))
    assert code == 2
    assert "ne s'applique pas" in capsys.readouterr().err


# --- le bornage s'exerce aussi sur les manifests désignés -------------------


def test_un_manifest_hors_de_la_racine_declaree_est_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(GOVERNED_ROOT_ENV, str(tmp_path))
    code, _, _ = _c1(monkeypatch, tmp_path, _cas_wave0_legacy())
    assert code == 2
    assert "hors de la racine gouvernée" in capsys.readouterr().err


def test_un_manifest_atteint_par_un_lien_symbolique_est_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    alias = tmp_path / "wave0-alias"
    alias.symlink_to(WAVE0.parent, target_is_directory=True)
    code, _, _ = _c1(
        monkeypatch,
        tmp_path,
        {MANIFEST_PATH_ENV: str(alias / WAVE0.name), MANIFEST_SHA256_ENV: _sha(WAVE0)},
    )
    assert code == 2
    assert "lien symbolique" in capsys.readouterr().err


def test_un_manifest_relatif_est_refuse_en_deploiement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _c1(
        monkeypatch,
        tmp_path,
        {MANIFEST_PATH_ENV: "wave0/wave0.release.json", MANIFEST_SHA256_ENV: _sha(WAVE0)},
    )
    assert code == 2
    assert "n'est pas absolu" in capsys.readouterr().err


# --- une seule écriture de la sélection ------------------------------------


def test_le_runtime_consomme_la_selection_du_contrat_sans_la_reecrire() -> None:
    """Le runtime appelle la sélection ET le chargement du contrat ; il ne lit
    plus aucune des cinq variables lui-même, et ne porte plus le mot
    « ambiguous » : la règle n'est écrite qu'une fois."""
    racine = Path(__file__).resolve().parents[3]
    module_runtime = racine / "services" / "rag-engine" / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    if not module_runtime.is_file():
        pytest.skip("module runtime absent de ce checkout")
    source = module_runtime.read_text(encoding="utf-8")

    assert "select_release_authority(" in source
    assert "load_selected_release_registry(" in source
    for litteral in TOUTES_LES_VARIABLES:
        assert litteral not in source, f"le runtime relit {litteral} lui-même"
    assert "ambiguous" not in source.replace("scope source SHA is ambiguous", "")
    assert "release manifest configuration" not in source
    assert "json.loads" not in source


def test_c1_ne_lit_aucune_variable_de_liaison_lui_meme() -> None:
    import compute_promoted_content_set as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for litteral in TOUTES_LES_VARIABLES[:-1]:
        assert litteral not in source, f"C1 relit {litteral} lui-même : seconde écriture"
    assert "select_release_authority(" in source
