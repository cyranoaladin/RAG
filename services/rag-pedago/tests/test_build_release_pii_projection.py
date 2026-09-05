"""Le producteur projette la décision humaine, il ne la fabrique pas (ADR-0047).

`_pii_evidence` scannait le corpus et écrivait `DETECTED_RECORDED` pour tout
contenu détecté — un verdict honnête, mais définitif : rien ne pouvait admettre
un contenu après revue. Ces tests fixent le comportement inverse : le
producteur lit un ensemble de décisions scellé et son reçu, les confronte à son
propre scan, et projette leur résultat — ou refuse.

Le point qui compte : la population autorisée est CALCULÉE depuis les preuves.
Aucun compte attendu n'est écrit dans le producteur.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rag_pedago.imports.pii_review_projection import (
    PiiProjectionError,
    ScannedContent,
    ScannedFinding,
    project_pii_review,
)

PRODUCER = (
    Path(__file__).resolve().parents[1] / "scripts" / "build_production_profile_release.py"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DECISION_SET = REPO_ROOT / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
REAL_RECEIPT = REPO_ROOT / "governance/pii-review-bindings/pii-review-2026-09-03-final.json"
REAL_ANCHOR = REPO_ROOT / "governance/trust-anchors/review-binding-v1.json"
REAL_INDEX = REPO_ROOT / "docs/reports/evidence-index/pii_review_index_20260903.json"
REAL_REVIEWERS = REPO_ROOT / "scripts/github/trusted-reviewers.json"


class TestProducerCarriesNoBusinessConstant:
    def test_no_expected_population_is_written_in_the_producer(self) -> None:
        """Ni 297, ni 23, ni 320 comme littéraux du producteur.

        La garde lit l'arbre syntaxique : un commentaire a le droit
        d'expliquer d'où vient un nombre, le code n'a pas le droit de le
        présupposer."""
        literals = {
            node.value
            for node in ast.walk(ast.parse(PRODUCER.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert literals & {297, 23, 320} == set()


class TestProducerExposesTheReviewAuthority:
    def test_producer_declares_injected_review_authority_arguments(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """L'autorité de revue s'injecte ; elle n'est pas devinée d'un chemin.

        On interroge la VRAIE surface d'appel — `--help` — et non le texte du
        fichier : les options sont construites par boucle, et une garde qui
        cherche un littéral dans la source échouerait sur du code correct."""
        from conftest import load_producer

        module = load_producer()
        with pytest.raises(SystemExit):
            module.main(["--help"])
        helptext = capsys.readouterr().out
        for option in (
            "--pii-decision-set",
            "--pii-review-receipt",
            "--review-trust-anchor",
            "--pii-review-index",
            "--pii-review-reviewer",
        ):
            assert option in helptext, f"option {option} absente du producteur"

    def test_producer_binds_the_review_authority_into_the_release(self) -> None:
        """Le decision set et son reçu appartiennent à la chaîne d'autorité
        du NOUVEAU candidat (§7), pas à une release historique."""
        source = PRODUCER.read_text(encoding="utf-8")
        assert "pii_decision_set_sha256" in source
        assert "pii_review_receipt_sha256" in source


class TestRealDecisionSetProjectsOntoARealisticScan:
    """La projection tient sur le decision set réellement scellé."""

    def _decision_set(self) -> dict:
        import json

        return json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))

    def _scan_from_decisions(self, clean_count: int) -> list[ScannedContent]:
        """Reconstruit un scan cohérent avec les décisions réelles.

        On ne re-scanne pas 320 PDF ici : on vérifie l'ALGÈBRE sur les vraies
        décisions. Le scan réel est confronté aux décisions lors de la
        production de la candidate."""
        document = self._decision_set()
        scanned: list[ScannedContent] = []
        for index in range(clean_count):
            scanned.append(
                ScannedContent(
                    content_sha256=f"{index:064x}",
                    pages_scanned=1,
                    characters_scanned=1,
                    ignored_empty_pages=(),
                    findings=(),
                )
            )
        for decision in document["decisions"]:
            scanned.append(
                ScannedContent(
                    content_sha256=decision["content_sha256"],
                    pages_scanned=1,
                    characters_scanned=1,
                    ignored_empty_pages=(),
                    findings=tuple(
                        ScannedFinding(
                            finding_id=f["finding_id"],
                            pattern_id=f["pattern_id"],
                            page=f["page"],
                            match_sha256=f["match_sha256"],
                            context_sha256=f["context_sha256"],
                        )
                        for f in decision["findings"]
                    ),
                )
            )
        return scanned

    def _bundles(self) -> dict[str, str]:
        import json

        index = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        return {b["content_sha256"]: b["bundle_sha256"] for b in index["bundles"]}

    def _project(self, clean_count: int):
        document = self._decision_set()
        return project_pii_review(
            self._scan_from_decisions(clean_count),
            decision_set_document=document,
            review_bundles=self._bundles(),
            policy_sha256=document["policy_sha256"],
            scanner_sha256=document["scanner_sha256"],
            page_policy_sha256=document["page_policy_sha256"],
            corpus_manifest_sha256=document["corpus_manifest_sha256"],
        )

    def test_the_real_decisions_project_without_refusal(self) -> None:
        document = self._decision_set()
        decided = len(document["decisions"])
        projection = self._project(clean_count=7)
        assert projection.counts["detected_count"] == decided
        assert projection.counts["reviewed_accepted_count"] == decided
        assert projection.counts["rejected_count"] == 0
        assert projection.counts["cleared_count"] == 7
        assert projection.counts["authorized_count"] == 7 + decided

    def test_the_index_bundles_found_the_real_decisions(self) -> None:
        """Chaque décision réelle est adossée au paquet que l'index lui donne."""
        document = self._decision_set()
        bundles = self._bundles()
        for decision in document["decisions"]:
            assert bundles[decision["content_sha256"]] == decision["review_bundle_sha256"]

    def test_a_substituted_bundle_is_refused(self) -> None:
        """Sabotage : même cardinalité, un paquet remplacé."""
        document = self._decision_set()
        bundles = self._bundles()
        victim = document["decisions"][0]["content_sha256"]
        bundles[victim] = "0" * 64
        with pytest.raises(PiiProjectionError, match="bundle"):
            project_pii_review(
                self._scan_from_decisions(3),
                decision_set_document=document,
                review_bundles=bundles,
                policy_sha256=document["policy_sha256"],
                scanner_sha256=document["scanner_sha256"],
                page_policy_sha256=document["page_policy_sha256"],
                corpus_manifest_sha256=document["corpus_manifest_sha256"],
            )

    def test_a_scan_that_lost_one_decided_finding_is_refused(self) -> None:
        """Sabotage : une disposition qui ne porte plus sur rien."""
        document = self._decision_set()
        scanned = self._scan_from_decisions(3)
        # Un contenu à plusieurs findings : en retirer un doit déclencher la
        # garde des FINDINGS. Sur un contenu à finding unique, c'est la garde
        # « décision devenue sans objet » qui se déclenche d'abord — elle est
        # correcte aussi, mais ce n'est pas celle qu'on veut prouver ici.
        victim = next(c for c in scanned if len(c.findings) > 1)
        amputated = ScannedContent(
            content_sha256=victim.content_sha256,
            pages_scanned=victim.pages_scanned,
            characters_scanned=victim.characters_scanned,
            ignored_empty_pages=victim.ignored_empty_pages,
            findings=victim.findings[1:],
        )
        scanned = [amputated if c is victim else c for c in scanned]
        with pytest.raises(PiiProjectionError, match="no longer"):
            project_pii_review(
                scanned,
                decision_set_document=document,
                review_bundles=self._bundles(),
                policy_sha256=document["policy_sha256"],
                scanner_sha256=document["scanner_sha256"],
                page_policy_sha256=document["page_policy_sha256"],
                corpus_manifest_sha256=document["corpus_manifest_sha256"],
            )


class TestCandidateIsFinalButNotActivable:
    """Corpus final ≠ permission de déployer (§9-§10).

    Une release post-revue contient le corpus autorisé définitif, et n'est
    pourtant pas activable : le gate PII n'est qu'un des gates de go-live. Le
    producteur doit donc pouvoir émettre, en mode PRODUCTION (donc avec le vrai
    corpus, pas une répétition), une release marquée non promouvable et non
    activable — sous les enums qui existent déjà, et que le runtime refuse
    déjà mécaniquement."""

    def test_production_mode_accepts_candidate_status_flags(self) -> None:
        import inspect

        from conftest import load_producer

        signature = inspect.signature(load_producer()._release_topology_documents)
        for parameter in ("promotion_status", "activation_status", "review_status"):
            assert parameter in signature.parameters

    def test_the_production_path_forwards_the_candidate_flags(self) -> None:
        """Comportemental : une candidate SORT bloquée, quoi qu'on demande.

        La version précédente découpait le source du producteur à une
        indentation littérale de huit espaces et au premier `"\n    )"` — une
        indentation n'est pas une API, et le test cassait au moindre
        reformatage sans qu'aucun comportement ait changé."""
        from conftest import load_producer

        module = load_producer()
        statuses = module.resolve_release_lifecycle_statuses(
            release_mode="production", release_id=None,
            promotion_status=None, activation_status=None, review_status=None,
        )
        assert statuses["promotion_status"] == "NOT_PROMOTABLE"
        assert statuses["activation_status"] == "NO_PRODUCTION_ACTIVATION"

    def test_the_production_release_id_is_not_silently_reused(self) -> None:
        """Comportemental : `--release-id` décide de l'identité produite."""
        import inspect

        from conftest import load_producer

        signature = inspect.signature(load_producer().build_release)
        assert "release_id" in signature.parameters
        assert signature.parameters["release_id"].default is None


class TestCurrentnessVerdictNamesItsOwnRelease:
    """Un verdict de currentness porte sur LA release qui l'embarque (§8, §14).

    La branche de rejeu hors ligne écrivait `verdict_scope.release_id` depuis
    la constante historique du module, quel que soit le `--release-id` demandé.
    Une candidate aurait donc embarqué un verdict d'invérifiabilité désigné
    pour une autre release — et l'auditeur humain, seul consommateur déclaré de
    ce champ, aurait lu une portée qui n'est pas la sienne.
    """

    def _audit(self, release_id: str | None):
        import os

        from conftest import load_producer

        module = load_producer()
        previous = os.environ.get("NEXUS_CURRENTNESS_UNVERIFIED")
        os.environ["NEXUS_CURRENTNESS_UNVERIFIED"] = "SOURCE_UNREACHABLE"
        try:
            audit, _rows = module.resolve_currentness_network_audit(
                [],
                verify_official_downloads=False,
                release_id=release_id,
            )
        finally:
            if previous is None:
                os.environ.pop("NEXUS_CURRENTNESS_UNVERIFIED", None)
            else:
                os.environ["NEXUS_CURRENTNESS_UNVERIFIED"] = previous
        return audit

    def test_the_verdict_names_the_release_being_produced(self) -> None:
        audit = self._audit("production-profile-gate-2026-2027-v2-candidate-xyz")
        assert audit["verdict_scope"]["release_id"] == (
            "production-profile-gate-2026-2027-v2-candidate-xyz"
        )

    def test_without_an_explicit_identity_the_historical_one_is_kept(self) -> None:
        """Aucune émission existante ne change de cible du fait de ce correctif."""
        from conftest import load_producer

        module = load_producer()
        audit = self._audit(None)
        assert audit["verdict_scope"]["release_id"] == module.RELEASE_ID

    def test_the_verdict_never_claims_a_verification_took_place(self) -> None:
        audit = self._audit("candidate-x")
        assert audit["network_mode"] == "UNVERIFIED"
        assert audit["currentness_status"] == "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"
        assert audit["attempts"] == []
        assert audit["attempts_made_by_this_producer"] is False
        assert audit["verified_at"] is None


class TestRawPiiIsMeasuredNotDeclared:
    """P1 — `raw_pii_in_output: false` était une constante déclarative.

    Le producteur certifiait que sa preuve ne porte aucune matière brute sans
    jamais la mesurer. Une attestation qu'aucune mesure ne fonde ne vaut rien :
    elle dit ce que l'auteur croit, pas ce que le fichier contient.

    La mesure s'exécute désormais AVANT l'émission, sur les résultats
    réellement produits, et un finding est un refus — pas une note."""

    def _entries(self, extra: dict | None = None) -> list[dict]:
        rows = [
            {
                "content_sha256": f"{i:064x}",
                "status": "CLEARED",
                "pii_detected": False,
                "pages_scanned": 1,
                "characters_scanned": 1,
                "ignored_empty_pages": [],
                "source_path": f"01_EDUSCOL_OFFICIEL/doc-{i}.pdf",
            }
            for i in range(3)
        ]
        if extra:
            rows[1].update(extra)
        return rows

    def test_clean_evidence_passes_and_is_attested(self) -> None:
        from rag_pedago.imports.raw_pii_guard import require_no_raw_pii

        require_no_raw_pii({"results": self._entries()}, label="pii_evidence")

    def test_a_phone_injected_into_the_evidence_is_refused(self) -> None:
        from rag_pedago.imports.raw_pii_guard import RawPiiLeakError, require_no_raw_pii

        with pytest.raises(RawPiiLeakError, match="phone_french"):
            require_no_raw_pii(
                {"results": self._entries({"source_path": "appeler le 0612345678"})},
                label="pii_evidence",
            )

    def test_an_email_injected_into_the_evidence_is_refused(self) -> None:
        from rag_pedago.imports.raw_pii_guard import RawPiiLeakError, require_no_raw_pii

        with pytest.raises(RawPiiLeakError, match="email_address"):
            require_no_raw_pii(
                {"results": self._entries({"source_path": "contact jean@example.org"})},
                label="pii_evidence",
            )

    def test_the_refusal_never_repeats_the_material_it_reports(self) -> None:
        """Un rapport de fuite qui recopie la fuite est la fuite."""
        from rag_pedago.imports.raw_pii_guard import RawPiiLeakError, require_no_raw_pii

        try:
            require_no_raw_pii(
                {"results": self._entries({"source_path": "tel 0612345678"})},
                label="pii_evidence",
            )
        except RawPiiLeakError as exc:
            assert "0612345678" not in str(exc)
        else:  # pragma: no cover - le cas précédent lève toujours
            raise AssertionError("aucun refus")

    def test_the_producer_calls_the_guard_before_emitting(self) -> None:
        """La garde doit être DANS le chemin qui certifie, pas à côté."""
        source = PRODUCER.read_text(encoding="utf-8")
        assert "require_no_raw_pii" in source
        emission = source[: source.index('"raw_pii_in_output": False')]
        assert "require_no_raw_pii" in emission, (
            "la garde doit s'exécuter avant l'émission de l'attestation"
        )


class TestACandidateCanNeverBeAskedToBeActivable:
    """P1 — le cycle de vie ne se déduit pas du NOM de la release.

    La version précédente écrivait `is_candidate = release_id is not None`. Une
    production utilisant le `release_id` par défaut — cas parfaitement légitime,
    le paramètre valant `None` — était donc traitée comme non-candidate et
    transmettait des statuts activables au manifeste.

    Le signal juste est le MODE : une release de production n'est jamais émise
    activable, parce que la promotion se gagne aux gates C1-C6 et non par un
    argument de producteur. Une demande activante est refusée plutôt
    qu'écrasée — un appel qui la formule se trompe, et l'écraser sans rien dire
    lui laisserait croire qu'il l'a obtenue."""

    def _resolve(self, **kw):
        from conftest import load_producer

        return load_producer().resolve_release_lifecycle_statuses(**kw)

    def test_an_unsupported_mode_is_refused_not_treated_as_lenient(self) -> None:
        """`staging` n'est pas « pas la production » : c'est un mode inconnu.

        La garde s'écrivait `if release_mode != "production"`, si bien que
        `staging` — ou une simple faute de frappe — tombait dans la branche
        permissive et CONSERVAIT des statuts activables. Un mode que le
        producteur ne connaît pas doit être refusé, pas rattaché par défaut au
        cas le plus large."""
        with pytest.raises(ValueError, match="not supported"):
            self._resolve(
                release_mode="staging", release_id=None,
                promotion_status="PROMOTABLE",
                activation_status="PRODUCTION_ACTIVATION_ALLOWED",
                review_status=None,
            )

    def test_a_typo_in_the_mode_is_refused_too(self) -> None:
        with pytest.raises(ValueError, match="not supported"):
            self._resolve(
                release_mode="Production", release_id=None,
                promotion_status="PROMOTABLE", activation_status=None,
                review_status=None,
            )

    def test_rehearsal_remains_a_supported_mode(self) -> None:
        statuses = self._resolve(
            release_mode="rehearsal", release_id=None,
            promotion_status="PROMOTABLE", activation_status=None,
            review_status=None,
        )
        assert statuses["promotion_status"] == "PROMOTABLE"

    def test_production_without_release_id_defaults_to_blocking(self) -> None:
        statuses = self._resolve(
            release_mode="production", release_id=None,
            promotion_status=None, activation_status=None, review_status=None,
        )
        assert statuses["promotion_status"] == "NOT_PROMOTABLE"
        assert statuses["activation_status"] == "NO_PRODUCTION_ACTIVATION"

    def test_production_without_release_id_refuses_promotable(self) -> None:
        """Le cas exact que l'ancienne heuristique laissait passer."""
        with pytest.raises(ValueError, match="PROMOTABLE|activable"):
            self._resolve(
                release_mode="production", release_id=None,
                promotion_status="PROMOTABLE", activation_status=None,
                review_status=None,
            )

    def test_production_without_release_id_refuses_activation(self) -> None:
        with pytest.raises(ValueError, match="ACTIVATION|activable"):
            self._resolve(
                release_mode="production", release_id=None,
                promotion_status=None,
                activation_status="PRODUCTION_ACTIVATION_ALLOWED",
                review_status=None,
            )

    def test_production_with_explicit_release_id_refuses_promotable(self) -> None:
        with pytest.raises(ValueError, match="PROMOTABLE|activable"):
            self._resolve(
                release_mode="production", release_id="une-candidate-v2",
                promotion_status="PROMOTABLE", activation_status=None,
                review_status=None,
            )

    def test_production_with_explicit_release_id_and_blocking_values_passes(self) -> None:
        statuses = self._resolve(
            release_mode="production", release_id="une-candidate-v2",
            promotion_status="NOT_PROMOTABLE",
            activation_status="NO_PRODUCTION_ACTIVATION",
            review_status="REVIEWED",
        )
        assert statuses["review_status"] == "REVIEWED"

    def test_both_activating_values_are_refused(self) -> None:
        with pytest.raises(ValueError):
            self._resolve(
                release_mode="production", release_id=None,
                promotion_status="PROMOTABLE",
                activation_status="PRODUCTION_ACTIVATION_ALLOWED",
                review_status=None,
            )

    def test_the_lifecycle_never_depends_on_the_release_id(self) -> None:
        """Trois identités, un seul cycle de vie."""
        results = [
            self._resolve(
                release_mode="production", release_id=rid,
                promotion_status=None, activation_status=None, review_status=None,
            )
            for rid in (None, "auto-genere", "explicite-v2-candidate")
        ]
        assert all(r["promotion_status"] == "NOT_PROMOTABLE" for r in results)
        assert all(r["activation_status"] == "NO_PRODUCTION_ACTIVATION" for r in results)

    def test_the_producer_holds_no_release_id_heuristic(self) -> None:
        """Le motif exact qui déduisait le cycle de vie du nom ne doit pas revenir."""
        assert "is_candidate=release_id is not None" not in PRODUCER.read_text(
            encoding="utf-8"
        )


class TestTheDecisionSetMustCoverThisCorpus:
    """P1 — un ensemble scellé pour un AUTRE corpus projetait quand même.

    `corpus_manifest_sha256` figure dans l'ensemble de décisions précisément
    pour dire de quel corpus il parle. Rien ne le confrontait au corpus de la
    candidate : une campagne de revue menée sur un autre corpus, dont les SHA
    de contenus coïncideraient, aurait admis des contenus que personne n'a
    examinés dans CE corpus."""

    def _project(self, manifest: str):
        import json as _json

        from rag_pedago.imports.pii_review_projection import project_pii_review

        document = _json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))
        scanned = TestRealDecisionSetProjectsOntoARealisticScan()._scan_from_decisions(3)
        bundles = TestRealDecisionSetProjectsOntoARealisticScan()._bundles()
        return project_pii_review(
            scanned,
            decision_set_document=document,
            review_bundles=bundles,
            policy_sha256=document["policy_sha256"],
            scanner_sha256=document["scanner_sha256"],
            page_policy_sha256=document["page_policy_sha256"],
            corpus_manifest_sha256=manifest,
        )

    def test_the_matching_corpus_manifest_projects(self) -> None:
        import json as _json

        document = _json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))
        projection = self._project(document["corpus_manifest_sha256"])
        assert projection.counts["reviewed_accepted_count"] == 23

    def test_another_corpus_manifest_is_refused(self) -> None:
        from rag_pedago.imports.pii_review_projection import PiiProjectionError

        with pytest.raises(PiiProjectionError, match="corpus manifest"):
            self._project("0" * 64)

    def test_the_binding_is_required_not_optional(self) -> None:
        """Omettre le manifeste n'est pas une façon d'échapper au contrôle."""
        from rag_pedago.imports.pii_review_projection import PiiProjectionError

        with pytest.raises((PiiProjectionError, TypeError)):
            self._project(None)  # type: ignore[arg-type]


class TestTheReviewIndexCannotDisableItsOwnCheck:
    """P2 — un champ interne au fichier désactivait le contrôle du fichier.

    Le producteur ne comparait l'empreinte de l'index à celle scellée dans les
    décisions que si l'index ne déclarait PAS `review_index_sha256_declared`.
    Cette clé vit dans le fichier vérifié : quiconque fournit l'index pouvait
    donc la poser et éteindre le seul contrôle qui le lie à la campagne.

    L'index réel satisfait le contrôle (bcb4c6f4…), qui devient donc
    inconditionnel sans rien casser de la campagne scellée."""

    def test_the_real_index_matches_the_sealed_digest(self) -> None:
        import hashlib
        import json as _json

        decisions = _json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))
        assert (
            hashlib.sha256(REAL_INDEX.read_bytes()).hexdigest()
            == decisions["review_index_sha256"]
        )

    def test_a_self_declared_flag_no_longer_disables_the_check(self) -> None:
        source = PRODUCER.read_text(encoding="utf-8")
        assert 'index.get("review_index_sha256_declared")' not in source, (
            "un champ du fichier vérifié ne peut pas décider s'il est vérifié"
        )

    def test_a_substituted_index_is_refused(self, tmp_path: Path) -> None:
        """Sabotage : un index d'une autre campagne, correctement formé."""
        import json as _json

        from conftest import load_producer

        module = load_producer()
        index = _json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        index["campaign_id"] = "pii-review-autre-campagne"
        forged = tmp_path / "index.json"
        forged.write_text(_json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        inputs = module.ReviewAuthorityInputs(
            decision_set_path=REAL_DECISION_SET,
            receipt_path=REAL_RECEIPT,
            trust_anchor_path=REAL_ANCHOR,
            review_index_path=forged,
            reviewers=("abenrhouma",),
        )
        with pytest.raises(ValueError, match="review index"):
            module._load_review_authority(inputs)


class TestTheProjectionIsBoundToTheAuthorityFile:
    """Le producteur doit passer l'empreinte du FICHIER d'autorité.

    L'ensemble de décisions scellé enregistre, sous `corpus_manifest_sha256`,
    l'empreinte des OCTETS du fichier d'autorité de manifeste. Le producteur
    passait `CORPUS_MANIFEST_AUTHORITY`, qui est la valeur que ce fichier
    DÉCLARE. Deux mesures de la même autorité, jamais égales.

    Conséquence mesurée : la garde censée empêcher qu'une revue soit projetée
    sur un autre corpus refusait le corpus même sur lequel la revue avait été
    rendue, et la candidate de production devenait irreproductible —
    « the decisions describe another corpus », sur les décisions qui la
    décrivent exactement.
    """

    def test_the_producer_binds_the_projection_to_the_authority_file_bytes(
        self,
    ) -> None:
        import json

        from conftest import load_producer

        producer = load_producer()
        sealed = json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))[
            "corpus_manifest_sha256"
        ]

        bound = producer.corpus_manifest_authority_file_sha256()
        assert bound == sealed, (
            "le producteur ne lie plus la projection au fichier d'autorité sur "
            "lequel la revue humaine a été rendue"
        )

    def test_the_declared_value_alone_would_refuse_the_sealed_campaign(self) -> None:
        """Ce qui rend le test précédent nécessaire, dit explicitement."""
        import json

        from conftest import load_producer

        producer = load_producer()
        sealed = json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))[
            "corpus_manifest_sha256"
        ]
        assert producer.CORPUS_MANIFEST_AUTHORITY != sealed, (
            "la valeur déclarée et l'empreinte du fichier ont convergé : la "
            "confusion cesserait d'être une erreur"
        )

    def test_an_authority_file_declaring_another_corpus_is_refused(
        self, tmp_path, monkeypatch
    ) -> None:
        """L'égalité d'empreinte ne prouve rien si le fichier décrit un AUTRE corpus.

        Le fichier d'autorité et la release doivent d'abord parler du même
        objet : sans cette vérification, on comparerait l'empreinte d'octets
        d'un document sans rapport à la valeur que l'ensemble scellé attend,
        et la coïncidence — ou son absence — ne dirait rien du corpus."""
        import json
        import shutil

        from conftest import load_producer

        producer = load_producer()
        forged_root = tmp_path / "profile_gate"
        forged_root.mkdir(parents=True)
        original = producer.RELEASE_ROOT / "corpus_manifest_authority.json"
        shutil.copy2(original, forged_root / "corpus_manifest_authority.json")

        target = forged_root / "corpus_manifest_authority.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        document["authority_sha256"] = "9" * 64
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        monkeypatch.setattr(producer, "RELEASE_ROOT", forged_root)
        with pytest.raises(ValueError, match="do not describe the same corpus authority"):
            producer.corpus_manifest_authority_file_sha256()

    def test_a_missing_authority_file_is_refused_by_name(
        self, tmp_path, monkeypatch
    ) -> None:
        from conftest import load_producer

        producer = load_producer()
        monkeypatch.setattr(producer, "RELEASE_ROOT", tmp_path)
        with pytest.raises(ValueError, match="corpus manifest authority is missing"):
            producer.corpus_manifest_authority_file_sha256()


class TestTheHumanReviewBindsTheFinalCandidateCorpus:
    """Le pont entre la revue humaine et la candidate — mesuré, pas affirmé.

    La chaîne d'autorités prouvait que chaque DOCUMENT était intact : decision
    set, reçu, ancre, index. Aucune de ces vérifications ne disait sur quelle
    MATIÈRE la revue avait porté.

    Mesuré sur la campagne réelle : le fichier d'autorité que le decision set
    scelle décrit 26 contenus ; la candidate en émet 320. Prouver que ce
    fichier est intact ne prouve donc rien de la candidate. Le seul champ qui
    désigne la matière revue est `content_set_sha256` de l'index — lu pour ses
    paquets, jamais confronté à l'ensemble produit. La coïncidence était
    affirmée dans un commentaire et vérifiée nulle part.
    """

    def test_the_reviewed_content_set_is_the_one_the_candidate_ships(self) -> None:
        """Les quatre maillons, sur les artefacts RÉELS de la campagne."""
        import hashlib
        import json

        from conftest import load_producer

        producer = load_producer()

        decisions = json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))
        index_path = REAL_INDEX
        index = json.loads(index_path.read_text(encoding="utf-8"))

        # 1. le decision set scelle CET index
        assert decisions["review_index_sha256"] == hashlib.sha256(
            index_path.read_bytes()
        ).hexdigest()
        # 2. le decision set scelle CE fichier d'autorité
        assert decisions["corpus_manifest_sha256"] == (
            producer.corpus_manifest_authority_file_sha256()
        )
        # 3. l'index nomme l'ensemble de contenus revu
        reviewed = index["content_set_sha256"]
        # 4. la lignée canonique produit exactement cet ensemble
        assert producer.CANONICAL_CONTENT_SET_SHA256 == reviewed, (
            "la lignée canonique ne produit plus l'ensemble que la revue a "
            "couvert : la revue ne lierait plus la candidate"
        )

    def test_the_reviewed_authority_file_describes_another_selection(self) -> None:
        """Ce qui rend le pont NÉCESSAIRE, énoncé plutôt que sous-entendu.

        Si ce test venait à échouer parce que les deux sélections ont
        convergé, le pont deviendrait redondant — et on le saurait."""
        import json

        from conftest import load_producer

        producer = load_producer()
        wrapper = json.loads(
            (producer.RELEASE_ROOT / "corpus_manifest_authority.json").read_text(
                encoding="utf-8"
            )
        )
        assert wrapper["final_content_set_sha256"] != (
            producer.CANONICAL_CONTENT_SET_SHA256
        ), "le fichier scellé et la candidate décrivent la même sélection"

    def test_a_review_covering_another_content_set_is_refused(self) -> None:
        """La garde elle-même, exercée — pas seulement ses prémisses."""
        from conftest import load_producer

        producer = load_producer()
        with pytest.raises(ValueError, match="does not bind the corpus"):
            producer.require_review_covers_produced_content_set(
                reviewed_content_set_sha256="a" * 64,
                produced_content_set_sha256="b" * 64,
            )

    def test_the_matching_content_set_passes(self) -> None:
        from conftest import load_producer

        load_producer().require_review_covers_produced_content_set(
            reviewed_content_set_sha256="a" * 64,
            produced_content_set_sha256="a" * 64,
        )

    def test_no_review_authority_means_nothing_to_bind(self) -> None:
        """Absence d'autorité : rien n'est projeté, le registre refuse ailleurs."""
        from conftest import load_producer

        load_producer().require_review_covers_produced_content_set(
            reviewed_content_set_sha256=None,
            produced_content_set_sha256="a" * 64,
        )

    def test_the_loader_carries_the_reviewed_content_set_through(self) -> None:
        """Le CÂBLAGE, pas seulement la garde.

        La garde peut être parfaite et ne jamais recevoir la valeur : si le
        chargeur d'autorité cesse d'extraire `content_set_sha256` de l'index,
        la confrontation reçoit `None` et se tait. Ce test exerce la chaîne
        réelle, sur les artefacts scellés de la campagne."""
        import json

        from conftest import load_producer

        producer = load_producer()
        index_path = REAL_INDEX
        reviewers = tuple(
            json.loads(REAL_REVIEWERS.read_text(encoding="utf-8"))["reviewers"]
        )
        inputs = producer.ReviewAuthorityInputs(
            decision_set_path=REAL_DECISION_SET,
            receipt_path=REAL_RECEIPT,
            trust_anchor_path=REAL_ANCHOR,
            review_index_path=index_path,
            reviewers=reviewers,
        )
        _document, _bundles, digests = producer._load_review_authority(inputs)
        expected = json.loads(index_path.read_text(encoding="utf-8"))["content_set_sha256"]
        assert digests.get("reviewed_content_set_sha256") == expected, (
            "le chargeur ne transmet plus l'ensemble de contenus revu : la "
            "confrontation avec la candidate ne recevrait rien à comparer"
        )


class TestTheContentSetDigestHasOneMeaning:
    """Trois implémentations, une seule vérité — ou la preuve ne veut rien dire.

    La formule d'empreinte d'ensemble est écrite dans le producteur
    (`_final_set_digest`), dans le moteur (`content_set_sha256`) et dans le
    vérificateur de store adressable par contenu. Trois copies qui dérivent
    produiraient trois « vérités » : le store prouverait sa conformité à une
    attente que le producteur ne partage plus.

    Ce test les confronte sur les mêmes entrées. Il ne les fusionne pas — les
    trois vivent dans des périmètres différents, et un import croisé entre
    services est interdit par AGENTS.md — mais il interdit qu'elles divergent.
    """

    def test_the_qualification_verifier_agrees_with_the_producer(self) -> None:
        import importlib.util
        import pathlib

        from conftest import load_producer

        producer = load_producer()
        repository = pathlib.Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "_verify_cas", repository / "scripts/qualification/verify_corpus_cas.py"
        )
        assert spec and spec.loader
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)

        for sample in (
            {"a" * 64},
            {"a" * 64, "b" * 64},
            {f"{i:064x}" for i in range(37)},
        ):
            assert verifier.content_set_digest(sample) == producer._final_set_digest(
                sorted(sample)
            ), "le vérificateur du store et le producteur ne calculent plus la même chose"

    def test_the_two_implementations_agree_on_a_real_shaped_input(self) -> None:
        """PARITÉ D'IMPLÉMENTATION sur une entrée de forme réelle — rien de plus.

        Ce test s'appelait « real lineage digest » et prétendait donc prouver
        la lignée. Il ne le pouvait pas : les deux côtés calculent la même
        formule sur la même entrée, et l'ensemble dérivé des 23 paquets n'est
        même pas le `content_set_sha256` de l'index, qui porte sur les 320.
        Un nom qui promet plus que l'assertion égare quiconque s'y fie.

        La vraie attente versionnée est vérifiée par
        `test_the_versioned_expectation_is_the_lineage_the_producer_holds`."""
        import importlib.util
        import json
        import pathlib

        from conftest import load_producer

        producer = load_producer()
        repository = pathlib.Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "_verify_cas2", repository / "scripts/qualification/verify_corpus_cas.py"
        )
        assert spec and spec.loader
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)

        index = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        contents = {entry["content_sha256"] for entry in index["bundles"]}
        assert verifier.content_set_digest(contents) == producer._final_set_digest(
            sorted(contents)
        )


class TestTheVersionedExpectationIsNotDrifting:
    """L'attente que le store doit satisfaire est-elle celle du producteur ?

    Le vérificateur du store adressable par contenu compare l'ensemble récupéré
    à l'empreinte que l'index de la revue humaine DÉCLARE. Encore faut-il que
    cette empreinte soit celle que la lignée canonique produit — sinon le store
    prouverait sa conformité à une attente que le producteur ne partage plus.
    """

    def test_the_versioned_expectation_is_the_lineage_the_producer_holds(self) -> None:
        import json

        from conftest import load_producer

        producer = load_producer()
        index = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        assert index["content_set_sha256"] == producer.CANONICAL_CONTENT_SET_SHA256, (
            "l'index de revue et la lignée canonique ne désignent plus le même "
            "ensemble de contenus : le store serait vérifié contre une attente "
            "que le producteur ne produit pas"
        )

    def test_the_versioned_count_matches_the_lineage_count(self) -> None:
        """Le compte que le workflow lit doit décrire le même ensemble."""
        import json

        index = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        assert index["counts"]["scanned"] == 320, (
            "le compte versionné a changé sans que la lignée soit revue"
        )
