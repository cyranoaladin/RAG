"""Générateur de manifeste scellé — déterminisme et refus.

Aucun corpus réel : chaque test construit quelques fichiers texte sous
``tmp_path``. Aucun PDF, aucune archive de production, aucun octet
institutionnel n'entre dans le dépôt.
"""
from __future__ import annotations

import hashlib
import os
import tarfile
import unicodedata
from pathlib import Path

import pytest

from rag_pedago.governance.sealed_corpus import (
    MANIFEST_SELF_PATH,
    SealedCorpusError,
    build_canonical_archive,
    catalog_self_object,
    compute_tree_digest,
    generate_sealed_manifest,
)


def _corpus(tmp_path: Path, files: dict[str, bytes] | None = None) -> Path:
    root = tmp_path / "corpus"
    payload = files if files is not None else {
        "01_EDUSCOL/b.pdf": b"deuxieme",
        "01_EDUSCOL/a.pdf": b"premier",
        "02_AUTRE/c.pdf": b"troisieme",
    }
    for relative, content in payload.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


class TestCanonicalFormat:
    def test_the_gnu_format_is_exact(self, tmp_path: Path) -> None:
        """Deux espaces, hex minuscule, LF final — ce que
        ``_parse_manifest`` exige, à l'octet près."""
        manifest = generate_sealed_manifest(_corpus(tmp_path))
        text = manifest.content.decode("utf-8")
        for line in text.splitlines():
            digest, sep, path = line.partition("  ")
            assert sep == "  ", "le séparateur doit être exactement deux espaces"
            assert len(digest) == 64 and digest == digest.lower()
            assert int(digest, 16) >= 0
            assert not path.startswith(" ")
        assert text.endswith("\n")
        assert "\r" not in text

    def test_the_order_is_lexicographic_on_paths(self, tmp_path: Path) -> None:
        manifest = generate_sealed_manifest(_corpus(tmp_path))
        paths = [p for _d, p in manifest.entries]
        assert paths == sorted(paths)

    def test_the_digests_are_the_real_file_digests(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        manifest = generate_sealed_manifest(root)
        for digest, path in manifest.entries:
            assert digest == hashlib.sha256((root / path).read_bytes()).hexdigest()

    def test_manifest_sha256_is_the_digest_of_the_file_bytes(
        self, tmp_path: Path
    ) -> None:
        manifest = generate_sealed_manifest(_corpus(tmp_path))
        assert (
            manifest.manifest_sha256
            == hashlib.sha256(manifest.content).hexdigest()
        )


class TestSelfObject:
    def test_the_manifest_never_contains_itself(self, tmp_path: Path) -> None:
        """Aucun point fixe : un fichier ne peut pas contenir son digest."""
        root = _corpus(tmp_path)
        (root / "00_ADMIN").mkdir(parents=True, exist_ok=True)
        (root / MANIFEST_SELF_PATH).write_bytes(b"stale manifest\n")
        manifest = generate_sealed_manifest(root)
        assert all(path != MANIFEST_SELF_PATH for _d, path in manifest.entries)

    def test_a_stale_self_object_does_not_change_the_digest(
        self, tmp_path: Path
    ) -> None:
        """Le contenu résiduel du self-object est ignoré, donc régénérer
        deux fois de suite converge au lieu d'osciller."""
        root = _corpus(tmp_path)
        first = generate_sealed_manifest(root)
        (root / "00_ADMIN").mkdir(parents=True, exist_ok=True)
        (root / MANIFEST_SELF_PATH).write_bytes(first.content)
        second = generate_sealed_manifest(root)
        assert second.manifest_sha256 == first.manifest_sha256

    def test_the_catalog_entry_carries_the_manifest_digest(
        self, tmp_path: Path
    ) -> None:
        manifest = generate_sealed_manifest(_corpus(tmp_path))
        entry = catalog_self_object(manifest)
        assert entry == {
            "path": MANIFEST_SELF_PATH,
            "content_sha256": manifest.manifest_sha256,
        }


class TestDeterminism:
    def test_two_runs_produce_identical_bytes(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        assert (
            generate_sealed_manifest(root).content
            == generate_sealed_manifest(root).content
        )

    def test_creation_order_does_not_matter(self, tmp_path: Path) -> None:
        """L'ordre de ``rglob`` suit le système de fichiers ; le manifeste
        ne doit pas en dépendre."""
        forward = _corpus(
            tmp_path / "one", {"z/last.pdf": b"L", "a/first.pdf": b"F"}
        )
        backward = _corpus(
            tmp_path / "two", {"a/first.pdf": b"F", "z/last.pdf": b"L"}
        )
        assert (
            generate_sealed_manifest(forward).content
            == generate_sealed_manifest(backward).content
        )

    def test_mtime_does_not_enter_the_digest(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        before = generate_sealed_manifest(root).manifest_sha256
        for path in root.rglob("*.pdf"):
            os.utime(path, (0, 0))
        assert generate_sealed_manifest(root).manifest_sha256 == before

    def test_the_archive_is_reproducible(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        manifest = generate_sealed_manifest(root)
        assert build_canonical_archive(root, manifest) == build_canonical_archive(
            root, manifest
        )

    def test_the_archive_carries_no_machine_metadata(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        manifest = generate_sealed_manifest(root)
        import io

        with tarfile.open(
            fileobj=io.BytesIO(build_canonical_archive(root, manifest)), mode="r"
        ) as archive:
            members = archive.getmembers()
        assert members, "l'archive ne doit pas être vide"
        for member in members:
            assert member.mtime == 0
            assert member.uid == 0 and member.gid == 0
            assert member.uname == "" and member.gname == ""
            assert member.mode == 0o644
            assert not member.name.startswith("/")
            assert ".." not in Path(member.name).parts

    def test_the_tree_digest_is_length_prefixed(self, tmp_path: Path) -> None:
        """Le préfixe de longueur empêche deux inventaires différents de
        produire la même concaténation."""
        one = _corpus(tmp_path / "a", {"ab/c.pdf": b"x", "d.pdf": b"y"})
        two = _corpus(tmp_path / "b", {"a/bc.pdf": b"x", "d.pdf": b"y"})
        assert compute_tree_digest(
            generate_sealed_manifest(one)
        ) != compute_tree_digest(generate_sealed_manifest(two))


class TestRefusals:
    def test_a_symlink_is_refused(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        (root / "01_EDUSCOL/link.pdf").symlink_to(root / "01_EDUSCOL/a.pdf")
        with pytest.raises(SealedCorpusError, match="symlink"):
            generate_sealed_manifest(root)

    def test_a_hard_link_is_refused(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        os.link(root / "01_EDUSCOL/a.pdf", root / "01_EDUSCOL/hard.pdf")
        with pytest.raises(SealedCorpusError, match="hard link"):
            generate_sealed_manifest(root)

    def test_a_fifo_is_refused(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        os.mkfifo(root / "01_EDUSCOL/pipe")
        with pytest.raises(SealedCorpusError, match="not a regular file"):
            generate_sealed_manifest(root)

    def test_an_empty_corpus_is_refused(self, tmp_path: Path) -> None:
        """Un manifeste vide ne scellerait rien tout en ayant l'air
        valide."""
        root = tmp_path / "empty"
        root.mkdir()
        with pytest.raises(SealedCorpusError, match="empty"):
            generate_sealed_manifest(root)

    def test_a_missing_root_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SealedCorpusError, match="not a directory"):
            generate_sealed_manifest(tmp_path / "absent")

    def test_a_unicode_normalisation_collision_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Deux écritures NFC/NFD du même nom produiraient deux lignes de
        manifeste pour un seul objet."""
        root = tmp_path / "corpus"
        (root / "z").mkdir(parents=True)
        nfc = unicodedata.normalize("NFC", "café.pdf")
        nfd = unicodedata.normalize("NFD", "café.pdf")
        if nfc == nfd:  # pragma: no cover - dépend de la plateforme
            pytest.skip("NFC et NFD coïncident ici")
        (root / "z" / nfc).write_bytes(b"un")
        try:
            (root / "z" / nfd).write_bytes(b"deux")
        except OSError:  # pragma: no cover - système de fichiers normalisant
            pytest.skip("le système de fichiers normalise les noms lui-même")
        if len(list((root / "z").iterdir())) < 2:  # pragma: no cover
            pytest.skip("le système de fichiers a fusionné les deux noms")
        with pytest.raises(SealedCorpusError, match="NFC normalisation"):
            generate_sealed_manifest(root)

    def test_too_many_files_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.sealed_corpus.MAX_FILES", 2, raising=True
        )
        with pytest.raises(SealedCorpusError, match="objects"):
            generate_sealed_manifest(_corpus(tmp_path))

    def test_an_oversized_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.sealed_corpus.MAX_SINGLE_FILE_BYTES", 4, raising=True
        )
        with pytest.raises(SealedCorpusError, match="byte bound"):
            generate_sealed_manifest(_corpus(tmp_path))

    def test_an_oversized_corpus_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.sealed_corpus.MAX_TOTAL_BYTES", 10, raising=True
        )
        with pytest.raises(SealedCorpusError, match="governed bound"):
            generate_sealed_manifest(_corpus(tmp_path))

    def test_an_overlong_path_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.sealed_corpus.MAX_PATH_BYTES", 5, raising=True
        )
        with pytest.raises(SealedCorpusError, match="path exceeds"):
            generate_sealed_manifest(_corpus(tmp_path))


class TestMutationSensitivity:
    def test_one_changed_byte_changes_the_digest(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        before = generate_sealed_manifest(root).manifest_sha256
        (root / "01_EDUSCOL/a.pdf").write_bytes(b"premieR")
        assert generate_sealed_manifest(root).manifest_sha256 != before

    def test_an_added_file_changes_the_digest(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        before = generate_sealed_manifest(root).manifest_sha256
        (root / "01_EDUSCOL/d.pdf").write_bytes(b"quatrieme")
        assert generate_sealed_manifest(root).manifest_sha256 != before

    def test_a_removed_file_changes_the_digest(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        before = generate_sealed_manifest(root).manifest_sha256
        (root / "02_AUTRE/c.pdf").unlink()
        assert generate_sealed_manifest(root).manifest_sha256 != before

    def test_a_moved_file_changes_the_digest(self, tmp_path: Path) -> None:
        """Mêmes octets, autre chemin : l'identité du corpus change."""
        root = _corpus(tmp_path)
        before = generate_sealed_manifest(root).manifest_sha256
        (root / "02_AUTRE/c.pdf").rename(root / "01_EDUSCOL/c.pdf")
        assert generate_sealed_manifest(root).manifest_sha256 != before

    def test_identical_bytes_at_two_paths_stay_distinct_entries(
        self, tmp_path: Path
    ) -> None:
        root = _corpus(tmp_path, {"a.pdf": b"same", "b.pdf": b"same"})
        manifest = generate_sealed_manifest(root)
        assert manifest.object_count == 2
        assert manifest.entries[0][0] == manifest.entries[1][0]
        assert manifest.entries[0][1] != manifest.entries[1][1]


class TestArchiveDigestSemantics:
    """Ce que ``source_archive_sha256`` couvre exactement.

    Le digest porte sur le tar canonique **non compressé**. Hacher le blob
    compressé lierait l'identité d'un corpus approuvé à la version du
    compresseur : une mise à jour de zstd invaliderait une campagne
    pourtant inchangée.
    """

    def test_the_canonical_archive_is_an_uncompressed_tar(
        self, tmp_path: Path
    ) -> None:
        root = _corpus(tmp_path)
        raw = build_canonical_archive(root, generate_sealed_manifest(root))
        assert b"ustar" in raw[:512], "le tar canonique doit être un tar POSIX"
        assert raw[:4] != b"\x28\xb5\x2f\xfd", "il ne doit pas être compressé zstd"

    def test_the_archive_digest_survives_recompression(
        self, tmp_path: Path
    ) -> None:
        """La propriété qui compte : deux transports différents du même
        tar donnent le même ``source_archive_sha256``."""
        import zlib

        root = _corpus(tmp_path)
        manifest = generate_sealed_manifest(root)
        canonical = build_canonical_archive(root, manifest)
        expected = hashlib.sha256(canonical).hexdigest()
        # Deux « transports » distincts, deux blobs différents…
        fast = zlib.compress(canonical, 1)
        slow = zlib.compress(canonical, 9)
        assert fast != slow
        # …mais la même identité une fois décompressés.
        assert hashlib.sha256(zlib.decompress(fast)).hexdigest() == expected
        assert hashlib.sha256(zlib.decompress(slow)).hexdigest() == expected


class TestDigestDomainsAreDistinct:
    """Les trois identités portent sur trois objets différents.

    C'est cela, et non leur inégalité, qui rend les trois vérifications
    non redondantes.
    """

    def test_the_tree_digest_is_not_the_archive_digest(
        self, tmp_path: Path
    ) -> None:
        root = _corpus(tmp_path)
        manifest = generate_sealed_manifest(root)
        archive_digest = hashlib.sha256(
            build_canonical_archive(root, manifest)
        ).hexdigest()
        assert compute_tree_digest(manifest) != archive_digest

    def test_the_tree_digest_is_not_the_manifest_digest(
        self, tmp_path: Path
    ) -> None:
        manifest = generate_sealed_manifest(_corpus(tmp_path))
        assert compute_tree_digest(manifest) != manifest.manifest_sha256

    def test_the_tree_digest_ignores_archive_framing(self, tmp_path: Path) -> None:
        """Le digest d'arbre ne dépend que du contenu matérialisé.

        Un packer qui changerait son cadrage tar sans toucher aux fichiers
        laisse donc le tree digest inchangé — c'est pourquoi les deux
        vérifications ne se remplacent pas."""
        root = _corpus(tmp_path)
        first = compute_tree_digest(generate_sealed_manifest(root))
        (root / "01_EDUSCOL").rename(root / "01_EDUSCOL_tmp")
        (root / "01_EDUSCOL_tmp").rename(root / "01_EDUSCOL")
        assert compute_tree_digest(generate_sealed_manifest(root)) == first


class TestStreamingArchiveMatchesInMemory:
    """``write_canonical_archive`` existe parce que ``build_canonical_archive``
    immobilise l'archive entière en mémoire — 1,75 Gio sur le corpus réel,
    doublés par tout appelant qui la compresse ensuite, alors que
    ``MAX_TOTAL_BYTES`` en autorise 8. Les deux doivent produire des octets
    identiques, sinon le chemin de production et le chemin de test
    scelleraient deux objets différents."""

    def _tree(self, tmp_path: Path) -> Path:
        root = tmp_path / "corpus"
        (root / "01_EDUSCOL_OFFICIEL").mkdir(parents=True)
        (root / "01_EDUSCOL_OFFICIEL" / "a.pdf").write_bytes(b"%PDF-a" * 500)
        (root / "01_EDUSCOL_OFFICIEL" / "b.pdf").write_bytes(b"%PDF-b" * 300)
        (root / "04_COMPLEMENTS_PEDAGOGIQUES").mkdir(parents=True)
        (root / "04_COMPLEMENTS_PEDAGOGIQUES" / "c.pdf").write_bytes(b"%PDF-c")
        return root

    def test_both_paths_produce_identical_bytes(self, tmp_path: Path) -> None:
        import io

        from rag_pedago.governance.sealed_corpus import write_canonical_archive

        root = self._tree(tmp_path)
        manifest = generate_sealed_manifest(root)

        in_memory = build_canonical_archive(root, manifest)
        buffer = io.BytesIO()
        digest = write_canonical_archive(root, manifest, buffer)

        assert buffer.getvalue() == in_memory
        assert digest == hashlib.sha256(in_memory).hexdigest()

    def test_the_streamed_digest_is_computed_without_a_second_pass(
        self, tmp_path: Path
    ) -> None:
        """Le digest sort de l'écriture elle-même : sur plusieurs gigaoctets,
        une relecture doublerait le coût d'E/S pour rien."""
        from rag_pedago.governance.sealed_corpus import write_canonical_archive

        root = self._tree(tmp_path)
        manifest = generate_sealed_manifest(root)
        target = tmp_path / "corpus.tar"
        with target.open("wb") as handle:
            digest = write_canonical_archive(root, manifest, handle)

        assert digest == hashlib.sha256(target.read_bytes()).hexdigest()

    def test_the_streamed_archive_is_deterministic(self, tmp_path: Path) -> None:
        import io

        from rag_pedago.governance.sealed_corpus import write_canonical_archive

        root = self._tree(tmp_path)
        manifest = generate_sealed_manifest(root)
        first = write_canonical_archive(root, manifest, io.BytesIO())
        second = write_canonical_archive(root, manifest, io.BytesIO())
        assert first == second
