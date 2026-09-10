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

Les chemins sont derives de l emplacement de ce fichier ; `NEXUS_REPO_ROOT`
permet de les surcharger.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(
    os.environ.get("NEXUS_REPO_ROOT", pathlib.Path(__file__).resolve().parents[2])
)

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
NON_PDF = "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json"
POLITIQUE_ACTUALITE = (
    "services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"
)
DISPOSITIONS_PR = "docs/reports/go_live/open_pr_dispositions.json"
BLOQUEURS_QUALIFICATION = "docs/reports/go_live/qualification_blockers.json"
SORTIE_JSON = "docs/reports/go_live/go_live_readiness_state.json"
SORTIE_MD = "docs/reports/go_live/GO_LIVE_READINESS.md"
SORTIE_LEDGER_JSON = "docs/reports/go_live/blocker_closure_ledger.json"
SORTIE_LEDGER_MD = "docs/reports/go_live/BLOCKER_CLOSURE_LEDGER.md"

#: Le ledger est DERIVE de l etat calcule. Ecrire ses valeurs a la main
#: recreerait une seconde source, et deux sources finissent par diverger.
#: Seule la partie non calculable — qui doit agir, sous quelle condition la
#: fermeture est acquise — est declaree ici, une fois.
LEDGER_SPEC: tuple[dict[str, Any], ...] = (
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
        "evidence_source": NON_PDF + " (NON_PDF_LOCAL_COPY_RETAINED)",
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


def _disque() -> tuple[int, int]:
    usage = shutil.disk_usage(REPO_ROOT)
    return usage.free, round(usage.used * 100 / usage.total)


def evaluer(*, declared_lot_facts: dict[str, int]) -> dict[str, Any]:
    matrice = _charger(MATRICE)
    non_pdf = _charger(NON_PDF)
    dispositions = _charger(DISPOSITIONS_PR)["dispositions"]
    qualification = _charger(BLOQUEURS_QUALIFICATION)["blockers"]

    par_verdict = matrice["by_verdict"]
    pii_undecided = matrice["by_pii"].get("PII_UNDECIDED", 0)
    programme_incompatible = par_verdict.get("REFUSED_PROGRAM_INCOMPATIBLE", 0)
    actualite_appliquee = _politique_actualite_appliquee()

    non_pdf_servables = non_pdf["NON_PDF_SERVABLE"]
    non_pdf_reacquis = non_pdf["NON_PDF_LOCAL_COPY_RETAINED"]

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
        "pii_undecided": pii_undecided,
        "program_incompatible_in_servable_set": programme_incompatible,
        "currentness_policy_applied": actualite_appliquee,
        "non_pdf_servable_total": non_pdf_servables,
        "non_pdf_servable_reacquired": non_pdf_reacquis,
        "non_pdf_servable_complete": non_pdf_reacquis >= non_pdf_servables,
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
        "Pour une decision de deploiement :",
        "",
        "```",
        "python3 scripts/go_live/check_go_live_readiness.py --check-only",
        "python3 scripts/go_live/check_go_live_readiness.py \\",
        "    --verify-snapshot docs/reports/go_live/go_live_readiness_state.json",
        "```",
        "",
        "Un instantane perime n autorise rien, et un instantane a jour non plus :",
        "il ne fait que concorder.",
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
    parser.add_argument("--check-only", action="store_true")
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

    if args.verify_snapshot:
        try:
            verdict = verifier_instantane(REPO_ROOT / args.verify_snapshot)
        except EntreeManquante as exc:
            print(f"REFUS : {exc}", file=sys.stderr)
            return 2
        for cle, valeur in verdict.items():
            print(f"{cle}={valeur}")
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
