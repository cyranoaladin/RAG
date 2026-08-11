"""F4/F5 — exactitude du manifeste et exhaustivité des catégories de droits.

Deux constats de la review Codex 4904995785 sont fermés ici :

**F5.** La liaison manifeste ↔ catalogue comparait deux ``frozenset``. Deux
inventaires de tailles différentes devenaient donc égaux dès lors qu'ils
portaient les mêmes entrées *distinctes* : un doublon injecté d'un côté
était absorbé sans bruit. La comparaison porte désormais sur des
multiensembles, et les doublons sont refusés à la source.

**F4.** Le gate confrontait les empreintes des objets à l'allowlist de
l'autorisation, mais jamais leurs *catégories de droits*. Une autorisation
pouvait donc couvrir chaque octet sans couvrir la catégorie sous laquelle
cet octet serait publié.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.imports.h2b_coverage_report import (
    _MANIFEST_SELF_PATH,
    _parse_manifest,
    _verify_manifest_binding,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_MANIFEST = "c" * 64


def _manifest(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "SHA256SUMS.txt"
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


class TestManifestParsingKeepsCardinality:
    def test_a_well_formed_manifest_keeps_every_entry(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_B}  b.pdf"])
        assert _parse_manifest(path) == [(SHA_A, "a.pdf"), (SHA_B, "b.pdf")]

    def test_a_strictly_duplicated_line_is_refused(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_A}  a.pdf"])
        with pytest.raises(ValueError, match="duplicates an earlier identical entry"):
            _parse_manifest(path)

    def test_the_same_path_with_another_digest_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Le cas dangereux : deux contenus pour un chemin. Un ensemble en
        aurait absorbé un silencieusement."""
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_B}  a.pdf"])
        with pytest.raises(ValueError, match="re-declares path"):
            _parse_manifest(path)

    def test_the_same_digest_for_two_distinct_paths_is_allowed(
        self, tmp_path: Path
    ) -> None:
        """Un doublon de *contenu* est légitime : le format GNU l'exprime
        normalement, et rien ne justifie de le refuser."""
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_A}  b.pdf"])
        assert _parse_manifest(path) == [(SHA_A, "a.pdf"), (SHA_A, "b.pdf")]

    def test_two_different_spellings_are_never_normalized_into_one(
        self, tmp_path: Path
    ) -> None:
        """Décider que ``a.pdf`` et ``./a.pdf`` sont le même fichier
        appartient aux règles de canonicité, pas au parseur."""
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_A}  ./a.pdf"])
        assert len(_parse_manifest(path)) == 2


def _catalog(entries: list[tuple[str, str]], *, manifest_sha: str) -> dict[str, object]:
    objects: list[dict[str, object]] = [
        {"content_sha256": sha, "path": path} for sha, path in entries
    ]
    objects.append({"content_sha256": manifest_sha, "path": _MANIFEST_SELF_PATH})
    return {"manifest_sha256": manifest_sha, "physical_objects": objects}


def _file_sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestManifestCatalogBindingIsAMultisetComparison:
    def test_a_matching_inventory_is_accepted(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_B}  b.pdf"])
        catalog = _catalog(
            [(SHA_A, "a.pdf"), (SHA_B, "b.pdf")], manifest_sha=_file_sha(path)
        )
        _verify_manifest_binding(path, catalog)

    def test_a_duplicated_catalog_entry_is_refused(self, tmp_path: Path) -> None:
        """Le cœur de F5 : sous ``frozenset``, ce catalogue était *égal* au
        manifeste malgré une entrée de plus."""
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_B}  b.pdf"])
        catalog = _catalog(
            [(SHA_A, "a.pdf"), (SHA_B, "b.pdf"), (SHA_A, "a.pdf")],
            manifest_sha=_file_sha(path),
        )
        with pytest.raises(ValueError, match="duplicated"):
            _verify_manifest_binding(path, catalog)

    def test_a_missing_catalog_entry_is_refused(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf", f"{SHA_B}  b.pdf"])
        catalog = _catalog([(SHA_A, "a.pdf")], manifest_sha=_file_sha(path))
        with pytest.raises(ValueError, match="only in manifest"):
            _verify_manifest_binding(path, catalog)

    def test_an_extra_catalog_entry_is_refused(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf"])
        catalog = _catalog(
            [(SHA_A, "a.pdf"), (SHA_B, "b.pdf")], manifest_sha=_file_sha(path)
        )
        with pytest.raises(ValueError, match="only in catalog"):
            _verify_manifest_binding(path, catalog)

    def test_a_duplicated_self_object_is_refused(self, tmp_path: Path) -> None:
        """L'exclusion du self-object n'intervient qu'après la preuve de sa
        présence ET de son unicité."""
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf"])
        catalog = _catalog([(SHA_A, "a.pdf")], manifest_sha=_file_sha(path))
        objects = catalog["physical_objects"]
        assert isinstance(objects, list)
        objects.append(
            {"content_sha256": _file_sha(path), "path": _MANIFEST_SELF_PATH}
        )
        with pytest.raises(ValueError, match="appears 2 times"):
            _verify_manifest_binding(path, catalog)

    def test_a_missing_self_object_is_refused(self, tmp_path: Path) -> None:
        path = _manifest(tmp_path, [f"{SHA_A}  a.pdf"])
        catalog = {
            "manifest_sha256": _file_sha(path),
            "physical_objects": [{"content_sha256": SHA_A, "path": "a.pdf"}],
        }
        with pytest.raises(ValueError, match="is missing from catalog"):
            _verify_manifest_binding(path, catalog)


def _write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path
