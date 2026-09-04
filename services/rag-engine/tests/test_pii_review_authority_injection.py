"""Injection de l'autorité de revue PII par le mécanisme canonique (ADR-0047).

Le worker ne connaît aucune campagne. Il reçoit, comme toutes ses autres
autorités, des couples `--<nom>-path` / `--<nom>-sha256` et une allowlist de
reviewers ; il les vérifie ; il refuse si la chaîne ne tient pas. Faire tourner
un autre ensemble de décisions demain ne doit toucher aucun fichier Python.

Ces tests portent sur le *mécanisme*, pas sur son contenu : ils ne nomment
jamais un identifiant de campagne réel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from pathlib import Path

import pytest

from ingestor.ingestion_worker.multilevel_runtime_authority import (
    add_multilevel_runtime_authority_arguments,
    multilevel_runtime_authority_inputs_from_args,
)
from ingestor.ingestion_worker.runtime_authority import (
    add_runtime_authority_arguments,
    runtime_authority_inputs_from_args,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

REVIEW_ARGUMENTS = (
    "pii-decision-set",
    "pii-review-receipt",
    "review-trust-anchor",
    "pii-review-reviewers",
)


def _parser(add: object) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    add(parser)  # type: ignore[operator]
    return parser


def _wave0_parser() -> argparse.ArgumentParser:
    """Le parseur tel que les CLI le composent : autorités + preuves scellées.

    `add_runtime_authority_arguments` ne déclare pas les preuves PII/droits ni
    le manifeste de corpus — les CLI les ajoutent. On reproduit cet assemblage
    plutôt que d'en supposer un autre."""
    parser = _parser(add_runtime_authority_arguments)
    parser.add_argument("--pii-evidence-path", required=True, type=Path)
    parser.add_argument("--pii-evidence-sha256", required=True)
    parser.add_argument("--rights-evidence-path", required=True, type=Path)
    parser.add_argument("--rights-evidence-sha256", required=True)
    parser.add_argument("--corpus-manifest-sha256", required=True)
    return parser


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


class TestArgumentsAreDeclared:
    def test_wave0_parser_declares_the_review_authority_couples(self) -> None:
        options = _option_strings(_parser(add_runtime_authority_arguments))
        for name in REVIEW_ARGUMENTS:
            assert f"--{name}-path" in options
            assert f"--{name}-sha256" in options

    def test_multilevel_parser_declares_the_review_authority_couples(self) -> None:
        options = _option_strings(_parser(add_multilevel_runtime_authority_arguments))
        for name in REVIEW_ARGUMENTS:
            assert f"--{name}-path" in options
            assert f"--{name}-sha256" in options

    def test_review_authority_is_optional(self) -> None:
        """Une release sans aucun contenu détecté n'a pas de décisions à joindre.

        L'absence n'ouvre rien : le registre refuse toute entrée qui se
        déclare admise sans ensemble scellé. C'est là qu'est la garde, pas
        dans l'obligation de passer un fichier vide."""
        parser = _parser(add_runtime_authority_arguments)
        for action in parser._actions:
            if any(opt.startswith(f"--{n}") for n in REVIEW_ARGUMENTS for opt in action.option_strings):
                assert action.required is False


class TestInputsCarryTheInjectedAuthority:
    def _base(self) -> list[str]:
        args: list[str] = []
        for name in (
            "catalog", "candidate-inventory", "currentness-evidence", "mapping",
            "release-manifest", "programme-index", "collection-config",
            "pii-evidence", "rights-evidence",
        ):
            args += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "0" * 64]
        args += ["--corpus-manifest-sha256", "1" * 64]
        return args

    def test_absent_review_authority_yields_none_not_a_guess(self) -> None:  # noqa: D401
        parser = _wave0_parser()
        inputs = runtime_authority_inputs_from_args(parser.parse_args(self._base()))
        assert inputs.pii_decision_set_path is None
        assert inputs.pii_review_receipt_path is None
        assert inputs.review_trust_anchor_path is None
        assert inputs.pii_review_reviewers == ()

    def test_injected_review_authority_reaches_the_inputs(self) -> None:
        parser = _wave0_parser()
        allowlist = REPO_ROOT / "scripts/github/trusted-reviewers.json"
        extra = [
            "--pii-decision-set-path", "/tmp/ds.json",
            "--pii-decision-set-sha256", "2" * 64,
            "--pii-review-receipt-path", "/tmp/receipt.json",
            "--pii-review-receipt-sha256", "3" * 64,
            "--review-trust-anchor-path", "/tmp/anchor.json",
            "--review-trust-anchor-sha256", "4" * 64,
            "--pii-review-reviewers-path", str(allowlist),
            "--pii-review-reviewers-sha256",
            hashlib.sha256(allowlist.read_bytes()).hexdigest(),
        ]
        inputs = runtime_authority_inputs_from_args(parser.parse_args(self._base() + extra))
        assert inputs.pii_decision_set_path == Path("/tmp/ds.json")
        assert inputs.pii_decision_set_sha256 == "2" * 64
        assert inputs.pii_review_receipt_path == Path("/tmp/receipt.json")
        # P3 : l'empreinte du reçu était passée sans jamais être assertée.
        assert inputs.pii_review_receipt_sha256 == "3" * 64
        assert inputs.review_trust_anchor_path == Path("/tmp/anchor.json")
        assert inputs.review_trust_anchor_sha256 == "4" * 64
        assert inputs.pii_review_reviewers == ("abenrhouma",)

    def test_multilevel_inputs_carry_the_injected_authority(self) -> None:
        parser = _parser(add_multilevel_runtime_authority_arguments)
        args: list[str] = []
        for name in (
            "candidate-inventory", "currentness-evidence", "levels-mapping",
            "subjects-mapping", "document-types-mapping", "release-manifest",
            "programme-registry", "profile-manifest", "collection-config",
            "pii-evidence", "rights-evidence",
        ):
            args += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "0" * 64]
        args += [
            "--corpus-manifest-sha256", "1" * 64,
            "--repository-root", "/tmp/repo",
            "--pii-decision-set-path", "/tmp/ds.json",
            "--pii-decision-set-sha256", "2" * 64,
            "--pii-review-receipt-path", "/tmp/receipt.json",
            "--pii-review-receipt-sha256", "3" * 64,
            "--review-trust-anchor-path", "/tmp/anchor.json",
            "--review-trust-anchor-sha256", "4" * 64,
            "--pii-review-reviewers-path", str(REPO_ROOT / "scripts/github/trusted-reviewers.json"),
            "--pii-review-reviewers-sha256",
            hashlib.sha256((REPO_ROOT / "scripts/github/trusted-reviewers.json").read_bytes()).hexdigest(),
        ]
        inputs = multilevel_runtime_authority_inputs_from_args(parser.parse_args(args))
        assert inputs.pii_decision_set_path == Path("/tmp/ds.json")
        assert inputs.pii_review_reviewers == ("abenrhouma",)


class TestNoUnpinnedAuthorityCanBeInjected:
    """Un chemin sans son empreinte n'est pas une autorité (P1).

    Fournir `--x-path` sans `--x-sha256` faisait sauter la vérification de
    digest et acceptait une chaîne non épinglée. Les deux vont ensemble, ou
    aucun des deux."""

    def _base(self) -> list[str]:
        args: list[str] = []
        for name in (
            "catalog", "candidate-inventory", "currentness-evidence", "mapping",
            "release-manifest", "programme-index", "collection-config",
            "pii-evidence", "rights-evidence",
        ):
            args += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "0" * 64]
        return args + ["--corpus-manifest-sha256", "1" * 64]

    @pytest.mark.parametrize("name", REVIEW_ARGUMENTS)
    def test_a_path_without_its_digest_is_refused(self, name: str) -> None:
        parser = _wave0_parser()
        args = parser.parse_args(self._base() + [f"--{name}-path", "/tmp/x.json"])
        with pytest.raises(ValueError, match="sha256|digest|épingl|pinned"):
            runtime_authority_inputs_from_args(args)

    @pytest.mark.parametrize("name", REVIEW_ARGUMENTS)
    def test_a_digest_without_its_path_is_refused(self, name: str) -> None:
        parser = _wave0_parser()
        args = parser.parse_args(self._base() + [f"--{name}-sha256", "2" * 64])
        with pytest.raises(ValueError, match="path|chemin"):
            runtime_authority_inputs_from_args(args)

    def test_complete_couples_are_accepted(self) -> None:
        parser = _wave0_parser()
        allowlist = REPO_ROOT / "scripts/github/trusted-reviewers.json"
        extra: list[str] = []
        for name in REVIEW_ARGUMENTS:
            if name == "pii-review-reviewers":
                extra += [f"--{name}-path", str(allowlist), f"--{name}-sha256",
                          hashlib.sha256(allowlist.read_bytes()).hexdigest()]
            else:
                extra += [f"--{name}-path", f"/tmp/{name}.json", f"--{name}-sha256", "3" * 64]
        inputs = runtime_authority_inputs_from_args(parser.parse_args(self._base() + extra))
        assert inputs.pii_decision_set_sha256 == "3" * 64
        assert inputs.pii_review_receipt_sha256 == "3" * 64
        assert inputs.review_trust_anchor_sha256 == "3" * 64
        assert inputs.pii_review_reviewers == ("abenrhouma",)


class TestTheReviewerAllowlistIsAVersionedAuthority:
    """Les reviewers ne se fournissent plus à la main (P1).

    `--pii-review-reviewer abenrhouma` faisait confiance à n'importe quel
    compte que l'appelant nommait. L'allowlist est un artefact versionné —
    `scripts/github/trusted-reviewers.json`, protocole NEXUS-TRUSTED-REVIEW-V1 —
    déjà lu par le reste de la chaîne d'autorité GitHub. Il est désormais
    injecté comme les autres : par un couple chemin + empreinte."""

    def test_the_free_form_reviewer_flag_is_gone(self) -> None:
        options = _option_strings(_parser(add_runtime_authority_arguments))
        assert "--pii-review-reviewer" not in options

    def test_the_canonical_allowlist_is_read_and_verified(self, tmp_path: Path) -> None:
        from ingestor.ingestion_worker.runtime_authority import load_trusted_reviewers

        config = tmp_path / "trusted-reviewers.json"
        config.write_text(
            json.dumps(
                {
                    "protocol": "NEXUS-TRUSTED-REVIEW-V1",
                    "repository": "cyranoaladin/RAG",
                    "base_ref": "main",
                    "reviewers": ["abenrhouma"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(config.read_bytes()).hexdigest()
        assert load_trusted_reviewers(config, digest) == ("abenrhouma",)

    def test_a_tampered_allowlist_is_refused(self, tmp_path: Path) -> None:
        from ingestor.ingestion_worker.runtime_authority import load_trusted_reviewers

        config = tmp_path / "trusted-reviewers.json"
        config.write_text(
            json.dumps(
                {
                    "protocol": "NEXUS-TRUSTED-REVIEW-V1",
                    "repository": "cyranoaladin/RAG",
                    "base_ref": "main",
                    "reviewers": ["abenrhouma"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        legitimate = hashlib.sha256(config.read_bytes()).hexdigest()
        config.write_text(
            json.dumps(
                {
                    "protocol": "NEXUS-TRUSTED-REVIEW-V1",
                    "repository": "cyranoaladin/RAG",
                    "base_ref": "main",
                    "reviewers": ["abenrhouma", "intrus"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_trusted_reviewers(config, legitimate)

    def test_a_foreign_repository_allowlist_is_refused(self, tmp_path: Path) -> None:
        from ingestor.ingestion_worker.runtime_authority import load_trusted_reviewers

        config = tmp_path / "trusted-reviewers.json"
        config.write_text(
            json.dumps(
                {
                    "protocol": "NEXUS-TRUSTED-REVIEW-V1",
                    "repository": "quelquun/autre",
                    "base_ref": "main",
                    "reviewers": ["abenrhouma"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="repository|dépôt"):
            load_trusted_reviewers(config, hashlib.sha256(config.read_bytes()).hexdigest())

    def test_the_repository_allowlist_loads(self) -> None:
        """L'artefact réellement versionné se lit avec ce chargeur."""
        from ingestor.ingestion_worker.runtime_authority import load_trusted_reviewers

        path = Path(__file__).resolve().parents[3] / "scripts/github/trusted-reviewers.json"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert "abenrhouma" in load_trusted_reviewers(path, digest)


class TestTheRuntimeChainMustMatchTheManifestChain:
    """P1 — la comparaison, sans laquelle porter la chaîne ne sert à rien.

    Le manifeste déclare sa chaîne de revue ; le worker charge la sienne depuis
    ses arguments. Les porter toutes deux ne prouve rien tant que personne ne
    les confronte : c'est la confrontation qui interdit qu'une release annonce
    la chaîne A pendant que le worker en vérifie une B."""

    def _compare(self, **kw):
        from ingestor.ingestion_worker.runtime_authority import (
            require_runtime_review_chain_matches_release,
        )

        return require_runtime_review_chain_matches_release(**kw)

    DECLARED = {
        "pii_decision_set_sha256": "a" * 64,
        "pii_review_receipt_sha256": "b" * 64,
        "pii_review_trust_anchor_sha256": "c" * 64,
        "pii_review_index_sha256": "d" * 64,
    }

    def test_identical_chains_are_accepted(self) -> None:
        self._compare(declared=self.DECLARED, runtime=dict(self.DECLARED))

    def test_both_absent_is_accepted(self) -> None:
        self._compare(
            declared=dict.fromkeys(self.DECLARED, None),
            runtime=dict.fromkeys(self.DECLARED, None),
        )

    @pytest.mark.parametrize("field", sorted(DECLARED))
    def test_each_field_is_compared_independently(self, field: str) -> None:
        runtime = dict(self.DECLARED)
        runtime[field] = "9" * 64
        with pytest.raises(ValueError, match=field):
            self._compare(declared=self.DECLARED, runtime=runtime)

    def test_a_manifest_chain_without_a_runtime_chain_is_refused(self) -> None:
        with pytest.raises(ValueError, match="pii_decision_set_sha256"):
            self._compare(
                declared=self.DECLARED, runtime=dict.fromkeys(self.DECLARED, None)
            )

    def test_a_runtime_chain_the_manifest_never_declared_is_refused(self) -> None:
        """Charger une autorité que la release ne nomme pas est le cas B."""
        with pytest.raises(ValueError, match="pii_decision_set_sha256"):
            self._compare(
                declared=dict.fromkeys(self.DECLARED, None), runtime=self.DECLARED
            )


class TestRehearsalVerifiesTheSameChainAsProduction:
    """P2 — une répétition vérifiait son reçu comme une production.

    ADR-0035 sépare les clés : une clé de fixture ne valide jamais un gate de
    production, et une clé de production n'est jamais exercée par une
    répétition. Le worker multi-niveaux connaissait pourtant `rehearsal` sans
    en tenir compte pour le reçu, si bien qu'une répétition portant sa propre
    autorité de revue ne pouvait pas la charger.

    Le mode `test` ne retire AUCUNE garde : signature, challenge, empreintes,
    reviewer et liaison de corpus restent tous vérifiés. Il ne change que la
    clé recevable."""

    def test_rehearsal_maps_to_the_test_verification_environment(self) -> None:
        from ingestor.ingestion_worker.multilevel_runtime_authority import (
            review_verification_environment,
        )

        assert review_verification_environment("rehearsal") == "test"
        assert review_verification_environment("production") == "production"

    def test_an_unknown_environment_is_refused(self) -> None:
        from ingestor.ingestion_worker.multilevel_runtime_authority import (
            review_verification_environment,
        )

        with pytest.raises(ValueError, match="rehearsal|production"):
            review_verification_environment("autre-chose")

    def test_the_multilevel_loader_derives_it_instead_of_hardcoding(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/ingestor/ingestion_worker/multilevel_runtime_authority.py"
        ).read_text(encoding="utf-8")
        loader = source[source.index("pii = VerifiedPIIEvidenceRegistry.load(") :]
        loader = loader[: loader.index("\n        )")]
        assert "review_verification_environment(environment)" in loader


class TestTheWaveZeroSchemaCannotDeclareAReviewChain:
    """Le schéma Wave 0 ne porte PAS la chaîne de revue, et ne doit pas l'apprendre.

    La revue a relevé que `VerifiedPedagogicalPlacementResolver.release_review_chain`
    est toujours entièrement `None` : `load_subject_release` ferme `authorities`
    à huit noms et refuse tout le reste. Le constat est exact.

    La correction n'est pas d'élargir Wave 0 — ce serait faire dire à un format
    antérieur à la campagne de revue ce qu'il n'a jamais déclaré. C'est de
    rendre la propriété EXPLICITE et de la tenir : une release qui admet du
    contenu détecté se déclare en V2, où la chaîne est réellement portée.
    """

    def test_the_wave_zero_authorities_are_closed_to_eight_names(self) -> None:
        from ingestor import wave0_release

        source = pathlib.Path(wave0_release.__file__).read_text(encoding="utf-8")
        block = source[source.index("authority_names = {") :]
        block = block[: block.index("}")]
        declared = {line.strip().strip('",') for line in block.splitlines()[1:] if line.strip()}
        assert len(declared) == 8
        assert not declared & {
            "pii_decision_set_sha256",
            "pii_review_receipt_sha256",
            "pii_review_trust_anchor_sha256",
            "pii_review_index_sha256",
        }, "le schéma Wave 0 s'est élargi à la chaîne de revue sans ADR"

    def test_a_worker_chain_cannot_be_served_by_a_wave_zero_release(self) -> None:
        """La conséquence voulue, énoncée comme telle.

        Déclaré vide (Wave 0 ne peut pas faire autrement), chargé non vide :
        le démarrage doit refuser plutôt que de servir une release qui
        n'affirme rien sur la revue."""
        from ingestor.ingestion_worker.runtime_authority import (
            require_runtime_review_chain_matches_release,
        )

        with pytest.raises(ValueError, match="not the one this worker verifies"):
            require_runtime_review_chain_matches_release(
                declared={
                    "pii_decision_set_sha256": None,
                    "pii_review_receipt_sha256": None,
                    "pii_review_trust_anchor_sha256": None,
                    "pii_review_index_sha256": None,
                },
                runtime={
                    "pii_decision_set_sha256": "a" * 64,
                    "pii_review_receipt_sha256": "b" * 64,
                    "pii_review_trust_anchor_sha256": "c" * 64,
                    "pii_review_index_sha256": "d" * 64,
                },
            )
