"""L'unique autorite qui calcule l'etat de readiness go-live.

Pourquoi une seule
------------------

Une soixantaine de fichiers du depot citent un compteur de go-live. Tant que
chacun porte sa propre valeur, deux d entre eux finissent par ne pas dire la
meme chose, et le jour ou ils divergent, aucun ne fait autorite.

Ce script est la seule autorite logique. Le JSON qu il produit est genere ; le
Markdown en est derive. Aucun rapport ecrit a la main ne doit etre presente
comme la source.

Ce qu il refuse de faire
------------------------

Il ne DECLARE pas `go_live_ready`. Il le CALCULE, depuis des artefacts
versionnes et des sondes locales, et rend faux des qu une entree manque. Une
entree absente n est jamais traitee comme un zero : ne pas savoir n est pas
savoir que c est bon.

Trois compteurs lui echappent par nature — ecritures en base de production,
deploiements, bascule courante. Aucune lecture du depot ne prouve qu ils sont
restes a zero. Ils sont donc DECLARES par le lot, et le script le dit au lieu
de faire croire qu il les a mesures.

Trois modes, et un seul est un garde
------------------------------------

`--check-only`     diagnostic. Calcule et imprime. Rend 0 des lors que le
                   CALCUL a pu s executer, meme si le systeme n est pas pret.
                   Ne jamais s en servir dans une chaine de deploiement : un
                   mode qui rend 0 quand rien n est pret est un faux vert.

`--verify-snapshot` concordance. Dit si un instantane vaut encore pour le HEAD
                   courant. N autorise RIEN, jamais, meme concordant.

`--assert-ready`   LE garde. Rend 0 seulement si le systeme est reellement
                   pret, 1 s il ne l est pas, 2 si une entree manque. C est le
                   seul mode utilisable comme condition de deploiement.

Les chemins sont derives de l emplacement de ce fichier ; `NEXUS_REPO_ROOT`
permet de les surcharger.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(
    os.environ.get("NEXUS_REPO_ROOT", pathlib.Path(__file__).resolve().parents[2])
)

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
NON_PDF = "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json"
POLITIQUE_RETENTION_NON_PDF = "docs/reports/go_live/non_pdf_retention_policy.json"
RECONCILIATEUR_NON_PDF = "scripts/go_live/reconcile_non_pdf_counts.py"
POLITIQUE_ACTUALITE = (
    "services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"
)
DISPOSITIONS_PR = "docs/reports/go_live/open_pr_dispositions.json"
BLOQUEURS_QUALIFICATION = "docs/reports/go_live/qualification_blockers.json"
ECART_RECHERCHE = "docs/reports/go_live/rag_searchability_gap.json"
SORTIE_JSON = "docs/reports/go_live/go_live_readiness_state.json"
SORTIE_MD = "docs/reports/go_live/GO_LIVE_READINESS.md"
SORTIE_LEDGER_JSON = "docs/reports/go_live/blocker_closure_ledger.json"
SORTIE_LEDGER_MD = "docs/reports/go_live/BLOCKER_CLOSURE_LEDGER.md"
SORTIE_PLAN_JSON = "docs/reports/go_live/closure_plan.json"
SORTIE_PLAN_MD = "docs/reports/go_live/CLOSURE_PLAN.md"

#: Cinq niveaux distincts, souvent confondus. Les confondre fait croire qu un
#: contenu compte parmi les servis parce qu il figure dans une matrice.
#:
#: Trois d entre eux ne se mesurent PAS depuis le depot : ils exigent une
#: base et un service identifies. Rendre zero pour eux serait une fausse
#: assurance ; ils sont donc declares non mesurables, et le disent.
NIVEAUX_DE_CONTENU = (
    {
        "id": "PROMOTED",
        "libelle": "contenu promu",
        "mesure": "ensemble promu canonique",
        "measurable_from_repository": True,
    },
    {
        "id": "SERVABLE_CANDIDATE",
        "libelle": "contenu candidat a la servabilite",
        "mesure": "matrice de servabilite, applied=false",
        "measurable_from_repository": True,
    },
    {
        "id": "INGESTED",
        "libelle": "contenu ingere",
        "mesure": "base pgvector d un environnement identifie",
        "measurable_from_repository": False,
    },
    {
        "id": "SEARCHABLE",
        "libelle": "contenu exploitable par recherche",
        "mesure": "contrat de retrieval sur un service identifie",
        "measurable_from_repository": False,
    },
    {
        "id": "SERVED_IN_PRODUCTION",
        "libelle": "contenu reellement servi en production",
        "mesure": "production, hors de portee de ce lot",
        "measurable_from_repository": False,
    },
)

#: L ordre impose. Une etape ne s ouvre pas tant que celles dont elle depend
#: ne sont pas fermees : l annoncer evite de qualifier un staging qu on devra
#: refaire.
PHASES_DE_CLOTURE = (
    {
        "id": "P1_PRE_RELEASE",
        "titre": "Fermer les bloqueurs de pre-release",
        "blockers": ["PII_UNDECIDED", "CURRENTNESS_POLICY_APPLIED"],
        "depends_on": [],
        "gate": "pre_release_blockers == 0",
    },
    {
        "id": "P2_DEPOT",
        "titre": "Vider le depot de ses PR bloquantes",
        "blockers": ["OPEN_PRS_BLOCKING"],
        "depends_on": [],
        "gate": "open_prs_blocking == 0",
    },
    {
        "id": "P3_OCTETS",
        "titre": "Disposer des octets des contenus servables",
        "blockers": ["NON_PDF_SERVABLE_REACQUIRED"],
        "depends_on": ["P1_PRE_RELEASE"],
        "gate": "non_pdf_servable_reacquired == non_pdf_servable_total",
    },
    {
        "id": "P4_QUALIFICATION",
        "titre": "Fermer les gates de qualification",
        "blockers": ["GO_LIVE_QUALIFICATION_BLOCKERS"],
        "depends_on": ["P1_PRE_RELEASE", "P2_DEPOT", "P3_OCTETS"],
        "gate": "go_live_qualification_blockers == 0",
    },
    {
        "id": "P5_DEPLOIEMENT",
        "titre": "Deployer, apres et seulement apres",
        "blockers": [],
        "depends_on": ["P4_QUALIFICATION"],
        "gate": "--assert-ready rend 0",
    },
)

#: Le calculateur canonique d ensemble promu, deja present dans le depot. Il
#: passe par `select_release_authority` et le contrat de release — le MEME que
#: le runtime. Le readiness gate ne redefinit donc pas ce qu est un contenu
#: promu : il le demande a l autorite qui le sait.
CALCULATEUR_ENSEMBLE_PROMU = "scripts/qualification/compute_promoted_content_set.py"

#: Le ledger est DERIVE de l etat calcule. Ecrire ses valeurs a la main
#: recreerait une seconde source, et deux sources finissent par diverger.
#: Seule la partie non calculable — qui doit agir, sous quelle condition la
#: fermeture est acquise — est declaree ici, une fois.
LEDGER_SPEC: tuple[dict[str, Any], ...] = (
    {
        "id": "RAG_SEARCHABILITY",
        "category": "DATA",
        "value_key": "rag_searchability_blocker",
        "blocking_when": "value is true",
        "evidence_source": (
            ECART_RECHERCHE + " (derive de l audit d ingestion sur une base nommee)"
        ),
        "required_action": (
            "Indexer le perimetre cible en vecteurs, puis valider le retrieval :"
            " top-k, citations, filtres de portee, latence, rollback. Un corpus"
            " qualifie servable reste inatteignable tant qu aucun vecteur ne le"
            " reference."
        ),
        "owner_type": "OPERATOR",
        "automation_possible": True,
        "human_decision_required": False,
        "close_condition": (
            "toutes les conditions de fermeture de l ecart de recherche sont"
            " tenues, mesurees et non supposees"
        ),
        "related_prs": [],
        "deployment_dependency": "BLOQUE_LE_DEPLOIEMENT",
    },
    {
        "id": "RELEASE_PROMOTED_REFUSED_CONTENTS",
        "category": "BUSINESS",
        "value_key": "release_promoted_refused_contents",
        "blocking_when": "value > 0",
        "evidence_source": (
            MATRICE
            + " croisee avec l ensemble promu canonique : un contenu promu dont"
            " le gate de servabilite refuse le verdict"
        ),
        "required_action": (
            "Decider du sort de chaque contenu promu desormais refuse : le"
            " retirer et resceller la release sous une identite neuve, ou"
            " documenter une derogation gouvernee. Ni l un ni l autre ne peut"
            " etre fait par un script."
        ),
        "owner_type": "HUMAN_REVIEWER",
        "automation_possible": False,
        "human_decision_required": True,
        "close_condition": (
            "aucun contenu de l ensemble promu ne porte un verdict de refus"
            " dans la matrice de servabilite"
        ),
        "related_prs": [],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
    {
        "id": "PII_UNDECIDED",
        "category": "BUSINESS",
        "value_key": "pii_undecided",
        "blocking_when": "value > 0",
        "evidence_source": MATRICE + " (by_pii.PII_UNDECIDED)",
        "required_action": (
            "Trancher chaque paquet de revue, ou exclure explicitement ces "
            "contenus du perimetre servable par une decision gouvernee."
        ),
        "owner_type": "HUMAN_REVIEWER",
        "automation_possible": False,
        "human_decision_required": True,
        "related_prs": [],
        "close_condition": (
            "0 PII indecise dans le perimetre servable, ou exclusion gouvernee "
            "et versionnee de ces contenus."
        ),
        "regression_tests_required": [
            "une PII indecise dans le perimetre servable bloque le gate"
        ],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
    {
        "id": "PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET",
        "category": "BUSINESS",
        "value_key": "program_incompatible_in_servable_set",
        "blocking_when": "value > 0",
        "evidence_source": MATRICE + " (by_verdict.REFUSED_PROGRAM_INCOMPATIBLE)",
        "required_action": (
            "L artefact est nomme dans la partition programme. L exclure de la "
            "prochaine release, ou corriger sa liaison de perimetre. Ne jamais "
            "corriger sa verite pour faire passer le gate."
        ),
        "owner_type": "HUMAN_DECISION",
        "automation_possible": False,
        "human_decision_required": True,
        "related_prs": [],
        "close_condition": (
            "Artefact exclu du perimetre servable ou reattribue, avec une "
            "epreuve discriminante ; il reste comptabilise dans les 2530 en "
            "GOVERNED_NOT_SERVABLE, jamais supprime de l historique."
        ),
        "regression_tests_required": [
            "un artefact prouve incompatible dans le perimetre servable bloque"
        ],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
    {
        "id": "CURRENTNESS_POLICY_APPLIED",
        "category": "GOVERNANCE",
        "value_key": "currentness_policy_applied",
        "blocking_when": "value is false",
        "evidence_source": POLITIQUE_ACTUALITE + " (champ applied)",
        "required_action": (
            "Cabler la politique dans le runtime. ADR-0055 l adopte ; adopter "
            "et cabler sont deux actes distincts, et les confondre ferait d une "
            "revue de texte un changement de comportement."
        ),
        "owner_type": "ENGINEERING",
        "automation_possible": True,
        "human_decision_required": False,
        "related_prs": [151],
        "close_condition": (
            "Un consommateur de production applique la politique et le gate le "
            "constate ; un registre seulement present ne suffit pas."
        ),
        "regression_tests_required": [
            "applied=false bloque le gate",
            "la politique ne decide rien qui appartienne a un autre gate",
        ],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
    {
        "id": "NON_PDF_SERVABLE_REACQUIRED",
        "category": "DATA",
        "value_key": "non_pdf_servable_reacquired",
        "blocking_when": "value < non_pdf_servable_total",
        "evidence_source": (
            POLITIQUE_RETENTION_NON_PDF
            + " (magasin durable mesure) ; plancher : "
            + NON_PDF
            + " (NON_PDF_LOCAL_COPY_RETAINED)"
        ),
        "required_action": (
            "Reacquerir les ressources interactives servables depuis Drive, "
            "empreinte et taille attendues au manifeste, ou les exclure par une "
            "decision gouvernee et non silencieuse."
        ),
        "owner_type": "OPERATOR",
        "automation_possible": True,
        "human_decision_required": False,
        "related_prs": [],
        "close_condition": (
            "Octets disponibles pour chaque ressource servable, empreintes "
            "concordantes, ou exclusion gouvernee."
        ),
        "regression_tests_required": [
            "une reacquisition incomplete bloque le gate"
        ],
        "deployment_dependency": "BLOQUE_L_INGESTION_STAGING",
    },
    {
        "id": "GO_LIVE_QUALIFICATION_BLOCKERS",
        "category": "QUALIFICATION",
        "value_key": "go_live_qualification_blockers",
        "blocking_when": "value > 0",
        "evidence_source": BLOQUEURS_QUALIFICATION,
        "required_action": (
            "Fermer chaque gate avec sa preuve. Fermer les bloqueurs metier ne "
            "suffit PAS a deployer : ces gates-la restent entiers."
        ),
        "owner_type": "MIXED",
        "automation_possible": False,
        "human_decision_required": True,
        "related_prs": [132, 167, 168],
        "close_condition": "Chaque entree du tableau porte closed=true et sa preuve.",
        "regression_tests_required": [
            "un bloqueur de qualification ouvert bloque le gate"
        ],
        "deployment_dependency": "BLOQUE_LE_DEPLOIEMENT",
    },
    {
        "id": "OPEN_PRS_BLOCKING",
        "category": "REPOSITORY",
        "value_key": "open_prs_blocking",
        "blocking_when": "value > 0",
        "evidence_source": DISPOSITIONS_PR,
        "required_action": (
            "Fusionner, fermer sur preuve, ou reclasser avec justification "
            "mesuree. Une PR non classee est UNKNOWN et bloque par construction."
        ),
        "owner_type": "HUMAN_DECISION",
        "automation_possible": False,
        "human_decision_required": True,
        "related_prs": [98, 132, 134, 138, 140, 151],
        "close_condition": "Aucune disposition BLOCKING ni UNKNOWN.",
        "regression_tests_required": [
            "une PR BLOCKING bloque",
            "une PR UNKNOWN bloque",
            "une disposition inventee est refusee",
        ],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
    {
        "id": "PRE_RELEASE_BLOCKERS",
        "category": "AGGREGATE",
        "value_key": "pre_release_blockers",
        "blocking_when": "value > 0",
        "evidence_source": "agregat calcule",
        "required_action": (
            "Rien directement. Ce compteur DERIVE de PII, programme et "
            "actualite. Le fermer par lui-meme reviendrait a maquiller les trois."
        ),
        "owner_type": "DERIVED",
        "automation_possible": False,
        "human_decision_required": False,
        "related_prs": [],
        "close_condition": "Se ferme seul quand ses trois sources se ferment.",
        "regression_tests_required": [],
        "deployment_dependency": "BLOQUE_LE_SCELLEMENT",
    },
)

#: Dispositions qui empechent le go-live. `UNKNOWN` en fait partie par
#: construction : une PR qu on n a pas classee est une PR qu on n a pas lue.
#: Le verdict qui n oppose aucun refus. Tout autre verdict, sur un contenu
#: PROMU, est une incoherence de release.
VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"
VERDICT_NON_ACTUEL = "BLOCKED_NOT_CURRENT_BY_SOURCE"

DISPOSITIONS_BLOQUANTES = frozenset({"BLOCKING", "UNKNOWN"})

#: Dispositions qui laissent une PR ouverte sans bloquer, chacune devant etre
#: justifiee dans le fichier de dispositions.
DISPOSITIONS_NON_BLOQUANTES = frozenset(
    {
        "MERGE_CANDIDATE",
        "REBASE_REQUIRED",
        "CLOSE_SUPERSEDED",
        "KEEP_OPEN_GOVERNANCE_ANCHOR",
        "KEEP_OPEN_EXTERNAL_REVIEW",
    }
)

#: Les worktrees legitimes sont NOMMES dans un fichier versionne. Une premiere
#: version les reconnaissait par suffixe de chemin, `/Bureau/RAG` compris : un
#: chemin machine-local dans du code versionne, qui ne survit pas au premier
#: autre poste — et qu AGENTS.md interdit.
WORKTREES_ATTENDUS = "docs/reports/go_live/expected_worktrees.json"

#: Le disque doit garder de quoi rejouer une qualification complete.
DISQUE_LIBRE_MINIMUM_OCTETS = 40 * 1024**3


class EntreeManquante(RuntimeError):
    """Une entree du calcul est absente. Elle ne vaut pas zero."""


def _charger(relative: str) -> Any:
    chemin = REPO_ROOT / relative
    if not chemin.is_file():
        raise EntreeManquante(
            f"entree absente : {relative}. Le readiness ne se calcule pas sur "
            "une entree manquante ; l absence n est pas un zero."
        )
    if chemin.suffix == ".json":
        return json.loads(chemin.read_text(encoding="utf-8"))
    return chemin.read_text(encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def _git_sha(ref: str) -> str | None:
    """Resout une ref en empreinte, ou rend None.

    `git rev-parse <ref>` ne se contente PAS d echouer quand la ref n existe
    pas : il RECOPIE la chaine sur la sortie standard. Sans `--verify`, un
    champ cense porter une empreinte porte alors le texte `origin/main` — une
    valeur absurde d apparence plausible, qui ne se voit que sur un depot ou la
    ref manque.
    """
    # Deux protections, volontairement redondantes : `--verify --quiet` fait
    # taire la sortie, et le code de retour la confirme. Retirer une seule des
    # deux ne change rien — c est le but. Les retirer toutes les deux fait
    # tomber une epreuve.
    resultat = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    sortie = resultat.stdout.strip()
    return sortie if resultat.returncode == 0 and sortie else None


def _store_non_pdf(politique: dict) -> pathlib.Path | None:
    """Resout l emplacement durable nomme par la politique.

    Ordre: la variable d environnement declaree par la politique, puis la
    racine canonique du projet, dont on prend le sous-repertoire le plus
    recent. Aucun chemin machine-local n est ecrit dans le code: la politique
    nomme la racine, l environnement la surcharge.
    """
    magasin = politique.get("durable_store") or {}
    surcharge = os.environ.get(magasin.get("env_override") or "")
    if surcharge:
        chemin = pathlib.Path(surcharge)
        return chemin if chemin.is_dir() else None
    racine = magasin.get("canonical_root")
    if not racine:
        return None
    racine_chemin = pathlib.Path(racine)
    if not racine_chemin.is_dir():
        return None
    horodatages = sorted(
        (d for d in racine_chemin.iterdir() if (d / "bytes").is_dir()),
        key=lambda d: d.name,
    )
    return (horodatages[-1] / "bytes") if horodatages else None


def _non_pdf_servables_retenus() -> tuple[int, dict[str, Any]]:
    """Compte les ressources servables RETENUES, en deleguant la mesure.

    Le compteur ne lit plus une valeur figee: il mesure. Mais il ne mesure que
    sous une politique versionnee, et seulement au magasin durable qu elle
    nomme. Sans politique, ou sans magasin lisible, le bloqueur reste ouvert:
    un zero non mesure et un zero mesure se ressemblent dans un rapport et ne
    disent pas la meme chose.

    La mesure elle-meme n est pas refaite ici. Elle est deleguee au
    reconciliateur canonique, qui est deja l autorite du rapport 37/57 et de la
    verification des octets. Deux implementations de la retention finiraient
    par ne pas compter pareil.
    """
    chemin_politique = REPO_ROOT / POLITIQUE_RETENTION_NON_PDF
    if not chemin_politique.is_file():
        return 0, {
            "non_pdf_retention_policy_versioned": False,
            "non_pdf_retention_reason": "POLICY_ABSENT",
        }
    politique = json.loads(chemin_politique.read_text(encoding="utf-8"))
    if not politique.get("adopted"):
        return 0, {
            "non_pdf_retention_policy_versioned": False,
            "non_pdf_retention_reason": "POLICY_NOT_ADOPTED",
        }

    magasin = _store_non_pdf(politique)
    if magasin is None:
        return 0, {
            "non_pdf_retention_policy_versioned": True,
            "non_pdf_retention_reason": "DURABLE_STORE_UNREADABLE",
        }

    reconciliateur = REPO_ROOT / RECONCILIATEUR_NON_PDF
    if not reconciliateur.is_file():
        raise EntreeManquante(f"reconciliateur canonique absent : {reconciliateur}")

    with tempfile.TemporaryDirectory() as repertoire:
        sortie = pathlib.Path(repertoire) / "reconciliation.json"
        execution = subprocess.run(
            [
                sys.executable,
                str(reconciliateur),
                "--durable-store",
                str(magasin),
                "--output-json",
                str(sortie),
                "--output-md",
                str(pathlib.Path(repertoire) / "reconciliation.md"),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env={**os.environ, "NEXUS_REPO_ROOT": str(REPO_ROOT)},
        )
        if not sortie.is_file():
            raise EntreeManquante(
                "le reconciliateur canonique n a produit aucune sortie : "
                f"{execution.stderr.strip()[:300]}"
            )
        etat = json.loads(sortie.read_text(encoding="utf-8"))

    if not etat.get("reconciled"):
        return 0, {
            "non_pdf_retention_policy_versioned": True,
            "non_pdf_retention_reason": "RECONCILIATION_REFUSED",
        }
    return int(etat["retention"]["retained_servable"]), {
        "non_pdf_retention_policy_versioned": True,
        "non_pdf_retention_reason": "MEASURED",
        "non_pdf_retention_store_named": True,
    }


def _politique_actualite_appliquee() -> bool:
    texte = _charger(POLITIQUE_ACTUALITE)
    for ligne in texte.splitlines():
        nu = ligne.strip()
        if nu.startswith("applied:"):
            return nu.split(":", 1)[1].strip().lower() == "true"
    raise EntreeManquante(
        "la politique d actualite ne declare pas `applied`. Sans cette "
        "declaration, on ne peut pas savoir si elle s applique."
    )


def _worktrees() -> tuple[list[dict[str, Any]], int]:
    attendus = _charger(WORKTREES_ATTENDUS)
    noms_attendus = set(attendus["expected_basenames"])
    marqueur_session = attendus["session_temporary_path_marker"]
    principal = str(_racine_du_checkout_principal())
    brut = _git("worktree", "list", "--porcelain")
    worktrees: list[dict[str, Any]] = []
    courant: dict[str, Any] = {}
    for ligne in brut.splitlines():
        if ligne.startswith("worktree "):
            if courant:
                worktrees.append(courant)
            courant = {"path": ligne.split(" ", 1)[1]}
        elif ligne.startswith("branch "):
            courant["branch"] = ligne.split(" ", 1)[1]
        elif ligne.startswith("HEAD "):
            courant["head"] = ligne.split(" ", 1)[1]
    if courant:
        worktrees.append(courant)

    obsoletes = 0
    for wt in worktrees:
        chemin = wt["path"]
        est_principal = chemin == principal
        nomme = pathlib.PurePath(chemin).name in noms_attendus
        # Un worktree temporaire de session vit sous le scratchpad : il est
        # attendu tant que la session tourne, et disparait avec elle.
        temporaire = marqueur_session in chemin
        wt["expected"] = bool(est_principal or nomme or temporaire)
        if not wt["expected"]:
            obsoletes += 1
    return worktrees, obsoletes


#: Les fichiers versionnes dont ce gate tire ses faits. Les sorties qu il
#: produit en sont volontairement absentes : les voir bouger avec lui ne
#: prouverait rien.
ENTREES_VERSIONNEES = (
    MATRICE,
    NON_PDF,
    POLITIQUE_RETENTION_NON_PDF,
    POLITIQUE_ACTUALITE,
    DISPOSITIONS_PR,
    BLOQUEURS_QUALIFICATION,
    ECART_RECHERCHE,
    WORKTREES_ATTENDUS,
)


def _empreintes_des_entrees() -> dict[str, str]:
    """Empreinte de chaque entree, ou ABSENT.

    Une entree absente est nommee ABSENT, jamais omise : une cle manquante se
    lirait comme une entree inchangee.
    """
    empreintes = {}
    for relatif in ENTREES_VERSIONNEES:
        chemin = REPO_ROOT / relatif
        if not chemin.is_file():
            empreintes[relatif] = "ABSENT"
            continue
        empreintes[relatif] = hashlib.sha256(chemin.read_bytes()).hexdigest()
    return empreintes


def _racine_du_checkout_principal() -> pathlib.Path:
    """Le checkout PRINCIPAL, pas le worktree courant.

    Les residus vivent sous le `.worktrees/` du checkout principal. Sonder le
    worktree courant n y trouve rien — et rendre zero parce qu on a regarde au
    mauvais endroit est pire que ne pas regarder.
    """
    commun = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if commun.endswith("/.git"):
        return pathlib.Path(commun).parent
    return REPO_ROOT


def _residus_root() -> list[dict[str, Any]]:
    """Repertoires sous .worktrees/ qui ne sont plus des worktrees git.

    Ils ne sont pas detectables par git : c est precisement pour cela qu ils
    passent inapercus.
    """
    racine = _racine_du_checkout_principal() / ".worktrees"
    if not racine.is_dir():
        return []
    enregistres = {wt["path"] for wt in _worktrees()[0]}
    residus = []
    for entree in sorted(racine.iterdir()):
        if not entree.is_dir() or str(entree) in enregistres:
            continue
        appartient_a_autrui = False
        try:
            mien = os.getuid()
            appartient_a_autrui = any(
                p.stat().st_uid != mien
                for p in [entree, *list(entree.rglob("*"))[:2000]]
            )
        except OSError:
            appartient_a_autrui = True
        # Chemin RELATIF a la racine : un chemin absolu rendrait le fichier
        # genere different sur chaque poste, et ferait entrer un chemin
        # machine-local dans le depot.
        residus.append(
            {
                "path": str(entree.relative_to(_racine_du_checkout_principal())),
                "foreign_owned_entries": appartient_a_autrui,
            }
        )
    return residus


def _ensemble_promu() -> tuple[frozenset[str], dict[str, Any]]:
    """Les contenus reellement promus, selon l autorite canonique.

    Pourquoi pas la matrice
    -----------------------

    La matrice dit ce qui SERAIT servable ; elle est emise `applied=false` et
    refuse elle-meme un contenu programme-incompatible des la premiere marche
    de sa cascade. Compter les incompatibles « dans le perimetre servable »
    depuis cette cascade donnerait toujours zero : une mesure qui ne peut
    jamais etre non nulle ne protege rien.

    Pourquoi pas un scan de fichiers
    --------------------------------

    Une premiere version balayait tous les JSON de `data/releases` a la
    recherche de chaines de 64 caracteres hexadecimaux. Elle trouvait 20739
    empreintes la ou l autorite canonique en compte 319 : elle ramassait des
    empreintes d arbres, de modeles, de manifestes — tout ce qui a la FORME
    d un sha256 sans en avoir le ROLE. Une union de digests techniques n est
    pas un ensemble de contenus servis, et s en servir comme garde revenait a
    tirer une conclusion d une coincidence de format.

    Elle rendait de surcroit un ensemble VIDE quand la racine manquait, ce qui
    transformait « je ne sais pas » en « rien n est promu ».

    L autorite est donc celle qui sait : `select_release_authority` et le
    contrat de release, le meme chemin que le runtime. Tout refus du chargeur
    canonique remonte ici comme un refus, jamais comme un ensemble vide.
    """
    # L arbre EVALUE, pas le checkout principal. Le readiness rend compte de
    # l arbre qu on lui donne ; aller chercher le calculateur ailleurs ferait
    # mesurer un arbre et conclure sur un autre.
    racine = REPO_ROOT
    chemin = racine / CALCULATEUR_ENSEMBLE_PROMU
    if not chemin.is_file():
        raise EntreeManquante(
            f"calculateur canonique absent : {CALCULATEUR_ENSEMBLE_PROMU}. "
            "Le readiness ne redefinit pas ce qu est un contenu promu."
        )
    with tempfile.TemporaryDirectory() as bac:
        sortie = pathlib.Path(bac) / "promoted.json"
        resultat = subprocess.run(
            [sys.executable, str(chemin), "--output", str(sortie)],
            capture_output=True,
            text=True,
            cwd=str(racine),
            check=False,
        )
        if resultat.returncode != 0 or not sortie.is_file():
            raise EntreeManquante(
                "l autorite canonique refuse de rendre l ensemble promu : "
                f"{(resultat.stderr or resultat.stdout).strip()[:400]}. "
                "Un refus n est pas un ensemble vide."
            )
        charge = json.loads(sortie.read_text(encoding="utf-8"))

    contenus = frozenset(charge.get("content_sha256") or ())
    if not contenus:
        raise EntreeManquante(
            "l ensemble promu canonique est vide : toute comparaison avec lui "
            "serait vraie par vacuite."
        )
    autorite = charge.get("release_authority")
    mecanisme = (
        autorite.get("mechanism") if isinstance(autorite, dict) else autorite
    )
    provenance = {
        "promoted_content_set_source": CALCULATEUR_ENSEMBLE_PROMU,
        "promoted_content_set_sha256": charge.get("content_set_sha256"),
        "promoted_content_set_size": len(contenus),
        "promoted_release_authority_mechanism": mecanisme,
        "promoted_release_registry_source": charge.get("release_registry_source"),
    }
    return contenus, provenance


def _disque() -> tuple[int, int]:
    usage = shutil.disk_usage(REPO_ROOT)
    return usage.free, round(usage.used * 100 / usage.total)


def evaluer(*, declared_lot_facts: dict[str, int]) -> dict[str, Any]:
    matrice = _charger(MATRICE)
    non_pdf = _charger(NON_PDF)
    # Un corpus gouverne n est pas un corpus interrogeable. L ecart est LU,
    # jamais suppose : sans ce fichier, on ne saurait pas si le corpus est
    # atteignable, et ne pas savoir n est pas une autorisation.
    ecart_recherche = _charger(ECART_RECHERCHE)
    dispositions = _charger(DISPOSITIONS_PR)["dispositions"]
    qualification = _charger(BLOQUEURS_QUALIFICATION)["blockers"]

    par_verdict = matrice["by_verdict"]
    matrice_par_contenu = {
        ligne["content_sha256"]: ligne["verdict"]
        for ligne in matrice.get("rows", ())
        if "content_sha256" in ligne and "verdict" in ligne
    }
    pii_undecided = matrice["by_pii"].get("PII_UNDECIDED", 0)

    # --- programme incompatible : compter ce que le nom annonce
    #
    # Une premiere version lisait `by_verdict["REFUSED_PROGRAM_INCOMPATIBLE"]`,
    # c est-a-dire un histogramme de TOUTE la population. Elle comptait donc
    # comme « dans le perimetre servable » un contenu que la matrice REFUSE, ce
    # que son propre verdict dit. Le nom promettait une portee que le calcul
    # n avait pas.
    #
    # Ce qui est mesure ici : les contenus prouves incompatibles qui sont
    # encore PROMUS, c est-a-dire presents dans une release materialisee.
    incompatibles = frozenset(
        ligne["content_sha256"]
        for ligne in matrice.get("rows", ())
        if ligne.get("program") == "INCOMPATIBLE_PROVEN"
    )
    promus, provenance_promus = _ensemble_promu()
    incompatibles_promus = sorted(incompatibles & promus)
    programme_incompatible = len(incompatibles_promus)
    programme_incompatible_total = len(incompatibles)
    programme_incompatible_refuse = par_verdict.get(
        "REFUSED_PROGRAM_INCOMPATIBLE", 0
    )
    actualite_appliquee = _politique_actualite_appliquee()

    # Une release promue ne doit pas contenir un contenu que le gate de
    # servabilite refuse. Le cas se produit quand une dimension se met a
    # bloquer APRES la promotion : le contenu reste dans la release, et plus
    # rien ne le signale. Compter ces contenus est le seul moyen de ne pas
    # laisser une incoherence de release passer pour une release saine.
    # Un contenu promu que la matrice ne recense pas ne peut pas etre croise.
    # Le compter comme candidat serait un zero NON MESURE presente comme un
    # zero mesure : on dit donc qu on n a pas pu mesurer, et cela bloque.
    promus_hors_matrice = sorted(promus - set(matrice_par_contenu))
    refuses_promus = sorted(
        sha
        for sha in promus
        if sha in matrice_par_contenu
        and matrice_par_contenu[sha] != VERDICT_CANDIDAT
    )
    refuses_par_verdict = collections.Counter(
        matrice_par_contenu[sha] for sha in refuses_promus
    )
    refuses_par_actualite = [
        sha
        for sha in refuses_promus
        if matrice_par_contenu[sha] == VERDICT_NON_ACTUEL
    ]

    non_pdf_servables = non_pdf["NON_PDF_SERVABLE"]
    # Le compteur fige de la consolidation reste le PLANCHER: la mesure ne peut
    # que le confirmer ou le depasser, jamais le faire baisser.
    non_pdf_mesure, provenance_non_pdf = _non_pdf_servables_retenus()
    non_pdf_reacquis = max(non_pdf["NON_PDF_LOCAL_COPY_RETAINED"], non_pdf_mesure)

    inconnues = [n for n, d in dispositions.items() if d["disposition"] == "UNKNOWN"]
    bloquantes = [
        n
        for n, d in dispositions.items()
        if d["disposition"] in DISPOSITIONS_BLOQUANTES
    ]
    invalides = [
        n
        for n, d in dispositions.items()
        if d["disposition"]
        not in (DISPOSITIONS_BLOQUANTES | DISPOSITIONS_NON_BLOQUANTES)
    ]
    if invalides:
        raise EntreeManquante(
            f"dispositions de PR non reconnues : {invalides!r}. Une disposition "
            "inventee echappe au gate."
        )

    qualification_ouverts = [b for b in qualification if not b["closed"]]
    worktrees, worktrees_obsoletes = _worktrees()
    residus = _residus_root()
    disque_libre, disque_pourcent = _disque()

    pre_release = []
    if pii_undecided:
        pre_release.append(f"PII_UNDECIDED={pii_undecided}")
    if programme_incompatible:
        pre_release.append(
            f"PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET={programme_incompatible}"
        )
    if not actualite_appliquee:
        pre_release.append("CURRENTNESS_POLICY_APPLIED=false")

    etat: dict[str, Any] = {
        "kind": "NEXUS-GO-LIVE-READINESS-STATE-V1",
        "generated_by": "scripts/go_live/check_go_live_readiness.py",
        "note": (
            "Fichier GENERE. Toute valeur de go-live citee ailleurs dans le "
            "depot est une projection de celle-ci, jamais une autorite."
        ),
        # --- fraicheur : ce fichier est-il l etat COURANT, ou un instantane ?
        #
        # La question n est pas rhetorique. Un fichier ecrit puis commite ne
        # peut pas, par construction, contenir le commit qui le contient : il
        # est genere AVANT. Il ne pourra donc jamais etre l etat operatoire du
        # commit ou il vit. Le dire une fois, ici, ferme l ambiguite pour de
        # bon — au lieu de la laisser se reposer a chaque lecture.
        #
        # L autorite operatoire est le script, relance en direct. Ce fichier en
        # est la trace, utile pour comparer, jamais pour autoriser.
        "state_freshness_kind": "COMMITTED_SNAPSHOT",
        "snapshot_contains_self_commit": False,
        "snapshot_is_operational_current": False,
        "snapshot_freshness_note": (
            "Instantane derive. Genere AVANT le commit qui le contient, il ne "
            "peut donc jamais etre l etat operatoire de ce commit. Pour une "
            "decision de deploiement, relancer le script en direct."
        ),
        # Deux commits distincts, et les confondre ferait dire au fichier
        # qu une branche de travail EST main.
        "main_head": _git_sha("origin/main"),
        "origin_main_at_generation": _git_sha("origin/main"),
        "evaluated_ref": _git("rev-parse", "--abbrev-ref", "HEAD") or "DETACHED",
        "evaluated_head": _git_sha("HEAD"),
        # Nommer le commit evalue ne suffit pas : un instantane est produit
        # AVANT le commit qui le porte, il nomme donc toujours le parent. Ce
        # qui se verifie, c est que les ENTREES n ont pas bouge depuis. Les
        # empreintes rendent cela decidable sans historique git, donc aussi
        # sur un clone superficiel.
        "input_digests": _empreintes_des_entrees(),
        "open_prs_total": len(dispositions),
        "open_prs_blocking": len(bloquantes),
        "open_prs_disposition_unknown": len(inconnues),
        "open_prs_blocking_ids": sorted(bloquantes, key=int),
        "worktrees_total": len(worktrees),
        "obsolete_worktrees_remaining": worktrees_obsoletes,
        "root_owned_worktree_residues": len(residus),
        "root_owned_worktree_residue_paths": [r["path"] for r in residus],
        "pre_release_blockers": len(pre_release),
        "pre_release_blocker_ids": pre_release,
        "go_live_qualification_blockers": len(qualification_ouverts),
        "go_live_qualification_blocker_ids": [b["id"] for b in qualification_ouverts],
        "servable_candidate_count": par_verdict.get(
            "CANDIDATE_NO_BLOCKING_DIMENSION", 0
        ),
        "pii_undecided": pii_undecided,
        "program_incompatible_in_servable_set": programme_incompatible,
        "program_incompatible_in_servable_set_ids": incompatibles_promus,
        # Informatifs, NON bloquants : l incompatibilite reste visible meme
        # quand elle ne bloque pas. La faire disparaitre du rapport serait la
        # maquiller.
        "program_incompatible_total": programme_incompatible_total,
        "program_incompatible_refused_by_matrix": programme_incompatible_refuse,
        **provenance_promus,
        "currentness_policy_applied": actualite_appliquee,
        # Le blocage de release est SEPARE du blocage PII et du drapeau
        # d actualite : ils ne disent pas la meme chose. La PII parle d une
        # decision humaine sur des donnees personnelles ; l actualite, de ce
        # que la source declare ; l impact de release, du fait qu une release
        # deja promue contient un contenu desormais refuse. Les fondre ferait
        # disparaitre le troisieme derriere les deux autres.
        "release_promoted_refused_contents": len(refuses_promus),
        "release_promoted_refused_content_ids": refuses_promus,
        "release_promoted_refused_by_verdict": dict(sorted(refuses_par_verdict.items())),
        "release_promoted_refused_by_currentness": len(refuses_par_actualite),
        "release_currentness_impact": refuses_par_actualite,
        "release_reseal_required": bool(refuses_promus),
        "release_promoted_unmatched_in_matrix": len(promus_hors_matrice),
        "release_impact_measurable": not promus_hors_matrice,
        # L exploitabilite par RECHERCHE, distincte de la servabilite. Un
        # contenu peut etre promu, servable et ingere sans qu aucune requete ne
        # puisse l atteindre.
        "rag_searchable": ecart_recherche["rag_searchable"],
        "staging_vectors_present": ecart_recherche["measured"]["staging_vectors_present"],
        "target_scope_searchable": ecart_recherche["target_scope_searchable"],
        "production_searchable": ecart_recherche["production_searchable"],
        "retrieval_contract_validated": ecart_recherche["retrieval_contract_validated"],
        "rag_searchability_blocker": ecart_recherche["rag_searchability_blocker"],
        "rag_searchability_conditions_not_met": ecart_recherche["conditions_not_met"],
        "non_pdf_servable_total": non_pdf_servables,
        "non_pdf_servable_reacquired": non_pdf_reacquis,
        "non_pdf_servable_complete": non_pdf_reacquis >= non_pdf_servables,
        **provenance_non_pdf,
        "disk_free_bytes": disque_libre,
        "disk_used_percent": disque_pourcent,
        "disk_policy_ok": disque_libre >= DISQUE_LIBRE_MINIMUM_OCTETS,
        # Declares par le lot : aucune lecture du depot ne prouve une absence
        # d action sur la production. Le dire vaut mieux que le simuler.
        "production_db_writes": declared_lot_facts["production_db_writes"],
        "production_deployments": declared_lot_facts["production_deployments"],
        "current_switch": declared_lot_facts["current_switch"],
        "production_facts_are_declared_not_measured": True,
    }

    refus = []
    if etat["pre_release_blockers"]:
        refus.append("pre_release_blockers")
    if etat["go_live_qualification_blockers"]:
        refus.append("go_live_qualification_blockers")
    if etat["pii_undecided"]:
        refus.append("pii_undecided")
    if etat["program_incompatible_in_servable_set"]:
        refus.append("program_incompatible_in_servable_set")
    if not etat["currentness_policy_applied"]:
        refus.append("currentness_policy_applied")
    # Appliquer la politique d actualite ne suffit pas : si une release DEJA
    # promue contient un contenu que le gate refuse desormais, la release est
    # incoherente. Fermer le drapeau d actualite en laissant cette incoherence
    # non bloquante ferait disparaitre le risque au moment meme ou on le
    # decouvre.
    if etat["release_promoted_refused_contents"]:
        refus.append("release_promoted_refused_contents")
    # Fermer PII, release, qualification et PR ne rendra pas le corpus
    # interrogeable. Un go-live prononce sur les seuls compteurs de gouvernance
    # livrerait un RAG qui ne repond a rien.
    if etat["rag_searchability_blocker"]:
        refus.append("rag_searchability_blocker")
    # Ne pas avoir pu croiser n est pas la meme chose que n avoir rien trouve.
    if not etat["release_impact_measurable"]:
        refus.append("release_impact_measurable")
    if not etat["non_pdf_servable_complete"]:
        refus.append("non_pdf_servable_reacquired")
    if etat["open_prs_blocking"]:
        refus.append("open_prs_blocking")
    if etat["open_prs_disposition_unknown"]:
        refus.append("open_prs_disposition_unknown")
    if etat["obsolete_worktrees_remaining"]:
        refus.append("obsolete_worktrees_remaining")
    if etat["root_owned_worktree_residues"]:
        refus.append("root_owned_worktree_residues")
    if etat["production_db_writes"]:
        refus.append("production_db_writes")
    if etat["production_deployments"]:
        refus.append("production_deployments")
    if etat["current_switch"]:
        refus.append("current_switch")
    if not etat["disk_policy_ok"]:
        refus.append("disk_policy_ok")

    etat["blocking_reasons"] = refus
    etat["go_live_ready"] = not refus
    return etat


def construire_ledger(etat: dict[str, Any]) -> dict[str, Any]:
    """Derive le ledger de l etat calcule. Aucune valeur n y est saisie."""
    entrees = []
    for spec in LEDGER_SPEC:
        valeur = etat[spec["value_key"]]
        if spec["id"] == "NON_PDF_SERVABLE_REACQUIRED":
            bloque = not etat["non_pdf_servable_complete"]
            valeur = f"{valeur}/{etat['non_pdf_servable_total']}"
        elif spec["id"] == "CURRENTNESS_POLICY_APPLIED":
            bloque = not valeur
        else:
            bloque = bool(valeur)
        entree = {k: v for k, v in spec.items() if k != "value_key"}
        entree["current_value"] = valeur
        entree["blocking"] = bloque
        entrees.append(entree)
    return {
        "kind": "NEXUS-BLOCKER-CLOSURE-LEDGER-V1",
        "generated_by": "scripts/go_live/check_go_live_readiness.py",
        "note": (
            "Fichier DERIVE. Les valeurs viennent de l etat calcule ; seules "
            "les conditions de fermeture sont declarees, une fois."
        ),
        "evaluated_head": etat["evaluated_head"],
        "go_live_ready": etat["go_live_ready"],
        "blockers_total": len(entrees),
        "blockers_open": sum(1 for e in entrees if e["blocking"]),
        "blockers": entrees,
    }


def rendre_ledger_markdown(ledger: dict[str, Any]) -> str:
    lignes = [
        "# Ledger de fermeture des bloqueurs go-live",
        "",
        "> **Fichier derive.** Regenere par",
        "> `scripts/go_live/check_go_live_readiness.py`. Les valeurs viennent de",
        "> l etat calcule ; les editer a la main les rendrait faux sans les",
        "> rendre fermes.",
        "",
        f"`blockers_open={ledger['blockers_open']}` sur {ledger['blockers_total']}",
        "",
        "| Bloqueur | Valeur | Bloque | Qui agit | Condition de fermeture |",
        "| --- | ---: | :---: | --- | --- |",
    ]
    for e in ledger["blockers"]:
        lignes.append(
            f"| `{e['id']}` | {e['current_value']} | "
            f"{'oui' if e['blocking'] else 'non'} | {e['owner_type']} | "
            f"{e['close_condition']} |"
        )
    lignes += ["", "## Detail", ""]
    for e in ledger["blockers"]:
        lignes += [
            f"### {e['id']}",
            "",
            f"- categorie : `{e['category']}`",
            f"- valeur : `{e['current_value']}`, bloque : "
            f"`{'oui' if e['blocking'] else 'non'}`",
            f"- source de preuve : `{e['evidence_source']}`",
            f"- action requise : {e['required_action']}",
            f"- decision humaine requise : "
            f"`{'oui' if e['human_decision_required'] else 'non'}`",
            f"- automatisable : `{'oui' if e['automation_possible'] else 'non'}`",
            f"- PR liees : {e['related_prs'] or 'aucune'}",
            f"- dependance de deploiement : `{e['deployment_dependency']}`",
            "",
        ]
    return "\n".join(lignes)


def construire_plan(etat: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Derive le plan de cloture de l etat et du ledger. Rien n y est saisi."""
    par_id = {b["id"]: b for b in ledger["blockers"]}
    ouverts = {b["id"] for b in ledger["blockers"] if b["blocking"]}

    niveaux = []
    for niveau in NIVEAUX_DE_CONTENU:
        entree = dict(niveau)
        if niveau["id"] == "PROMOTED":
            entree["value"] = etat["promoted_content_set_size"]
        elif niveau["id"] == "SERVABLE_CANDIDATE":
            entree["value"] = etat.get("servable_candidate_count")
        else:
            entree["value"] = None
            entree["why_not_measured"] = (
                "exige une base ou un service identifies ; rendre zero serait "
                "une fausse assurance"
            )
        niveaux.append(entree)

    phases = []
    for phase in PHASES_DE_CLOTURE:
        bloqueurs = [b for b in phase["blockers"] if b in ouverts]
        amont_ouvertes = [
            autre["id"]
            for autre in PHASES_DE_CLOTURE
            if autre["id"] in phase["depends_on"]
            and any(b in ouverts for b in autre["blockers"])
        ]
        phases.append(
            {
                **phase,
                "open_blockers": bloqueurs,
                "blocked_by_phases": amont_ouvertes,
                "actionable_now": not amont_ouvertes and bool(bloqueurs),
                "closed": not bloqueurs and not amont_ouvertes,
                "owners": sorted(
                    {par_id[b]["owner_type"] for b in bloqueurs if b in par_id}
                ),
            }
        )

    return {
        "kind": "NEXUS-GO-LIVE-CLOSURE-PLAN-V1",
        "generated_by": "scripts/go_live/check_go_live_readiness.py",
        "note": (
            "Fichier DERIVE de l etat calcule et du ledger. Il ordonne ce qui "
            "reste ; il n autorise rien."
        ),
        "evaluated_head": etat["evaluated_head"],
        "go_live_ready": etat["go_live_ready"],
        "content_levels": niveaux,
        "phases": phases,
        "phases_closed": sum(1 for p in phases if p["closed"]),
        "phases_total": len(phases),
    }


def rendre_plan_markdown(plan: dict[str, Any]) -> str:
    lignes = [
        "# Plan de cloture go-live",
        "",
        "> **Fichier derive.** Regenere par",
        "> `scripts/go_live/check_go_live_readiness.py`. Il ordonne ce qui reste ;",
        "> il n autorise rien. Le seul garde est `--assert-ready`.",
        "",
        f"`go_live_ready={'true' if plan['go_live_ready'] else 'false'}`",
        f" — phases fermees : {plan['phases_closed']} sur {plan['phases_total']}",
        "",
        "## Cinq niveaux, souvent confondus",
        "",
        "Un contenu qui figure dans une matrice n est pas pour autant servi.",
        "",
        "| Niveau | Mesure | Valeur |",
        "| --- | --- | --- |",
    ]
    for n in plan["content_levels"]:
        valeur = (
            str(n["value"])
            if n["measurable_from_repository"] and n["value"] is not None
            else "non mesurable depuis le depot"
        )
        lignes.append(f"| {n['libelle']} | {n['mesure']} | {valeur} |")
    lignes += [
        "",
        "Trois de ces cinq niveaux **ne se mesurent pas depuis le depot**. Ils",
        "exigent une base et un service identifies. Rendre zero pour eux serait",
        "une fausse assurance, et c est pourquoi ils sont declares non mesurables",
        "plutot que remplis.",
        "",
        "## Ordre impose",
        "",
        "| Phase | Etat | Bloqueurs ouverts | Bloquee par | Qui agit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in plan["phases"]:
        etat_phase = (
            "fermee"
            if p["closed"]
            else ("actionnable" if p["actionable_now"] else "en attente")
        )
        lignes.append(
            f"| `{p['id']}` {p['titre']} | {etat_phase} | "
            f"{', '.join(p['open_blockers']) or '—'} | "
            f"{', '.join(p['blocked_by_phases']) or '—'} | "
            f"{', '.join(p['owners']) or '—'} |"
        )
    lignes += [
        "",
        "Une phase ne s ouvre pas tant que celles dont elle depend restent",
        "ouvertes. Qualifier un staging avant d avoir les octets, ou deployer",
        "avant d avoir qualifie, oblige a tout refaire.",
        "",
        "## Conditions de fermeture",
        "",
    ]
    for p in plan["phases"]:
        lignes += [f"### {p['id']} — {p['titre']}", "", f"Gate : `{p['gate']}`", ""]
    return "\n".join(lignes)


def rendre_markdown(etat: dict[str, Any]) -> str:
    lignes = [
        "# Etat de readiness go-live",
        "",
        "> **Fichier derive.** Il est regenere par",
        "> `scripts/go_live/check_go_live_readiness.py` depuis",
        "> `go_live_readiness_state.json`. Ne pas l editer a la main : toute",
        "> correction faite ici serait perdue, et pire, ferait croire a une",
        "> seconde source de verite.",
        "",
        f"`GO_LIVE_READY={'true' if etat['go_live_ready'] else 'false'}`",
        "",
        f"`main_head={etat['main_head']}`",
        "",
    ]
    if etat["blocking_reasons"]:
        lignes += [
            "## Ce qui empeche le go-live",
            "",
            "| Raison | Valeur |",
            "| --- | ---: |",
        ]
        for raison in etat["blocking_reasons"]:
            lignes.append(f"| `{raison}` | {etat.get(raison)} |")
        lignes.append("")
    lignes += ["## Etat calcule", "", "| Cle | Valeur |", "| --- | ---: |"]
    for cle, valeur in etat.items():
        if cle in {"kind", "note", "generated_by"} or isinstance(valeur, list):
            continue
        lignes.append(f"| `{cle}` | {valeur} |")
    lignes += [
        "",
        "## Ce fichier n autorise aucun deploiement",
        "",
        "L autorite operatoire est le script, **relance en direct**. Ce fichier",
        "est un instantane : genere avant le commit qui le contient, il ne peut",
        "pas etre l etat operatoire de ce commit.",
        "",
        "Trois modes, et un seul est un garde :",
        "",
        "| Mode | Code de retour | Role |",
        "| --- | --- | --- |",
        "| `--check-only` | 0 des que le calcul s execute | diagnostic |",
        "| `--verify-snapshot` | 0 si concordant | concordance |",
        "| `--assert-ready` | 0 seulement si pret, 1 sinon, 2 si entree manquante | **garde** |",
        "",
        "**Seul `--assert-ready` peut conditionner un deploiement.**",
        "`--check-only` rend 0 meme quand rien n est pret : c est un faux vert",
        "si on s en sert comme garde. Et un instantane, perime ou non,",
        "n autorise rien : il ne fait que concorder.",
        "",
        "```",
        "python3 scripts/go_live/check_go_live_readiness.py --assert-ready",
        "```",
        "",
        "## Ce que ce fichier ne mesure pas",
        "",
        "Trois compteurs sont **declares par le lot**, pas mesures :",
        "`production_db_writes`, `production_deployments`, `current_switch`.",
        "Aucune lecture du depot ne prouve qu aucune action n a eu lieu sur la",
        "production. Les presenter comme mesures serait une fausse assurance.",
        "",
    ]
    return "\n".join(lignes)


def verifier_instantane(chemin: pathlib.Path) -> dict[str, Any]:
    """Repond, a la LECTURE, si un instantane vaut encore pour aujourd hui.

    C est la seule facon honnete de repondre : `snapshot_is_operational_current`
    ne peut pas etre une valeur stockee, puisqu elle serait vraie l instant de
    l ecriture et fausse aussitot apres.
    """
    if not chemin.is_file():
        raise EntreeManquante(f"instantane absent : {chemin}")
    instantane = json.loads(chemin.read_text(encoding="utf-8"))
    tete_courante = _git_sha("HEAD")
    main_courant = _git_sha("origin/main")
    a_jour = (
        instantane.get("evaluated_head") == tete_courante
        and instantane.get("origin_main_at_generation") == main_courant
    )
    return {
        "snapshot_path": str(chemin),
        "snapshot_evaluated_head": instantane.get("evaluated_head"),
        "snapshot_origin_main": instantane.get("origin_main_at_generation"),
        "current_head": tete_courante,
        "current_origin_main": main_courant,
        "snapshot_is_operational_current": bool(a_jour),
        "snapshot_go_live_ready": instantane.get("go_live_ready"),
        # Un instantane perime ne peut RIEN autoriser. Meme a jour, il n est
        # qu une trace : l autorite reste le calcul en direct.
        "snapshot_may_authorize_go_live": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=SORTIE_JSON)
    parser.add_argument("--markdown", default=SORTIE_MD)
    parser.add_argument("--ledger-json", default=SORTIE_LEDGER_JSON)
    parser.add_argument("--ledger-markdown", default=SORTIE_LEDGER_MD)
    parser.add_argument("--plan-json", default=SORTIE_PLAN_JSON)
    parser.add_argument("--plan-markdown", default=SORTIE_PLAN_MD)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--assert-ready",
        action="store_true",
        help=(
            "Garde de deploiement : rend 0 seulement si le systeme est pret, "
            "1 sinon, 2 si une entree manque. N ecrit aucun fichier."
        ),
    )
    parser.add_argument(
        "--verify-snapshot",
        metavar="CHEMIN",
        help=(
            "Repond si un instantane committe vaut encore pour le HEAD courant. "
            "N ecrit rien."
        ),
    )
    parser.add_argument("--production-db-writes", type=int, default=0)
    parser.add_argument("--production-deployments", type=int, default=0)
    parser.add_argument("--current-switch", type=int, default=0)
    args = parser.parse_args()

    if args.assert_ready:
        try:
            etat = evaluer(
                declared_lot_facts={
                    "production_db_writes": args.production_db_writes,
                    "production_deployments": args.production_deployments,
                    "current_switch": args.current_switch,
                }
            )
        except EntreeManquante as exc:
            # Une entree manquante n est pas un refus ordinaire : c est
            # l impossibilite de conclure. Elle merite son propre code.
            print(f"REFUS : {exc}", file=sys.stderr)
            print("GO_LIVE_READY=unknown", file=sys.stderr)
            return 2
        pret = etat["go_live_ready"]
        print(f"GO_LIVE_READY={'true' if pret else 'false'}")
        print("blocking_reasons=" + ",".join(etat["blocking_reasons"]))
        if not pret:
            print(
                "ASSERT_READY=failed — ce code de retour non nul est le seul "
                "signal fiable pour une chaine de deploiement.",
                file=sys.stderr,
            )
            return 1
        return 0

    if args.verify_snapshot:
        try:
            verdict = verifier_instantane(REPO_ROOT / args.verify_snapshot)
        except EntreeManquante as exc:
            print(f"REFUS : {exc}", file=sys.stderr)
            return 2
        for cle, valeur in verdict.items():
            print(f"{cle}={valeur}")
        # Repete en clair : le code de retour de ce mode dit CONCORDANT, pas
        # AUTORISE. Les confondre transformerait un simple accord de commits en
        # feu vert de deploiement.
        print("SNAPSHOT_AUTHORIZATION=false")
        print("USE_ASSERT_READY_TO_GATE_A_DEPLOYMENT=true")
        return 0 if verdict["snapshot_is_operational_current"] else 1

    try:
        etat = evaluer(
            declared_lot_facts={
                "production_db_writes": args.production_db_writes,
                "production_deployments": args.production_deployments,
                "current_switch": args.current_switch,
            }
        )
    except EntreeManquante as exc:
        print(f"REFUS : {exc}", file=sys.stderr)
        return 2

    if not args.check_only:
        chemin_json = REPO_ROOT / args.json
        chemin_json.parent.mkdir(parents=True, exist_ok=True)
        chemin_json.write_text(
            json.dumps(etat, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (REPO_ROOT / args.markdown).write_text(
            rendre_markdown(etat), encoding="utf-8"
        )
        ledger = construire_ledger(etat)
        chemin_ledger = REPO_ROOT / args.ledger_json
        chemin_ledger.parent.mkdir(parents=True, exist_ok=True)
        chemin_ledger.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (REPO_ROOT / args.ledger_markdown).write_text(
            rendre_ledger_markdown(ledger), encoding="utf-8"
        )
        plan = construire_plan(etat, ledger)
        chemin_plan = REPO_ROOT / args.plan_json
        chemin_plan.parent.mkdir(parents=True, exist_ok=True)
        chemin_plan.write_text(
            json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (REPO_ROOT / args.plan_markdown).write_text(
            rendre_plan_markdown(plan), encoding="utf-8"
        )

    print(f"GO_LIVE_READY={'true' if etat['go_live_ready'] else 'false'}")
    for cle in (
        "pre_release_blockers",
        "go_live_qualification_blockers",
        "pii_undecided",
        "program_incompatible_in_servable_set",
        "currentness_policy_applied",
        "non_pdf_servable_reacquired",
        "open_prs_blocking",
        "open_prs_disposition_unknown",
        "obsolete_worktrees_remaining",
        "root_owned_worktree_residues",
        "disk_used_percent",
    ):
        print(f"{cle}={etat[cle]}")
    if etat["blocking_reasons"]:
        print("blocking_reasons=" + ",".join(etat["blocking_reasons"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
