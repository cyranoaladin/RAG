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
        # Deux commits distincts, et les confondre ferait dire au fichier
        # qu une branche de travail EST main. `main_head` est resolu depuis
        # `origin/main` ; `computed_from_head` est le commit reellement lu.
        "main_head": _git("rev-parse", "origin/main") or None,
        "computed_from_head": _git("rev-parse", "HEAD"),
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
        "## Ce que ce fichier ne mesure pas",
        "",
        "Trois compteurs sont **declares par le lot**, pas mesures :",
        "`production_db_writes`, `production_deployments`, `current_switch`.",
        "Aucune lecture du depot ne prouve qu aucune action n a eu lieu sur la",
        "production. Les presenter comme mesures serait une fausse assurance.",
        "",
    ]
    return "\n".join(lignes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default=SORTIE_JSON)
    parser.add_argument("--markdown", default=SORTIE_MD)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--production-db-writes", type=int, default=0)
    parser.add_argument("--production-deployments", type=int, default=0)
    parser.add_argument("--current-switch", type=int, default=0)
    args = parser.parse_args()

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
