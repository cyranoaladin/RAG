"""Un repli d'import ne doit jamais renommer la cause réelle.

Le défaut fermé ici a coûté un diagnostic entier : une dépendance
transitive manquante ressortait en ``ModuleNotFoundError: No module named
'retrieval_v2_endpoint'`` — un module parfaitement présent. Le repli
réessayait le même code par un autre chemin, échouait pour la même
raison, et c'est *son* message qui remontait.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest

from src.ingestor._import_compat import (
    import_first_available,
    is_missing_module,
    legacy_candidates,
)


@pytest.fixture
def clean_modules():
    """Retire les modules synthétiques après chaque test."""
    created: list[str] = []
    yield created
    for name in created:
        sys.modules.pop(name, None)


def install(name: str, registry: list[str], *, body=None) -> types.ModuleType:
    module = types.ModuleType(name)
    if body is not None:
        body(module)
    sys.modules[name] = module
    registry.append(name)
    return module


class TestA_CanonicalImportWorks:
    def test_the_package_form_is_preferred(self, clean_modules) -> None:
        """La forme paquet doit gagner : sinon un même module vivrait sous
        deux identités, avec deux états globaux distincts."""
        install("fakepkg", clean_modules)
        install("fakepkg.target", clean_modules)
        install("target", clean_modules)

        resolved = import_first_available("target", package="fakepkg")
        assert resolved is sys.modules["fakepkg.target"]

    def test_the_legacy_form_is_used_when_the_package_form_is_absent(
        self, clean_modules
    ) -> None:
        install("legacy_only_target", clean_modules)
        resolved = import_first_available(
            "legacy_only_target", candidates=["absent.pkg.form", "legacy_only_target"]
        )
        assert resolved is sys.modules["legacy_only_target"]

    def test_a_genuinely_absent_module_still_raises(self) -> None:
        with pytest.raises(ModuleNotFoundError, match="none of"):
            import_first_available(
                "nowhere", candidates=["a.nowhere", "b.nowhere", "nowhere"]
            )


class TestB_TransitiveModuleNotFoundIsNotRenamed:
    def test_a_missing_dependency_keeps_its_own_name(self, clean_modules) -> None:
        """Le cœur du défaut : ``fake_dependency`` doit rester
        ``fake_dependency``, jamais devenir le nom du module qui l'importe."""
        name = "shim_target_with_bad_dep"

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                raise ModuleNotFoundError(
                    "No module named 'fake_dependency'", name="fake_dependency"
                )

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == name:
                    return importlib.util.spec_from_loader(fullname, Loader())
                return None

        finder = Finder()
        sys.meta_path.insert(0, finder)
        try:
            with pytest.raises(ModuleNotFoundError) as excinfo:
                import_first_available(name, candidates=[name])
            assert excinfo.value.name == "fake_dependency"
            assert "fake_dependency" in str(excinfo.value)
            assert name not in str(excinfo.value)
        finally:
            sys.meta_path.remove(finder)
            sys.modules.pop(name, None)

    def test_the_fallback_is_not_attempted_after_a_dependency_failure(
        self, clean_modules
    ) -> None:
        """Réessayer par un autre chemin rejouerait le même échec sous un
        autre nom : le repli ne doit même pas être tenté."""
        attempted: list[str] = []
        real_import = importlib.import_module

        def spy(fullname, package=None):
            attempted.append(fullname)
            if fullname == "pkg.thing":
                raise ModuleNotFoundError(
                    "No module named 'deep_dep'", name="deep_dep"
                )
            return real_import(fullname, package)

        import src.ingestor._import_compat as compat

        original = compat.importlib.import_module
        compat.importlib.import_module = spy
        try:
            with pytest.raises(ModuleNotFoundError) as excinfo:
                import_first_available("thing", candidates=["pkg.thing", "thing"])
            assert excinfo.value.name == "deep_dep"
            assert attempted == ["pkg.thing"], "the fallback must not be attempted"
        finally:
            compat.importlib.import_module = original


class TestC_NonImportErrorsPropagateExactly:
    def test_a_value_error_raised_at_import_propagates(self) -> None:
        """``except (ImportError, ValueError)`` convertissait une
        configuration refusée en « module manquant ». Une ``ValueError``
        n'est jamais une raison de changer de chemin d'import."""
        name = "shim_target_raising_value_error"

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                raise ValueError("sentinel")

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == name:
                    return importlib.util.spec_from_loader(fullname, Loader())
                return None

        finder = Finder()
        sys.meta_path.insert(0, finder)
        try:
            with pytest.raises(ValueError, match="^sentinel$"):
                import_first_available(name, candidates=[name, "legacy_" + name])
        finally:
            sys.meta_path.remove(finder)
            sys.modules.pop(name, None)

    def test_is_missing_module_rejects_non_module_errors(self) -> None:
        assert is_missing_module(ModuleNotFoundError(name="x"), "x") is True
        assert is_missing_module(ModuleNotFoundError(name="y"), "x") is False
        assert is_missing_module(ImportError("cannot import name"), "x") is False
        assert is_missing_module(ValueError("nope"), "x") is False


class TestD_CanonicalCiInvocation:
    def test_the_conftest_import_form_works(self) -> None:
        """L'invocation exacte de `tests/integration/conftest.py`."""
        from src.ingestor.api import app

        assert app is not None

    def test_the_flat_form_resolves_to_the_same_routers(self) -> None:
        import ingestor.api as flat

        assert flat.app is not None

    def test_candidate_order_puts_the_package_form_first(self) -> None:
        order = legacy_candidates("retrieval_v2_endpoint", package="src.ingestor")
        assert order[0] == "src.ingestor.retrieval_v2_endpoint"
        assert order[-1] == "retrieval_v2_endpoint"


class TestE_CanonicalRuntimeStillImports:
    def test_api_v2_app_imports(self) -> None:
        from src.ingestor.api_v2 import app

        assert app is not None

    def test_the_v2_routers_are_mounted(self) -> None:
        from src.ingestor.api_v2 import app

        paths = {route.path for route in app.routes}
        assert any(path.startswith("/search/v2") for path in paths), sorted(paths)


class TestNoMaskingPatternRemains:
    """Garde-fou de non-régression sur le chemin critique."""

    CRITICAL = (
        "api.py",
        "api_v2.py",
        "retrieval_v2_endpoint.py",
        "ingest_v2_endpoint.py",
        "review_v2_endpoint.py",
    )

    def test_no_import_shim_catches_value_error(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "ingestor"
        offenders = [
            name
            for name in self.CRITICAL
            if "except (ImportError, ValueError)" in (root / name).read_text()
        ]
        assert offenders == [], (
            f"{offenders} still convert a configuration failure into a missing module"
        )

    def test_no_import_shim_catches_bare_exception(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "ingestor"
        source = (root / "api.py").read_text()
        # Les quatre routeurs passent désormais par le helper.
        assert source.count("import_first_available(") >= 4
        assert 'importlib.import_module("retrieval_v2_endpoint")' not in source


class TestFlatDockerRuntime:
    """Le runtime aplati de l'image Docker est un mode supporté, pas un
    reliquat : ``src/ingestor`` y est directement sur le ``sys.path`` et
    les modules n'ont pas de paquet parent.

    C'est la raison d'être du ``ValueError`` d'origine — remplacé ici par
    une condition explicite, parce qu'attraper toutes les ``ValueError``
    convertissait aussi les configurations refusées en « module manquant »."""

    def test_a_parentless_relative_import_allows_the_fallback(self) -> None:
        exc = ImportError(
            "attempted relative import with no known parent package"
        )
        assert is_missing_module(exc, "src.ingestor.thing") is True

    def test_a_cannot_import_name_does_not_allow_the_fallback(self) -> None:
        """Un module présent mais incomplet : le repli chargerait le même
        code par un autre chemin et échouerait pareil."""
        exc = ImportError("cannot import name 'gone' from 'pkg.thing'")
        assert is_missing_module(exc, "pkg.thing") is False

    def test_a_missing_parent_package_allows_the_fallback(self) -> None:
        """``import ingestor.foo`` quand ``ingestor`` n'existe pas lève
        ``ModuleNotFoundError(name='ingestor')`` : cette disposition
        n'existe pas ici."""
        exc = ModuleNotFoundError("No module named 'ingestor'", name="ingestor")
        assert is_missing_module(exc, "ingestor.retrieval_v2_endpoint") is True

    def test_a_sibling_dependency_never_allows_the_fallback(self) -> None:
        exc = ModuleNotFoundError("No module named 'torch'", name="torch")
        assert is_missing_module(exc, "src.ingestor.inference_runtime") is False
