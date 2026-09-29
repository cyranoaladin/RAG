#!/usr/bin/env python3
"""Garde PreToolUse de Claude Code pour le dépôt Nexus RAG.

Reçoit sur stdin le JSON du hook (``tool_name``, ``tool_input``, ``cwd``) et
rend une décision :

- ``deny`` : action interdite sans exception (écriture sur ``main``, push
  forcé, lecture de secret, auto-approbation de PR, destruction de racine) ;
- ``ask`` : mutation externe ou destructive qui exige une autorisation humaine
  pour cette opération précise (SSH, psql distant, fusion/fermeture de PR,
  push, reset --hard, bascule ``current``…), ou commande que le garde ne sait
  pas classer sûrement ;
- rien : la décision revient aux règles de permission natives.

Le garde analyse le TEXTE de la commande, sans jamais l'exécuter ni demander
une expansion au shell : les motifs sont développés par ``glob`` en Python, les
liens résolus par ``os.path.realpath``. Ce n'est pas un interpréteur Bash : une
construction qu'il ne sait pas classer reçoit ``ask``, jamais le silence.
Plusieurs segments d'une commande composée sont tous évalués ; la décision la
plus sévère l'emporte.

Limite fail-closed : une exception interne est convertie en ``deny``. Cela ne
couvre PAS un script de hook absent, un interpréteur indisponible ou un
dépassement de délai : Claude Code laisse alors passer l'action (voir
``docs/agentic/CLAUDE_CONFIGURATION.md``). Les règles natives ``deny``/``ask``
de ``.claude/settings.json`` restent la défense indépendante.

Le garde n'imprime jamais le contenu d'un fichier ni la valeur d'une variable :
les raisons citent seulement la règle et le chemin.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
SEVERITY = {"ask": 1, "deny": 2}

# Fichiers dont la lecture exposerait un secret dans le transcript.
SECRET_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env(\.[^/]*)?$"),
    re.compile(r"(^|/)\.envrc$"),
    re.compile(r"(^|/)[^/]+\.env$"),
    re.compile(r"\.(pem|key|p12|pfx)$"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"(^|/)\.ssh/"),
    re.compile(r"(^|/)\.pgpass$"),
    re.compile(r"(^|/)\.netrc$"),
    re.compile(r"\.seed(\.hex)?$"),
    re.compile(r"(^|/)creds/"),
    re.compile(r"(^|/)\.credentials\.json$"),
    re.compile(r"(^|/)seed-admin/"),
    re.compile(r"(^|/)(hosts\.yml|\.git-credentials)$"),
    re.compile(r"^/proc/[^/]+/environ$"),
]
SECRET_PATH_ALLOWED = [re.compile(r"(^|/)[^/]*\.env\.example$")]
# Noms représentatifs : un motif qui peut en produire un est refusé, même si
# aucun fichier correspondant n'existe au moment de l'analyse.
SECRET_SAMPLES = [
    ".env", ".env.local", ".env.production", ".envrc", "prod.env", "server.key",
    "cert.pem", "bundle.p12", "id_rsa", "id_ed25519", "readiness.seed",
    "rehearsal-readiness-ed25519.seed.hex", ".pgpass", ".netrc", ".git-credentials",
]

READERS = {
    "cat", "tac", "less", "more", "head", "tail", "bat", "batcat", "nl", "cut", "sort", "uniq",
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk", "gawk", "jq", "yq",
    "cp", "scp", "base64", "xxd", "od", "hexdump", "strings", "source", ".", "tee",
    "diff", "cmp", "paste", "column", "fold", "rev", "iconv", "zcat", "bzcat", "xzcat",
    "openssl", "tar", "zip", "view", "vi", "vim", "nano",
}
# Premier opérande = motif ou programme, pas un fichier (sauf -e/-f).
PATTERN_FIRST = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk", "gawk", "jq", "yq"}
VALUE_OPTIONS = {
    "grep": {"-e", "-f", "-m", "-A", "-B", "-C", "-d", "-D", "--regexp", "--file", "--max-count",
             "--after-context", "--before-context", "--context", "--label", "--color"},
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "cut": {"-d", "-f", "-c", "-b"},
    "sed": {"-e", "-f", "-l"}, "awk": {"-f", "-v", "-F"}, "rg": {"-e", "-f", "-g", "-t", "-T",
    "-m", "-A", "-B", "-C", "--glob", "--type", "--max-count"}, "jq": {"--arg", "--argjson"},
}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}"}
SCAN_LIMIT = 20000
SCAN_SKIP_DIRS = {".git"}

GH_GLOBAL_VALUE = {"-R", "--repo", "--hostname"}
GH_GLOBAL_FLAGS = {"--help", "-h", "--version"}
GH_KNOWN = {
    "pr", "issue", "repo", "api", "run", "workflow", "release", "auth", "alias", "browse",
    "search", "status", "gist", "label", "secret", "variable", "ssh-key", "gpg-key", "codespace",
    "cache", "project", "ruleset", "attestation", "extension", "config", "completion", "org",
}
GH_MUTATIONS = {
    "pr": {"merge", "close", "ready", "reopen", "edit", "create", "comment", "review", "lock",
           "unlock", "update-branch", "revert"},
    "issue": {"create", "close", "comment", "edit", "delete", "reopen", "transfer", "lock",
              "unlock", "pin", "unpin", "develop"},
    "repo": {"create", "delete", "edit", "rename", "archive", "unarchive", "fork", "sync",
             "set-default", "deploy-key"},
    "run": {"cancel", "rerun", "delete"}, "workflow": {"run", "enable", "disable"},
    "release": {"create", "delete", "edit", "upload", "delete-asset"},
    "secret": {"set", "delete"}, "variable": {"set", "delete"},
    "label": {"create", "edit", "delete", "clone"}, "gist": {"create", "edit", "delete", "clone"},
    "alias": {"set", "delete", "import"}, "extension": {"install", "upgrade", "remove", "exec"},
    "cache": {"delete"}, "ruleset": set(), "project": {"create", "delete", "edit", "close",
    "item-add", "item-edit", "item-delete", "field-create", "field-delete", "copy", "link",
    "unlink", "mark-template"}, "codespace": {"create", "delete", "edit", "ssh", "cp", "stop"},
    "ssh-key": {"add", "delete"}, "gpg-key": {"add", "delete"}, "config": {"set", "clear-cache"},
    "auth": {"login", "logout", "refresh", "setup-git", "switch"},
}


class Verdict:
    def __init__(self) -> None:
        self.kind: str | None = None
        self.reasons: list[str] = []

    def add(self, kind: str, reason: str) -> None:
        if self.kind is None or SEVERITY[kind] > SEVERITY[self.kind]:
            self.kind, self.reasons = kind, [reason]
        elif kind == self.kind and reason not in self.reasons:
            self.reasons.append(reason)


def is_secret_path(path: str) -> bool:
    if any(p.search(path) for p in SECRET_PATH_ALLOWED):
        return False
    return any(p.search(path) for p in SECRET_PATH_PATTERNS)


def is_secret_target(path: str) -> bool:
    """Le chemin, ou ce qu'il désigne après résolution des liens, est-il un secret ?"""
    if is_secret_path(path):
        return True
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return real != path and is_secret_path(real)


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


def absolute(path: str, cwd: str) -> str:
    expanded = os.path.expanduser(path)
    return os.path.normpath(expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded))


# --------------------------------------------------------------------------
# Outils fichiers
# --------------------------------------------------------------------------

def check_file_tool(v: Verdict, tool: str, tool_input: dict, cwd: str) -> None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not raw:
        return
    path = absolute(str(raw), cwd)
    if tool in {"Read", "Grep", "Glob"}:
        if tool != "Glob" and is_secret_target(path):
            v.add("deny", f"lecture d'un fichier de secret interdite ({tool}) ; "
                          "vérifier sa présence avec `test -f`, jamais son contenu")
        return
    # Write / Edit / NotebookEdit
    if is_secret_target(path):
        v.add("deny", "écriture d'un fichier de secret interdite")
        return
    parent = existing_dir(Path(path).parent)
    top = git(parent, "rev-parse", "--show-toplevel")
    if top is None:
        return
    branch = current_branch(parent)
    if branch in PROTECTED_BRANCHES:
        v.add("deny", f"écriture dans un worktree sur `{branch}` interdite : "
                      "créer une branche de lot dans un worktree dédié")
        return
    session_top = git(cwd, "rev-parse", "--show-toplevel")
    if session_top and os.path.realpath(top) != os.path.realpath(session_top):
        same_repo = git(parent, "rev-parse", "--git-common-dir")
        session_repo = git(cwd, "rev-parse", "--git-common-dir")
        if same_repo and session_repo and (
            os.path.realpath(os.path.join(parent, same_repo))
            == os.path.realpath(os.path.join(cwd, session_repo))
        ):
            v.add("ask", f"écriture dans un autre worktree ({top}) que celui de la session : "
                         "vérifier qu'il n'appartient pas à un lot actif")


# --------------------------------------------------------------------------
# Lecture de la commande : substitutions, heredocs, jetons, segments
# --------------------------------------------------------------------------

class Unparseable(Exception):
    pass


def _matching(text: str, start: int, opening: str, closing: str) -> int:
    """Index de la fermeture correspondant à l'ouverture située juste avant ``start``."""
    depth, i, quote = 1, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == "\\":
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif text.startswith("<<", i) and not text.startswith("<<<", i):
            m = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", text[i:])
            if m:
                # Le corps d'un heredoc est du texte : ses apostrophes ne comptent pas.
                eol = text.find("\n", i)
                if eol < 0:
                    raise Unparseable("heredoc non terminé")
                end = re.compile(r"^\t*" + re.escape(m.group(2)) + r"$", re.M).search(text, eol + 1)
                if not end:
                    raise Unparseable("heredoc non terminé")
                i = end.end()
                continue
        elif c == opening:
            depth += 1
        elif c == closing:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise Unparseable("parenthèse non fermée")


def preprocess(command: str) -> tuple[str, list[str], dict[str, str]]:
    """Extrait substitutions et heredocs ; rend le texte externe analysable.

    - ``$(…)``, ``<(…)``, ``>(…)`` et `` `…` `` hors apostrophes : leur corps est
      une commande, analysée séparément ; il est remplacé par ``__SUBST__``.
    - heredoc ``<<MOT`` : le corps est retiré et conservé sous ``__HEREDOC_n__`` ;
      il ne sera analysé comme commande que si le programme est un shell.
    - retour à la ligne hors guillemets : séparateur de commandes.
    """
    out: list[str] = []
    subs: list[str] = []
    heredocs: dict[str, str] = {}
    pending: list[tuple[str, str, bool]] = []
    i, quote = 0, None
    while i < len(command):
        c = command[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < len(command):
            out.append(command[i:i + 2])
            i += 2
            continue
        if quote is None and c == "'":
            quote = "'"
            out.append(c)
            i += 1
            continue
        if c == '"':
            quote = None if quote == '"' else '"'
            out.append(c)
            i += 1
            continue
        two = command[i:i + 2]
        if two in {"$(", "<(", ">("} and not (quote == '"' and two != "$("):
            end = _matching(command, i + 2, "(", ")")
            subs.append(command[i + 2:end])
            out.append(" __SUBST__ " if quote is None else "__SUBST__")
            i = end + 1
            continue
        if c == "`":
            end = command.find("`", i + 1)
            if end < 0:
                raise Unparseable("apostrophe inverse non fermée")
            subs.append(command[i + 1:end])
            out.append("__SUBST__")
            i = end + 1
            continue
        if quote is None and command.startswith("<<", i) and not command.startswith("<<<", i):
            m = re.match(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", command[i:])
            if not m:
                raise Unparseable("heredoc sans délimiteur lisible")
            name = f"__HEREDOC_{len(heredocs) + len(pending)}__"
            pending.append((name, m.group(3), m.group(1) == "-"))
            out.append(f" << {name} ")
            i += m.end()
            continue
        if quote is None and c == "\n":
            out.append(" ; ")
            i += 1
            for name, delim, strip_tabs in pending:
                body: list[str] = []
                while True:
                    if i >= len(command):
                        raise Unparseable("heredoc non terminé")
                    end = command.find("\n", i)
                    line = command[i:] if end < 0 else command[i:end]
                    i = len(command) if end < 0 else end + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delim:
                        break
                    body.append(line)
                heredocs[name] = "\n".join(body)
            pending = []
            continue
        out.append(c)
        i += 1
    if quote is not None:
        raise Unparseable("guillemet non fermé")
    if pending:
        raise Unparseable("heredoc non terminé")
    return "".join(out), subs, heredocs


def is_operator(token: str) -> bool:
    return bool(token) and all(ch in "();<>|&" for ch in token)


def pipelines(text: str) -> list[list[list[str]]]:
    """Découpe en pipelines (listes de segments), en respectant les guillemets."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise Unparseable(str(exc)) from exc
    result: list[list[list[str]]] = [[[]]]
    for tok in tokens:
        if is_operator(tok) and not any(ch in tok for ch in "<>"):
            if tok in {"|", "|&"}:
                result[-1].append([])
            else:
                result.append([[]])
        else:
            result[-1][-1].append(tok)
    return [[seg for seg in pipe if seg] for pipe in result if any(pipe)]


# --------------------------------------------------------------------------
# Préfixes : sudo, env, command, timeout, nice, xargs…
# --------------------------------------------------------------------------

WRAPPERS: dict[str, tuple[set[str], set[str]]] = {
    # nom : (options qui prennent une valeur, options sans valeur)
    "sudo": ({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "--user", "--group",
              "--close-from", "--chdir", "--host", "--prompt", "--role", "--type",
              "--command-timeout", "--other-user"},
             {"-A", "-b", "-E", "-e", "-H", "-i", "-K", "-k", "-l", "-n", "-P", "-S", "-s", "-V",
              "-v", "-B", "-N", "-R", "--askpass", "--background", "--preserve-env", "--edit",
              "--set-home", "--login", "--remove-timestamp", "--reset-timestamp", "--list",
              "--non-interactive", "--preserve-groups", "--stdin", "--shell"}),
    "env": ({"-u", "--unset", "-C", "--chdir"},
            {"-i", "-0", "-v", "--ignore-environment", "--null", "--debug", "-"}),
    "command": (set(), {"-p"}),
    "builtin": (set(), set()),
    "exec": ({"-a"}, {"-c", "-l"}),
    "nohup": (set(), set()),
    "time": (set(), {"-p"}),
    "timeout": ({"-s", "-k", "--signal", "--kill-after"},
                {"--foreground", "--preserve-status", "-v", "--verbose"}),
    "nice": ({"-n", "--adjustment"}, set()),
    "stdbuf": ({"-i", "-o", "-e", "--input", "--output", "--error"}, set()),
    "ionice": ({"-c", "-n", "--class", "--classdata"}, {"-t", "--ignore"}),
    "setsid": (set(), {"-f", "-w", "-c", "--fork", "--wait", "--ctty"}),
    "xargs": ({"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s", "--arg-file", "--delimiter",
               "--eof", "--replace", "--max-lines", "--max-args", "--max-procs", "--max-chars",
               "--process-slot-var"},
              {"-0", "--null", "-r", "--no-run-if-empty", "-t", "--verbose", "-p",
               "--interactive", "-x", "--exit", "-o", "--open-tty"}),
}


def _consume_options(name: str, words: list[str], v: Verdict) -> list[str] | None:
    """Consomme les options d'un préfixe ; ``None`` si une option est inconnue."""
    valued, flags = WRAPPERS[name]
    i = 1
    while i < len(words):
        w = words[i]
        if w == "--":
            return words[i + 1:]
        if not w.startswith("-") or w == "-" and name != "env":
            break
        if w == "-" and name == "env":
            i += 1
            continue
        if w.startswith("--"):
            key = w.split("=", 1)[0]
            if key in valued:
                i += 1 if "=" in w else 2
            elif key in flags:
                i += 1
            elif name == "env" and key == "--split-string":
                v.add("ask", "env --split-string : commande non analysable")
                return None
            else:
                return None
            continue
        if name == "nice" and re.fullmatch(r"-\d+", w):
            i += 1
            continue
        # Grappe d'options courtes : -nu postgres, -upostgres…
        j, consumed_next = 1, False
        while j < len(w):
            opt = "-" + w[j]
            if name == "env" and opt == "-S":
                v.add("ask", "env -S : commande non analysable")
                return None
            if opt in valued:
                if j + 1 >= len(w):
                    consumed_next = True
                break
            if opt not in flags:
                return None
            j += 1
        i += 2 if consumed_next else 1
    return words[i:]


def unwrap(words: list[str], v: Verdict, ctx: dict) -> list[str] | None:
    """Retire préfixes, mots-clés et affectations ; rend la commande réellement exécutée.

    Rend ``[]`` si le segment n'exécute rien, ``None`` si le préfixe n'a pas pu être
    classé (une décision prudente a alors été ajoutée).
    """
    while words:
        w = words[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            ctx.setdefault("assignments", []).append(w)
            words = words[1:]
            continue
        if w in KEYWORDS:
            words = words[1:]
            continue
        if w in {"for", "case", "select", "function"}:
            return []
        base = os.path.basename(w)
        if base in {"doas", "su", "runuser", "pkexec"}:
            v.add("ask", f"{base} : élévation de privilèges")
            return None
        if base not in WRAPPERS:
            return words
        if base == "command" and len(words) > 1 and words[1] in {"-v", "-V"}:
            return []
        if base == "sudo":
            v.add("ask", "sudo : élévation de privilèges")
        if base == "xargs":
            ctx["xargs"] = True
        rest = _consume_options(base, words, v)
        if rest is None:
            v.add("ask", f"préfixe `{base}` avec des options non reconnues : commande non classée")
            return None
        if base == "timeout":
            if not rest:
                return []
            rest = rest[1:]  # durée
        if not rest:
            if base == "env":
                v.add("ask", "affichage de l'environnement : risque d'exposer des secrets")
            return []
        words = rest
    return words


# --------------------------------------------------------------------------
# Programmes
# --------------------------------------------------------------------------

def check_git(v: Verdict, words: list[str], cwd: str) -> None:
    args = words[1:]
    while args and args[0].startswith("-"):
        opt = args[0]
        if opt in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"} and len(args) > 1:
            if opt == "-C":
                cwd = absolute(args[1], cwd)
            args = args[2:]
        else:
            args = args[1:]
    if not args:
        return
    sub, rest = args[0], args[1:]
    if sub == "push":
        if any(a in {"-f", "--force", "--mirror"} or (a.startswith("--force") and
               not a.startswith("--force-with-lease")) for a in rest) \
                or any(a.startswith("+") for a in rest):
            v.add("deny", "git push forcé interdit")
        if any(a.startswith("--force-with-lease") for a in rest):
            v.add("ask", "git push --force-with-lease : réécriture d'une branche distante")
        refs = [a for a in rest if not a.startswith("-")]
        if any(a in {"--delete", "-d"} for a in rest) or any(r.startswith(":") for r in refs):
            v.add("ask", "suppression d'une branche distante")
        for ref in refs[1:]:
            dest = ref.split(":")[-1].removeprefix("refs/heads/")
            if dest in PROTECTED_BRANCHES:
                v.add("deny", f"push direct vers `{dest}` interdit : passer par une PR")
        if len(refs) <= 1 and current_branch(cwd) in PROTECTED_BRANCHES:
            v.add("deny", "push depuis `main` interdit : passer par une PR")
        v.add("ask", "git push : mutation externe")
    elif sub == "commit" and current_branch(cwd) in PROTECTED_BRANCHES:
        v.add("deny", "commit sur `main` interdit : travailler sur une branche de lot")
    elif sub == "reset" and "--hard" in rest:
        v.add("ask", "git reset --hard : perte possible de travail non commité")
    elif sub == "clean" and any(re.match(r"^-[a-zA-Z]*f", a) or a == "--force" for a in rest):
        v.add("ask", "git clean forcé : suppression de fichiers non suivis")
    elif (sub == "checkout" and ("--" in rest or "." in rest)) or \
            (sub == "restore" and "--staged" not in rest and rest):
        v.add("ask", f"git {sub} : écrasement de modifications locales")
    elif sub == "branch" and any(a in {"-D", "--delete", "-d"} for a in rest):
        v.add("ask", "suppression de branche locale")
    elif sub == "worktree" and rest[:1] == ["remove"]:
        v.add("ask", "suppression d'un worktree : vérifier qu'il n'appartient pas à un lot actif")
    elif sub == "stash" and rest[:1] in (["pop"], ["drop"], ["clear"]):
        v.add("ask", "la pile de stash est partagée entre worktrees : pop/drop/clear exigent une vérification")
    elif sub == "credential":
        v.add("deny", "git credential : affichage d'identifiants interdit")


def check_gh(v: Verdict, words: list[str]) -> None:
    """Normalise les options héritées (-R/--repo, --hostname) avant la sous-commande."""
    positionals: list[str] = []
    options: list[str] = []
    args = words[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if len(positionals) < 2 and a.startswith("-") and a != "-":
            key = a.split("=", 1)[0]
            if key in GH_GLOBAL_VALUE:
                i += 1 if "=" in a else 2
                continue
            if a.startswith("-R") and len(a) > 2:
                i += 1
                continue
            if key in GH_GLOBAL_FLAGS:
                return
            if not positionals:
                v.add("ask", f"gh : option `{key}` avant la commande, non classée")
                return
            options.append(a)
            i += 1
            continue
        if a.startswith("-"):
            options.append(a)
        else:
            positionals.append(a)
        i += 1
    if not positionals:
        return
    group = positionals[0]
    sub = positionals[1] if len(positionals) > 1 else ""
    if group not in GH_KNOWN:
        v.add("ask", f"gh {group} : commande inconnue (alias ou extension possible)")
        return
    if group == "auth" and (sub == "token" or (sub == "status" and any(
            o in {"-t", "--show-token"} for o in options))):
        v.add("deny", "gh auth : affichage de jeton interdit")
        return
    if group == "pr" and sub == "review" and any(
            o in {"--approve", "-a"} or re.fullmatch(r"-[a-zA-Z]*a[a-zA-Z]*", o) for o in options):
        v.add("deny", "auto-approbation d'une PR interdite : l'approbation est une décision humaine")
        return
    if group == "api":
        method = None
        for k, a in enumerate(args):
            if a in {"-X", "--method"} and k + 1 < len(args):
                method = args[k + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
            elif a.startswith("-X") and len(a) > 2:
                method = a[2:].lstrip("=").upper()
        fields = any(a.split("=", 1)[0] in {"-f", "-F", "--field", "--raw-field", "--input"}
                     or re.fullmatch(r"-[fF].+", a) for a in args)
        if any(re.search(r"event=APPROVE", a, re.I) for a in args):
            v.add("deny", "approbation de PR par gh api interdite")
        elif (method and method != "GET") or (method is None and fields):
            v.add("ask", "gh api en écriture : mutation GitHub")
        return
    if sub in GH_MUTATIONS.get(group, set()):
        v.add("ask", f"gh {group} {sub} : mutation GitHub, autorisation explicite requise")


def _brace_expand(pattern: str) -> list[str]:
    m = re.search(r"\{([^{}]*,[^{}]*)\}", pattern)
    if not m:
        return [pattern]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out += _brace_expand(pattern[:m.start()] + alt + pattern[m.end():])
    return out


def _pattern_can_hit_secret(pattern: str) -> bool:
    base = os.path.basename(pattern) or pattern
    if is_secret_path(os.path.join(os.path.dirname(pattern), "x")) and os.path.dirname(pattern):
        return True
    if not re.sub(r"[*?]|\[[^\]]*\]", "", base):
        return False  # motif sans partie littérale : seule l'expansion réelle décide
    for sample in SECRET_SAMPLES:
        if sample.startswith(".") and not base.startswith("."):
            continue  # comme Bash : `*` ne produit pas de fichier caché
        if fnmatch.fnmatchcase(sample, base):
            return True
    return False


def scan_tree(roots: list[str]) -> tuple[str | None, bool]:
    """Cherche un fichier sensible sous ``roots`` (liens inclus, sans les suivre).

    Rend (premier chemin sensible, arbre trop grand pour être inspecté).
    """
    seen = 0
    for root in roots:
        if is_secret_target(root):
            return root, False
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
            for name in filenames + dirnames:
                seen += 1
                if seen > SCAN_LIMIT:
                    return None, True
                full = os.path.join(dirpath, name)
                if is_secret_target(full):
                    return full, False
    return None, False


def _recursive(prog: str, options: list[str]) -> bool:
    if prog in {"rg", "ag"}:
        return any(o in {"-u", "-uu", "-uuu", "--unrestricted", "--no-ignore", "--no-ignore-vcs",
                         "-U", "--skip-vcs-ignores"} for o in options)
    if prog == "ack":
        return True
    if prog in {"grep", "egrep", "fgrep", "diff"}:
        return any(o in {"--recursive", "--dereference-recursive", "-r", "-R"}
                   or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", o) for o in options) \
            or "--directories=recurse" in options
    return False


def check_reader(v: Verdict, prog: str, words: list[str], cwd: str, ctx: dict) -> None:
    valued = VALUE_OPTIONS.get(prog, set())
    options: list[str] = []
    operands: list[str] = []
    explicit_pattern = False
    i = 1
    while i < len(words):
        w = words[i]
        if w == "--":
            operands += words[i + 1:]
            break
        if w.startswith("-") and w != "-":
            key = w.split("=", 1)[0]
            options.append(key)
            if key in {"-e", "-f", "--regexp", "--file"} and prog in PATTERN_FIRST:
                explicit_pattern = True
                if key in {"-f", "--file"}:
                    target = w.split("=", 1)[1] if "=" in w else (words[i + 1] if i + 1 < len(words) else "")
                    if target and is_secret_target(absolute(target, cwd)):
                        v.add("deny", f"lecture d'un fichier de secret interdite ({prog} -f)")
            if key in valued and "=" not in w:
                i += 2
                continue
            i += 1
            continue
        operands.append(w)
        i += 1
    if prog in PATTERN_FIRST and not explicit_pattern and operands:
        operands = operands[1:]
    if ctx.get("xargs"):
        v.add("ask", f"xargs {prog} : fichiers lus fournis par l'entrée standard, non vérifiables")
    for op in operands:
        if "__SUBST__" in op or "$" in op or "__HEREDOC_" in op:
            v.add("ask", f"{prog} sur un chemin non résolu ({op}) : fichier lu non vérifiable")
            continue
        if any(ch in op for ch in "*?[") or re.search(r"\{[^{}]*,[^{}]*\}", op):
            for pattern in _brace_expand(op):
                if _pattern_can_hit_secret(pattern):
                    v.add("deny", f"{prog} avec un motif qui peut désigner un secret ({op})")
                    break
                for hit in glob.glob(absolute(pattern, cwd)):
                    if is_secret_target(hit):
                        v.add("deny", f"{prog} avec un motif qui atteint un secret ({op})")
                        break
            continue
        path = absolute(op, cwd)
        if is_secret_target(path):
            v.add("deny", f"lecture d'un fichier de secret interdite ({prog}) ; "
                          "vérifier sa présence avec `test -f`, jamais son contenu")
    if _recursive(prog, options) or (prog == "tar" and operands):
        roots = [absolute(op, cwd) for op in operands if "$" not in op] or [cwd]
        found, too_big = scan_tree(roots)
        if found:
            v.add("deny", f"lecture récursive qui englobe un fichier sensible ({found}) : "
                          "utiliser `git grep` ou restreindre le chemin")
        elif too_big:
            v.add("deny", "lecture récursive d'un arbre trop grand pour être vérifié : "
                          "utiliser `git grep` ou restreindre le chemin")


def check_find(v: Verdict, words: list[str], cwd: str, ctx: dict) -> None:
    args = words[1:]
    roots: list[str] = []
    for a in args:
        if a.startswith("-") or a in {"(", "!", ")"}:
            break
        roots.append(a)
    if "-delete" in args:
        v.add("ask", "find -delete : suppression de fichiers")
    for k, a in enumerate(args):
        if a in {"-exec", "-execdir", "-ok", "-okdir"} and k + 1 < len(args):
            inner = args[k + 1:]
            end = next((j for j, t in enumerate(inner) if t in {";", "+"}), len(inner))
            inner = inner[:end]
            prog = os.path.basename(inner[0]) if inner else ""
            if prog in READERS:
                found, too_big = scan_tree([absolute(r, cwd) for r in roots] or [cwd])
                if found or too_big:
                    v.add("deny", "find -exec lisant des fichiers d'un arbre qui contient (ou peut "
                                  "contenir) un secret : utiliser `git grep` ou restreindre")
            classify(v, [t for t in inner if t != "{}"] or inner, cwd, dict(ctx))


def check_rm(v: Verdict, words: list[str], cwd: str) -> None:
    flags = "".join(a.lstrip("-") for a in words[1:] if a.startswith("-") and not a.startswith("--"))
    long_flags = {a for a in words[1:] if a.startswith("--")}
    if not ("r" in flags.lower() or "--recursive" in long_flags):
        return
    targets = [a for a in words[1:] if not a.startswith("-")]
    home = os.path.expanduser("~")
    here = os.path.normpath(cwd)
    for t in targets:
        expanded = os.path.expanduser(t)
        norm = absolute(t, cwd)
        if t in {"/", "~", "~/", ".", "..", "*", "$HOME", "${HOME}"} or norm in {"/", home} \
                or norm == here or here.startswith(norm + os.sep):
            v.add("deny", f"rm récursif sur une racine ou un parent du répertoire courant ({t})")
        elif "$" in t or "*" in t or "?" in t or "__SUBST__" in t:
            v.add("ask", f"rm récursif sur un chemin construit ou un motif ({t}) : "
                         "valider l'allowlist exacte des chemins avant suppression")
        elif os.path.isabs(expanded) and not norm.startswith(here + os.sep) \
                and not norm.startswith("/tmp/"):
            v.add("ask", f"rm récursif hors du worktree courant ({t})")


def check_psql(v: Verdict, words: list[str], ctx: dict) -> None:
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
    for assignment in ctx.get("assignments", []):
        if assignment.startswith("PGHOST="):
            hosts.append(assignment.split("=", 1)[1])
    if any(h not in LOCAL_HOSTS and not h.startswith("/") for h in hosts):
        v.add("ask", "psql vers une base non locale : opération live, autorisation explicite requise")
    elif not hosts and any("$" in a or "__SUBST__" in a or "DSN" in a.upper() for a in words[1:]):
        v.add("ask", "psql avec un DSN non explicite : vérifier qu'il ne vise pas une base réelle")


def check_docker(v: Verdict, words: list[str], ctx: dict) -> None:
    args = words[1:]
    global_opts: list[str] = []
    while args and args[0].startswith("-"):
        global_opts.append(args[0])
        args = args[1:]
    if any(o.split("=")[0] in {"-H", "--host", "--context", "-c"} for o in global_opts) \
            or any(a.startswith("DOCKER_HOST=") for a in ctx.get("assignments", [])):
        v.add("ask", "docker vers un démon distant : opération live")
    if args[:1] == ["push"]:
        v.add("ask", "docker push : publication d'image")
    if args[:2] in (["system", "prune"], ["volume", "rm"], ["volume", "prune"], ["image", "prune"]) \
            or args[:1] == ["rmi"]:
        v.add("ask", f"docker {' '.join(args[:2])} : destruction de ressources Docker partagées")


def classify(v: Verdict, words: list[str], cwd: str, ctx: dict) -> None:
    inner = unwrap(words, v, ctx)
    if not inner:
        return
    prog = os.path.basename(inner[0])
    if prog in SHELLS:
        script = next((inner[k + 1] for k, a in enumerate(inner[1:], start=1)
                       if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) and k + 1 < len(inner)), None)
        if script is not None:
            analyse_bash(v, script, cwd)
        return
    if prog == "eval":
        text = " ".join(inner[1:])
        if "$" in text or "__SUBST__" in text:
            v.add("ask", "eval d'un texte non résolu : commande non analysable")
        else:
            analyse_bash(v, text, cwd)
        return
    if prog == "git":
        check_git(v, inner, cwd)
    elif prog == "gh":
        check_gh(v, inner)
    elif prog == "rm":
        check_rm(v, inner, cwd)
        if ctx.get("xargs") and any(re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*|--recursive", a)
                                    for a in inner[1:]):
            v.add("ask", "xargs rm récursif : chemins fournis par l'entrée standard, non vérifiables")
    elif prog == "find":
        check_find(v, inner, cwd, ctx)
    elif prog in {"ssh", "scp", "sftp", "mosh"}:
        targets = [w for w in inner[1:] if not w.startswith("-")]
        if prog == "ssh" and targets and targets[0].split("@")[-1] == "github.com":
            return
        v.add("ask", f"{prog} : accès à un hôte distant, autorisation explicite requise")
        if prog == "scp":
            check_reader(v, prog, inner, cwd, ctx)
    elif prog == "rsync" and any(re.match(r"^[^/\s]+:", w) for w in inner[1:]):
        v.add("ask", "rsync vers ou depuis un hôte distant")
    elif prog in {"psql", "pg_dump", "pg_restore", "pg_dumpall"}:
        check_psql(v, inner, ctx)
    elif prog == "docker":
        check_docker(v, inner, ctx)
    elif prog == "printenv":
        v.add("ask", "affichage de l'environnement : risque d'exposer des secrets dans le transcript")
    elif prog in {"echo", "printf"} and any(re.search(
            r"\$\{?[A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|SEED|DSN|CREDENTIAL|API_KEY)",
            w, re.I) for w in inner[1:]):
        v.add("ask", f"{prog} d'une variable sensible : risque d'exposer un secret")
    elif prog in READERS:
        check_reader(v, prog, inner, cwd, ctx)
    elif prog in {"curl", "wget"} and any(
            a.split("=", 1)[0] in {"-X", "--request", "-d", "--data", "--data-binary", "-F",
                                   "--form", "-T", "--upload-file"} for a in inner[1:]):
        v.add("ask", f"{prog} en écriture vers un service distant")
    elif prog in {"kubectl", "terraform", "ansible", "ansible-playbook"}:
        v.add("ask", f"{prog} : outil d'opération d'infrastructure")
    elif prog == "systemctl" and len(inner) > 1 and inner[1] not in {
            "status", "show", "list-units", "is-active", "cat"}:
        v.add("ask", "systemctl en écriture")


def check_redirections(v: Verdict, segment: list[str], cwd: str, heredocs: dict[str, str]) -> list[str]:
    """Évalue les cibles de redirection et les retire du segment."""
    words: list[str] = []
    i = 0
    while i < len(segment):
        tok = segment[i]
        if is_operator(tok):
            target = segment[i + 1] if i + 1 < len(segment) else ""
            if words and words[-1].isdigit():
                words.pop()
            if tok == "<<":
                runner = (unwrap(list(words), Verdict(), {}) or [""])[0]
                if target in heredocs and os.path.basename(runner) in SHELLS:
                    analyse_bash(v, heredocs[target], cwd)
            elif "<" in tok and target:
                if "$" in target or "*" in target:
                    v.add("ask", f"redirection d'entrée non résolue ({target})")
                elif is_secret_target(absolute(target, cwd)):
                    v.add("deny", "lecture d'un fichier de secret par redirection interdite")
            elif ">" in tok and target and not target.startswith("&") and not target.isdigit():
                if is_secret_target(absolute(target, cwd)):
                    v.add("deny", "écriture d'un fichier de secret par redirection interdite")
            i += 2
            continue
        words.append(tok)
        i += 1
    return words


def analyse_bash(v: Verdict, command: str, cwd: str, depth: int = 0) -> None:
    if depth > 5:
        v.add("ask", "imbrication de commandes trop profonde : commande non classée")
        return
    lowered = command.lower()
    if re.search(r"\bln\s+-[a-z]*s[a-z]*\b[^\n;&|]*\bcurrent\b", lowered) or \
            re.search(r"\b(switch|bascule)[-_ ]?current\b", lowered):
        v.add("ask", "bascule du lien `current` : opération de release, autorisation explicite requise")
    try:
        outer, subs, heredocs = preprocess(command)
        groups = pipelines(outer)
    except Unparseable as exc:
        v.add("ask", f"commande non analysable ({exc}) : confirmation requise")
        return
    for sub in subs:
        analyse_bash(v, sub, cwd, depth + 1)
    for pipe in groups:
        for segment in pipe:
            words = check_redirections(v, segment, cwd, heredocs)
            if words:
                classify(v, words, cwd, {})


def decide(payload: dict) -> Verdict:
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input non objet")
    cwd = payload.get("cwd") or os.getcwd()
    v = Verdict()
    if tool == "Bash":
        analyse_bash(v, str(tool_input.get("command", "")), cwd)
    elif tool in {"Read", "Grep", "Glob", "Write", "Edit", "NotebookEdit"}:
        check_file_tool(v, tool, tool_input, cwd)
    return v


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
        verdict = decide(payload)
    except Exception as exc:  # noqa: BLE001 — fail-closed volontaire
        emit("deny", f"garde en erreur ({type(exc).__name__}) : action refusée par prudence")
        return 0
    if verdict.kind is not None:
        emit(verdict.kind, " ; ".join(verdict.reasons))
    trace = os.environ.get("NEXUS_GUARD_TRACE")
    if trace:
        # Épreuves d'intégration seulement : outil, commande ou chemin, décision.
        # Jamais le contenu d'un Write/Edit.
        tool_input = payload.get("tool_input") or {}
        with open(trace, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tool": payload.get("tool_name"),
                "target": tool_input.get("command") or tool_input.get("file_path"),
                "decision": verdict.kind or "aucune",
            }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
