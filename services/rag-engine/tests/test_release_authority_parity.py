"""Le runtime sélectionne et charge les releases PAR le contrat — P2 ASTRA-PR153-P2-001.

``retrieval_v2_endpoint`` portait sa propre écriture de la sélection des trois
mécanismes ; le qualificateur C1 n'en consommait qu'un tiers et divergeait.
La sélection vit désormais dans ``release_readiness`` — le module que cette
image embarque octet pour octet — et le runtime ne fait que l'appeler puis
traduire le type d'erreur vers celui qu'il remonte à l'appelant HTTP.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexus_release_chain import release_readiness as readiness  # noqa: E402
from ingestor import retrieval_v2_endpoint as endpoint  # noqa: E402

RELEASES = (
    Path(__file__).resolve().parents[3]
    / "services" / "rag-pedago" / "data" / "releases" / "prerentree_2026_2027"
)
REGISTRY = RELEASES / "release-registry.json"
WAVE0 = RELEASES / "wave0" / "wave0.release.json"
MULTILEVEL = RELEASES / "multilevel" / "multilevel.release.json"
VARIABLES = (
    "RAG_RELEASE_REGISTRY_PATH",
    "RAG_RELEASE_REGISTRY_SHA256",
    "RAG_RELEASE_MANIFESTS_JSON",
    "RAG_RELEASE_MANIFEST_PATH",
    "RAG_RELEASE_MANIFEST_SHA256",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _environnement_vierge(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def _poser(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for cle, valeur in env.items():
        monkeypatch.setenv(cle, valeur)


@pytest.mark.parametrize(
    "configuration",
    [
        lambda: {"RAG_RELEASE_REGISTRY_PATH": str(REGISTRY), "RAG_RELEASE_REGISTRY_SHA256": _sha(REGISTRY)},
        lambda: {"RAG_RELEASE_MANIFEST_PATH": str(WAVE0), "RAG_RELEASE_MANIFEST_SHA256": _sha(WAVE0)},
        lambda: {"RAG_RELEASE_MANIFESTS_JSON": json.dumps([{"path": str(WAVE0), "sha256": _sha(WAVE0)}])},
        lambda: {
            "RAG_RELEASE_MANIFESTS_JSON": json.dumps(
                [{"path": str(WAVE0), "sha256": _sha(WAVE0)}, {"path": str(MULTILEVEL), "sha256": _sha(MULTILEVEL)}]
            )
        },
    ],
    ids=["registre", "legacy wave0", "liste wave0", "liste wave0+multilevel"],
)
def test_le_runtime_charge_exactement_ce_que_la_selection_du_contrat_designe(
    configuration, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = configuration()
    _poser(monkeypatch, env)

    par_le_runtime = endpoint._configured_release_registry()
    selection = readiness.select_release_authority(env)
    assert selection is not None
    par_le_contrat = readiness.load_selected_release_registry(selection)

    assert par_le_runtime == par_le_contrat
    assert par_le_runtime is not None
    liaisons_runtime = sorted((str(m.path), m.expected_sha256) for m in par_le_runtime.manifests)
    liaisons_contrat = sorted((str(m.path), m.expected_sha256) for m in par_le_contrat.manifests)
    assert liaisons_runtime == liaisons_contrat


def test_sans_configuration_le_runtime_ne_charge_rien() -> None:
    assert endpoint._configured_release_registry() is None


@pytest.mark.parametrize(
    ("configuration", "motif"),
    [
        ({"RAG_RELEASE_REGISTRY_PATH": str(REGISTRY)}, "incomplete"),
        ({"RAG_RELEASE_MANIFEST_PATH": str(WAVE0)}, "incomplete"),
        ({"RAG_RELEASE_REGISTRY_PATH": str(REGISTRY), "RAG_RELEASE_REGISTRY_SHA256": "a" * 64, "RAG_RELEASE_MANIFESTS_JSON": "[]"}, "ambiguous"),
        ({"RAG_RELEASE_MANIFEST_PATH": str(WAVE0), "RAG_RELEASE_MANIFEST_SHA256": "a" * 64, "RAG_RELEASE_MANIFESTS_JSON": "[]"}, "ambiguous"),
        ({"RAG_RELEASE_MANIFESTS_JSON": "{nope"}, "not valid JSON"),
        ({"RAG_RELEASE_MANIFESTS_JSON": "{}"}, "must be an array"),
        ({"RAG_RELEASE_MANIFESTS_JSON": json.dumps([{"path": str(WAVE0)}])}, "entry 0 is invalid"),
        ({"RAG_RELEASE_MANIFESTS_JSON": "[]"}, "must not be empty"),
    ],
)
def test_un_refus_du_contrat_remonte_comme_erreur_de_readiness(
    configuration: dict[str, str], motif: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le type d'erreur est celui que le service remonte à l'appelant HTTP ;
    le message est celui du contrat, mot pour mot."""
    _poser(monkeypatch, configuration)
    with pytest.raises(readiness.ReleaseReadinessError, match=motif):
        endpoint._configured_release_registry()
    assert endpoint._release_evidence_for_collection("rag_nexus_maths_troisieme_tc") is False


def test_le_runtime_ne_porte_plus_de_seconde_ecriture_de_la_selection() -> None:
    """Les deux sélecteurs privés ont disparu ; la façade unique reste."""
    assert not hasattr(endpoint, "_configured_release_manifest")
    assert not hasattr(endpoint, "_configured_release_registry_file")
    assert callable(endpoint._configured_release_registry)
    source = Path(endpoint.__file__).read_text(encoding="utf-8")
    for variable in VARIABLES:
        assert variable not in source
