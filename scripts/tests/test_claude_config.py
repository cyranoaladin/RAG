"""Épreuves de la configuration Claude Code du dépôt.

La configuration agentique est du code : un hook absent laisse passer une
action, un skill dangereux auto-invocable peut être lancé sans humain, une
règle dont les chemins ne correspondent à rien ne se charge jamais. Ces
épreuves portent d'abord sur les refus : ce que le garde doit bloquer ou
soumettre à confirmation, et son comportement quand il est lui-même en erreur.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2]
CLAUDE_DIR = RACINE / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
GUARD = RACINE / "scripts/claude/pretool-guard.py"
SESSION = RACINE / "scripts/claude/session-context.sh"
POST_EDIT = RACINE / "scripts/claude/post-edit-check.sh"
STOP = RACINE / "scripts/claude/stop-check.sh"

MANUAL_ONLY_SKILLS = {"staging-operation", "production-deploy", "incident-response"}
BUILTIN_COMMANDS = {
    "status", "model", "effort", "context", "compact", "plan", "diff", "agents", "skills",
    "hooks", "permissions", "code-review", "security-review", "insights",
    "fewer-permission-prompts", "doctor", "review", "memory", "config",
}
BUILTIN_AGENTS = {"Plan", "Explore", "general-purpose"}


def _config_files() -> list[Path]:
    fichiers = [RACINE / "CLAUDE.md", RACINE / "AGENTS.md", SETTINGS]
    fichiers += sorted(CLAUDE_DIR.glob("rules/*.md"))
    fichiers += sorted(CLAUDE_DIR.glob("skills/*/SKILL.md"))
    fichiers += sorted(CLAUDE_DIR.glob("agents/*.md"))
    fichiers += sorted(p for p in (RACINE / "scripts/claude").iterdir() if p.is_file())
    fichiers += sorted((RACINE / "docs/agentic").glob("*.md"))
    fichiers += sorted(RACINE.glob("services/*/CLAUDE.md"))
    return fichiers


def _frontmatter(path: Path) -> tuple[dict, str]:
    texte = path.read_text(encoding="utf-8")
    assert texte.startswith("---\n"), f"{path} : frontmatter absent"
    _, brut, corps = texte.split("---\n", 2)
    donnees = yaml.safe_load(brut)
    assert isinstance(donnees, dict), f"{path} : frontmatter non objet"
    return donnees, corps


def _settings() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _tracked_files() -> list[str]:
    sortie = subprocess.run(
        ["git", "-C", str(RACINE), "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return sortie.splitlines()


def _glob_regex(motif: str) -> re.Pattern[str]:
    morceaux = []
    i = 0
    while i < len(motif):
        if motif.startswith("**/", i):
            morceaux.append("(?:.*/)?")
            i += 3
        elif motif.startswith("**", i):
            morceaux.append(".*")
            i += 2
        elif motif[i] == "*":
            morceaux.append("[^/]*")
            i += 1
        elif motif[i] == "?":
            morceaux.append("[^/]")
            i += 1
        else:
            morceaux.append(re.escape(motif[i]))
            i += 1
    return re.compile("^" + "".join(morceaux) + "$")


# --------------------------------------------------------------------------
# Mémoire : CLAUDE.md, AGENTS.md
# --------------------------------------------------------------------------

def test_claude_md_est_un_adaptateur_court_qui_importe_agents_md() -> None:
    lignes = (RACINE / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "@AGENTS.md"
    assert (RACINE / "AGENTS.md").is_file()
    assert len(lignes) <= 120, "CLAUDE.md doit rester un adaptateur, pas un manuel"


def test_agents_md_reste_sous_la_limite_recommandee() -> None:
    lignes = (RACINE / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    assert len(lignes) <= 200


def test_chaque_agents_md_de_service_est_importe_pour_claude() -> None:
    # Avec un CLAUDE.md racine, Claude Code ne lit pas les AGENTS.md des
    # sous-répertoires : sans cet import, leurs règles lui sont invisibles.
    for agents in RACINE.glob("services/*/AGENTS.md"):
        claude = agents.with_name("CLAUDE.md")
        assert claude.is_file(), f"{claude} absent"
        assert "@AGENTS.md" in claude.read_text(encoding="utf-8").splitlines()


def test_pas_de_faux_fichier_de_configuration_racine() -> None:
    for nom in ("RULES.md", "SKILLS.md"):
        assert not (RACINE / nom).exists(), f"{nom} n'est pas lu par Claude Code"


# --------------------------------------------------------------------------
# settings.json
# --------------------------------------------------------------------------

def test_settings_laisse_le_choix_du_mode_sans_l_imposer() -> None:
    """Le propriétaire peut choisir bypass au lancement ; le dépôt ne
    l'interdit plus, mais ne l'impose à personne (aucun mode par défaut sans
    garde) et ne désactive aucun hook."""
    reglages = _settings()
    permissions = reglages["permissions"]
    assert "disableBypassPermissionsMode" not in permissions
    assert permissions.get("defaultMode") not in {"bypassPermissions", "dontAsk", "auto"}
    assert "bypassPermissions" not in SETTINGS.read_text(encoding="utf-8")
    assert reglages.get("disableAllHooks") is not True
    assert permissions["deny"] and permissions["ask"]


def test_settings_refuse_la_lecture_des_secrets() -> None:
    refus = set(_settings()["permissions"]["deny"])
    for regle in ("Read(.env)", "Read(.env.*)", "Read(*.pem)", "Read(*.key)", "Read(*.seed)",
                  "Read(~/.ssh/**)"):
        assert regle in refus, f"règle de refus manquante : {regle}"


def test_settings_demande_confirmation_pour_les_mutations_externes() -> None:
    demandes = set(_settings()["permissions"]["ask"])
    for regle in ("Bash(git push *)", "Bash(gh pr merge *)", "Bash(gh pr close *)",
                  "Bash(ssh *)", "Bash(psql *)"):
        assert regle in demandes, f"règle ask manquante : {regle}"
    autorisees = _settings()["permissions"]["allow"]
    for regle in autorisees:
        assert not re.search(r"\b(push|merge|close|ssh|psql|rm|reset|clean)\b(?!-)", regle), regle


def test_limites_de_sous_agents_prudentes() -> None:
    env = _settings()["env"]
    assert int(env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"]) == 1
    assert 1 <= int(env["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"]) <= 3
    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in env


def test_hooks_pointent_vers_des_scripts_executables_du_depot() -> None:
    hooks = _settings()["hooks"]
    assert set(hooks) == {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
    for groupes in hooks.values():
        for groupe in groupes:
            for hook in groupe["hooks"]:
                commande = hook["command"]
                m = re.fullmatch(r'"\$\{CLAUDE_PROJECT_DIR\}"/(scripts/claude/[\w.-]+)', commande)
                assert m, f"commande de hook inattendue : {commande}"
                script = RACINE / m.group(1)
                assert script.is_file() and os.access(script, os.X_OK), f"{script} non exécutable"
                assert hook.get("timeout", 600) <= 30
    pre = hooks["PreToolUse"][0]["matcher"].split("|")
    assert {"Bash", "Read", "Write", "Edit"} <= set(pre)


def test_outils_des_hooks_disponibles() -> None:
    # Un hook qui ne peut pas démarrer (127) laisse passer l'action.
    for outil in ("python3", "jq", "git"):
        assert shutil.which(outil), f"{outil} requis par les hooks"


# --------------------------------------------------------------------------
# Rules, skills, agents
# --------------------------------------------------------------------------

def test_rules_ont_des_chemins_qui_correspondent_au_depot() -> None:
    suivis = _tracked_files()
    regles = sorted(CLAUDE_DIR.glob("rules/*.md"))
    assert regles
    for regle in regles:
        donnees, corps = _frontmatter(regle)
        assert set(donnees) == {"paths"}, f"{regle} : seul `paths` est lu"
        assert donnees["paths"], f"{regle} : liste de chemins vide"
        for motif in donnees["paths"]:
            regex = _glob_regex(motif)
            assert any(regex.match(f) for f in suivis), f"{regle.name} : {motif} ne correspond à rien"
        assert len(corps.splitlines()) <= 60, f"{regle} trop longue pour une règle"


def test_skills_valides_et_dangereux_manuels() -> None:
    skills = {p.parent.name: p for p in CLAUDE_DIR.glob("skills/*/SKILL.md")}
    assert MANUAL_ONLY_SKILLS <= set(skills)
    for nom, chemin in skills.items():
        donnees, corps = _frontmatter(chemin)
        assert donnees.get("name") == nom
        assert 40 <= len(donnees.get("description", "")) <= 1536
        dangereux = nom in MANUAL_ONLY_SKILLS or re.search(
            r"\b(deploy|déploi|staging-operation|production)\b", nom)
        if dangereux:
            assert donnees.get("disable-model-invocation") is True, f"{nom} doit être manuel"
        assert "## Sortie" in corps, f"{nom} : sortie structurée absente"


def test_agents_sont_en_lecture_seule() -> None:
    agents = sorted(CLAUDE_DIR.glob("agents/*.md"))
    assert agents
    for agent in agents:
        donnees, _ = _frontmatter(agent)
        assert donnees.get("name") == agent.stem
        outils = {o.strip() for o in str(donnees.get("tools", "")).split(",")}
        interdits = {o.strip() for o in str(donnees.get("disallowedTools", "")).split(",")}
        assert outils and not ({"Write", "Edit", "NotebookEdit"} & outils)
        assert {"Write", "Edit", "NotebookEdit", "Agent"} <= interdits
        assert donnees.get("permissionMode") not in {"bypassPermissions", "acceptEdits", "dontAsk"}


def test_references_aux_skills_et_agents_existent() -> None:
    skills = {p.parent.name for p in CLAUDE_DIR.glob("skills/*/SKILL.md")}
    agents = {p.stem for p in CLAUDE_DIR.glob("agents/*.md")} | BUILTIN_AGENTS
    textes = [RACINE / "CLAUDE.md", *CLAUDE_DIR.glob("skills/*/SKILL.md"),
              *CLAUDE_DIR.glob("rules/*.md"), RACINE / "docs/agentic/CLAUDE_CONFIGURATION.md",
              RACINE / "docs/agentic/OPERATING_MODEL.md"]
    for chemin in textes:
        texte = chemin.read_text(encoding="utf-8")
        for nom in re.findall(r"`/([a-z][a-z-]+)`", texte):
            assert nom in skills | BUILTIN_COMMANDS, f"{chemin.name} : /{nom} inconnu"
        for nom in re.findall(r"agent `([A-Za-z-]+)`", texte):
            assert nom in agents, f"{chemin.name} : agent {nom} inconnu"


def test_pas_de_duplication_flagrante_avec_agents_md() -> None:
    agents = {ligne.strip() for ligne in (RACINE / "AGENTS.md").read_text(encoding="utf-8").splitlines()
              if len(ligne.strip()) > 60}
    for chemin in [RACINE / "CLAUDE.md", *CLAUDE_DIR.glob("rules/*.md")]:
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            assert ligne.strip() not in agents, f"{chemin.name} recopie AGENTS.md : {ligne.strip()[:60]}"


# --------------------------------------------------------------------------
# Hygiène : chemins, secrets, ignorés
# --------------------------------------------------------------------------

def test_aucun_chemin_absolu_personnel_ni_secret_dans_la_configuration() -> None:
    secret = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|github_pat_\w{30,}"
        r"|sk-ant-[\w-]{20,}|AKIA[0-9A-Z]{16}|postgres(ql)?://[^:@/\s]+:[^@$<{\s]{6,}@"
    )
    for chemin in _config_files():
        texte = chemin.read_text(encoding="utf-8")
        assert not re.search(r"/home/[a-z][\w-]*/|/Users/[A-Za-z]", texte), f"{chemin} : chemin absolu"
        assert not secret.search(texte), f"{chemin} : secret probable"


def test_fichiers_de_configuration_non_ignores_et_etat_local_ignore() -> None:
    for chemin in _config_files():
        rel = chemin.relative_to(RACINE)
        ignore = subprocess.run(["git", "-C", str(RACINE), "check-ignore", "-q", str(rel)])
        assert ignore.returncode == 1, f"{rel} est ignoré par Git"
    for rel in (".claude/settings.local.json", ".claude/worktrees/x", "CLAUDE.local.md"):
        ignore = subprocess.run(["git", "-C", str(RACINE), "check-ignore", "-q", rel])
        assert ignore.returncode == 0, f"{rel} devrait être ignoré"


def test_worktreeinclude_et_mcp_restent_sans_secret() -> None:
    inclusion = RACINE / ".worktreeinclude"
    if inclusion.exists():
        for ligne in inclusion.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"\.env|\.key|\.pem|seed|token|credential|dump|backup|settings\.local",
                                 ligne, re.I), ligne
    mcp = RACINE / ".mcp.json"
    if mcp.exists():
        assert not re.search(r"(token|secret|password|key)\"\s*:\s*\"[^$]", mcp.read_text(), re.I)


# --------------------------------------------------------------------------
# Garde PreToolUse : refus d'abord
# --------------------------------------------------------------------------

@pytest.fixture()
def depots(tmp_path: Path) -> dict[str, Path]:
    def init(chemin: Path, branche: str) -> Path:
        chemin.mkdir()
        subprocess.run(["git", "init", "-q", "-b", branche, str(chemin)], check=True)
        return chemin
    return {"main": init(tmp_path / "sur-main", "main"), "lot": init(tmp_path / "sur-lot", "go-live/x")}


def _garde(payload: object) -> dict | None:
    entree = payload if isinstance(payload, str) else json.dumps(payload)
    res = subprocess.run([str(GUARD)], input=entree, capture_output=True, text=True, timeout=20)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)["hookSpecificOutput"] if res.stdout.strip() else None


def _bash(commande: str, cwd: Path) -> str | None:
    sortie = _garde({"tool_name": "Bash", "tool_input": {"command": commande}, "cwd": str(cwd)})
    return sortie["permissionDecision"] if sortie else None


@pytest.mark.parametrize("commande", [
    "git push --force origin go-live/x",
    "git push -f",
    "git push origin +go-live/x",
    "git push origin HEAD:main",
    "gh pr review 270 --approve",
    "cat services/rag-engine/infra/.env",
    "head -5 ~/.ssh/id_ed25519",
    "grep x /tmp/rehearsal/nexus-rehearsal-readiness.seed",
    "rm -rf /",
    "rm -rf ~",
    "cd /tmp && rm -rf ..",
])
def test_garde_refuse(commande: str, depots: dict[str, Path]) -> None:
    assert _bash(commande, depots["lot"]) == "deny"


@pytest.mark.parametrize("commande", [
    "git push origin go-live/x",
    "gh pr merge 262 --squash",
    "gh pr close 270",
    "gh pr ready 270",
    "gh api -X PUT repos/o/r/pulls/1/merge",
    "gh api repos/o/r/issues/1/comments -f body=x",
    "ssh -o BatchMode=yes nexus-prod-direct 'docker ps'",
    "scp a nexus-staging:/tmp/",
    "rsync -a x nexus-prod:/srv/",
    "psql -h db.example.org -U rag ragdb",
    "psql postgresql://rag@10.0.0.5/ragdb",
    "psql \"$STAGING_DSN\"",
    "git reset --hard origin/main",
    "git clean -fdx",
    "rm -rf \"$WORK\"/*",
    "rm -rf /srv/nexus/releases/old",
    "ln -sfn /srv/releases/v5 /srv/releases/current",
    "docker system prune -af",
    "docker -H ssh://nexus-prod build .",
    "printenv",
    "git worktree remove .worktrees/lot-cv-b",
    "git stash pop",
])
def test_garde_demande_confirmation(commande: str, depots: dict[str, Path]) -> None:
    assert _bash(commande, depots["lot"]) == "ask"


@pytest.mark.parametrize("commande", [
    "git status --short",
    "git diff origin/main...HEAD",
    "git log --oneline -5",
    "gh pr view 270 --json state",
    "gh api repos/o/r/pulls/270",
    "make test",
    "python3 -m pytest -q scripts/tests/",
    "rm -rf .venv build",
    "rm -rf /tmp/ci-local-contracts-venv",
    "cat services/rag-engine/infra/.env.example",
    "psql -h localhost -U rag ragdb_test",
    "ssh -T git@github.com",
    "docker compose -f docker-compose.v2.yml ps",
    "git commit -m 'docs: x (lot CU)'",
])
def test_garde_laisse_passer_le_travail_local(commande: str, depots: dict[str, Path]) -> None:
    assert _bash(commande, depots["lot"]) is None


def test_garde_refuse_commit_et_ecriture_sur_main(depots: dict[str, Path]) -> None:
    assert _bash("git commit -m x", depots["main"]) == "deny"
    assert _bash("git push", depots["main"]) == "deny"
    ecriture = _garde({"tool_name": "Write", "cwd": str(depots["main"]),
                       "tool_input": {"file_path": str(depots["main"] / "a.py"), "content": ""}})
    assert ecriture and ecriture["permissionDecision"] == "deny"
    permis = _garde({"tool_name": "Edit", "cwd": str(depots["lot"]),
                     "tool_input": {"file_path": str(depots["lot"] / "a.py")}})
    assert permis is None


def test_garde_refuse_lecture_de_secret_par_outil(depots: dict[str, Path]) -> None:
    for chemin in (".env", "infra/.env.production", "certs/server.key", "creds/token.json"):
        sortie = _garde({"tool_name": "Read", "cwd": str(depots["lot"]),
                         "tool_input": {"file_path": str(depots["lot"] / chemin)}})
        assert sortie and sortie["permissionDecision"] == "deny", chemin
    exemple = _garde({"tool_name": "Read", "cwd": str(depots["lot"]),
                      "tool_input": {"file_path": str(depots["lot"] / ".env.example")}})
    assert exemple is None


def test_garde_demande_confirmation_pour_un_autre_worktree(tmp_path: Path) -> None:
    principal = tmp_path / "depot"
    subprocess.run(["git", "init", "-q", "-b", "go-live/a", str(principal)], check=True)
    subprocess.run(["git", "-C", str(principal), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    autre = tmp_path / "autre-lot"
    subprocess.run(["git", "-C", str(principal), "worktree", "add", "-q", "-b", "go-live/b",
                    str(autre)], check=True)
    sortie = _garde({"tool_name": "Edit", "cwd": str(principal),
                     "tool_input": {"file_path": str(autre / "x.py")}})
    assert sortie and sortie["permissionDecision"] == "ask"


@pytest.mark.parametrize("entree", ["", "pas du json", "[1, 2]", '{"tool_name": "Bash", "tool_input": 3}'])
def test_garde_echoue_ferme(entree: str) -> None:
    sortie = _garde(entree)
    assert sortie and sortie["permissionDecision"] == "deny"


def test_garde_n_affiche_aucun_contenu(depots: dict[str, Path]) -> None:
    sortie = _garde({"tool_name": "Bash", "cwd": str(depots["lot"]),
                     "tool_input": {"command": "cat .env # SECRET=abc123"}})
    assert sortie and "abc123" not in sortie["permissionDecisionReason"]


# --------------------------------------------------------------------------
# Autres hooks
# --------------------------------------------------------------------------

def _run(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script)], input=json.dumps(payload), capture_output=True,
                          text=True, timeout=40)


def test_session_context_decrit_le_worktree_sans_bloquer(depots: dict[str, Path]) -> None:
    res = _run(SESSION, {"cwd": str(depots["main"]), "source": "startup"})
    assert res.returncode == 0
    assert "branche : main" in res.stdout and "branche protégée" in res.stdout
    assert "LOCAL" in res.stdout, "origin/main doit être présenté comme état du dernier fetch"


def test_post_edit_signale_json_et_python_invalides(tmp_path: Path) -> None:
    mauvais = tmp_path / "x.json"
    mauvais.write_text("{", encoding="utf-8")
    assert _run(POST_EDIT, {"tool_input": {"file_path": str(mauvais)}, "cwd": str(tmp_path)}).returncode == 2
    py = tmp_path / "x.py"
    py.write_text("def f(:\n", encoding="utf-8")
    assert _run(POST_EDIT, {"tool_input": {"file_path": str(py)}, "cwd": str(tmp_path)}).returncode == 2
    bon = tmp_path / "ok.json"
    bon.write_text("{}", encoding="utf-8")
    assert _run(POST_EDIT, {"tool_input": {"file_path": str(bon)}, "cwd": str(tmp_path)}).returncode == 0


def test_stop_bloque_un_secret_sans_l_afficher(depots: dict[str, Path]) -> None:
    fuite = depots["lot"] / "notes.txt"
    valeur = "ghp_" + "A" * 36
    fuite.write_text(f"token={valeur}\n", encoding="utf-8")
    res = _run(STOP, {"cwd": str(depots["lot"]), "stop_hook_active": False})
    assert res.returncode == 2 and "notes.txt" in res.stderr and valeur not in res.stderr
    assert _run(STOP, {"cwd": str(depots["lot"]), "stop_hook_active": True}).returncode == 0
    fuite.unlink()
    (depots["lot"] / "dump.sql.gz").write_bytes(b"x")
    assert _run(STOP, {"cwd": str(depots["lot"]), "stop_hook_active": False}).returncode == 2


# --------------------------------------------------------------------------
# Revue #272 : préfixes, gh, motifs, cas du projet, pannes du garde
# --------------------------------------------------------------------------

WRAPPER = RACINE / "scripts/claude/pretool-guard.sh"


@pytest.fixture()
def bac(tmp_path: Path) -> Path:
    """Bac à sable jetable : secrets SYNTHÉTIQUES, lien symbolique, arbre imbriqué."""
    racine = tmp_path / "bac"
    (racine / "nested/deep").mkdir(parents=True)
    (racine / "nested/keys").mkdir(parents=True)
    (racine / "docs").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "lot/x", str(racine)], check=True)
    (racine / ".env.production").write_text("SYNTHETIC=1\n", encoding="utf-8")
    (racine / ".env.example").write_text("EXAMPLE=1\n", encoding="utf-8")
    (racine / "nested/deep/.env.local").write_text("SYNTHETIC=1\n", encoding="utf-8")
    (racine / "nested/keys/rehearsal-readiness-ed25519.seed.hex").write_text("00\n", encoding="utf-8")
    (racine / "docs/notes.md").write_text("public\n", encoding="utf-8")
    (racine / "innocent-link.txt").symlink_to(".env.production")
    return racine


@pytest.mark.parametrize("commande, attendu", [
    # A — préfixes : options consommées, commande enveloppée classée
    ("sudo -u postgres psql -c 'select 1'", "ask"),
    ("sudo -nu postgres psql", "ask"),
    ("sudo --user=postgres -- psql", "ask"),
    ("env -u HOME psql -h db.invalid", "ask"),
    ("env -i PATH=/usr/bin psql -h db.invalid", "ask"),
    ("command -- psql -h db.invalid", "ask"),
    ("command -p ssh nexus-prod.invalid", "ask"),
    ("env -u X timeout -s KILL 5 nice -n 5 gh pr merge 1", "ask"),
    ("sudo -E env -u X cat .env.production", "deny"),
    ("sudo --option-inconnue ls", "ask"),
    ("env -S 'ls -l'", "ask"),
    ("env --split-string='ls -l'", "ask"),
    ("env", "ask"),
    ("bash -c 'gh -R o/r pr merge 1'", "ask"),
    ("eval \"$CMD\"", "ask"),
    ("command -v psql", None),
    ("timeout 30 make test", None),
    ("nice -n 5 python3 -m pytest -q", None),
    # B — gh : options héritées normalisées avant la sous-commande
    ("gh -R example-invalid/none pr merge 1", "ask"),
    ("gh --repo example-invalid/none pr close 1", "ask"),
    ("gh --repo=example-invalid/none pr ready 1", "ask"),
    ("gh -Rexample-invalid/none pr merge 1", "ask"),
    ("gh pr -R example-invalid/none merge 1", "ask"),
    ("gh -R o/r pr review 1 --approve", "deny"),
    ("gh pr review 1 -a", "deny"),
    ("gh api repos/o/r/pulls/1/reviews -f event=APPROVE", "deny"),
    ("gh api -XPUT repos/o/r/pulls/1/merge", "ask"),
    ("gh auth token", "deny"),
    ("gh auth status --show-token", "deny"),
    ("gh --flag-inconnu pr view 1", "ask"),
    ("gh mon-alias 1", "ask"),
    ("gh -R o/r pr view 1 --json state,mergeable", None),
    ("gh pr list --search review:required", None),
    ("gh run view 123 --log", None),
    ("gh api repos/o/r/pulls/1", None),
    ("gh auth status", None),
    # C — motifs et lectures sensibles, sans expansion par un shell
    ("cat .env*", "deny"),
    ("head -n 2 .env.*", "deny"),
    ("tail -5 .env{,.production}", "deny"),
    ("less *.env", "deny"),
    ("cat nested/deep/.env.local", "deny"),
    ("cat nested/keys/*.seed.hex", "deny"),
    ("cat nested/keys/rehearsal-readiness-ed25519.seed.hex", "deny"),
    ("xxd nested/keys/rehearsal-readiness-ed25519.seed.hex", "deny"),
    ("cat innocent-link.txt", "deny"),
    ("grep -rn SYNTHETIC nested", "deny"),
    ("grep -r SYNTHETIC .", "deny"),
    ("find . -name '*.md' -exec cat {} +", "deny"),
    ("ls | xargs cat", "ask"),
    ("cat < .env.production", "deny"),
    ("diff <(cat .env.production) docs/notes.md", "deny"),
    ("echo \"$(cat .env.production)\"", "deny"),
    ("cat \"$FICHIER\"", "ask"),
    ("echo \"$GITHUB_TOKEN\"", "ask"),
    ("cat /proc/self/environ", "deny"),
    ("cat .env.example", None),
    ("cat docs/*.md", None),
    ("grep -rn public docs", None),
    ("rg SYNTHETIC", None),
    ("git grep -n SYNTHETIC", None),
    ("test -f .env.production && echo présent", None),
    ("grep -n '.env' docs/notes.md", None),
    # Composition : la décision la plus sévère l'emporte
    ("ssh nexus.invalid true; cat .env.production", "deny"),
    ("gh pr view 1 && gh pr merge 1", "ask"),
])
def test_revue_272_decisions_du_garde(bac: Path, commande: str, attendu: str | None) -> None:
    assert _bash(commande, bac) == attendu


def test_revue_272_message_de_commit_heredoc_sans_friction(bac: Path) -> None:
    commande = (
        "git commit -m \"$(cat <<'EOF'\n"
        "docs: l'état du lot (ssh, rm -rf /, cat .env et gh pr merge dans le texte)\n"
        "\n"
        "Co-Authored-By: x <x@example.invalid>\n"
        "EOF\n"
        ")\""
    )
    assert _bash(commande, bac) is None


def test_revue_272_heredoc_vers_un_shell_est_analyse(bac: Path) -> None:
    assert _bash("bash <<'EOF'\ncat .env.production\nEOF", bac) == "deny"


def test_revue_272_outils_fichiers_liens_et_graines(bac: Path) -> None:
    for outil, chemin in (("Read", "innocent-link.txt"),
                          ("Read", "nested/keys/rehearsal-readiness-ed25519.seed.hex"),
                          ("Edit", "innocent-link.txt"),
                          ("Write", "nested/keys/autre.seed.hex")):
        sortie = _garde({"tool_name": outil, "cwd": str(bac),
                         "tool_input": {"file_path": str(bac / chemin)}})
        assert sortie and sortie["permissionDecision"] == "deny", (outil, chemin)


def test_revue_272_le_garde_n_execute_rien(bac: Path, tmp_path: Path) -> None:
    # Des exécutables factices en tête du PATH : s'ils étaient appelés, ils laisseraient une trace.
    faux = tmp_path / "faux-bin"
    faux.mkdir()
    trace = tmp_path / "invocations.log"
    for nom in ("gh", "ssh", "psql", "sudo", "cat"):
        script = faux / nom
        script.write_text(f"#!/bin/sh\necho {nom} >> '{trace}'\n", encoding="utf-8")
        script.chmod(0o755)
    env = dict(os.environ, PATH=f"{faux}{os.pathsep}{os.environ['PATH']}")
    for commande in ("sudo -u postgres psql", "gh -R o/r pr merge 1", "cat .env*", "ssh h.invalid"):
        payload = json.dumps({"tool_name": "Bash", "cwd": str(bac), "tool_input": {"command": commande}})
        subprocess.run([str(WRAPPER)], input=payload, env=env, capture_output=True, text=True,
                       timeout=20, check=True)
    assert not trace.exists()


def _enveloppe(env_extra: dict[str, str]) -> tuple[dict | None, float]:
    import time
    payload = json.dumps({"tool_name": "Bash", "cwd": "/", "tool_input": {"command": "ls"}})
    debut = time.monotonic()
    res = subprocess.run([str(WRAPPER)], input=payload, env=dict(os.environ, **env_extra),
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0
    sortie = json.loads(res.stdout)["hookSpecificOutput"] if res.stdout.strip() else None
    return sortie, time.monotonic() - debut


def test_enveloppe_refuse_si_interpreteur_absent() -> None:
    sortie, _ = _enveloppe({"NEXUS_GUARD_PYTHON": "interpreteur-absent-xyz"})
    assert sortie and sortie["permissionDecision"] == "deny"


def test_enveloppe_refuse_avant_le_delai_de_claude(tmp_path: Path) -> None:
    lent = tmp_path / "python-lent"
    lent.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    lent.chmod(0o755)
    sortie, duree = _enveloppe({"NEXUS_GUARD_PYTHON": str(lent), "NEXUS_GUARD_TIMEOUT": "1"})
    assert sortie and sortie["permissionDecision"] == "deny"
    assert duree < 10


def test_enveloppe_refuse_si_le_garde_plante(tmp_path: Path) -> None:
    casse = tmp_path / "python-casse"
    casse.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    casse.chmod(0o755)
    sortie, _ = _enveloppe({"NEXUS_GUARD_PYTHON": str(casse)})
    assert sortie and sortie["permissionDecision"] == "deny"


def test_enveloppe_laisse_passer_une_commande_sure() -> None:
    sortie, _ = _enveloppe({})
    assert sortie is None


def test_delai_de_l_enveloppe_inferieur_a_celui_du_hook() -> None:
    hook = _settings()["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"].endswith("/scripts/claude/pretool-guard.sh")
    texte = WRAPPER.read_text(encoding="utf-8")
    delai = int(re.search(r"NEXUS_GUARD_TIMEOUT:-(\d+)", texte).group(1))
    assert delai < hook["timeout"]


def test_regles_natives_independantes_du_hook() -> None:
    # Défense qui tient quand le hook manque ou expire (mesuré en session réelle,
    # voir scripts/tests/claude_permissions_integration.py).
    permissions = _settings()["permissions"]
    for regle in ("Bash(sudo *)", "Bash(gh * merge *)", "Bash(gh * close *)", "Bash(gh * review *)",
                  "Bash(gh api * -X *)", "Bash(*.env*)", "Bash(*.seed*)"):
        assert regle in permissions["ask"], regle
    for regle in ("Read(*.seed.hex)", "Edit(*.seed.hex)", "Bash(gh * --approve*)", "Bash(gh auth token*)"):
        assert regle in permissions["deny"], regle
    # La négation ne carve que les règles qui la précèdent dans la même liste.
    refus = permissions["deny"]
    assert refus.index("Read(!.env.example)") > refus.index("Read(.env.*)")
    assert refus.index("Edit(!.env.example)") > refus.index("Edit(.env.*)")
