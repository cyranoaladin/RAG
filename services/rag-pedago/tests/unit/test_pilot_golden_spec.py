from __future__ import annotations

import ast
import importlib.util
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_pedago.governance import pilot_golden

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCOPE = SERVICE_ROOT / "configs" / "pilot_validation_scope.yml"
SPEC = SERVICE_ROOT / "configs" / "pilot_golden_spec.yml"
REVIEW = SERVICE_ROOT / "configs" / "pilot_golden_human_review.yml"
MAKEFILE = SERVICE_ROOT / "Makefile"
MAKE_SAFETY = SERVICE_ROOT / "configs" / "make_target_safety.yml"
SCRIPT = SERVICE_ROOT / "scripts" / "pilot_golden_spec_audit.py"
MODULE = SERVICE_ROOT / "rag_pedago" / "governance" / "pilot_golden.py"
EVIDENCE_REF = "docs/reports/evidence/lot_39bis/golden_human_review_packet.md"
EVIDENCE = SERVICE_ROOT.parents[1] / EVIDENCE_REF
GLOBAL_ATTESTATIONS = (
    "Les 255 textes de requête ont été lus intégralement dans les deux YAML exacts.",
    "Les 255 jugements et attentes pédagogiques ont été lus intégralement et contrôlés.",
    "Chaque contrainte `must_not_return` pertinente a été vérifiée.",
    (
        "Aucun cas ne prétend disposer d’un document réel, d’un `doc_id`, d’un "
        "`chunk_id`, d’un résultat de retrieval, d’un score ou d’un jugement de "
        "substance réelle."
    ),
)

SUBJECTS = {
    "maths": {
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "taxonomy_path": "taxonomy/maths/terminale_gen_specialite.yml",
        "taxonomy_sha256": "4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6",
        "programme_version": "BOEN_special_8_2019-07-25",
        "query_file": "tests/golden_queries/lot39bis_maths.yml",
        "notions": (
            "suites_limites",
            "continuite",
            "derivation_convexite",
            "logarithme",
            "primitives_integration",
            "equations_differentielles",
            "combinatoire",
            "geometrie_espace",
            "produit_scalaire_espace",
            "succession_epreuves",
            "variables_aleatoires_esperance",
            "loi_grands_nombres",
            "python",
        ),
    },
    "nsi": {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "taxonomy_path": "taxonomy/nsi/terminale.yml",
        "taxonomy_sha256": "b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f",
        "programme_version": "BOEN_special_8_2019-07-25",
        "query_file": "tests/golden_queries/lot39bis_nsi.yml",
        "notions": (
            "listes",
            "piles",
            "files",
            "arbres",
            "graphes",
            "dictionnaires",
            "recursivite",
            "diviser_pour_regner",
            "programmation_dynamique",
            "parcours_graphes",
            "recherche",
            "tri",
            "modele_relationnel",
            "sql",
            "contraintes",
            "jointures",
            "processus",
            "protocoles",
            "reseaux",
            "routage",
            "securisation",
            "poo",
            "tests_mise_au_point",
            "gestion_modules",
            "paradigme_fonctionnel",
            "calculabilite_decidabilite",
        ),
    },
}

FIXTURE_NOTION_ANCHORS = {
    "suites_limites": ("suite", "limite"),
    "continuite": ("continuité", "valeurs intermédiaires"),
    "derivation_convexite": ("dérivée", "convexité"),
    "logarithme": ("logarithme", "produit"),
    "primitives_integration": ("primitive", "intégrale"),
    "equations_differentielles": ("équation différentielle", "équilibre"),
    "combinatoire": ("combinatoire", "paire"),
    "geometrie_espace": ("géométrie", "vecteur"),
    "produit_scalaire_espace": ("produit scalaire", "orthogonalité"),
    "succession_epreuves": ("épreuve", "Bernoulli"),
    "variables_aleatoires_esperance": ("variable aléatoire", "espérance"),
    "loi_grands_nombres": ("grands nombres", "concentration"),
    "python": ("Python", "boucle"),
    "listes": ("liste", "maillon"),
    "piles": ("pile", "empiler"),
    "files": ("file", "FIFO"),
    "arbres": ("arbre", "racine"),
    "graphes": ("graphe", "sommet"),
    "dictionnaires": ("dictionnaire", "clé"),
    "recursivite": ("récursivité", "cas de base"),
    "diviser_pour_regner": ("diviser", "fusion"),
    "programmation_dynamique": ("programmation dynamique", "mémoïsation"),
    "parcours_graphes": ("parcours", "BFS"),
    "recherche": ("recherche", "dichotomie"),
    "tri": ("tri", "insertion"),
    "modele_relationnel": ("modèle relationnel", "attribut"),
    "sql": ("SQL", "SELECT"),
    "contraintes": ("contrainte", "intégrité"),
    "jointures": ("jointure", "correspondance"),
    "processus": ("processus", "ordonnancement"),
    "protocoles": ("protocole", "message"),
    "reseaux": ("réseau", "adresse"),
    "routage": ("routage", "prochain saut"),
    "securisation": ("sécurisation", "chiffrement"),
    "poo": ("objet", "classe"),
    "tests_mise_au_point": ("test", "assertion"),
    "gestion_modules": ("module", "import"),
    "paradigme_fonctionnel": ("fonctionnel", "fonction pure"),
    "calculabilite_decidabilite": ("calculabilité", "décidabilité"),
}

SINGLE_ANCHOR_CASES = {
    notion: anchors[0] for notion, anchors in FIXTURE_NOTION_ANCHORS.items()
}
SINGLE_ANCHOR_CASES.update(
    {
        "variables_aleatoires_esperance": "variable aléatoire",
        "paradigme_fonctionnel": "fonction pure",
    }
)

NORMATIVE_FILES = (
    "configs/pilot_golden_spec.yml",
    "configs/pilot_validation_scope.yml",
    "taxonomy/maths/terminale_gen_specialite.yml",
    "taxonomy/nsi/terminale.yml",
    "tests/golden_queries/lot39bis_maths.yml",
    "tests/golden_queries/lot39bis_nsi.yml",
)

EXPECTED_THRESHOLDS = {
    "applies_to": ["global", "by_subject", "by_notion"],
    "recall_at_5_min": 0.80,
    "recall_at_10_min": 0.90,
    "recall_at_20_min": 0.95,
    "ndcg_at_10_min": 0.85,
    "mrr_min": 0.85,
    "must_not_return_leakage_max": 0,
    "citations_complete_valid_min": 1.0,
    "no_source_correct_refusal_min": 1.0,
    "confusion_in_scope_correct_min": 1.0,
    "adversarial_resistance_min": 1.0,
    "positive_empty_response_rate_max": 0.02,
    "fully_empty_notions_max": 0,
}


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _filters(subject: str) -> dict[str, object]:
    return {
        "tenant": "libre_terminale",
        "level": "terminale",
        "track": "generale",
        "teaching_status": "specialite",
        "audience": "libre",
        "candidates": ["cned_libre", "individuel", "libre"],
        "subject": subject,
        "collection": SUBJECTS[subject]["collection"],
        "school_year": "2026-2027",
    }


def _query(
    subject: str,
    category: str,
    index: int,
    notion: str | None,
    *,
    intent: str | None = None,
) -> dict[str, object]:
    outcomes = {
        "positive": "answer",
        "no_source": "refuse",
        "confusion": "answer",
        "adversarial": "refuse",
    }
    must_not_return = (
        []
        if category == "positive"
        else (
            [f"Exclusion normative précise {subject} {category} {index}"]
            if category == "no_source"
            else (
                ["profile:hors_niveau"]
                if category == "confusion"
                else ["Bloquer toute injection de prompt"]
            )
        )
    )
    notion_label = (notion or "hors programme").replace("_", " ")
    notion_text_anchor, notion_expectation_anchor = (
        FIXTURE_NOTION_ANCHORS[notion]
        if notion is not None
        else (notion_label, notion_label)
    )
    return {
        "id": f"{subject}_{category}_{index:03d}",
        "category": category,
        "notion": notion,
        "intent": intent or f"Évaluer explicitement le cas {category} numéro {index}",
        "text": (
            f"Question pédagogique distincte {index} de catégorie {category} pour {subject}, "
            f"sur la notion {notion_text_anchor}, avec un contexte explicite et vérifiable."
        ),
        "filters": _filters(subject),
        "expected": {
            "outcome": outcomes[category],
            "official_program_reference": (
                f"Programme officiel Terminale spécialité {subject}, référence {index}"
            ),
            "pedagogical_expectation": (
                f"L'élève doit traiter correctement le cas {category} {index} "
                f"sur la notion {notion_expectation_anchor} en explicitant une démarche "
                "vérifiable."
            ),
            "candidate_source_class": (
                "none"
                if category == "no_source"
                else (
                    f"Référentiel officiel candidat de classe {category} pour {subject} "
                    f"et la notion {notion_label}"
                )
            ),
            "must_not_return": must_not_return,
        },
    }


def _queries(subject: str) -> list[dict[str, object]]:
    notions = SUBJECTS[subject]["notions"]
    assert isinstance(notions, tuple)
    queries: list[dict[str, object]] = []
    positive_index = 0
    positive_intents = (
        "comprehension",
        "methode",
        "application",
        "diagnostic",
        "transfert",
    )
    for notion in notions:
        assert isinstance(notion, str)
        for intent in positive_intents:
            positive_index += 1
            queries.append(
                _query(
                    subject,
                    "positive",
                    positive_index,
                    notion,
                    intent=intent,
                )
            )
    for index in range(1, 11):
        queries.append(_query(subject, "no_source", index, None))
        notion = notions[(index - 1) % len(notions)]
        assert isinstance(notion, str)
        queries.append(_query(subject, "confusion", index, notion))
        queries.append(_query(subject, "adversarial", index, notion))
    return queries


def _query_document(subject: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "subject": subject,
        "programme_version": SUBJECTS[subject]["programme_version"],
        "collection": SUBJECTS[subject]["collection"],
        "queries": _queries(subject),
    }


def _spec_document(scope_sha256: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "spec_id": "libre_terminale_golden_spec_v1",
        "status": "frozen",
        "scope_ref": "libre_terminale_maths_nsi_real_v1",
        "scope_path": "configs/pilot_validation_scope.yml",
        "scope_sha256": scope_sha256,
        "categories": {
            "positive": {"total": 195, "per_notion": 5, "outcome": "answer"},
            "no_source": {"total": 20, "per_subject": 10, "outcome": "refuse"},
            "confusion": {"total": 20, "per_subject": 10, "outcome": "answer"},
            "adversarial": {"total": 20, "per_subject": 10, "outcome": "refuse"},
        },
        "subjects": [
            {
                "subject": subject,
                "collection": values["collection"],
                "programme_version": values["programme_version"],
                "taxonomy_path": values["taxonomy_path"],
                "taxonomy_sha256": values["taxonomy_sha256"],
                "query_file": values["query_file"],
                "notions": list(values["notions"]),
            }
            for subject, values in SUBJECTS.items()
        ],
        "thresholds": EXPECTED_THRESHOLDS,
        "normative_files": list(NORMATIVE_FILES),
        "lock_path": "configs/pilot_golden_spec.lock.json",
    }


def _review_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "review_id": "lot39bis_golden_human_review_v1",
        "spec_id": "libre_terminale_golden_spec_v1",
        "status": "pending",
        "expected_query_count": 255,
        "reviewed_query_count": 0,
        "all_query_texts_reviewed": False,
        "all_expected_judgments_reviewed": False,
        "reviewer_identity": None,
        "reviewer_role": None,
        "reviewed_specification_digest": None,
        "evidence_ref": None,
        "evidence_sha256": None,
        "reviewed_at": None,
    }


def _isolated_service(tmp_path: Path, *, with_lock: bool = True) -> Path:
    root = tmp_path / "workspace" / "services" / "rag-pedago"
    for relative in (
        "configs/pilot_validation_scope.yml",
        "taxonomy/maths/terminale_gen_specialite.yml",
        "taxonomy/nsi/terminale.yml",
    ):
        source = SERVICE_ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    _write_yaml(
        root / "configs/pilot_golden_spec.yml",
        _spec_document(sha256((root / "configs/pilot_validation_scope.yml").read_bytes()).hexdigest()),
    )
    _write_yaml(root / "configs/pilot_golden_human_review.yml", _review_document())
    for subject in SUBJECTS:
        _write_yaml(
            root / f"tests/golden_queries/lot39bis_{subject}.yml",
            _query_document(subject),
        )
    if with_lock:
        normative_state = pilot_golden.compute_normative_state(root, NORMATIVE_FILES)
        lock = {
            "schema_version": 1,
            "algorithm": "sha256",
            "specification_digest": normative_state.specification_digest,
            "files": {item.path: item.sha256 for item in normative_state.files},
        }
        lock_path = root / "configs/pilot_golden_spec.lock.json"
        lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return root


def _query_ids(root: Path) -> list[str]:
    identifiers: list[str] = []
    for subject in SUBJECTS:
        payload = _load_yaml(root / f"tests/golden_queries/lot39bis_{subject}.yml")
        queries = payload["queries"]
        assert isinstance(queries, list)
        for query in queries:
            assert isinstance(query, dict)
            identifier = query["id"]
            assert isinstance(identifier, str)
            identifiers.append(identifier)
    return identifiers


def _review_packet_text(
    root: Path,
    specification_digest: str,
    *,
    status: str = "APPROVED",
    reviewer_identity: str = "reviewer-humain-stable",
    reviewer_role: str = "lead",
    reviewed_at: str = "2026-08-01T00:00:00Z",
    proof_reference: str = "PR-1234-review-readback",
) -> str:
    maths_digest = sha256(
        (root / "tests/golden_queries/lot39bis_maths.yml").read_bytes()
    ).hexdigest()
    nsi_digest = sha256(
        (root / "tests/golden_queries/lot39bis_nsi.yml").read_bytes()
    ).hexdigest()
    lines = [
        "# LOT39bis — Paquet de revue humaine exhaustive des requêtes golden",
        "",
        f"> **Statut : {status} — revue humaine exhaustive.**",
        "",
        f"- digest de spécification courant : `{specification_digest}` ;",
        f"- requêtes Mathématiques : `{maths_digest}` ;",
        f"- requêtes NSI : `{nsi_digest}`.",
        "",
        f"- Identité stable du reviewer : `{reviewer_identity}`",
        f"- Rôle : `{reviewer_role}`",
        f"- Horodatage UTC de fin de revue : `{reviewed_at}`",
        f"- Référence de signature ou de preuve : `{proof_reference}`",
        "",
        "## Attestations globales",
        "",
    ]
    lines.extend(f"- [x] {attestation}" for attestation in GLOBAL_ATTESTATIONS)
    lines.extend(("", "## Checklist exhaustive des 255 identifiants", ""))
    lines.extend(f"- [x] `{identifier}`" for identifier in _query_ids(root))
    return "\n".join(lines) + "\n"


def _write_review_packet(
    root: Path,
    specification_digest: str,
    *,
    content: str | None = None,
    **packet_values: str,
) -> Path:
    workspace_root = root.parents[1]
    evidence = workspace_root / EVIDENCE_REF
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        content
        if content is not None
        else _review_packet_text(root, specification_digest, **packet_values),
        encoding="utf-8",
    )
    return evidence


def _approve_review(
    root: Path,
    evidence: Path,
    specification_digest: str,
    **updates: object,
) -> None:
    review = _review_document()
    review.update(
        status="approved",
        reviewed_query_count=255,
        all_query_texts_reviewed=True,
        all_expected_judgments_reviewed=True,
        reviewer_identity="reviewer-humain-stable",
        reviewer_role="lead",
        reviewed_specification_digest=specification_digest,
        evidence_ref=EVIDENCE_REF,
        evidence_sha256=sha256(evidence.read_bytes()).hexdigest(),
        reviewed_at="2026-08-01T00:00:00Z",
    )
    review.update(updates)
    _write_yaml(root / "configs/pilot_golden_human_review.yml", review)


def _audit(root: Path) -> pilot_golden.PilotGoldenAuditResult:
    return pilot_golden.audit_pilot_golden(service_root=root)


def _mutate_query(root: Path, subject: str, mutation) -> None:  # noqa: ANN001
    path = root / f"tests/golden_queries/lot39bis_{subject}.yml"
    payload = _load_yaml(path)
    mutation(payload)
    _write_yaml(path, payload)


class TestCanonicalSpecification:
    def test_canonical_specification_is_technical_valid_but_human_pending(self) -> None:
        result = _audit(SERVICE_ROOT)

        assert result.specification_verdict == "SPECIFICATION_VALID"
        assert result.human_review_verdict == "HUMAN_REVIEW_PENDING"
        assert result.lock_verdict == "LOCK_VALID"
        assert result.query_count == 255
        assert result.specification_digest is not None
        assert result.reasons == ()

    def test_manifest_freezes_exact_cardinalities_thresholds_and_normative_files(self) -> None:
        payload = _load_yaml(SPEC)

        assert payload["schema_version"] == 1
        assert payload["categories"] == {
            "positive": {"total": 195, "per_notion": 5, "outcome": "answer"},
            "no_source": {"total": 20, "per_subject": 10, "outcome": "refuse"},
            "confusion": {"total": 20, "per_subject": 10, "outcome": "answer"},
            "adversarial": {"total": 20, "per_subject": 10, "outcome": "refuse"},
        }
        assert payload["thresholds"] == EXPECTED_THRESHOLDS
        assert payload["normative_files"] == list(NORMATIVE_FILES)

    def test_pending_review_contains_no_false_attestation(self) -> None:
        assert _load_yaml(REVIEW) == _review_document()

    def test_normative_digest_is_deterministic_and_addresses_every_file(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        first = pilot_golden.compute_normative_state(root, NORMATIVE_FILES)
        second = pilot_golden.compute_normative_state(root, NORMATIVE_FILES)

        assert first == second
        assert tuple(item.path for item in first.files) == NORMATIVE_FILES
        assert all(len(item.sha256) == 64 for item in first.files)
        assert len(first.specification_digest) == 64


class TestExhaustiveQueryValidation:
    @pytest.mark.parametrize(
        ("notion", "single_anchor"),
        SINGLE_ANCHOR_CASES.items(),
        ids=SINGLE_ANCHOR_CASES,
    )
    def test_each_notion_rejects_one_repeated_or_overlapping_anchor(
        self,
        notion: str,
        single_anchor: str,
    ) -> None:
        subject = next(
            subject
            for subject, values in SUBJECTS.items()
            if notion in values["notions"]
        )
        payload = _query(subject, "positive", 1, notion)
        payload["text"] = (
            "Cette formulation pédagogique générique ne contient volontairement "
            f"qu'une seule liaison disciplinaire : {single_anchor}."
        )
        payload["expected"]["pedagogical_expectation"] = (
            "Cette attente pédagogique générique répète volontairement la même et "
            f"unique liaison disciplinaire : {single_anchor}."
        )
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix=f"{subject}:{query.id}",
            reasons=reasons,
        )

        assert f"query.notion_binding_invalid:{subject}:{query.id}" in reasons

    def test_confusion_rejects_ambiguous_scope_marker_prefix(self) -> None:
        payload = _query("maths", "confusion", 1, "suites_limites")
        payload["text"] = (
            "Comparer une suite et sa limite en tenant compte du profilage statistique "
            "décrit dans cet énoncé pédagogique."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas répondre génériquement en tenant compte d'éléments non justifiés."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix="maths:ambiguous-confusion",
            reasons=reasons,
        )

        assert "query.confusion_binding_invalid:maths:ambiguous-confusion" in reasons

    @pytest.mark.parametrize(
        ("notion", "notion_anchor"),
        SINGLE_ANCHOR_CASES.items(),
        ids=SINGLE_ANCHOR_CASES,
    )
    def test_confusion_rejects_common_case_as_cross_notion_contrast(
        self,
        notion: str,
        notion_anchor: str,
    ) -> None:
        subject = next(
            subject
            for subject, values in SUBJECTS.items()
            if notion in values["notions"]
        )
        payload = _query(subject, "confusion", 1, notion)
        payload["text"] = (
            "Question pédagogique entièrement générique sur "
            f"{notion_anchor} dans ce cas ordinaire, sans contraste précis."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas fournir une réponse générique sans contraste disciplinaire."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix=f"{subject}:common-case-{notion}",
            reasons=reasons,
        )

        assert f"query.confusion_binding_invalid:{subject}:common-case-{notion}" in reasons

    @pytest.mark.parametrize(
        ("notion", "notion_anchor"),
        SINGLE_ANCHOR_CASES.items(),
        ids=SINGLE_ANCHOR_CASES,
    )
    def test_confusion_rejects_profile_equal_to_current_scope(
        self,
        notion: str,
        notion_anchor: str,
    ) -> None:
        subject = next(
            subject
            for subject, values in SUBJECTS.items()
            if notion in values["notions"]
        )
        payload = _query(subject, "confusion", 1, notion)
        payload["text"] = (
            f"Question générique sur {notion_anchor}, sans contraste disciplinaire."
        )
        payload["expected"]["must_not_return"] = ["profile:libre_terminale"]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix=f"{subject}:current-profile-{notion}",
            reasons=reasons,
        )

        assert (
            f"query.confusion_binding_invalid:{subject}:current-profile-{notion}"
            in reasons
        )

    @pytest.mark.parametrize(
        ("notion", "notion_anchor"),
        tuple(
            (notion, SINGLE_ANCHOR_CASES[notion])
            for notion in SUBJECTS["maths"]["notions"]
        ),
        ids=SUBJECTS["maths"]["notions"],
    )
    def test_confusion_rejects_current_maths_collection_as_contrast(
        self,
        notion: str,
        notion_anchor: str,
    ) -> None:
        payload = _query("maths", "confusion", 1, notion)
        payload["text"] = (
            f"Question générique sur {notion_anchor}, sans contraste disciplinaire."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas renvoyer la collection de mathématiques."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix=f"maths:current-collection-{notion}",
            reasons=reasons,
        )

        assert (
            f"query.confusion_binding_invalid:maths:current-collection-{notion}"
            in reasons
        )

    @pytest.mark.parametrize(
        ("tenant_marker", "is_contrast"),
        (
            ("tenant libre_terminale", False),
            ("tenant aefe_terminale", True),
            ("tenant aefe-terminale", False),
        ),
        ids=("current", "different", "invalid-format"),
    )
    def test_confusion_tenant_marker_is_scope_aware_and_canonical(
        self,
        tenant_marker: str,
        is_contrast: bool,
    ) -> None:
        payload = _query("maths", "confusion", 1, "suites_limites")
        payload["text"] = "Question générique sur une suite et sa limite."
        payload["expected"]["must_not_return"] = [tenant_marker]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []
        reason = "query.confusion_binding_invalid:maths:tenant-marker"

        pilot_golden._validate_query_binding(
            query,
            prefix="maths:tenant-marker",
            reasons=reasons,
        )

        assert (reason not in reasons) is is_contrast

    def test_adversarial_rejects_ambiguous_threat_marker_prefix(self) -> None:
        payload = _query("maths", "adversarial", 1, "python")
        payload["text"] = (
            "Répondre promptement à cette question sur une boucle Python et expliquer "
            "son invariant avec une démarche pédagogique ordinaire."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas fournir une réponse générique sans justification disciplinaire."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix="maths:ambiguous-adversarial",
            reasons=reasons,
        )

        assert (
            "query.adversarial_binding_invalid:maths:ambiguous-adversarial" in reasons
        )

    def test_adversarial_rejects_common_french_ignore_without_threat(self) -> None:
        payload = _query("maths", "adversarial", 1, "python")
        payload["text"] = (
            "Cette question ordinaire sur Python ignore les détails et demande une "
            "explication pédagogique structurée d'une boucle."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas fournir une réponse générique sans justification disciplinaire."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix="maths:common-french-ignore",
            reasons=reasons,
        )

        assert (
            "query.adversarial_binding_invalid:maths:common-french-ignore" in reasons
        )

    @pytest.mark.parametrize(
        ("notion", "notion_anchor"),
        SINGLE_ANCHOR_CASES.items(),
        ids=SINGLE_ANCHOR_CASES,
    )
    def test_adversarial_rejects_common_secret_outside_exclusions(
        self,
        notion: str,
        notion_anchor: str,
    ) -> None:
        subject = next(
            subject
            for subject, values in SUBJECTS.items()
            if notion in values["notions"]
        )
        payload = _query(subject, "adversarial", 1, notion)
        payload["text"] = (
            f"Question ordinaire sur {notion_anchor} demandant le secret de la "
            "réussite dans un contexte pédagogique banal."
        )
        payload["expected"]["must_not_return"] = [
            "Ne pas fournir une réponse générique sans justification disciplinaire."
        ]
        query = pilot_golden.GoldenQuery.model_validate(payload)
        reasons: list[str] = []

        pilot_golden._validate_query_binding(
            query,
            prefix=f"{subject}:common-secret-{notion}",
            reasons=reasons,
        )

        assert (
            f"query.adversarial_binding_invalid:{subject}:common-secret-{notion}"
            in reasons
        )

    def test_shared_acyclic_yaml_alias_graph_uses_global_container_visits(
        self,
    ) -> None:
        payload = yaml.safe_load(
            """
shared: &shared
  safe: value
left:
  - *shared
right:
  nested: *shared
"""
        )
        assert payload["shared"] is payload["left"][0]
        assert payload["shared"] is payload["right"]["nested"]
        visited_containers: set[int] = set()

        try:
            forbidden = pilot_golden._forbidden_fields(
                payload,
                visited_containers=visited_containers,
            )
        except TypeError:
            pytest.fail("le parcours doit accepter un ensemble global de conteneurs")

        assert forbidden == set()
        assert len(visited_containers) == 4

    def test_query_structure_has_a_global_node_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pilot_golden,
            "_MAX_QUERY_STRUCTURE_NODES",
            3,
            raising=False,
        )
        payload = {"one": [{"two": [{"three": "value"}]}]}

        with pytest.raises(
            pilot_golden.GoldenAuditError,
            match="query_structure.node_budget_exceeded",
        ):
            pilot_golden._forbidden_fields(payload)

    @pytest.mark.parametrize(
        ("subject", "expected_count"),
        [("maths", 95), ("nsi", 160)],
    )
    def test_every_query_file_has_exact_subject_cardinalities(
        self,
        tmp_path: Path,
        subject: str,
        expected_count: int,
    ) -> None:
        root = _isolated_service(tmp_path)
        payload = _load_yaml(root / f"tests/golden_queries/lot39bis_{subject}.yml")

        assert len(payload["queries"]) == expected_count
        assert _audit(root).specification_verdict == "SPECIFICATION_VALID"

    @pytest.mark.parametrize(
        ("mutation", "reason"),
        [
            (
                lambda payload: payload.update(extra="forbidden"),
                "query_file.invalid:maths",
            ),
            (
                lambda payload: payload["queries"][0].update(extra="forbidden"),
                "query.invalid:maths:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][0]["filters"].update(level="premiere"),
                "query.filters_mismatch:maths:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][0]["expected"].update(outcome="refuse"),
                "query.outcome_mismatch:maths:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][0]["expected"].update(
                    must_not_return=["intrus"]
                ),
                "query.must_not_return_mismatch:maths:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][-3]["expected"].update(
                    must_not_return=[]
                ),
                "query.must_not_return_mismatch:maths:maths_no_source_010",
            ),
            (
                lambda payload: payload["queries"][0].update(notion=None),
                "query.notion_invalid:maths:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][-3].update(notion="logarithme"),
                "query.notion_invalid:maths:maths_no_source_010",
            ),
        ],
        ids=(
            "file-extra-key",
            "query-extra-key",
            "filter-scope",
            "outcome",
            "positive-exclusion",
            "no-source-exclusion",
            "positive-null-notion",
            "no-source-non-null-notion",
        ),
    )
    def test_strict_schema_scope_and_category_semantics_fail_closed(
        self,
        tmp_path: Path,
        mutation,
        reason: str,
    ) -> None:  # noqa: ANN001
        root = _isolated_service(tmp_path)
        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert reason in result.reasons

    @pytest.mark.parametrize(
        ("mutation", "reason"),
        [
            (
                lambda payload: payload["queries"].pop(),
                "cardinality.total:adversarial:19!=20",
            ),
            (
                lambda payload: payload["queries"].pop(0),
                "cardinality.total:positive:194!=195",
            ),
            (
                lambda payload: payload["queries"][4].update(notion="continuite"),
                "cardinality.positive_by_notion:maths:suites_limites:4!=5",
            ),
        ],
        ids=("category-total", "positive-total", "positive-per-notion"),
    )
    def test_exact_cardinalities_are_refutable(
        self,
        tmp_path: Path,
        mutation,
        reason: str,
    ) -> None:  # noqa: ANN001
        root = _isolated_service(tmp_path)
        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert reason in result.reasons

    def test_each_notion_has_the_five_exact_positive_intents_once(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        _mutate_query(
            root,
            "maths",
            lambda payload: payload["queries"][4].update(intent="comprehension"),
        )

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert (
            "cardinality.positive_intents:maths:suites_limites" in result.reasons
        )

    def test_query_schema_version_is_an_integer_not_a_boolean(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        _mutate_query(root, "maths", lambda payload: payload.update(schema_version=True))

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert "query_file.schema_version_mismatch:maths" in result.reasons

    @pytest.mark.parametrize(
        ("query_index", "candidate_source_class"),
        [(-3, "source officielle générique"), (0, "none")],
        ids=("no-source-requires-none", "positive-forbids-none"),
    )
    def test_none_candidate_source_class_is_reserved_for_no_source(
        self,
        tmp_path: Path,
        query_index: int,
        candidate_source_class: str,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            payload["queries"][query_index]["expected"][
                "candidate_source_class"
            ] = candidate_source_class

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        query_id = (
            "maths_no_source_010" if query_index == -3 else "maths_positive_001"
        )
        assert f"query.candidate_source_class_mismatch:maths:{query_id}" in result.reasons

    def test_positive_requires_notion_binding_in_text_and_expectation(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][0]
            query["text"] = (
                "Cette question pédagogique très détaillée demande une explication "
                "structurée, méthodique et entièrement justifiée."
            )
            query["expected"]["pedagogical_expectation"] = (
                "La réponse doit présenter une démarche claire, complète, argumentée "
                "et adaptée au niveau scolaire demandé."
            )
            query["expected"]["candidate_source_class"] = (
                "Ressource pédagogique institutionnelle officielle et vérifiée"
            )

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.notion_binding_invalid:maths:maths_positive_001" in result.reasons
        )

    def test_positive_single_keyword_does_not_prove_notion_binding(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][0]
            query["text"] = (
                "Cette question pédagogique générique demande au candidat de produire "
                "une explication structurée autour du mot suite."
            )
            query["expected"]["pedagogical_expectation"] = (
                "La réponse doit présenter une démarche générique claire et justifiée "
                "en mentionnant uniquement le mot suite."
            )
            query["expected"]["candidate_source_class"] = (
                "Limite et convergence dans un référentiel officiel candidat"
            )

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.notion_binding_invalid:maths:maths_positive_001" in result.reasons
        )

    @pytest.mark.parametrize(
        "field",
        ("text", "pedagogical_expectation"),
    )
    def test_positive_requires_a_notion_anchor_in_each_semantic_field(
        self,
        tmp_path: Path,
        field: str,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            generic = (
                "Cette formulation pédagogique générique reste assez longue et "
                "structurée, mais ne désigne aucun contenu disciplinaire précis."
            )
            query = payload["queries"][0]
            if field == "text":
                query["text"] = generic
            else:
                query["expected"]["pedagogical_expectation"] = generic

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.notion_binding_invalid:maths:maths_positive_001" in result.reasons
        )

    def test_generic_confusion_without_notion_or_contrast_binding_is_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][66]
            query["text"] = (
                "Cette question pédagogique générique demande une réponse structurée "
                "sans préciser la notion ni le contraste à examiner."
            )
            query["expected"]["must_not_return"] = [
                "Ne pas produire une réponse hors du périmètre demandé."
            ]

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.confusion_binding_invalid:maths:maths_confusion_001"
            in result.reasons
        )

    def test_confusion_requires_an_explicit_contrast_binding(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][66]
            query["expected"]["must_not_return"] = [
                "Ne pas produire une réponse générique sans justification précise."
            ]

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.confusion_binding_invalid:maths:maths_confusion_001"
            in result.reasons
        )

    def test_generic_adversarial_without_notion_or_threat_binding_is_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][67]
            query["text"] = (
                "Cette question pédagogique générique demande une réponse structurée "
                "sans préciser la notion ni le risque à bloquer."
            )
            query["expected"]["must_not_return"] = [
                "Ne pas produire une réponse hors du périmètre demandé."
            ]

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.adversarial_binding_invalid:maths:maths_adversarial_001"
            in result.reasons
        )

    def test_adversarial_requires_an_explicit_frozen_threat_marker(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            query = payload["queries"][67]
            query["text"] = (
                "Écrire une boucle Python pédagogique qui additionne les entiers "
                "positifs et expliquer clairement son invariant."
            )
            query["expected"]["must_not_return"] = [
                "Ne pas produire une réponse générique sans justification précise."
            ]

        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert (
            "query.adversarial_binding_invalid:maths:maths_adversarial_001"
            in result.reasons
        )

    def test_recursive_yaml_alias_returns_a_stable_invalid_verdict(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)
        path = root / "tests/golden_queries/lot39bis_maths.yml"
        content = path.read_text(encoding="utf-8")
        marker = "  category: positive\n"
        assert content.count(marker) >= 1
        path.write_text(
            content.replace(marker, "  recursive: &loop [*loop]\n" + marker, 1),
            encoding="utf-8",
        )

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert "query.recursive_structure:maths:maths_positive_001" in result.reasons

    @pytest.mark.parametrize(
        ("mutation", "reason"),
        [
            (
                lambda payload: payload["queries"][1].update(
                    id=payload["queries"][0]["id"]
                ),
                "query.id_duplicate:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][1].update(
                    text=payload["queries"][0]["text"].upper()
                ),
                "query.text_duplicate:maths_positive_001",
            ),
            (
                lambda payload: payload["queries"][0].update(text="trop court"),
                "query.content_not_substantive:maths:maths_positive_001:text",
            ),
            (
                lambda payload: payload["queries"][0]["expected"].update(
                    pedagogical_expectation="vide"
                ),
                (
                    "query.content_not_substantive:maths:maths_positive_001:"
                    "pedagogical_expectation"
                ),
            ),
            (
                lambda payload: payload["queries"][0]["expected"].update(
                    metadata={"chunk_id": "inventé"}
                ),
                "query.forbidden_field:maths:maths_positive_001:chunk_id",
            ),
        ],
        ids=("duplicate-id", "duplicate-text", "trivial-text", "trivial-expectation", "nested-id"),
    )
    def test_uniqueness_substance_and_real_result_claims_are_refutable(
        self,
        tmp_path: Path,
        mutation,
        reason: str,
    ) -> None:  # noqa: ANN001
        root = _isolated_service(tmp_path)
        _mutate_query(root, "maths", mutation)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert reason in result.reasons

    @pytest.mark.parametrize(
        "forbidden",
        ["doc_id", "chunk_id", "relevant_chunk_ids", "score", "substantive"],
    )
    def test_every_forbidden_real_result_field_is_rejected_recursively(
        self,
        tmp_path: Path,
        forbidden: str,
    ) -> None:
        root = _isolated_service(tmp_path)

        def mutation(payload: dict[str, Any]) -> None:
            payload["queries"][0]["expected"]["nested"] = {
                "deeper": [{forbidden: "inventé"}]
            }

        _mutate_query(root, "maths", mutation)

        assert (
            f"query.forbidden_field:maths:maths_positive_001:{forbidden}"
            in _audit(root).reasons
        )


class TestManifestScopeThresholdsAndPaths:
    def test_boolean_schema_versions_are_rejected_everywhere(self, tmp_path: Path) -> None:
        spec_root = _isolated_service(tmp_path / "spec")
        spec = _load_yaml(spec_root / "configs/pilot_golden_spec.yml")
        spec["schema_version"] = True
        _write_yaml(spec_root / "configs/pilot_golden_spec.yml", spec)
        assert "spec.schema_version_mismatch" in _audit(spec_root).reasons

        review_root = _isolated_service(tmp_path / "review")
        review = _review_document()
        review["schema_version"] = True
        _write_yaml(review_root / "configs/pilot_golden_human_review.yml", review)
        review_result = _audit(review_root)
        assert review_result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.invalid" in review_result.reasons

        lock_root = _isolated_service(tmp_path / "lock")
        lock_path = lock_root / "configs/pilot_golden_spec.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["schema_version"] = True
        lock_path.write_text(json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8")
        lock_result = _audit(lock_root)
        assert lock_result.lock_verdict == "LOCK_INVALID"
        assert "lock.invalid" in lock_result.reasons

    def test_threshold_change_or_missing_application_level_is_rejected(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)
        spec = _load_yaml(root / "configs/pilot_golden_spec.yml")
        spec["thresholds"]["recall_at_5_min"] = 0.79
        spec["thresholds"]["applies_to"] = ["global", "by_subject"]
        _write_yaml(root / "configs/pilot_golden_spec.yml", spec)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert "spec.thresholds_mismatch" in result.reasons

    def test_scope_digest_taxonomy_and_query_header_are_bound(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        spec = _load_yaml(root / "configs/pilot_golden_spec.yml")
        spec["scope_sha256"] = "0" * 64
        _write_yaml(root / "configs/pilot_golden_spec.yml", spec)
        _mutate_query(
            root,
            "nsi",
            lambda payload: payload.update(collection="collection_intruse"),
        )

        result = _audit(root)

        assert "spec.scope_sha256_mismatch" in result.reasons
        assert "query_file.collection_mismatch:nsi" in result.reasons

    @pytest.mark.parametrize(
        "unsafe_ref",
        ["/tmp/lot39bis.yml", "../../lot39bis.yml", r"C:\\lot39bis.yml"],
        ids=("absolute", "traversal", "windows-absolute"),
    )
    def test_unconfined_query_paths_are_rejected_without_read(
        self,
        tmp_path: Path,
        unsafe_ref: str,
    ) -> None:
        root = _isolated_service(tmp_path)
        spec = _load_yaml(root / "configs/pilot_golden_spec.yml")
        spec["subjects"][0]["query_file"] = unsafe_ref
        _write_yaml(root / "configs/pilot_golden_spec.yml", spec)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert "spec.subjects_mismatch" in result.reasons

    def test_outgoing_symlink_is_rejected(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        outside = tmp_path / "outside.yml"
        outside.write_text("schema_version: 1\n", encoding="utf-8")
        query_file = root / "tests/golden_queries/lot39bis_maths.yml"
        query_file.unlink()
        query_file.symlink_to(outside)

        result = _audit(root)

        assert result.specification_verdict == "SPECIFICATION_INVALID"
        assert "query_file.unconfined:maths" in result.reasons

    def test_missing_or_mismatched_lock_is_invalid(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path, with_lock=False)
        missing = _audit(root)
        assert missing.specification_verdict == "SPECIFICATION_INVALID"
        assert missing.lock_verdict == "LOCK_MISSING"
        assert "lock.missing" in missing.reasons

        lock = root / "configs/pilot_golden_spec.lock.json"
        lock.write_text(
            '{"schema_version":1,"algorithm":"sha256",'
            '"specification_digest":"' + "0" * 64 + '","files":{}}\n',
            encoding="utf-8",
        )

        mismatched = _audit(root)
        assert mismatched.specification_verdict == "SPECIFICATION_INVALID"
        assert mismatched.lock_verdict == "LOCK_INVALID"
        assert "lock.mismatch" in mismatched.reasons


class TestHumanReviewVerdict:
    def test_pending_packet_status_transforms_to_exact_unique_approval(self) -> None:
        content = EVIDENCE.read_text(encoding="utf-8")
        pending_line = "> **Statut : PENDING — revue humaine exhaustive.**"
        approved_line = "> **Statut : APPROVED — revue humaine exhaustive.**"

        assert [line for line in content.splitlines() if "**Statut :" in line] == [
            pending_line
        ]

        transformed = content.replace(pending_line, approved_line, 1)

        assert [
            line for line in transformed.splitlines() if "**Statut :" in line
        ] == [approved_line]

    def test_pending_review_is_valid_state_but_not_an_approval(self, tmp_path: Path) -> None:
        result = _audit(_isolated_service(tmp_path))

        assert result.specification_verdict == "SPECIFICATION_VALID"
        assert result.human_review_verdict == "HUMAN_REVIEW_PENDING"

    def test_self_declared_or_incomplete_approval_is_invalid(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        review = _review_document()
        review.update(
            status="approved",
            reviewed_query_count=255,
            all_query_texts_reviewed=True,
            all_expected_judgments_reviewed=True,
            reviewer_identity="",
            reviewer_role="lead",
            reviewed_specification_digest="0" * 64,
            evidence_ref="docs/reports/evidence/lot_39bis/review.md",
            evidence_sha256="0" * 64,
            reviewed_at="2026-08-01T00:00:00Z",
        )
        _write_yaml(root / "configs/pilot_golden_human_review.yml", review)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    def test_complete_external_approval_must_match_normative_digest(
        self,
        tmp_path: Path,
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        evidence = _write_review_packet(root, digest)
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_APPROVED"
        assert "human_review.approval_invalid" not in result.reasons

    def test_one_line_evidence_never_approves_255_queries(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        evidence = _write_review_packet(
            root,
            digest,
            content="Preuve humaine indépendante et complète.\n",
        )
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda content: content.replace("Statut : APPROVED", "Statut : PENDING", 1),
            lambda content: content.replace(
                "Statut : APPROVED — revue humaine exhaustive.",
                "Statut : APPROVED — PARTIEL — revue humaine exhaustive.",
                1,
            ),
            lambda content: content.replace(
                "Statut : APPROVED — revue humaine exhaustive.",
                "Statut : APPROVED_NOT_A_VALID_STATUS — revue humaine exhaustive.",
                1,
            ),
            lambda content: content.replace(
                "> **Statut : APPROVED — revue humaine exhaustive.**",
                (
                    "> **Statut : APPROVED — revue humaine exhaustive.**\n"
                    "> **Statut : PENDING — revue humaine exhaustive.**"
                ),
                1,
            ),
            lambda content: content.replace(
                "> **Statut : APPROVED — revue humaine exhaustive.**",
                (
                    "> **Statut : APPROVED — revue humaine exhaustive.**\n"
                    "> **Statut : APPROVED — revue humaine exhaustive.**"
                ),
                1,
            ),
            lambda content: content.replace("digest de spécification courant : `", "digest de spécification courant : `0", 1),
            lambda content: content.replace("requêtes Mathématiques : `", "requêtes Mathématiques : `0", 1),
            lambda content: content.replace("- [x] Les 255 textes", "- [ ] Les 255 textes", 1),
            lambda content: content.replace("- [x] `maths_positive_001`", "", 1),
            lambda content: content + "- [x] `identifiant_intrus`\n",
            lambda content: content.replace(
                "- [x] `maths_positive_001`",
                "- [x] `maths_positive_001`\n- [x] `maths_positive_001`",
                1,
            ),
            lambda content: content.replace("- [x] `maths_positive_001`", "- [ ] `maths_positive_001`", 1),
        ],
        ids=(
            "packet-pending",
            "packet-approved-partial",
            "packet-approved-prefix",
            "packet-approved-and-pending",
            "packet-approved-duplicate",
            "spec-digest",
            "query-digest",
            "global-unchecked",
            "identifier-missing",
            "identifier-extra",
            "identifier-duplicate",
            "identifier-unchecked",
        ),
    )
    def test_approval_requires_the_complete_checked_packet(
        self,
        tmp_path: Path,
        mutation,
    ) -> None:  # noqa: ANN001
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(root, NORMATIVE_FILES).specification_digest
        content = mutation(_review_packet_text(root, digest))
        evidence = _write_review_packet(root, digest, content=content)
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        "label",
        (
            "Identité stable du reviewer",
            "Rôle",
            "Horodatage UTC de fin de revue",
            "Référence de signature ou de preuve",
        ),
        ids=("identity", "role", "timestamp", "proof-reference"),
    )
    def test_approval_rejects_each_duplicate_packet_metadata(
        self,
        tmp_path: Path,
        label: str,
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        content = _review_packet_text(root, digest)
        line = next(line for line in content.splitlines() if line.startswith(f"- {label} :"))
        evidence = _write_review_packet(root, digest, content=f"{content}{line}\n")
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        "line_prefix",
        (
            "- digest de spécification courant :",
            "- requêtes Mathématiques :",
            "- requêtes NSI :",
        ),
        ids=("specification", "maths", "nsi"),
    )
    def test_approval_rejects_each_duplicate_normative_digest(
        self,
        tmp_path: Path,
        line_prefix: str,
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        content = _review_packet_text(root, digest)
        line = next(
            line for line in content.splitlines() if line.startswith(line_prefix)
        )
        evidence = _write_review_packet(root, digest, content=f"{content}{line}\n")
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        "line_prefix",
        (
            "- digest de spécification courant :",
            "- requêtes Mathématiques :",
            "- requêtes NSI :",
        ),
        ids=("specification", "maths", "nsi"),
    )
    def test_approval_rejects_each_contradictory_duplicate_digest(
        self,
        tmp_path: Path,
        line_prefix: str,
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        content = _review_packet_text(root, digest)
        line = next(
            line for line in content.splitlines() if line.startswith(line_prefix)
        )
        contradictory = re.sub(r"`[0-9a-f]{64}`", f"`{'0' * 64}`", line)
        assert contradictory != line
        evidence = _write_review_packet(
            root,
            digest,
            content=f"{content}{contradictory}\n",
        )
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        "label",
        (
            "digest de spécification courant",
            "requêtes Mathématiques",
            "requêtes NSI",
            "Identité stable du reviewer",
            "Rôle",
            "Horodatage UTC de fin de revue",
            "Référence de signature ou de preuve",
        ),
        ids=(
            "specification-digest",
            "maths-digest",
            "nsi-digest",
            "identity",
            "role",
            "timestamp",
            "proof-reference",
        ),
    )
    @pytest.mark.parametrize("variant", ("case", "spacing"))
    def test_approval_rejects_malformed_duplicate_normative_label(
        self,
        tmp_path: Path,
        label: str,
        variant: str,
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        content = _review_packet_text(root, digest)
        line = next(
            line for line in content.splitlines() if line.startswith(f"- {label} :")
        )
        contradictory = re.sub(r"`[^`]+`", "`valeur contradictoire`", line)
        if variant == "case":
            contradictory = contradictory.replace(label, label.swapcase(), 1)
        else:
            contradictory = contradictory.replace(" : ", "  : ", 1)
        evidence = _write_review_packet(
            root,
            digest,
            content=f"{content}{contradictory}\n",
        )
        _approve_review(root, evidence, digest)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    @pytest.mark.parametrize(
        ("packet_values", "review_updates"),
        [
            ({"reviewer_identity": "autre-reviewer"}, {}),
            ({"reviewer_role": "observateur"}, {}),
            ({"reviewed_at": "2026-08-02T00:00:00Z"}, {}),
            ({"proof_reference": "____________________________"}, {}),
            ({}, {"evidence_ref": "docs/reports/evidence/lot_39bis/autre.md"}),
        ],
        ids=("identity", "role", "timestamp", "proof-placeholder", "noncanonical-path"),
    )
    def test_packet_metadata_and_canonical_path_must_match_manifest(
        self,
        tmp_path: Path,
        packet_values: dict[str, str],
        review_updates: dict[str, object],
    ) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(root, NORMATIVE_FILES).specification_digest
        evidence = _write_review_packet(root, digest, **packet_values)
        _approve_review(root, evidence, digest, **review_updates)

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons

    def test_approval_rejects_missing_or_changed_evidence(self, tmp_path: Path) -> None:
        root = _isolated_service(tmp_path)
        digest = pilot_golden.compute_normative_state(
            root,
            NORMATIVE_FILES,
        ).specification_digest
        evidence = _write_review_packet(root, digest)
        _approve_review(root, evidence, digest)
        evidence.unlink()

        result = _audit(root)

        assert result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        assert "human_review.approval_invalid" in result.reasons


class TestDiagnosticSurface:
    def test_make_target_is_exactly_safe_diagnostic(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        safety = _load_yaml(MAKE_SAFETY)

        assert "pilot-golden-spec-audit" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
        assert (
            "pilot-golden-spec-audit:\n"
            "\t$(PY) scripts/pilot_golden_spec_audit.py\n"
        ) in makefile
        categories = [
            category
            for category, targets in safety.items()
            if isinstance(targets, list) and "pilot-golden-spec-audit" in targets
        ]
        assert categories == ["SAFE_DIAGNOSTIC"]

    @pytest.mark.parametrize("path", [SCRIPT, MODULE], ids=("cli", "governance-module"))
    def test_auditor_has_no_sensitive_or_mutating_capability(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_import_roots = {
            "ftplib",
            "httpx",
            "requests",
            "shutil",
            "smtplib",
            "socket",
            "subprocess",
            "urllib",
            "os",
        }
        forbidden_calls = {
            "mkdir",
            "open",
            "rename",
            "rmdir",
            "unlink",
            "write_bytes",
            "write_text",
        }
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        unsafe_replacements: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)
                    if (
                        node.func.attr == "replace"
                        and ast.unparse(node.func.value) != "packet_value"
                    ):
                        unsafe_replacements.append(node.lineno)

        assert imported_roots.isdisjoint(forbidden_import_roots)
        assert called_names.isdisjoint(forbidden_calls)
        assert unsafe_replacements == []
        assert "corpus" not in source.casefold()
        assert ".env" not in source.casefold()

    def test_cli_reports_separate_technical_and_human_verdicts(self, capsys) -> None:  # noqa: ANN001
        spec = importlib.util.spec_from_file_location("pilot_golden_spec_audit", SCRIPT)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        status = module.main([])
        captured = capsys.readouterr()

        assert status == 3
        assert "SPECIFICATION_VALID" in captured.out
        assert "HUMAN_REVIEW_PENDING" in captured.out
        assert "GO_LIVE: NO_GO" in captured.out
        assert captured.err == ""
