"""Résolveur de source — ce qu'il refuse, sans jamais toucher GHCR.

Le client OCI est injecté : aucun test n'ouvre de connexion, n'écrit dans
un registre ni ne crée d'archive réelle. Les archives sont synthétiques,
construites sous ``tmp_path`` à partir de quelques fichiers texte.
"""
from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from rag_pedago.governance.corpus_campaign import CorpusCampaignV1
from rag_pedago.governance.corpus_source_resolver import (
    CorpusSourceError,
    CorpusSourceUnavailable,
    ResolvedCorpus,
    decompress_transport_blob,
    resolve_corpus_source,
)
from rag_pedago.governance.sealed_corpus import (
    build_canonical_archive,
    compute_tree_digest,
    generate_sealed_manifest,
)

SOURCE_ROOT = "corpus"


def _build_source(tmp_path: Path, files: dict[str, bytes] | None = None) -> bytes:
    """Archive canonique synthétique, telle que le packer la produirait."""
    staging = tmp_path / "staging"
    root = staging / SOURCE_ROOT
    payload = files if files is not None else {
        "01_EDUSCOL/a.pdf": b"premier",
        "01_EDUSCOL/b.pdf": b"deuxieme",
    }
    for relative, content in payload.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    # L'archive contient ``corpus/...`` : c'est ``source_root`` qui la
    # désigne à l'intérieur de l'arbre extrait.
    manifest = generate_sealed_manifest(staging)
    return build_canonical_archive(staging, manifest)


def _campaign(tar_bytes: bytes, tmp_path: Path, **overrides: object) -> CorpusCampaignV1:
    extracted = tmp_path / "reference"
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as archive:
        archive.extractall(extracted, filter="data")
    manifest = generate_sealed_manifest(extracted / SOURCE_ROOT)
    fields: dict[str, object] = {
        "protocol_version": "NEXUS-CORPUS-CAMPAIGN-V1",
        "campaign_id": "resolver-test",
        "scope": {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_philo_terminale_tc",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "philosophie",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        },
        "source_kind": "ghcr-oci",
        "source_registry": "ghcr.io",
        "source_repository": "cyranoaladin/rag-corpus",
        "source_oci_digest": "sha256:" + "a" * 64,
        "source_archive_sha256": hashlib.sha256(tar_bytes).hexdigest(),
        "source_tree_digest": compute_tree_digest(manifest),
        "archive_format": "tar.zst",
        "source_root": SOURCE_ROOT,
        "expected_manifest_sha256": manifest.manifest_sha256,
        "expected_catalog_digest": "5" * 64,
        "authorization_id": "resolver-test-authorization",
        "compiler_version": "corpus-catalog-compiler/1",
        "routing_config_digest": "6" * 64,
        "rights_config_digest": "7" * 64,
        "pii_config_digest": "8" * 64,
        "golden_spec_digest": "9" * 64,
        "environment": "rehearsal",
        "retention_days": 90,
    }
    fields.update(overrides)
    return CorpusCampaignV1(**fields)  # type: ignore[arg-type]


def _pull(blob: bytes, digest: str | None = None):
    """Client OCI double : rend les octets et le digest « servi »."""
    calls: list[str] = []

    def pull(reference: str) -> tuple[bytes, str]:
        calls.append(reference)
        return blob, digest or "sha256:" + "a" * 64

    pull.calls = calls  # type: ignore[attr-defined]
    return pull


class TestTheReferenceComesFromTheDescriptor:
    def test_the_resolver_derives_the_reference_itself(
        self, tmp_path: Path
    ) -> None:
        """Aucun paramètre ne permet de désigner une autre référence."""
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path)
        pull = _pull(tar)
        resolve_corpus_source(campaign, destination=tmp_path / "out", pull=pull)
        assert pull.calls == [  # type: ignore[attr-defined]
            f"ghcr.io/cyranoaladin/rag-corpus@sha256:{'a' * 64}"
        ]

    def test_the_resolver_has_no_reference_parameter(self) -> None:
        import inspect

        parameters = set(inspect.signature(resolve_corpus_source).parameters)
        assert parameters == {"campaign", "destination", "pull"}
        assert not parameters & {"reference", "registry", "tag", "url", "path"}


class TestEightMandatoryChecks:
    def test_the_canonical_path_succeeds(self, tmp_path: Path) -> None:
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path)
        resolved = resolve_corpus_source(
            campaign, destination=tmp_path / "out", pull=_pull(tar)
        )
        assert isinstance(resolved, ResolvedCorpus)
        assert resolved.archive_sha256 == campaign.source_archive_sha256
        assert resolved.tree_digest == campaign.source_tree_digest
        assert resolved.manifest.manifest_sha256 == campaign.expected_manifest_sha256

    def test_a_registry_serving_another_digest_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Ce que le registre a *effectivement* servi doit correspondre."""
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path)
        with pytest.raises(CorpusSourceError, match="registry returned digest"):
            resolve_corpus_source(
                campaign,
                destination=tmp_path / "out",
                pull=_pull(tar, digest="sha256:" + "b" * 64),
            )

    def test_a_diverging_archive_digest_is_refused(self, tmp_path: Path) -> None:
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path)
        other = _build_source(tmp_path / "other", {"x.pdf": b"different"})
        with pytest.raises(CorpusSourceError, match="canonical archive digest"):
            resolve_corpus_source(
                campaign, destination=tmp_path / "out", pull=_pull(other)
            )

    def test_a_diverging_tree_digest_is_refused(self, tmp_path: Path) -> None:
        """Une extraction créative ne passe pas, alors qu'elle passerait
        une simple comparaison d'archives."""
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path, source_tree_digest="c" * 64)
        with pytest.raises(CorpusSourceError, match="extracted tree digest"):
            resolve_corpus_source(
                campaign, destination=tmp_path / "out", pull=_pull(tar)
            )

    def test_a_diverging_manifest_digest_is_refused(self, tmp_path: Path) -> None:
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path, expected_manifest_sha256="d" * 64)
        with pytest.raises(CorpusSourceError, match="regenerated manifest digest"):
            resolve_corpus_source(
                campaign, destination=tmp_path / "out", pull=_pull(tar)
            )

    def test_an_absent_source_root_is_refused(self, tmp_path: Path) -> None:
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path, source_root="autre")
        with pytest.raises(CorpusSourceError, match="is absent from the extracted"):
            resolve_corpus_source(
                campaign, destination=tmp_path / "out", pull=_pull(tar)
            )


class TestNoFallback:
    def test_an_unavailable_object_never_opens_an_alternative(
        self, tmp_path: Path
    ) -> None:
        """L'indisponibilité est un refus, pas une invitation à chercher
        ailleurs."""
        tar = _build_source(tmp_path)
        campaign = _campaign(tar, tmp_path)

        def failing(_reference: str) -> tuple[bytes, str]:
            raise CorpusSourceUnavailable("object not found")

        with pytest.raises(CorpusSourceUnavailable):
            resolve_corpus_source(
                campaign, destination=tmp_path / "out", pull=failing
            )

    def test_availability_and_authenticity_are_distinct_errors(self) -> None:
        assert issubclass(CorpusSourceUnavailable, CorpusSourceError)
        assert CorpusSourceUnavailable is not CorpusSourceError

    def test_no_tag_or_latest_appears_anywhere_in_the_module(self) -> None:
        source = Path(
            "rag_pedago/governance/corpus_source_resolver.py"
        ).read_text(encoding="utf-8")
        assert ":latest" not in source
        assert "docker pull" not in source


class TestArchiveSafety:
    def _tar_with(self, entries: list[tarfile.TarInfo], payload: bytes = b"x") -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for info in entries:
                if info.isreg():
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                else:
                    archive.addfile(info)
        return buffer.getvalue()

    def _resolve(self, tmp_path: Path, tar: bytes) -> None:
        campaign = _campaign(_build_source(tmp_path), tmp_path)
        campaign = campaign.model_copy(
            update={"source_archive_sha256": hashlib.sha256(tar).hexdigest()}
        )
        resolve_corpus_source(campaign, destination=tmp_path / "out", pull=_pull(tar))

    def test_path_traversal_is_refused(self, tmp_path: Path) -> None:
        info = tarfile.TarInfo("../escape.pdf")
        info.type = tarfile.REGTYPE
        with pytest.raises(CorpusSourceError, match="escapes the extraction root"):
            self._resolve(tmp_path, self._tar_with([info]))

    def test_an_absolute_path_is_refused(self, tmp_path: Path) -> None:
        info = tarfile.TarInfo("/etc/passwd")
        info.type = tarfile.REGTYPE
        with pytest.raises(CorpusSourceError, match="absolute path"):
            self._resolve(tmp_path, self._tar_with([info]))

    def test_a_symlink_entry_is_refused(self, tmp_path: Path) -> None:
        info = tarfile.TarInfo("corpus/link.pdf")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        with pytest.raises(CorpusSourceError, match="is a link"):
            self._resolve(tmp_path, self._tar_with([info]))

    def test_a_hard_link_entry_is_refused(self, tmp_path: Path) -> None:
        info = tarfile.TarInfo("corpus/hard.pdf")
        info.type = tarfile.LNKTYPE
        info.linkname = "corpus/a.pdf"
        with pytest.raises(CorpusSourceError, match="is a link"):
            self._resolve(tmp_path, self._tar_with([info]))

    def test_a_fifo_entry_is_refused(self, tmp_path: Path) -> None:
        info = tarfile.TarInfo("corpus/pipe")
        info.type = tarfile.FIFOTYPE
        with pytest.raises(CorpusSourceError, match="device or FIFO"):
            self._resolve(tmp_path, self._tar_with([info]))

    def test_a_duplicate_entry_is_refused(self, tmp_path: Path) -> None:
        """La seconde entrée écraserait la première : ce qui a été scellé
        deviendrait ambigu."""
        entries = []
        for _ in range(2):
            info = tarfile.TarInfo("corpus/dup.pdf")
            info.type = tarfile.REGTYPE
            entries.append(info)
        with pytest.raises(CorpusSourceError, match="twice"):
            self._resolve(tmp_path, self._tar_with(entries))

    def test_an_empty_archive_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusSourceError, match="no regular file"):
            self._resolve(tmp_path, self._tar_with([]))

    def test_an_oversized_entry_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.corpus_source_resolver.MAX_SINGLE_FILE_BYTES",
            2,
            raising=True,
        )
        info = tarfile.TarInfo("corpus/big.pdf")
        info.type = tarfile.REGTYPE
        with pytest.raises(CorpusSourceError, match="exceeds"):
            self._resolve(tmp_path, self._tar_with([info], payload=b"trop long"))

    def test_too_many_entries_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "rag_pedago.governance.corpus_source_resolver.MAX_FILES", 1, raising=True
        )
        entries = []
        for index in range(2):
            info = tarfile.TarInfo(f"corpus/f{index}.pdf")
            info.type = tarfile.REGTYPE
            entries.append(info)
        with pytest.raises(CorpusSourceError, match="entries"):
            self._resolve(tmp_path, self._tar_with(entries))


class TestTransportLayer:
    def test_an_uncompressed_tar_is_accepted_as_is(self, tmp_path: Path) -> None:
        tar = _build_source(tmp_path)
        assert decompress_transport_blob(tar) == tar

    def test_a_compression_bomb_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le ratio est borné avant que la mémoire ne le soit."""
        import shutil as _shutil

        monkeypatch.setattr(
            "rag_pedago.governance.corpus_source_resolver.MAX_COMPRESSION_RATIO",
            2,
            raising=True,
        )
        monkeypatch.setattr(
            "rag_pedago.governance.corpus_source_resolver.shutil",
            _shutil,
            raising=True,
        )
        monkeypatch.setattr(
            "rag_pedago.governance.corpus_source_resolver._run",
            lambda *_a, **_k: b"x" * 10_000,
            raising=True,
        )
        blob = b"\x28\xb5\x2f\xfd" + b"\x00" * 100
        with pytest.raises(CorpusSourceError, match="compression bomb"):
            decompress_transport_blob(blob)
