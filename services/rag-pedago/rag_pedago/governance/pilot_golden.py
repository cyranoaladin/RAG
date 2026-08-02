"""Audit déterministe de la spécification golden du pilote LOT39bis."""

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
)

from rag_pedago.governance.pilot_validation import (
    PilotValidationScope,
    _parse_yaml_bytes,
    load_scope,
    validate_scope_integrity,
)

_SPEC_REFERENCE = "configs/pilot_golden_spec.yml"
_REVIEW_REFERENCE = "configs/pilot_golden_human_review.yml"
_LOCK_REFERENCE = "configs/pilot_golden_spec.lock.json"
_SCOPE_REFERENCE = "configs/pilot_validation_scope.yml"
_EVIDENCE_REFERENCE = "docs/reports/evidence/lot_39bis/golden_human_review_packet.md"
_SPEC_ID = "libre_terminale_golden_spec_v1"
_SCOPE_ID = "libre_terminale_maths_nsi_real_v1"
_EXPECTED_CATEGORIES = {
    "positive": {"total": 195, "per_notion": 5, "outcome": "answer"},
    "no_source": {"total": 20, "per_subject": 10, "outcome": "refuse"},
    "confusion": {"total": 20, "per_subject": 10, "outcome": "answer"},
    "adversarial": {"total": 20, "per_subject": 10, "outcome": "refuse"},
}
_EXPECTED_THRESHOLDS = {
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
_EXPECTED_SUBJECTS: dict[str, dict[str, object]] = {
    "maths": {
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "programme_version": "BOEN_special_8_2019-07-25",
        "taxonomy_path": "taxonomy/maths/terminale_gen_specialite.yml",
        "taxonomy_sha256": "4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6",
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
        "programme_version": "BOEN_special_8_2019-07-25",
        "taxonomy_path": "taxonomy/nsi/terminale.yml",
        "taxonomy_sha256": "b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f",
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
_EXPECTED_NORMATIVE_FILES = (
    _SPEC_REFERENCE,
    _SCOPE_REFERENCE,
    "taxonomy/maths/terminale_gen_specialite.yml",
    "taxonomy/nsi/terminale.yml",
    "tests/golden_queries/lot39bis_maths.yml",
    "tests/golden_queries/lot39bis_nsi.yml",
)
_FORBIDDEN_REAL_RESULT_FIELDS = frozenset(
    {"doc_id", "chunk_id", "relevant_chunk_ids", "score", "substantive"}
)
_OUTCOMES = {
    "positive": "answer",
    "no_source": "refuse",
    "confusion": "answer",
    "adversarial": "refuse",
}
_POSITIVE_INTENTS = frozenset(
    {"comprehension", "methode", "application", "diagnostic", "transfert"}
)
_GLOBAL_REVIEW_ATTESTATIONS = (
    "Les 255 textes de requête ont été lus intégralement dans les deux YAML exacts.",
    "Les 255 jugements et attentes pédagogiques ont été lus intégralement et contrôlés.",
    "Chaque contrainte `must_not_return` pertinente a été vérifiée.",
    (
        "Aucun cas ne prétend disposer d’un document réel, d’un `doc_id`, d’un "
        "`chunk_id`, d’un résultat de retrieval, d’un score ou d’un jugement de "
        "substance réelle."
    ),
)
_NOTION_ANCHORS: dict[str, tuple[str, ...]] = {
    "suites_limites": (
        "suite",
        "limite",
        "converg",
        "n²",
        "born",
        "monoton",
        "oscill",
    ),
    "continuite": (
        "continuit",
        "continue",
        "valeurs intermédiaires",
        "antécédent",
        "unique solution",
        "encadrer zéro",
        "hypothèse manquante",
        "existence",
        "saut",
    ),
    "derivation_convexite": (
        "dériv",
        "deriv",
        "convex",
        "tangente",
        "f''",
        "inflexion",
        "concav",
    ),
    "logarithme": ("logarith", "ln", "exponent", "e^", "produit", "positiv"),
    "primitives_integration": (
        "primitive",
        "intégr",
        "integr",
        "aire",
        "∫",
        "f'",
        "volume",
        "débit",
    ),
    "equations_differentielles": (
        "équation différentielle",
        "equation differentielle",
        "équations différentielles",
        "equations differentielles",
        "y'",
        "t'",
        "condition initiale",
        "équilibre",
        "ce^",
        "température",
    ),
    "combinatoire": (
        "combin",
        "dénombre",
        "denombre",
        "factorielle",
        "binomial",
        "compter",
        "choisir",
        "c(",
        "combien",
        "paire",
        "surcompt",
        "coefficient binomi",
        "coefficients binomi",
    ),
    "geometrie_espace": (
        "géométrie",
        "geometrie",
        "espace",
        "coplana",
        "plan",
        "droite",
        "vecteur",
    ),
    "produit_scalaire_espace": (
        "produit scalaire",
        "orthogon",
        "norme",
        "vecteur normal",
        "n·",
        "u·v",
        "angle",
        "cos",
        "direction",
    ),
    "succession_epreuves": (
        "épreuve",
        "epreuve",
        "bernoulli",
        "binomial",
        "indépend",
        "independ",
        "loi b(",
        "probabilité",
    ),
    "variables_aleatoires_esperance": (
        "variable aléatoire",
        "variable aleatoire",
        "espérance",
        "esperance",
        "gain",
        "probabilit",
        "loi",
        "pondér",
        "linéarité",
        "coût net",
        "aléatoire",
        "moyenne",
    ),
    "loi_grands_nombres": (
        "grands nombres",
        "concentration",
        "échantillon",
        "echantillon",
        "tchebychev",
        "fréquence",
        "frequence",
        "variance",
        "var(",
        "majoration",
        "probabilité",
    ),
    "python": (
        "python",
        "algorith",
        "programme",
        "boucle",
        "itér",
        "seuil",
        "rang",
        "accumulateur",
        "o(n)",
        "compteur",
        "simul",
        "succès",
    ),
    "listes": ("liste", "maillon", "chaîn", "chain", "couple", "fusionn"),
    "piles": ("pile", "empil", "dépil", "depil", "lifo", "opérande"),
    "files": (
        "file",
        "enfil",
        "défil",
        "defil",
        "fifo",
        "tête",
        "queue",
        "indice",
        "bout",
        "retrait",
    ),
    "arbres": (
        "arbre",
        "racine",
        "feuille",
        "nœud",
        "noeud",
        "parcours",
        "opérateur",
        "préfix",
        "postfix",
    ),
    "graphes": (
        "graphe",
        "sommet",
        "arête",
        "arete",
        "orient",
        "poids",
        "degré",
        "voisin",
        "arc",
        "cycle",
    ),
    "dictionnaires": (
        "dictionnaire",
        "clé",
        "cle",
        "hach",
        "fréquen",
        "valeur associée",
        "mot",
        "valeur par défaut",
        "appartenance",
    ),
    "recursivite": (
        "récurs",
        "recurs",
        "cas de base",
        "sous-arbre",
        "arbre vide",
    ),
    "diviser_pour_regner": (
        "diviser",
        "sous-problème",
        "sous-probleme",
        "fusion",
        "décompos",
        "découp",
        "cas élémentaire",
        "récurs",
        "moitié",
        "combin",
        "strictement plus petit",
        "profondeur",
    ),
    "programmation_dynamique": (
        "programmation dynamique",
        "mémo",
        "memo",
        "sous-problème",
        "table",
        "état",
        "etat",
        "dynamiquement",
        "récurrence",
        "minimum",
        "montant",
        "cache",
        "budget",
        "pièce",
    ),
    "parcours_graphes": (
        "parcours",
        "largeur",
        "profondeur",
        "bfs",
        "dfs",
        "source",
        "voisin",
        "distance",
        "parent",
        "sommet",
        "visité",
        "composante",
        "marqu",
        "enfil",
        "arc",
        "cycle",
    ),
    "recherche": (
        "recherche",
        "dichotomie",
        "cible",
        "ordonn",
        "médian",
        "moitié",
        "borne",
        "intervalle",
        "milieu",
        "retrouv",
        "annuaire",
    ),
    "tri": (
        "tri",
        "trier",
        "ordre",
        "fusion",
        "insertion",
        "préfixe",
        "décalage",
        "sélection",
        "échange",
    ),
    "modele_relationnel": (
        "modèle relationnel",
        "modele relationnel",
        "relation",
        "attribut",
        "tuple",
        "schéma",
        "domaine",
        "entité",
        "clé",
        "cle",
        "redondance",
        "anomalie",
        "identifiant",
        "modélis",
        "association",
    ),
    "sql": (
        "sql",
        "select",
        "requête",
        "requete",
        "where",
        "projection",
        "sélection",
        "order by",
        "null",
        "égalité",
    ),
    "contraintes": (
        "contrainte",
        "clé primaire",
        "cle primaire",
        "intégrit",
        "integrit",
        "clé étrangère",
        "cle etrangere",
        "identifiant",
        "check",
        "domaine",
        "règle métier",
        "rejet",
    ),
    "jointures": (
        "jointure",
        "join",
        "tables",
        "correspondance",
        "ligne",
        "null",
        "clé étrangère",
        "cle etrangere",
        "cardinalité",
        "auteur_id",
        "produit cartésien",
        "sans condition",
        "alias",
    ),
    "processus": (
        "processus",
        "ordonn",
        "concurr",
        "interbloc",
        "instance active",
        "mémoire",
        "ressource",
        "processeur",
        "quantum",
        "transition",
        "compétition",
        "section critique",
        "tampon",
        "producteur",
        "consommateur",
        "exclusion mutuelle",
    ),
    "protocoles": (
        "protocole",
        "tcp",
        "ip",
        "paquet",
        "message",
        "échange",
        "fiabilité",
        "latence",
        "perte",
        "http",
        "requête",
        "client-serveur",
        "service réseau",
        "communication",
        "retransmission",
        "émetteur",
        "récepteur",
    ),
    "reseaux": (
        "réseau",
        "reseau",
        "adresse",
        "routeur",
        "masque",
        "ip",
        "connectivité",
        "résolution de nom",
        "encapsulation",
        "couche",
        "unité de données",
        "profil administrateur",
    ),
    "routage": (
        "rout",
        "passerelle",
        "table de routage",
        "prochain saut",
        "interface",
        "préfixe",
        "ttl",
        "boucle",
        "chemin",
        "convergence",
        "lien",
    ),
    "securisation": (
        "sécur",
        "secur",
        "chiffr",
        "authent",
        "certificat",
        "menace",
        "attaque",
        "défens",
        "defens",
        "risque",
        "clé",
        "cle",
        "jeton",
        "chaîne de connexion",
        "hybride",
        "clé publique",
        "signature",
        "identité",
        "hach",
        "sel",
        "empreinte",
        "mot de passe",
    ),
    "poo": (
        "objet",
        "classe",
        "instance",
        "hérit",
        "herit",
        "méthode",
        "invariant",
        "solde",
        "mutation",
        "interface",
        "responsabilité",
    ),
    "tests_mise_au_point": (
        "test",
        "assert",
        "débog",
        "debog",
        "doctest",
        "oracle",
        "résultat attendu",
        "vérification",
        "cas",
        "valeur limite",
        "couvrir",
        "erreur attendue",
        "propriété",
        "générer des cas",
    ),
    "gestion_modules": (
        "module",
        "import",
        "paquet",
        "espace de noms",
        "dépendance",
        "responsabilité",
        "interface",
        "initialisation",
        "abstraction",
        "export",
        "implémentation",
        "api",
        "fichier",
    ),
    "paradigme_fonctionnel": (
        "fonctionnel",
        "fonction pure",
        "pure",
        "lambda",
        "map",
        "filter",
        "réduction",
        "reduction",
        "effet de bord",
        "état mutable",
        "etat mutable",
        "fonction",
        "composition",
        "état",
        "filtr",
        "transform",
        "agrég",
        "composab",
        "mutation",
    ),
    "calculabilite_decidabilite": (
        "calculab",
        "décid",
        "decid",
        "arrêt",
        "arret",
        "turing",
        "algorithme",
        "termine",
        "terminant",
        "procédure effective",
        "preuve",
    ),
}
_PROFILE_SCOPE_PATTERN = re.compile(
    r"(?<!\w)profile:([a-z0-9_]+)(?!\w)",
    flags=re.IGNORECASE,
)
_TENANT_SCOPE_PATTERN = re.compile(
    r"(?<!\w)tenant\s+([a-z0-9]+_[a-z0-9_]+)(?!\w)",
    flags=re.IGNORECASE,
)
_THREAT_EXACT_LABELS = frozenset(
    {
        "system_prompt",
        "secret",
        "pii",
        "raw_source",
        "cross_tenant_content",
        "internal_reasoning",
        "copyrighted_full_text",
        "out_of_scope_profile",
    }
)
_THREAT_MARKERS = (
    "injection de prompt",
    "clé api",
    "clés api",
    "clé ou un jeton",
    "mot de passe",
    "variable secrète",
    "chaîne de connexion",
    "donnée personnelle",
    "données personnelles",
    "renseignements personnels",
    "personne réelle",
    "résultat scolaire individuel",
    "message système",
    "instructions cachées",
    "raisonnement interne",
    "fichier brut",
    "fichiers bruts",
    "exfiltration",
    "code d'exploitation",
    "commande destructive",
    "supprime toutes les tables",
    "autre tenant",
    "profil administrateur",
    "citation inventée",
    "fausse citation",
    "retrouvé sans preuve",
    "retrouvée sans preuve",
    "secret encodé",
    "secrets encodés",
    "canal caché",
    "non revu",
    "quarantaine",
    "désactivation des contrôles",
)
_APPROVED_REVIEW_PACKET_STATUS_LINE = (
    "> **Statut : APPROVED — revue humaine exhaustive.**"
)
_REVIEW_PACKET_STATUS_PATTERN = re.compile(
    r"^> \*\*Statut : .*\*\*$",
    flags=re.MULTILINE,
)
_QUERY_FILE_KEYS = frozenset(
    {"schema_version", "subject", "programme_version", "collection", "queries"}
)
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MAX_QUERY_STRUCTURE_DEPTH = 64
_MAX_QUERY_STRUCTURE_NODES = 4096
GoldenCategory = Literal["positive", "no_source", "confusion", "adversarial"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenAuditError(ValueError):
    """Erreur attendue et annotée d'un audit fermé par défaut."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NormativeFileState(_StrictModel):
    """Empreinte d'un fichier normatif."""

    path: str
    sha256: str


class NormativeState(_StrictModel):
    """État adressé de la spécification complète."""

    files: tuple[NormativeFileState, ...]
    specification_digest: str


class PilotGoldenAuditResult(_StrictModel):
    """Verdicts séparés de l'intégrité technique et de la revue humaine."""

    specification_verdict: Literal["SPECIFICATION_VALID", "SPECIFICATION_INVALID"]
    human_review_verdict: Literal[
        "HUMAN_REVIEW_PENDING",
        "HUMAN_REVIEW_INVALID",
    ]
    lock_verdict: Literal["LOCK_VALID", "LOCK_MISSING", "LOCK_INVALID"]
    query_count: int
    specification_digest: str | None
    reasons: tuple[str, ...]


class PositiveCategorySpec(_StrictModel):
    total: StrictInt
    per_notion: StrictInt
    outcome: Literal["answer"]


class PerSubjectCategorySpec(_StrictModel):
    total: StrictInt
    per_subject: StrictInt
    outcome: Literal["answer", "refuse"]


class GoldenCategories(_StrictModel):
    positive: PositiveCategorySpec
    no_source: PerSubjectCategorySpec
    confusion: PerSubjectCategorySpec
    adversarial: PerSubjectCategorySpec


class GoldenSubjectSpec(_StrictModel):
    subject: Literal["maths", "nsi"]
    collection: StrictStr
    programme_version: StrictStr
    taxonomy_path: StrictStr
    taxonomy_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    query_file: StrictStr
    notions: tuple[StrictStr, ...]


class GoldenThresholds(_StrictModel):
    applies_to: tuple[Literal["global", "by_subject", "by_notion"], ...]
    recall_at_5_min: StrictFloat
    recall_at_10_min: StrictFloat
    recall_at_20_min: StrictFloat
    ndcg_at_10_min: StrictFloat
    mrr_min: StrictFloat
    must_not_return_leakage_max: StrictInt
    citations_complete_valid_min: StrictFloat
    no_source_correct_refusal_min: StrictFloat
    confusion_in_scope_correct_min: StrictFloat
    adversarial_resistance_min: StrictFloat
    positive_empty_response_rate_max: StrictFloat
    fully_empty_notions_max: StrictInt


class PilotGoldenSpec(_StrictModel):
    schema_version: Literal[1]
    spec_id: StrictStr
    status: Literal["frozen"]
    scope_ref: StrictStr
    scope_path: StrictStr
    scope_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    categories: GoldenCategories
    subjects: tuple[GoldenSubjectSpec, ...]
    thresholds: GoldenThresholds
    normative_files: tuple[StrictStr, ...]
    lock_path: StrictStr


class GoldenFilters(_StrictModel):
    tenant: StrictStr
    level: StrictStr
    track: StrictStr
    teaching_status: StrictStr
    audience: StrictStr
    candidates: tuple[StrictStr, ...]
    subject: Literal["maths", "nsi"]
    collection: StrictStr
    school_year: StrictStr


class GoldenExpected(_StrictModel):
    outcome: Literal["answer", "refuse"]
    official_program_reference: StrictStr
    pedagogical_expectation: StrictStr
    candidate_source_class: StrictStr
    must_not_return: tuple[StrictStr, ...]


class GoldenQuery(_StrictModel):
    id: StrictStr
    category: GoldenCategory
    notion: StrictStr | None
    intent: StrictStr
    text: StrictStr
    filters: GoldenFilters
    expected: GoldenExpected


class HumanReview(_StrictModel):
    schema_version: Literal[1]
    review_id: Literal["lot39bis_golden_human_review_v1"]
    spec_id: Literal["libre_terminale_golden_spec_v1"]
    status: Literal["pending", "approved"]
    expected_query_count: StrictInt
    reviewed_query_count: StrictInt
    all_query_texts_reviewed: StrictBool
    all_expected_judgments_reviewed: StrictBool
    reviewer_identity: StrictStr | None
    reviewer_role: StrictStr | None
    reviewed_specification_digest: StrictStr | None
    evidence_ref: StrictStr | None
    evidence_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")] | None
    reviewed_at: AwareDatetime | None


class GoldenLock(_StrictModel):
    schema_version: Literal[1]
    algorithm: Literal["sha256"]
    specification_digest: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    files: dict[StrictStr, Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]]


def compute_normative_state(
    service_root: Path,
    normative_files: tuple[str, ...],
) -> NormativeState:
    """Calcule l'état déterministe des fichiers normatifs."""

    root = service_root.resolve(strict=True)
    if len(normative_files) != len(set(normative_files)):
        raise GoldenAuditError("normative_files.duplicate")
    states: list[NormativeFileState] = []
    for reference in sorted(normative_files):
        path = _confined_file(root, reference)
        states.append(
            NormativeFileState(
                path=reference,
                sha256=sha256(path.read_bytes()).hexdigest(),
            )
        )
    canonical = json.dumps(
        {
            "schema_version": 1,
            "files": [state.model_dump(mode="json") for state in states],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return NormativeState(
        files=tuple(states),
        specification_digest=sha256(canonical).hexdigest(),
    )


def _confined_file(root: Path, reference: str) -> Path:
    if not reference or "\0" in reference:
        raise GoldenAuditError("path.invalid")
    relative = Path(reference)
    windows = PureWindowsPath(reference)
    if (
        relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or windows.anchor
        or ".." in relative.parts
        or ".." in windows.parts
    ):
        raise GoldenAuditError("path.unconfined")
    try:
        resolved = (root / relative).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise GoldenAuditError("path.unconfined") from error
    if not resolved.is_file():
        raise GoldenAuditError("path.not_file")
    return resolved


def _load_yaml_file(root: Path, reference: str) -> object:
    return _parse_yaml_bytes(_confined_file(root, reference).read_bytes())


def _expected_subject_payloads() -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for subject, values in _EXPECTED_SUBJECTS.items():
        notions = values["notions"]
        assert isinstance(notions, tuple)
        payloads.append(
            {
                "subject": subject,
                "collection": values["collection"],
                "programme_version": values["programme_version"],
                "taxonomy_path": values["taxonomy_path"],
                "taxonomy_sha256": values["taxonomy_sha256"],
                "query_file": values["query_file"],
                "notions": list(notions),
            }
        )
    return payloads


def _validate_spec(
    root: Path,
    reasons: list[str],
) -> PilotGoldenSpec | None:
    try:
        payload = _load_yaml_file(root, _SPEC_REFERENCE)
        if not isinstance(payload, Mapping):
            raise ValueError("specification must be a mapping")
        if type(payload.get("schema_version")) is not int:
            reasons.append("spec.schema_version_mismatch")
        spec = PilotGoldenSpec.model_validate(payload)
    except (
        GoldenAuditError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
        yaml.YAMLError,
    ):
        reasons.append("spec.invalid")
        return None

    if spec.spec_id != _SPEC_ID or spec.scope_ref != _SCOPE_ID:
        reasons.append("spec.identity_mismatch")
    if spec.scope_path != _SCOPE_REFERENCE:
        reasons.append("spec.scope_path_mismatch")
    if spec.categories.model_dump(mode="json") != _EXPECTED_CATEGORIES:
        reasons.append("spec.categories_mismatch")
    if spec.thresholds.model_dump(mode="json") != _EXPECTED_THRESHOLDS:
        reasons.append("spec.thresholds_mismatch")
    if [subject.model_dump(mode="json") for subject in spec.subjects] != (
        _expected_subject_payloads()
    ):
        reasons.append("spec.subjects_mismatch")
    if spec.normative_files != _EXPECTED_NORMATIVE_FILES:
        reasons.append("spec.normative_files_mismatch")
    if spec.lock_path != _LOCK_REFERENCE:
        reasons.append("spec.lock_path_mismatch")
    return spec


def _validate_scope(
    root: Path,
    spec: PilotGoldenSpec | None,
    reasons: list[str],
) -> PilotValidationScope | None:
    try:
        scope_path = _confined_file(root, _SCOPE_REFERENCE)
        scope = load_scope(scope_path)
    except (
        GoldenAuditError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
        yaml.YAMLError,
    ):
        reasons.append("scope.invalid")
        return None

    reasons.extend(
        f"scope.invalid:{reason}"
        for reason in validate_scope_integrity(scope, service_root=root)
    )
    if spec is not None:
        digest = sha256(scope_path.read_bytes()).hexdigest()
        if spec.scope_sha256 != digest:
            reasons.append("spec.scope_sha256_mismatch")
    return scope


def _query_identifier(value: object, index: int) -> str:
    if isinstance(value, Mapping):
        identifier = value.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
    return f"index-{index}"


def _forbidden_fields(
    value: object,
    *,
    active_containers: set[int] | None = None,
    visited_containers: set[int] | None = None,
    remaining_nodes: list[int] | None = None,
    depth: int = 0,
) -> set[str]:
    if depth > _MAX_QUERY_STRUCTURE_DEPTH:
        raise GoldenAuditError("query_structure.depth_exceeded")
    active = active_containers if active_containers is not None else set()
    visited = visited_containers if visited_containers is not None else set()
    budget = (
        remaining_nodes
        if remaining_nodes is not None
        else [_MAX_QUERY_STRUCTURE_NODES]
    )
    found: set[str] = set()
    is_container = isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
    )
    if not is_container:
        budget[0] -= 1
        if budget[0] < 0:
            raise GoldenAuditError("query_structure.node_budget_exceeded")
        return found
    identity = id(value)
    if identity in active:
        raise GoldenAuditError("query_structure.recursive_alias")
    if identity in visited:
        return found
    budget[0] -= 1
    if budget[0] < 0:
        raise GoldenAuditError("query_structure.node_budget_exceeded")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and key in _FORBIDDEN_REAL_RESULT_FIELDS:
                    found.add(key)
                found.update(
                    _forbidden_fields(
                        nested,
                        active_containers=active,
                        visited_containers=visited,
                        remaining_nodes=budget,
                        depth=depth + 1,
                    )
                )
        elif isinstance(value, Sequence):
            for nested in value:
                found.update(
                    _forbidden_fields(
                        nested,
                        active_containers=active,
                        visited_containers=visited,
                        remaining_nodes=budget,
                        depth=depth + 1,
                    )
                )
    finally:
        active.remove(identity)
    visited.add(identity)
    return found


def _has_minimum_lexical_content(
    value: str,
    *,
    minimum_characters: int,
    minimum_words: int,
) -> bool:
    """Contrôle seulement une longueur lexicale minimale, pas la substance réelle."""

    normalized = " ".join(value.split())
    words = re.findall(r"[\wÀ-ÖØ-öø-ÿ]+", normalized, flags=re.UNICODE)
    return len(normalized) >= minimum_characters and len(words) >= minimum_words


def _anchor_occurrences(content: str, anchor: str) -> tuple[tuple[int, int], ...]:
    normalized_content = content.casefold()
    normalized_anchor = anchor.casefold()
    if normalized_anchor.isalnum():
        pattern = rf"(?<!\w){re.escape(normalized_anchor)}"
    else:
        pattern = re.escape(normalized_anchor)
    return tuple(match.span() for match in re.finditer(pattern, normalized_content))


def _contains_anchor(content: str, anchor: str) -> bool:
    return bool(_anchor_occurrences(content, anchor))


def _contains_exact_marker(content: str, marker: str) -> bool:
    normalized_marker = marker.casefold()
    prefix = r"(?<!\w)" if normalized_marker[:1].isalnum() else ""
    suffix = r"(?!\w)" if normalized_marker[-1:].isalnum() else ""
    return (
        re.search(
            f"{prefix}{re.escape(normalized_marker)}{suffix}",
            content.casefold(),
        )
        is not None
    )


def _matched_anchors(content: str, anchors: tuple[str, ...]) -> frozenset[str]:
    matches = sorted(
        (
            (start, end, anchor.casefold())
            for anchor in anchors
            for start, end in _anchor_occurrences(content, anchor)
        ),
        key=lambda match: (-(match[1] - match[0]), match[0], match[2]),
    )
    selected_spans: list[tuple[int, int]] = []
    selected_anchors: set[str] = set()
    for start, end, anchor in matches:
        if any(start < selected_end and end > selected_start for selected_start, selected_end in selected_spans):
            continue
        selected_spans.append((start, end))
        selected_anchors.add(anchor)
    return frozenset(selected_anchors)


def _has_contrast_binding(query: GoldenQuery) -> bool:
    filters = query.filters
    programme_version = str(
        _EXPECTED_SUBJECTS[filters.subject]["programme_version"]
    )
    expected_phrases = (
        f"profil autre que {filters.tenant}",
        f"profil scolaire incompatible avec {filters.tenant}",
        f"niveau autre que {filters.level}",
        f"collection autre que {filters.collection}",
        f"hors programme_version {programme_version}",
        f"matière autre que {filters.subject}",
        f"voie autre que {filters.track}",
        f"année scolaire autre que {filters.school_year}",
    )
    for exclusion in query.expected.must_not_return:
        if any(
            profile.casefold() != filters.tenant.casefold()
            for profile in _PROFILE_SCOPE_PATTERN.findall(exclusion)
        ):
            return True
        if any(
            tenant.casefold() != filters.tenant.casefold()
            for tenant in _TENANT_SCOPE_PATTERN.findall(exclusion)
        ):
            return True
        if any(
            _contains_exact_marker(exclusion, phrase)
            for phrase in expected_phrases
        ):
            return True
        if (
            filters.subject != "maths"
            and _contains_exact_marker(exclusion, "collection de mathématiques")
        ):
            return True
    return False


def _has_threat_binding(exclusions: Sequence[str]) -> bool:
    for exclusion in exclusions:
        normalized = " ".join(exclusion.casefold().split())
        if normalized in _THREAT_EXACT_LABELS or any(
            _contains_exact_marker(exclusion, marker)
            for marker in _THREAT_MARKERS
        ):
            return True
    return False


def _validate_query_binding(
    query: GoldenQuery,
    *,
    prefix: str,
    reasons: list[str],
) -> None:
    """Vérifie une liaison lexicale notion/menace, jamais la revue humaine."""

    if not isinstance(query.notion, str):
        return
    anchors = _NOTION_ANCHORS.get(query.notion, ())
    text_anchors = _matched_anchors(query.text, anchors)
    if query.category == "positive":
        expectation_anchors = _matched_anchors(
            query.expected.pedagogical_expectation,
            anchors,
        )
        required_distinct = min(2, len(frozenset(map(str.casefold, anchors))))
        if (
            not text_anchors
            or not expectation_anchors
            or len(text_anchors | expectation_anchors) < required_distinct
        ):
            reasons.append(f"query.notion_binding_invalid:{prefix}")
        return

    if query.category == "confusion" and (
        not text_anchors
        or not _has_contrast_binding(query)
    ):
        reasons.append(f"query.confusion_binding_invalid:{prefix}")
    if query.category == "adversarial" and (
        not text_anchors
        or not _has_threat_binding(query.expected.must_not_return)
    ):
        reasons.append(f"query.adversarial_binding_invalid:{prefix}")


def _expected_filters(subject: str) -> dict[str, object]:
    values = _EXPECTED_SUBJECTS[subject]
    return {
        "tenant": "libre_terminale",
        "level": "terminale",
        "track": "generale",
        "teaching_status": "specialite",
        "audience": "libre",
        "candidates": ["cned_libre", "individuel", "libre"],
        "subject": subject,
        "collection": values["collection"],
        "school_year": "2026-2027",
    }


def _validate_query_semantics(
    query: GoldenQuery,
    *,
    subject: str,
    notions: tuple[str, ...],
    reasons: list[str],
) -> None:
    prefix = f"{subject}:{query.id}"
    if not _ID_PATTERN.fullmatch(query.id):
        reasons.append(f"query.id_invalid:{prefix}")
    if query.filters.model_dump(mode="json") != _expected_filters(subject):
        reasons.append(f"query.filters_mismatch:{prefix}")
    if query.category == "no_source":
        if query.notion is not None:
            reasons.append(f"query.notion_invalid:{prefix}")
    elif query.notion not in notions:
        reasons.append(f"query.notion_invalid:{prefix}")
    if query.expected.outcome != _OUTCOMES[query.category]:
        reasons.append(f"query.outcome_mismatch:{prefix}")
    if (query.category == "positive" and query.expected.must_not_return) or (
        query.category != "positive" and not query.expected.must_not_return
    ):
        reasons.append(f"query.must_not_return_mismatch:{prefix}")
    source_class_is_none = query.expected.candidate_source_class == "none"
    if (query.category == "no_source") is not source_class_is_none:
        reasons.append(f"query.candidate_source_class_mismatch:{prefix}")

    content = {
        "intent": (query.intent, 5, 1),
        "text": (query.text, 20, 4),
        "official_program_reference": (
            query.expected.official_program_reference,
            12,
            3,
        ),
        "pedagogical_expectation": (
            query.expected.pedagogical_expectation,
            20,
            4,
        ),
        "candidate_source_class": (
            query.expected.candidate_source_class,
            8,
            1,
        ),
    }
    for field, (value, characters, words) in content.items():
        if (
            field == "candidate_source_class"
            and query.category == "no_source"
            and value == "none"
        ):
            continue
        if not _has_minimum_lexical_content(
            value,
            minimum_characters=characters,
            minimum_words=words,
        ):
            reasons.append(f"query.content_not_substantive:{prefix}:{field}")
    for exclusion in query.expected.must_not_return:
        if not exclusion.strip():
            reasons.append(f"query.content_not_substantive:{prefix}:must_not_return")
    _validate_query_binding(query, prefix=prefix, reasons=reasons)


def _validate_query_file(
    root: Path,
    *,
    subject: str,
    reasons: list[str],
) -> list[GoldenQuery]:
    values = _EXPECTED_SUBJECTS[subject]
    reference = values["query_file"]
    assert isinstance(reference, str)
    try:
        payload = _load_yaml_file(root, reference)
    except GoldenAuditError as error:
        reason = "query_file.unconfined" if error.reason == "path.unconfined" else "query_file.invalid"
        reasons.append(f"{reason}:{subject}")
        return []
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError, yaml.YAMLError):
        reasons.append(f"query_file.invalid:{subject}")
        return []
    if not isinstance(payload, Mapping) or set(payload) != _QUERY_FILE_KEYS:
        reasons.append(f"query_file.invalid:{subject}")
        return []
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        reasons.append(f"query_file.schema_version_mismatch:{subject}")
    if payload.get("subject") != subject:
        reasons.append(f"query_file.subject_mismatch:{subject}")
    if payload.get("programme_version") != values["programme_version"]:
        reasons.append(f"query_file.programme_version_mismatch:{subject}")
    if payload.get("collection") != values["collection"]:
        reasons.append(f"query_file.collection_mismatch:{subject}")
    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list):
        reasons.append(f"query_file.invalid:{subject}")
        return []

    queries: list[GoldenQuery] = []
    notions = values["notions"]
    assert isinstance(notions, tuple)
    for index, raw_query in enumerate(raw_queries):
        identifier = _query_identifier(raw_query, index)
        try:
            forbidden_fields = _forbidden_fields(raw_query)
        except GoldenAuditError:
            reasons.append(f"query.recursive_structure:{subject}:{identifier}")
            continue
        for forbidden in sorted(forbidden_fields):
            reasons.append(f"query.forbidden_field:{subject}:{identifier}:{forbidden}")
        try:
            query = GoldenQuery.model_validate(raw_query)
        except (TypeError, ValidationError, ValueError):
            reasons.append(f"query.invalid:{subject}:{identifier}")
            continue
        _validate_query_semantics(
            query,
            subject=subject,
            notions=notions,
            reasons=reasons,
        )
        queries.append(query)
    return queries


def _validate_cardinalities(
    queries_by_subject: Mapping[str, list[GoldenQuery]],
    reasons: list[str],
) -> None:
    all_queries = [query for queries in queries_by_subject.values() for query in queries]
    totals = Counter(query.category for query in all_queries)
    expected_totals: tuple[tuple[GoldenCategory, int], ...] = (
        ("positive", 195),
        ("no_source", 20),
        ("confusion", 20),
        ("adversarial", 20),
    )
    for category, expected in expected_totals:
        actual = totals[category]
        if actual != expected:
            reasons.append(f"cardinality.total:{category}:{actual}!={expected}")

    for subject, queries in queries_by_subject.items():
        subject_totals = Counter(query.category for query in queries)
        negative_categories: tuple[GoldenCategory, ...] = (
            "no_source",
            "confusion",
            "adversarial",
        )
        for category in negative_categories:
            actual = subject_totals[category]
            if actual != 10:
                reasons.append(
                    f"cardinality.by_subject:{subject}:{category}:{actual}!=10"
                )
        notions = _EXPECTED_SUBJECTS[subject]["notions"]
        assert isinstance(notions, tuple)
        positive_by_notion = Counter(
            query.notion for query in queries if query.category == "positive"
        )
        for notion in notions:
            actual = positive_by_notion[notion]
            if actual != 5:
                reasons.append(
                    f"cardinality.positive_by_notion:{subject}:{notion}:{actual}!=5"
                )
            positive_intents = Counter(
                query.intent
                for query in queries
                if query.category == "positive" and query.notion == notion
            )
            if positive_intents != Counter({intent: 1 for intent in _POSITIVE_INTENTS}):
                reasons.append(f"cardinality.positive_intents:{subject}:{notion}")


def _validate_uniqueness(
    queries_by_subject: Mapping[str, list[GoldenQuery]],
    reasons: list[str],
) -> None:
    seen_ids: set[str] = set()
    seen_texts: dict[str, str] = {}
    for subject in sorted(queries_by_subject):
        for query in queries_by_subject[subject]:
            if query.id in seen_ids:
                reasons.append(f"query.id_duplicate:{query.id}")
            else:
                seen_ids.add(query.id)
            normalized_text = " ".join(query.text.casefold().split())
            previous = seen_texts.get(normalized_text)
            if previous is not None:
                reasons.append(f"query.text_duplicate:{previous}")
            else:
                seen_texts[normalized_text] = query.id


def _load_review(root: Path) -> HumanReview | None:
    try:
        payload = _load_yaml_file(root, _REVIEW_REFERENCE)
        if (
            not isinstance(payload, Mapping)
            or type(payload.get("schema_version")) is not int
        ):
            return None
        return HumanReview.model_validate(payload)
    except (
        GoldenAuditError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
        yaml.YAMLError,
    ):
        return None


def _safe_unresolved_reference(reference: str) -> bool:
    relative = Path(reference)
    windows = PureWindowsPath(reference)
    return bool(reference) and not (
        "\0" in reference
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or windows.anchor
        or ".." in relative.parts
        or ".." in windows.parts
    )


def _workspace_root(service_root: Path) -> Path:
    if service_root.name != "rag-pedago" or service_root.parent.name != "services":
        raise GoldenAuditError("service_root.layout_invalid")
    try:
        workspace = service_root.parents[1].resolve(strict=True)
        service_root.relative_to(workspace)
    except (IndexError, OSError, RuntimeError, ValueError) as error:
        raise GoldenAuditError("service_root.layout_invalid") from error
    return workspace


def _unique_packet_value(
    content: str,
    label: str,
    *,
    suffix: str = "",
) -> str | None:
    normalized_label = label.casefold()
    label_pattern = re.compile(
        rf"^-\s+{re.escape(normalized_label)}\s*:",
    )
    lines = [
        line
        for line in content.splitlines()
        if label_pattern.match(" ".join(line.casefold().split())) is not None
    ]
    if len(lines) != 1:
        return None
    match = re.fullmatch(
        rf"- {re.escape(label)} : `([^`\r\n]+)`{re.escape(suffix)}",
        lines[0],
    )
    return match.group(1).strip() if match is not None else None


def _packet_metadata(content: str, label: str) -> str | None:
    return _unique_packet_value(content, label)


def _review_time_matches(packet_value: str | None, reviewed_at: datetime) -> bool:
    if packet_value is None:
        return False
    try:
        parsed = datetime.fromisoformat(packet_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        return parsed.astimezone(UTC) == reviewed_at.astimezone(UTC)
    except (OverflowError, ValueError):
        return False


def _filled_proof_reference(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().casefold()
    return bool(normalized) and "____" not in normalized and normalized not in {
        "pending",
        "à renseigner",
        "a renseigner",
        "n/a",
        "none",
    }


def _review_packet_valid(
    content: str,
    *,
    review: HumanReview,
    specification_digest: str,
    normative_state: NormativeState,
    expected_query_ids: tuple[str, ...],
) -> bool:
    file_hashes = {state.path: state.sha256 for state in normative_state.files}
    maths_hash = file_hashes.get("tests/golden_queries/lot39bis_maths.yml")
    nsi_hash = file_hashes.get("tests/golden_queries/lot39bis_nsi.yml")
    if maths_hash is None or nsi_hash is None:
        return False
    status_lines = _REVIEW_PACKET_STATUS_PATTERN.findall(content)
    packet_digests = (
        _unique_packet_value(
            content,
            "digest de spécification courant",
            suffix=" ;",
        ),
        _unique_packet_value(content, "requêtes Mathématiques", suffix=" ;"),
        _unique_packet_value(content, "requêtes NSI", suffix="."),
    )
    if (
        status_lines != [_APPROVED_REVIEW_PACKET_STATUS_LINE]
        or packet_digests != (specification_digest, maths_hash, nsi_hash)
    ):
        return False

    global_checkboxes = re.findall(
        r"^- \[([ xX])\] (?!`)(.+)$",
        content,
        flags=re.MULTILINE,
    )
    expected_attestations = set(_GLOBAL_REVIEW_ATTESTATIONS)
    if (
        len(global_checkboxes) != len(_GLOBAL_REVIEW_ATTESTATIONS)
        or {text for _, text in global_checkboxes} != expected_attestations
        or any(mark.casefold() != "x" for mark, _ in global_checkboxes)
    ):
        return False

    identifier_checkboxes = re.findall(
        r"^- \[([ xX])\] `([^`\r\n]+)`\s*$",
        content,
        flags=re.MULTILINE,
    )
    packet_ids = [identifier for _, identifier in identifier_checkboxes]
    if (
        len(identifier_checkboxes) != 255
        or len(set(packet_ids)) != 255
        or set(packet_ids) != set(expected_query_ids)
        or any(mark.casefold() != "x" for mark, _ in identifier_checkboxes)
    ):
        return False

    identity = _packet_metadata(content, "Identité stable du reviewer")
    role = _packet_metadata(content, "Rôle")
    packet_time = _packet_metadata(content, "Horodatage UTC de fin de revue")
    proof_reference = _packet_metadata(content, "Référence de signature ou de preuve")
    return (
        identity == review.reviewer_identity
        and role == review.reviewer_role
        and isinstance(review.reviewed_at, datetime)
        and _review_time_matches(packet_time, review.reviewed_at)
        and _filled_proof_reference(proof_reference)
    )


def _human_review_verdict(
    root: Path,
    review: HumanReview | None,
    *,
    specification_digest: str | None,
    normative_state: NormativeState | None,
    expected_query_ids: tuple[str, ...],
    reasons: list[str],
) -> Literal[
    "HUMAN_REVIEW_PENDING",
    "HUMAN_REVIEW_INVALID",
]:
    if review is None:
        reasons.append("human_review.invalid")
        return "HUMAN_REVIEW_INVALID"
    if review.expected_query_count != 255:
        reasons.append("human_review.expected_count_invalid")
        return "HUMAN_REVIEW_INVALID"
    if review.status == "pending":
        pending_is_clean = (
            0 <= review.reviewed_query_count < 255
            and review.all_query_texts_reviewed is False
            and review.all_expected_judgments_reviewed is False
            and review.reviewer_identity is None
            and review.reviewer_role is None
            and review.reviewed_specification_digest is None
            and review.evidence_ref is None
            and review.evidence_sha256 is None
            and review.reviewed_at is None
        )
        if pending_is_clean:
            return "HUMAN_REVIEW_PENDING"
        reasons.append("human_review.pending_invalid")
        return "HUMAN_REVIEW_INVALID"

    evidence_is_valid = False
    if (
        review.evidence_ref == _EVIDENCE_REFERENCE
        and isinstance(review.evidence_sha256, str)
        and specification_digest is not None
        and normative_state is not None
    ):
        try:
            evidence = _confined_file(_workspace_root(root), review.evidence_ref)
            raw_evidence = evidence.read_bytes()
            evidence_is_valid = (
                sha256(raw_evidence).hexdigest() == review.evidence_sha256
                and _review_packet_valid(
                    raw_evidence.decode("utf-8"),
                    review=review,
                    specification_digest=specification_digest,
                    normative_state=normative_state,
                    expected_query_ids=expected_query_ids,
                )
            )
        except (GoldenAuditError, OSError, RuntimeError, UnicodeError, ValueError):
            evidence_is_valid = False
    approval_is_complete = (
        review.reviewed_query_count == 255
        and review.all_query_texts_reviewed is True
        and review.all_expected_judgments_reviewed is True
        and isinstance(review.reviewer_identity, str)
        and bool(review.reviewer_identity.strip())
        and _filled_proof_reference(review.reviewer_role)
        and specification_digest is not None
        and review.reviewed_specification_digest == specification_digest
        and evidence_is_valid
        and isinstance(review.reviewed_at, datetime)
    )
    if approval_is_complete:
        reasons.append("human_review.trusted_channel_unavailable")
        return "HUMAN_REVIEW_PENDING"
    reasons.append("human_review.approval_invalid")
    return "HUMAN_REVIEW_INVALID"


def _json_no_duplicates(raw: bytes) -> object:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        mapping: dict[str, object] = {}
        for key, value in pairs:
            if key in mapping:
                raise ValueError(f"duplicate JSON key: {key}")
            mapping[key] = value
        return mapping

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)


def _lock_verdict(
    root: Path,
    normative_state: NormativeState | None,
    reasons: list[str],
) -> Literal["LOCK_VALID", "LOCK_MISSING", "LOCK_INVALID"]:
    candidate = root / _LOCK_REFERENCE
    if not candidate.exists() and not candidate.is_symlink():
        reasons.append("lock.missing")
        return "LOCK_MISSING"
    try:
        payload = _json_no_duplicates(_confined_file(root, _LOCK_REFERENCE).read_bytes())
        if (
            not isinstance(payload, Mapping)
            or type(payload.get("schema_version")) is not int
        ):
            raise ValueError("lock schema version must be an integer")
        lock = GoldenLock.model_validate(payload)
    except (
        GoldenAuditError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
    ):
        reasons.append("lock.invalid")
        return "LOCK_INVALID"
    expected_files = (
        {state.path: state.sha256 for state in normative_state.files}
        if normative_state is not None
        else None
    )
    if (
        normative_state is None
        or lock.specification_digest != normative_state.specification_digest
        or lock.files != expected_files
    ):
        reasons.append("lock.mismatch")
        return "LOCK_INVALID"
    return "LOCK_VALID"


def audit_pilot_golden(*, service_root: Path) -> PilotGoldenAuditResult:
    """Audite exhaustivement la spécification golden locale."""

    technical_reasons: list[str] = []
    human_reasons: list[str] = []
    query_count = 0
    normative_state: NormativeState | None = None
    try:
        root = service_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return PilotGoldenAuditResult(
            specification_verdict="SPECIFICATION_INVALID",
            human_review_verdict="HUMAN_REVIEW_INVALID",
            lock_verdict="LOCK_INVALID",
            query_count=0,
            specification_digest=None,
            reasons=("service_root.invalid",),
        )

    spec = _validate_spec(root, technical_reasons)
    _validate_scope(root, spec, technical_reasons)
    queries_by_subject = {
        subject: _validate_query_file(root, subject=subject, reasons=technical_reasons)
        for subject in sorted(_EXPECTED_SUBJECTS)
    }
    query_count = sum(len(queries) for queries in queries_by_subject.values())
    _validate_cardinalities(queries_by_subject, technical_reasons)
    _validate_uniqueness(queries_by_subject, technical_reasons)

    if spec is not None and spec.normative_files == _EXPECTED_NORMATIVE_FILES:
        try:
            normative_state = compute_normative_state(root, spec.normative_files)
        except (GoldenAuditError, OSError, RuntimeError, ValueError):
            technical_reasons.append("normative_state.invalid")
    lock_verdict = _lock_verdict(root, normative_state, technical_reasons)
    specification_digest = (
        normative_state.specification_digest if normative_state is not None else None
    )
    expected_query_ids = tuple(
        query.id
        for subject in sorted(queries_by_subject)
        for query in queries_by_subject[subject]
    )
    human_review_verdict = _human_review_verdict(
        root,
        _load_review(root),
        specification_digest=specification_digest,
        normative_state=normative_state,
        expected_query_ids=expected_query_ids,
        reasons=human_reasons,
    )
    reasons = tuple(sorted(set((*technical_reasons, *human_reasons))))
    return PilotGoldenAuditResult(
        specification_verdict=(
            "SPECIFICATION_INVALID" if technical_reasons else "SPECIFICATION_VALID"
        ),
        human_review_verdict=human_review_verdict,
        lock_verdict=lock_verdict,
        query_count=query_count,
        specification_digest=specification_digest,
        reasons=reasons,
    )
