#!/usr/bin/env python3
"""Garde PreToolUse de Claude Code pour le dépôt Nexus RAG.

Reçoit sur stdin le JSON du hook (``tool_name``, ``tool_input``, ``cwd``) et
rend une décision :

- ``deny`` : action interdite sans exception (écriture sur ``main``, push
  forcé, lecture de secret, auto-approbation de PR, destruction de racine) ;
- ``ask`` : mutation externe ou destructive qui exige une autorisation humaine
  pour cette opération précise (SSH, psql distant, fusion/fermeture de PR,
  push, reset --hard, bascule ``current``…) ;
- rien : la décision revient aux règles de permission.

Claude Code traite un hook qui plante (code ≠ 0 et ≠ 2) comme NON bloquant :
un garde qui lève une exception laisserait passer l'action. Toute erreur
interne est donc convertie en ``deny`` (fail-closed).

Le garde n'imprime jamais le contenu d'un fichier ni la valeur d'une variable :
les raisons citent seulement la règle, pour ne rien exposer dans le transcript.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}

# Fichiers dont la lecture exposerait un secret dans le transcript.
SECRET_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env(\.[^/]*)?$"),
    re.compile(r"\.(pem|key|p12|pfx)$"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"(^|/)\.ssh/"),
    re.compile(r"(^|/)\.pgpass$"),
    re.compile(r"(^|/)\.netrc$"),
    re.compile(r"\.seed$"),
    re.compile(r"(^|/)creds/"),
    re.compile(r"(^|/)\.credentials\.json$"),
    re.compile(r"(^|/)seed-admin/"),
    re.compile(r"(^|/)(hosts\.yml|\.git-credentials)$"),
]
SECRET_PATH_ALLOWED = [re.compile(r"(^|/)\.env\.example$")]

READ_COMMANDS = {
    "cat", "less", "more", "head", "tail", "bat", "grep", "rg", "sed", "awk",
    "cp", "scp", "base64", "xxd", "od", "strings", "source", ".", "tee", "nl",
}


class Decision(Exception):
    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


def deny(reason: str) -> None:
    raise Decision("deny", reason)


def ask(reason: str) -> None:
    raise Decision("ask", reason)


def is_secret_path(path: str) -> bool:
    if any(p.search(path) for p in SECRET_PATH_ALLOWED):
        return False
    return any(p.search(path) for p in SECRET_PATH_PATTERNS)


def git(cwd: str, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def current_branch(cwd: str) -> str | None:
    return git(cwd, "branch", "--show-current")


def existing_dir(path: Path) -> str:
    for candidate in [path, *path.parents]:
        if candidate.is_dir():
            return str(candidate)
    return "/"


# --------------------------------------------------------------------------
# Outils fichiers
# --------------------------------------------------------------------------

def check_file_tool(tool: str, tool_input: dict, cwd: str) -> None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not raw:
        return
    path = Path(raw) if os.path.isabs(raw) else Path(cwd) / raw
    path = Path(os.path.normpath(path))
    if tool in {"Read", "Grep", "Glob"}:
        if is_secret_path(str(path)):
            deny(f"lecture d'un fichier de secret interdite ({tool}) ; "
                 "vérifier sa présence avec `test -f`, jamais son contenu")
        return
    # Write / Edit / NotebookEdit
    if is_secret_path(str(path)):
        deny("écriture d'un fichier de secret interdite")
    parent = existing_dir(path.parent)
    top = git(parent, "rev-parse", "--show-toplevel")
    if top is None:
        return
    branch = current_branch(parent)
    if branch in PROTECTED_BRANCHES:
        deny(f"écriture dans un worktree sur `{branch}` interdite : "
             "créer une branche de lot dans un worktree dédié")
    session_top = git(cwd, "rev-parse", "--show-toplevel")
    if session_top and os.path.realpath(top) != os.path.realpath(session_top):
        same_repo = git(parent, "rev-parse", "--git-common-dir")
        session_repo = git(cwd, "rev-parse", "--git-common-dir")
        if same_repo and session_repo and (
            os.path.realpath(os.path.join(parent, same_repo))
            == os.path.realpath(os.path.join(cwd, session_repo))
        ):
            ask(f"écriture dans un autre worktree ({top}) que celui de la session : "
                "vérifier qu'il n'appartient pas à un lot actif")


# --------------------------------------------------------------------------
# Bash
# --------------------------------------------------------------------------

SEPARATORS = re.compile(r"\|\||&&|;|\||&|\n|\$\(|`|\(|\)")


def segments(command: str) -> list[list[str]]:
    result: list[list[str]] = []
    for part in SEPARATORS.split(command):
        part = part.strip()
        if not part:
            continue
        try:
            words = shlex.split(part, comments=True)
        except ValueError:
            words = part.split()
        # Retirer les affectations d'environnement et les enveloppes courantes.
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])
                         or words[0] in {"sudo", "env", "nohup", "time", "exec", "command"}):
            words = words[1:]
        if words:
            result.append(words)
    return result


def host_of(target: str) -> str:
    target = target.split("@", 1)[-1]
    return target.split(":", 1)[0]


def check_git(words: list[str], cwd: str) -> None:
    args = words[1:]
    # Options globales « git -C <dir> ».
    while args and args[0].startswith("-"):
        if args[0] in {"-C", "-c"} and len(args) > 1:
            if args[0] == "-C":
                cwd = args[1] if os.path.isabs(args[1]) else os.path.join(cwd, args[1])
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return
    sub, rest = args[0], args[1:]
    if sub == "push":
        if any(a in {"-f", "--force", "--mirror"} or a.startswith("--force") and a != "--force-with-lease"
               for a in rest) or any(a.startswith("+") for a in rest):
            deny("git push forcé interdit")
        if any(a == "--force-with-lease" or a.startswith("--force-with-lease=") for a in rest):
            ask("git push --force-with-lease : réécriture d'une branche distante")
        refs = [a for a in rest if not a.startswith("-")]
        if any(a in {"--delete", "-d"} for a in rest) or any(r.startswith(":") for r in refs):
            ask("suppression d'une branche distante")
        for ref in refs[1:]:
            dest = ref.split(":")[-1].removeprefix("refs/heads/")
            if dest in PROTECTED_BRANCHES:
                deny(f"push direct vers `{dest}` interdit : passer par une PR")
        if len(refs) <= 1 and current_branch(cwd) in PROTECTED_BRANCHES:
            deny("push depuis `main` interdit : passer par une PR")
        ask("git push : mutation externe")
    if sub == "commit" and current_branch(cwd) in PROTECTED_BRANCHES:
        deny("commit sur `main` interdit : travailler sur une branche de lot")
    if sub == "reset" and "--hard" in rest:
        ask("git reset --hard : perte possible de travail non commité")
    if sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in rest):
        ask("git clean forcé : suppression de fichiers non suivis")
    if sub == "checkout" and ("--" in rest or "." in rest) or sub == "restore" and "--staged" not in rest and rest:
        ask(f"git {sub} : écrasement de modifications locales")
    if sub == "branch" and any(a in {"-D", "--delete", "-d"} for a in rest):
        ask("suppression de branche locale")
    if sub == "worktree" and rest[:1] == ["remove"]:
        ask("suppression d'un worktree : vérifier qu'il n'appartient pas à un lot actif")
    if sub == "stash" and rest[:1] in (["pop"], ["drop"], ["clear"]):
        ask("la pile de stash est partagée entre worktrees : pop/drop/clear exigent une vérification")


def check_gh(words: list[str]) -> None:
    args = words[1:]
    if args[:2] == ["pr", "review"] and any(a in {"--approve", "-a"} for a in args):
        deny("auto-approbation d'une PR interdite : l'approbation est une décision humaine")
    if args[:1] == ["pr"] and len(args) > 1 and args[1] in {
            "merge", "close", "ready", "reopen", "edit", "create", "comment", "review"}:
        ask(f"gh pr {args[1]} : mutation GitHub, autorisation explicite requise")
    if args[:1] == ["api"]:
        method = None
        for i, a in enumerate(args):
            if a in {"-X", "--method"} and i + 1 < len(args):
                method = args[i + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
        has_fields = any(a in {"-f", "-F", "--field", "--raw-field", "--input"} for a in args)
        if (method and method != "GET") or (method is None and has_fields):
            ask("gh api en écriture : mutation GitHub")
    if args[:1] in (["release"], ["repo"], ["secret"], ["variable"], ["workflow"]) and len(args) > 1 \
            and args[1] in {"create", "delete", "edit", "set", "run", "enable", "disable"}:
        ask(f"gh {args[0]} {args[1]} : mutation GitHub")


def check_rm(words: list[str], cwd: str) -> None:
    flags = "".join(a.lstrip("-") for a in words[1:] if a.startswith("-") and not a.startswith("--"))
    long_flags = {a for a in words[1:] if a.startswith("--")}
    recursive = "r" in flags.lower() or "--recursive" in long_flags
    if not recursive:
        return
    targets = [a for a in words[1:] if not a.startswith("-")]
    home = os.path.expanduser("~")
    for t in targets:
        expanded = os.path.expanduser(t)
        norm = os.path.normpath(expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded))
        if t in {"/", "~", "~/", ".", "..", "*", "$HOME", "${HOME}"} or norm in {"/", home} \
                or norm == os.path.normpath(cwd) or os.path.normpath(cwd).startswith(norm + os.sep):
            deny(f"rm récursif sur une racine ou un parent du répertoire courant ({t})")
        if "$" in t or "*" in t or "?" in t:
            ask(f"rm récursif sur un chemin construit ou un motif ({t}) : "
                "valider l'allowlist exacte des chemins avant suppression")
        if os.path.isabs(expanded) and not norm.startswith(os.path.normpath(cwd) + os.sep) \
                and not norm.startswith("/tmp/"):
            ask(f"rm récursif hors du worktree courant ({t})")


def check_psql(words: list[str], env_prefix: str) -> None:
    hosts: list[str] = []
    for i, a in enumerate(words[1:], start=1):
        if a in {"-h", "--host"} and i + 1 < len(words):
            hosts.append(words[i + 1])
        elif a.startswith("--host="):
            hosts.append(a.split("=", 1)[1])
        m = re.match(r"^postgres(?:ql)?://(?:[^@/]*@)?([^/:?]*)", a)
        if m:
            hosts.append(m.group(1))
        m = re.search(r"(?:^|\s)host=([^\s]+)", a)
        if m:
            hosts.append(m.group(1))
    m = re.search(r"PGHOST=(\S+)", env_prefix)
    if m:
        hosts.append(m.group(1))
    if any(h not in LOCAL_HOSTS and not h.startswith("/") for h in hosts):
        ask("psql vers une base non locale : opération live, autorisation explicite requise")
    if not hosts and any(a.startswith("$") or "DSN" in a.upper() for a in words[1:]):
        ask("psql avec un DSN non explicite : vérifier qu'il ne vise pas une base réelle")


def check_bash(command: str, cwd: str) -> None:
    lowered = command.lower()
    if re.search(r"\bln\s+-[a-z]*s[a-z]*\b[^\n;&|]*\bcurrent\b", lowered) or \
            re.search(r"\b(switch|bascule)[-_ ]?current\b", lowered):
        ask("bascule du lien `current` : opération de release, autorisation explicite requise")
    for words in segments(command):
        prog = os.path.basename(words[0])
        if prog == "git":
            check_git(words, cwd)
        elif prog == "gh":
            check_gh(words)
        elif prog == "rm":
            check_rm(words, cwd)
        elif prog in {"ssh", "scp", "sftp", "mosh"}:
            targets = [w for w in words[1:] if not w.startswith("-")]
            if targets and host_of(targets[0]) == "github.com" and prog == "ssh":
                continue
            ask(f"{prog} : accès à un hôte distant, autorisation explicite requise")
        elif prog == "rsync" and any(re.match(r"^[^/\s]+:", w) for w in words[1:]):
            ask("rsync vers ou depuis un hôte distant")
        elif prog in {"psql", "pg_dump", "pg_restore", "pg_dumpall"}:
            check_psql(words, command)
        elif prog == "docker":
            args = words[1:]
            global_opts: list[str] = []
            while args and args[0].startswith("-"):
                global_opts.append(args[0])
                args = args[1:]
            if any(o.split("=")[0] in {"-H", "--host", "--context", "-c"} for o in global_opts) \
                    or "DOCKER_HOST=" in command:
                ask("docker vers un démon distant : opération live")
            if args[:1] == ["push"]:
                ask("docker push : publication d'image")
            if args[:2] in (["system", "prune"], ["volume", "rm"], ["volume", "prune"], ["image", "prune"]) \
                    or args[:1] == ["rmi"]:
                ask(f"docker {' '.join(args[:2])} : destruction de ressources Docker partagées")
        elif prog in {"printenv"} or (prog == "env" and len(words) == 1):
            ask("affichage de l'environnement : risque d'exposer des secrets dans le transcript")
        elif prog in READ_COMMANDS or prog in {"xargs"}:
            for w in words[1:]:
                if not w.startswith("-") and is_secret_path(os.path.expanduser(w)):
                    deny(f"lecture d'un fichier de secret interdite ({prog}) ; "
                         "vérifier sa présence avec `test -f`, jamais son contenu")
        elif prog in {"curl", "wget"} and any(
                a in {"-X", "--request", "-d", "--data", "--data-binary", "-F", "--form", "-T",
                      "--upload-file"} for a in words[1:]):
            ask(f"{prog} en écriture vers un service distant")
        elif prog in {"kubectl", "terraform", "ansible", "ansible-playbook"}:
            ask(f"{prog} : outil d'opération d'infrastructure")
        elif prog in {"systemctl"} and len(words) > 1 and words[1] not in {"status", "show", "list-units",
                                                                         "is-active", "cat"}:
            ask("systemctl en écriture")


def decide(payload: dict) -> Decision | None:
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    try:
        if tool == "Bash":
            check_bash(str(tool_input.get("command", "")), cwd)
        elif tool in {"Read", "Grep", "Glob", "Write", "Edit", "NotebookEdit"}:
            check_file_tool(tool, tool_input, cwd)
    except Decision as d:
        return d
    return None


def emit(kind: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": kind,
            "permissionDecisionReason": f"[nexus pretool-guard] {reason}",
        }
    }, ensure_ascii=False))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("entrée de hook non objet")
        decision = decide(payload)
    except Exception as exc:  # noqa: BLE001 — fail-closed volontaire
        emit("deny", f"garde en erreur ({type(exc).__name__}) : action refusée par prudence")
        return 0
    if decision is not None:
        emit(decision.kind, decision.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
