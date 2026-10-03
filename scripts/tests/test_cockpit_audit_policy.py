"""Politique d'audit du cockpit : l'exception est plus étroite que le problème qu'elle traite.

Hermétique : aucun appel à npm ni au réseau ; les sorties `npm audit --json` sont synthétiques mais
reproduisent la forme réelle (avis, chaîne `via`, `fixAvailable`, lockfile `dev: true`).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/cockpit_audit_policy.py"
SPEC = importlib.util.spec_from_file_location("cockpit_audit_policy", SCRIPT)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

AVANT_ECHEANCE = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
URL = "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm"
AVIS = {"source": 1240992, "name": "braces", "dependency": "braces", "severity": "high", "url": URL,
        "title": "braces vulnerable to stack-exhaustion denial of service through deeply nested patterns",
        "range": "<=3.0.3"}
CHAINES = {
    "braces": [AVIS], "chokidar": ["braces"], "micromatch": ["braces"], "fast-glob": ["micromatch"],
    "tailwindcss": ["chokidar", "fast-glob", "micromatch"], "tailwindcss-animate": ["tailwindcss"],
    "@next/eslint-plugin-next": ["fast-glob"],
}
# Ce que npm suggère aujourd'hui n'est pas un correctif de braces (un « downgrade » sans rapport).
FIX = {"name": "@next/eslint-plugin-next", "version": "14.2.35", "isSemVerMajor": True}


def vuln(name: str, via: list[Any], severity: str = "high", fix: Any = FIX) -> dict[str, Any]:
    return {"name": name, "severity": severity, "isDirect": False, "via": via, "effects": [], "range": "*",
            "nodes": [f"node_modules/{name}"], "fixAvailable": fix}


def comptes(vulns: dict[str, Any]) -> dict[str, int]:
    c = {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0}
    for v in vulns.values():
        c[v["severity"]] += 1
    return {**c, "total": len(vulns)}


def audit(vulns: dict[str, Any]) -> dict[str, Any]:
    return {"auditReportVersion": 2, "vulnerabilities": vulns, "metadata": {"vulnerabilities": comptes(vulns)}}


def baseline() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    full = audit({nom: vuln(nom, via) for nom, via in CHAINES.items()})
    paquets: dict[str, Any] = {"": {"name": "my-app"}, "node_modules/next": {"version": "16.3.8"}}
    for nom in CHAINES:
        paquets[f"node_modules/{nom}"] = {"version": "1.0.0", "dev": True}
    paquets["node_modules/@next/eslint-plugin-next/node_modules/fast-glob"] = {"version": "3.3.1", "dev": True}
    return full, audit({}), {"lockfileVersion": 3, "packages": paquets}


def evaluer(full: Any, prod: Any, lock: Any, now: datetime = AVANT_ECHEANCE) -> list[str]:
    return policy.evaluate(full, prod, lock, now)


# ── PASS : exactement l'exception connue ──────────────────────────────────────────────


def test_pass_uniquement_l_avis_connu_en_developpement_avant_l_echeance() -> None:
    assert evaluer(*baseline()) == []


def test_pass_a_la_seconde_exacte_de_l_echeance() -> None:
    assert evaluer(*baseline(), now=policy.EXPIRES_AT) == []


def test_l_echeance_est_le_17_octobre_2026_23h59m59_utc() -> None:
    assert policy.EXPIRES_AT == datetime(2026, 10, 17, 23, 59, 59, tzinfo=UTC)


# ── FAIL : chaque écart, nommé ───────────────────────────────────────────────────────


def mutate(f: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]) -> list[str]:
    full, prod, lock = copy.deepcopy(baseline())
    f(full, prod, lock)
    return evaluer(full, prod, lock)


def ajouter(nom: str, v: dict[str, Any]) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]:
    def _(full: dict[str, Any], _p: dict[str, Any], lock: dict[str, Any]) -> None:
        full["vulnerabilities"][nom] = v
        full["metadata"]["vulnerabilities"] = comptes(full["vulnerabilities"])
        lock["packages"][f"node_modules/{nom}"] = {"dev": True}
    return _


def test_fail_apres_l_echeance() -> None:
    erreurs = evaluer(*baseline(), now=policy.EXPIRES_AT + timedelta(seconds=1))
    assert any("expirée" in e for e in erreurs)


def test_fail_meme_avis_mais_braces_dans_l_arbre_de_production() -> None:
    erreurs = mutate(lambda _f, _p, lock: lock["packages"]["node_modules/braces"].pop("dev"))
    assert any("n'est pas marqué dev:true" in e for e in erreurs)


def test_fail_braces_vulnerable_dans_l_audit_de_production() -> None:
    erreurs = mutate(lambda _f, prod, _l: prod.update(audit({"braces": vuln("braces", [AVIS])})))
    assert any("audit de production non propre" in e for e in erreurs)


def test_fail_audit_de_production_rouge_pour_une_autre_raison() -> None:
    autre = vuln("lodash", [{"source": 1, "name": "lodash", "severity": "low", "url": "u", "range": "<4"}], "low")
    erreurs = mutate(lambda _f, prod, _l: prod.update(audit({"lodash": autre})))
    assert any("audit de production non propre" in e for e in erreurs)


def test_fail_un_autre_avis_high_est_ajoute() -> None:
    autre = vuln("left-pad", [{"source": 999, "name": "left-pad", "severity": "high", "url": "u", "range": "*"}])
    erreurs = mutate(ajouter("left-pad", autre))
    assert any("left-pad ne remonte pas exclusivement" in e for e in erreurs)
    assert any("population tolérée modifiée" in e for e in erreurs)


def test_fail_une_vulnerabilite_critique_est_ajoutee() -> None:
    critique = vuln("evil", [{"source": 5, "name": "evil", "severity": "critical", "url": "u", "range": "*"}],
                    "critical")
    erreurs = mutate(ajouter("evil", critique))
    assert any("critique" in e or "critical" in e for e in erreurs)


@pytest.mark.parametrize("severite", ["moderate", "low", "critical"])
def test_fail_meme_racine_et_meme_population_mais_severite_differente(severite: str) -> None:
    """Seul le contrôle de sévérité peut refuser ce cas : la racine causale et la population sont exactes."""
    def changer(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        full["vulnerabilities"]["tailwindcss-animate"]["severity"] = severite
        full["metadata"]["vulnerabilities"] = comptes(full["vulnerabilities"])
    assert any("sévérité" in e for e in mutate(changer))


def test_fail_le_compteur_critique_est_non_nul_meme_si_toutes_les_entrees_sont_high() -> None:
    """Seul le contrôle du compteur critique peut refuser ce cas (métadonnées incohérentes d'un npm modifié)."""
    def changer(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        full["metadata"]["vulnerabilities"]["critical"] = 1
    assert any("critique" in e for e in mutate(changer))


def test_fail_l_avis_est_absent_mais_l_audit_est_rouge() -> None:
    def retirer(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        full["vulnerabilities"]["braces"]["via"] = ["autre"]
    erreurs = mutate(retirer)
    assert any("est absent de braces" in e for e in erreurs)


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [("source", 7777777), ("url", "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"), ("range", "<=3.0.4"),
     ("severity", "critical"), ("name", "micromatch")],
)
def test_fail_un_avis_different_sur_braces(champ: str, valeur: Any) -> None:
    def changer(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        full["vulnerabilities"]["braces"]["via"][0][champ] = valeur
    assert mutate(changer)  # jamais accepté


def test_fail_un_paquet_de_plus_depend_de_braces_meme_avec_la_meme_racine() -> None:
    """Élargir silencieusement la population tolérée est un refus."""
    erreurs = mutate(ajouter("postcss-nested", vuln("postcss-nested", ["micromatch"])))
    assert any("population tolérée modifiée" in e and "postcss-nested" in e for e in erreurs)


def test_fail_une_vulnerabilite_moderee_s_ajoute() -> None:
    erreurs = mutate(ajouter("fast-uri", vuln("fast-uri", [{"source": 4, "name": "fast-uri", "severity": "moderate",
                                                             "url": "u", "range": "*"}], "moderate")))
    assert any("fast-uri" in e for e in erreurs)


def test_fail_la_population_tolérée_perd_un_paquet() -> None:
    def retirer(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        del full["vulnerabilities"]["tailwindcss-animate"]
        full["metadata"]["vulnerabilities"] = comptes(full["vulnerabilities"])
    assert any("population tolérée modifiée" in e for e in mutate(retirer))


@pytest.mark.parametrize("fix", [True, {"name": "braces", "version": "3.0.4", "isSemVerMajor": False}])
def test_fail_un_correctif_devient_disponible(fix: Any) -> None:
    def corriger(full: dict[str, Any], _p: dict[str, Any], _l: dict[str, Any]) -> None:
        full["vulnerabilities"]["braces"]["fixAvailable"] = fix
    assert any("correctif" in e and "supprimer l'exception" in e for e in mutate(corriger))


def test_fail_l_audit_complet_est_propre_l_exception_est_obsolete() -> None:
    erreurs = evaluer(audit({}), audit({}), baseline()[2])
    assert any("obsolète" in e for e in erreurs)


def test_fail_un_paquet_de_l_exception_absent_du_lockfile() -> None:
    def retirer(_f: dict[str, Any], _p: dict[str, Any], lock: dict[str, Any]) -> None:
        del lock["packages"]["node_modules/micromatch"]
    assert any("absent du lockfile" in e for e in mutate(retirer))


@pytest.mark.parametrize("mauvais", [[], None, "texte", 3, {"packages": None}, {}])
def test_fail_entrees_malformees(mauvais: Any) -> None:
    full, prod, lock = baseline()
    assert evaluer(mauvais, prod, lock)
    assert evaluer(full, mauvais, lock)
    assert evaluer(full, prod, mauvais)


# ── CLI : JSON malformé, verdict, aucun contournement ─────────────────────────────────


def ecrire(tmp: Path, nom: str, contenu: Any) -> Path:
    chemin = tmp / nom
    chemin.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu), encoding="utf-8")
    return chemin


def cli(tmp: Path, full: Any, prod: Any, lock: Any, now: str = "2026-10-03T12:00:00Z") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--full-json", str(ecrire(tmp, "full.json", full)),
         "--prod-json", str(ecrire(tmp, "prod.json", prod)), "--lockfile", str(ecrire(tmp, "lock.json", lock)),
         "--now", now],
        capture_output=True, text=True, check=False)


def test_cli_pass_avec_le_verdict_explicite(tmp_path: Path) -> None:
    resultat = cli(tmp_path, *baseline())
    assert resultat.returncode == 0
    assert resultat.stdout.startswith("COCKPIT_AUDIT_POLICY=PASS_WITH_EXACT_TEMPORARY_EXCEPTION ")
    assert "GHSA-vfj7-8cjw-p6xm" in resultat.stdout and "CVE-2026-93687" in resultat.stdout


def test_cli_refus_apres_l_echeance(tmp_path: Path) -> None:
    resultat = cli(tmp_path, *baseline(), now="2026-10-18T00:00:00Z")
    assert resultat.returncode == 1 and "COCKPIT_AUDIT_POLICY=REFUSED" in resultat.stderr
    assert "expirée" in resultat.stderr


@pytest.mark.parametrize("quel", ["full", "prod", "lock"])
def test_cli_json_malforme_refuse(tmp_path: Path, quel: str) -> None:
    full, prod, lock = baseline()
    entrees = {"full": full, "prod": prod, "lock": lock}
    entrees[quel] = "{pas du json"
    resultat = cli(tmp_path, entrees["full"], entrees["prod"], entrees["lock"])
    assert resultat.returncode != 0 and "COCKPIT_AUDIT_POLICY=PASS" not in resultat.stdout
    assert "INPUT_ERROR" in (resultat.stderr + resultat.stdout)


# ── câblage : aucun contournement de la CI ────────────────────────────────────────────


def job_cockpit() -> str:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    return ci.split("  cockpit:\n", 1)[1].split("\n  repository-controls:", 1)[0]


def test_la_ci_utilise_la_politique_et_garde_l_audit_de_production_strict() -> None:
    job = job_cockpit()
    assert "run: python3 ../../scripts/ci/cockpit_audit_policy.py" in job
    assert "run: npm audit --omit=dev\n" in job  # plus strict que --audit-level=high : toutes sévérités
    assert job.index("npm run build") < job.index("cockpit_audit_policy.py") < job.index("npm audit --omit=dev")


def run_cockpit_local() -> str:
    texte = (ROOT / "scripts/ci-local.sh").read_text(encoding="utf-8")
    return texte.split("run_cockpit() {", 1)[1].split("\n}\n", 1)[0]


def test_aucun_contournement_dans_le_job_cockpit_ni_dans_la_ci_locale() -> None:
    for source in (job_cockpit(), run_cockpit_local()):
        for interdit in ("|| true", "continue-on-error", "--audit-level=critical", "--audit-level=moderate",
                         "npm audit --omit=dev ||", "audit signatures"):
            assert interdit not in source, interdit
    assert not re.search(r"^\s*(run: )?npm audit\s*$", job_cockpit(), re.M)  # l'appel nu est remplacé
    assert not re.search(r"^\s*npm audit\s*$", run_cockpit_local(), re.M)


def test_la_ci_locale_exerce_la_meme_politique() -> None:
    fonction = run_cockpit_local()
    assert '"$REPO_ROOT/services/rag-pedago/.venv/bin/python" "$REPO_ROOT/scripts/ci/cockpit_audit_policy.py"' in fonction
    assert "npm audit --omit=dev" in fonction
