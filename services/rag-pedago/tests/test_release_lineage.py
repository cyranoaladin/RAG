"""La lignée d'une release est déclarée une fois, et jamais désactivable (§2-§4).

**Deux défauts réels que ces tests ferment.**

Le premier : les constantes du module documentaient la lignée servie — matrice
du 31 août, onze profils `v2_livraison_319` — mais `build_release` redéfinissait
ses propres défauts en interne, ceux du 25 août. Un lecteur qui lisait les
constantes se trompait sur ce que le producteur faisait, et une exécution
« par défaut » rendait 26 documents au lieu de 320.

Le second : `FINAL_SET_SHA256 if not NEXUS_FINAL_MATRIX else ""` — changer la
matrice ÉTEIGNAIT la vérification d'empreinte de l'ensemble final. Une surcharge
de lignée pouvait donc produire n'importe quel corpus sans qu'aucun invariant
d'ensemble ne s'y oppose : un défaut fail-open, dans un producteur dont tout le
reste est fail-closed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

PRODUCER = Path(__file__).resolve().parents[1] / "scripts" / "build_production_profile_release.py"
CANONICAL_SET_SHA = "77f01c824c6be14ba6fd66eda99c2179fd87d9a2aaaf3c58e56a917d1ad5c31d"

def _module() -> Any:
    from conftest import load_producer

    return load_producer()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NEXUS_FINAL_MATRIX",
        "NEXUS_PROFILE_ROOT",
        "NEXUS_PROFILE_MANIFEST",
        "NEXUS_FINAL_SET_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)


class TestCanonicalLineageIsTheDefault:
    def test_without_any_override_the_served_lineage_is_resolved(self) -> None:
        lineage = _module().resolve_release_lineage()
        assert lineage.matrix_path.name == "matrice_production_20260831.json"
        assert lineage.profile_root.name == "v2_livraison_319"
        assert lineage.profile_manifest_path.name == (
            "ingestion_manifest_v2_livraison_319.yml"
        )
        assert lineage.expected_content_set_sha256 == CANONICAL_SET_SHA
        assert lineage.is_overridden is False

    def test_the_canonical_lineage_files_exist(self) -> None:
        """Une lignée par défaut qui ne se lit pas n'est pas une lignée."""
        lineage = _module().resolve_release_lineage()
        assert lineage.matrix_path.is_file()
        assert lineage.profile_root.is_dir()
        assert lineage.profile_manifest_path.is_file()

    def test_the_canonical_lineage_yields_the_declared_content_set(self) -> None:
        """La preuve qui compte : la lignée déclarée produit bien son digest.

        Sans elle, l'empreinte attendue serait une affirmation invérifiée."""
        import json

        module = _module()
        lineage = module.resolve_release_lineage()
        matrix = json.loads(lineage.matrix_path.read_text(encoding="utf-8"))
        collections = {p.stem for p in lineage.profile_root.glob("*.yml")}
        contents = sorted(
            {
                content
                for row in matrix
                if row["dimensions"]["collection"]["value"] in collections
                for content in row["content_sha256"]
            }
        )
        assert module._final_set_digest(contents) == lineage.expected_content_set_sha256
        assert len(contents) == 320

    def test_there_is_no_second_set_of_defaults(self) -> None:
        """`build_release` doit consommer le resolver, pas redéfinir sa lignée.

        Le défaut d'origine était exactement là : deux jeux de défauts
        divergents, dont seul le second s'appliquait."""
        source = PRODUCER.read_text(encoding="utf-8")
        body = source[source.index("def build_release("):]
        body = body[: body.index("\ndef ", 1)]
        for absent in ("NEXUS_FINAL_MATRIX", "NEXUS_PROFILE_ROOT", "NEXUS_PROFILE_MANIFEST"):
            assert absent not in body, (
                f"build_release redéfinit {absent} au lieu de consommer le resolver"
            )
        assert "resolve_release_lineage()" in body


class TestAnOverrideNeverDisablesTheDigestGuard:
    def _resolve(self):
        return _module().resolve_release_lineage()

    @pytest.mark.parametrize(
        "variable",
        ["NEXUS_FINAL_MATRIX", "NEXUS_PROFILE_ROOT", "NEXUS_PROFILE_MANIFEST"],
    )
    def test_an_override_without_an_expected_digest_is_refused(
        self, variable: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(variable, str(tmp_path / "autre"))
        with pytest.raises(ValueError, match="NEXUS_FINAL_SET_SHA256"):
            self._resolve()

    def test_an_override_with_an_expected_digest_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("NEXUS_FINAL_MATRIX", str(tmp_path / "autre.json"))
        monkeypatch.setenv("NEXUS_FINAL_SET_SHA256", "a" * 64)
        lineage = self._resolve()
        assert lineage.matrix_path == tmp_path / "autre.json"
        assert lineage.expected_content_set_sha256 == "a" * 64
        assert lineage.is_overridden is True

    def test_the_expected_digest_is_never_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Il n'existe aucun chemin par lequel l'invariant devient vide."""
        monkeypatch.setenv("NEXUS_FINAL_MATRIX", str(tmp_path / "autre.json"))
        monkeypatch.setenv("NEXUS_FINAL_SET_SHA256", "")
        with pytest.raises(ValueError, match="NEXUS_FINAL_SET_SHA256"):
            self._resolve()

    def test_a_malformed_expected_digest_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("NEXUS_FINAL_MATRIX", str(tmp_path / "autre.json"))
        monkeypatch.setenv("NEXUS_FINAL_SET_SHA256", "pas-un-digest")
        with pytest.raises(ValueError, match="SHA-256|digest"):
            self._resolve()

    def test_pinning_a_digest_without_overriding_the_lineage_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Épingler reste toujours permis ; c'est éteindre qui ne l'est pas."""
        monkeypatch.setenv("NEXUS_FINAL_SET_SHA256", "b" * 64)
        assert self._resolve().expected_content_set_sha256 == "b" * 64

    def test_the_producer_holds_no_fail_open_digest_expression(self) -> None:
        """Le motif exact qui éteignait la garde ne doit pas revenir."""
        source = PRODUCER.read_text(encoding="utf-8")
        assert 'if not os.environ.get("NEXUS_FINAL_MATRIX") else ""' not in source
