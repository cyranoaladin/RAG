#!/usr/bin/env python3
"""HGGSP : migration de contrôle 019 → 020 et rôle adopter, sur l'hôte staging.

Opération ``successor_control_schema_020_and_adopter_role``. Bibliothèque
standard seule (l'hôte n'a pas psycopg) : PostgreSQL est interrogé par
``psql``, avec la connexion administrative de l'appelant (``PGHOST``,
``PGPORT``, ``PGUSER``, ``PGPASSWORD``, ``PGDATABASE`` dans l'environnement).
Ce compte n'est transmis à aucun conteneur, ni à Worker B, ni au CLI
d'adoption.

``observe`` : lecture seule, valable sur 019 comme sur 020, aucune colonne
de 020 n'est nommée tant que 020 n'est pas prouvée présente.

``apply`` : dans cet ordre, chaque sous-étape revérifiant l'état réel :

1. préflight (base, rôle, registre des migrations, concurrence, sauvegarde) ;
2. secret : absent → créé et CONSERVÉ avant tout rôle ; présent → réutilisé ;
   rôle présent sans secret → refus ; rôle et secret présents → connexion
   réelle exigée, jamais de réinitialisation du mot de passe ;
3. migration par le runner canonique si la tête est 019 (020 jamais rejouée) ;
4. provisionnement CIBLÉ du seul adopter (vérificateur SCRAM calculé ici :
   le mot de passe en clair ne quitte pas l'hôte) ;
5. dérivation du seul fichier DSN adopter (``staging_v4_role_env``) ;
6. connexion adopter réelle et droits EFFECTIFS ;
7. empreintes des données de contrôle antérieures identiques avant/après.

Le fichier secret, le DDL PostgreSQL et le fichier DSN ne forment PAS une
transaction atomique : l'ordre ci-dessus garantit qu'aucun rôle utilisable
n'existe sans son secret conservé, et chaque reprise repart de l'état réel.
Aucune valeur secrète n'est jamais écrite sur la sortie.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import staging_v4_role_env as role_env  # noqa: E402

DATABASE = "ragdb_profile_gate_v4"
ADOPTER = "ingestion_control_adopter"
HEAD_AVANT, HEAD_APRES = 19, 20
MIGRATIONS = Path("services/rag-engine/infra/postgres/ingestion_control/migrations")
BOOTSTRAP = Path("services/rag-engine/infra/scripts/bootstrap_ingestion_control_schema.sh")
PROVISIONNEUR = Path("services/rag-engine/infra/scripts/provision_ingestion_control_adopter_role.sh")
FICHIER_DSN = "ingestion-control-adopter.env"
SECRET = re.compile(r"^[A-Za-z0-9_-]{64}$")
#: Contraintes que 020 pose (noms exacts du fichier 020).
CONTRAINTES_020 = frozenset({
    "artifacts_identity_owner_unique",
    "sealed_release_adoptions_version_identity_shape",
    "sealed_release_adoptions_successor_artifact_owner",
})
#: Colonnes ajoutées par 020, exclues des empreintes pour comparer avant/après.
COLONNES_020 = ("successor_resource_id", "successor_artifact_id")
TABLES_PRESERVEES = (
    "ingestion_runs", "resources", "artifacts", "workflow_events",
    "artifact_attributions", "publication_attestations", "jobs",
    "scope_authorizations", "sealed_release_adoptions",
    "sealed_release_publication_authorizations",
)
#: Tables que l'adopter peut lire ET compléter ; aucune autre écriture.
INSERTABLES = frozenset({
    "ingestion_runs", "resources", "artifacts", "workflow_events",
    "artifact_attributions", "sealed_release_adoptions",
})
LISIBLES = INSERTABLES | {"scope_authorizations"}


class Refus(RuntimeError):
    """Une précondition n'est pas satisfaite : rien d'autre n'est écrit."""


# ── PostgreSQL par psql ──────────────────────────────────────────────────────


def _psql(sql: str, *, env: Mapping[str, str], lecture: bool = True) -> list[list[str]]:
    environ = dict(env)
    if lecture:
        environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
    resultat = subprocess.run(
        ["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-F", "\x1f", "-f", "-"],
        input=sql, env=environ, capture_output=True, text=True, check=False, timeout=120,
    )
    if resultat.returncode != 0:
        # stderr de psql ne contient ni DSN ni mot de passe (variables d'env).
        raise Refus(f"psql : {resultat.stderr.strip()[:400]}")
    return [ligne.split("\x1f") for ligne in resultat.stdout.splitlines() if ligne]


def _un(sql: str, *, env: Mapping[str, str]) -> str:
    lignes = _psql(sql, env=env)
    if len(lignes) != 1 or len(lignes[0]) != 1:
        raise Refus(f"une valeur attendue : {sql.splitlines()[0][:80]}")
    return lignes[0][0]


def _colonne_presente(table: str, colonne: str, *, env: Mapping[str, str]) -> bool:
    return _un(
        "SELECT count(*) FROM pg_attribute WHERE attrelid = "
        f"to_regclass('ingestion_control.{table}') AND attname = '{colonne}' "
        "AND NOT attisdropped", env=env,
    ) == "1"


def empreintes(env: Mapping[str, str]) -> dict[str, str]:
    """``count:md5`` de chaque table préservée, colonnes 020 exclues."""
    sortie: dict[str, str] = {}
    exclues = "".join(f" - '{c}'" for c in COLONNES_020)
    for table in TABLES_PRESERVEES:
        sortie[table] = _un(
            f"SELECT count(*) || ':' || md5(coalesce(string_agg((to_jsonb(t){exclues})::text, "
            f"'|' ORDER BY (to_jsonb(t){exclues})::text), '')) FROM ingestion_control.{table} t",
            env=env,
        )
    return sortie


def observer(env: Mapping[str, str], racine: Path) -> dict[str, Any]:
    """Préflight en lecture seule, valable sur 019 comme sur 020."""
    base, utilisateur, superuser = _psql(
        "SELECT current_database(), current_user, "
        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)", env=env,
    )[0]
    registre = _psql(
        "SELECT version, file_name, sha256 FROM ingestion_control.schema_migrations ORDER BY version",
        env=env,
    )
    versions = [int(v) for v, _f, _s in registre]
    fichiers = {
        int(p.name[:3]): p for p in (racine / MIGRATIONS).glob("[0-9][0-9][0-9]_*.sql")
    }
    ecarts = [
        f"migration {v:03d} : {f} / {s[:12]}"
        for v, f, s in ((int(a), b, c) for a, b, c in registre)
        if v not in fichiers or fichiers[v].name != f
        or hashlib.sha256(fichiers[v].read_bytes()).hexdigest() != s
    ]
    tete = max(versions, default=0)
    observation: dict[str, Any] = {
        "database": base, "admin_user": utilisateur, "admin_is_superuser": superuser == "t",
        "head": tete, "registry_contiguous": versions == list(range(1, tete + 1)),
        "registry_mismatches": ecarts,
        "adopter_role_exists": _un(
            f"SELECT count(*) FROM pg_roles WHERE rolname = '{ADOPTER}'", env=env) == "1",
        "running_jobs": int(_un(
            "SELECT count(*) FROM ingestion_control.jobs "
            "WHERE status = 'running' OR lease_token IS NOT NULL", env=env)),
        "v2_adoptions": 0,
    }
    # Les colonnes de 020 ne sont nommées qu'une fois prouvées présentes.
    if all(_colonne_presente("sealed_release_adoptions", c, env=env) for c in COLONNES_020):
        observation["v2_adoptions"] = int(_un(
            "SELECT count(*) FROM ingestion_control.sealed_release_adoptions "
            "WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2' "
            "OR successor_resource_id IS NOT NULL OR successor_artifact_id IS NOT NULL", env=env))
    return observation


def exiger_prevol(observation: Mapping[str, Any]) -> None:
    ecarts: list[str] = []
    if observation["database"] != DATABASE:
        ecarts.append(f"base {observation['database']!r}, attendu {DATABASE!r}")
    if not observation["admin_is_superuser"]:
        ecarts.append("connexion administrative non superutilisateur")
    if observation["head"] not in (HEAD_AVANT, HEAD_APRES):
        ecarts.append(f"tête de contrôle {observation['head']}, attendu 19 ou 20")
    if not observation["registry_contiguous"] or observation["registry_mismatches"]:
        ecarts.append("registre des migrations non intègre : "
                      + "; ".join(observation["registry_mismatches"])[:300])
    if observation["running_jobs"]:
        ecarts.append(f"{observation['running_jobs']} job(s) en cours ou sous bail : concurrence")
    if observation["head"] == HEAD_AVANT and observation["v2_adoptions"]:
        ecarts.append("adoption V2 observée sur 019")
    if ecarts:
        raise Refus("; ".join(ecarts))


# ── secret ───────────────────────────────────────────────────────────────────


def _verifier_repertoire(dossier: Path) -> None:
    etat = dossier.lstat()
    if not stat.S_ISDIR(etat.st_mode) or stat.S_ISLNK(etat.st_mode):
        raise Refus(f"{dossier} n'est pas un répertoire")
    if etat.st_uid != os.getuid() or stat.S_IMODE(etat.st_mode) != 0o700:
        raise Refus(f"{dossier} doit appartenir à l'appelant et être en 0700")


def lire_secret(chemin: Path) -> str | None:
    """Le secret conservé, ou None s'il n'existe pas ; refus s'il est suspect."""
    _verifier_repertoire(chemin.parent)
    try:
        etat = chemin.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(etat.st_mode) or stat.S_ISLNK(etat.st_mode):
        raise Refus(f"{chemin.name} n'est pas un fichier ordinaire")
    if etat.st_uid != os.getuid() or stat.S_IMODE(etat.st_mode) != 0o600:
        raise Refus(f"{chemin.name} doit appartenir à l'appelant et être en 0600")
    valeur = chemin.read_text(encoding="ascii").strip()
    if not SECRET.match(valeur):
        raise Refus(f"{chemin.name} : contenu inattendu (valeur non affichée)")
    return valeur


def creer_secret(chemin: Path) -> str:
    """Crée atomiquement le secret ; jamais d'écrasement (O_EXCL via link)."""
    _verifier_repertoire(chemin.parent)
    valeur = secrets.token_urlsafe(48)
    assert SECRET.match(valeur)
    descripteur, temporaire = tempfile.mkstemp(prefix=f".{chemin.name}.", dir=chemin.parent)
    try:
        os.fchmod(descripteur, 0o600)
        with os.fdopen(descripteur, "w", encoding="ascii") as flux:
            flux.write(valeur + "\n")
            flux.flush()
            os.fsync(flux.fileno())
        os.link(temporaire, chemin)  # échoue si le fichier existe déjà
    finally:
        Path(temporaire).unlink(missing_ok=True)
    repertoire = os.open(chemin.parent, os.O_RDONLY)
    try:
        os.fsync(repertoire)
    finally:
        os.close(repertoire)
    return valeur


def verificateur_scram(motdepasse: str, *, sel: bytes | None = None, iterations: int = 4096) -> str:
    """Vérificateur SCRAM-SHA-256 au format PostgreSQL (RFC 5802/7677).

    Le secret est ASCII (``token_urlsafe``) : SASLprep est l'identité."""
    sel = sel or secrets.token_bytes(16)
    sale = hashlib.pbkdf2_hmac("sha256", motdepasse.encode("utf-8"), sel, iterations)
    cle_client = hmac.new(sale, b"Client Key", hashlib.sha256).digest()
    cle_stockee = hashlib.sha256(cle_client).digest()
    cle_serveur = hmac.new(sale, b"Server Key", hashlib.sha256).digest()
    b64 = base64.b64encode
    return (f"SCRAM-SHA-256${iterations}:{b64(sel).decode()}"
            f"${b64(cle_stockee).decode()}:{b64(cle_serveur).decode()}")


def connexion_adopter(env: Mapping[str, str], motdepasse: str) -> bool:
    """Connexion RÉELLE avec le secret conservé (mot de passe par l'env)."""
    environ = {**env, "PGUSER": ADOPTER, "PGPASSWORD": motdepasse}
    try:
        lignes = _psql("SELECT current_user, current_database()", env=environ)
    except Refus:
        return False
    return lignes == [[ADOPTER, env.get("PGDATABASE", "")]]


# ── droits effectifs ─────────────────────────────────────────────────────────


def droits_effectifs(env: Mapping[str, str]) -> dict[str, Any]:
    """Droits observés du rôle adopter (PUBLIC et appartenances compris)."""
    a = ADOPTER
    attributs = _psql(
        f"SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, "
        f"rolinherit, rolcanlogin FROM pg_roles WHERE rolname = '{a}'", env=env)[0]
    appartenances = int(_un(
        f"SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
        f"WHERE r.rolname = '{a}'", env=env))
    tables = _psql(
        "SELECT c.relname, "
        f"has_table_privilege('{a}', c.oid, 'SELECT'), has_table_privilege('{a}', c.oid, 'INSERT'), "
        f"has_table_privilege('{a}', c.oid, 'UPDATE'), has_table_privilege('{a}', c.oid, 'DELETE'), "
        f"has_table_privilege('{a}', c.oid, 'TRUNCATE') "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'ingestion_control' AND c.relkind IN ('r','p','v') ORDER BY 1", env=env)
    produit = _psql(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND ("
        f"has_table_privilege('{a}', c.oid, 'INSERT') OR has_table_privilege('{a}', c.oid, 'UPDATE') "
        f"OR has_table_privilege('{a}', c.oid, 'DELETE') OR has_table_privilege('{a}', c.oid, 'TRUNCATE')) "
        "ORDER BY 1", env=env)
    lecture_produit = _psql(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE n.nspname = 'public' AND c.relkind IN ('r','p') "
        f"AND has_table_privilege('{a}', c.oid, 'SELECT') ORDER BY 1", env=env)
    definers = _psql(
        "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        f"WHERE n.nspname IN ('ingestion_control', 'public') AND p.prosecdef "
        f"AND has_function_privilege('{a}', p.oid, 'EXECUTE') ORDER BY 1", env=env)
    bases = _psql(
        f"SELECT datname FROM pg_database WHERE datallowconn "
        f"AND has_database_privilege('{a}', oid, 'CONNECT') ORDER BY 1", env=env)
    creation_schemas = _psql(
        "SELECT nspname FROM pg_namespace "
        f"WHERE has_schema_privilege('{a}', oid, 'CREATE') ORDER BY 1", env=env)
    return {
        "attributes": dict(zip(
            ("superuser", "createrole", "createdb", "replication", "bypassrls", "inherit", "login"),
            (x == "t" for x in attributs), strict=True)),
        "memberships": appartenances,
        "control_tables": {r[0]: [x == "t" for x in r[1:]] for r in tables},
        "product_writable": [r[0] for r in produit],
        "product_readable": [r[0] for r in lecture_produit],
        "security_definer_executable": [r[0] for r in definers],
        "connectable_databases": [r[0] for r in bases],
        "create_schemas": [r[0] for r in creation_schemas],
    }


def exiger_moindre_privilege(droits: Mapping[str, Any]) -> list[str]:
    """Écarts bloquants ; les accès hérités hors périmètre sont rapportés à part."""
    ecarts: list[str] = []
    attributs = droits["attributes"]
    if any(attributs[k] for k in ("superuser", "createrole", "createdb", "replication", "bypassrls", "inherit")):
        ecarts.append(f"attributs excessifs : {attributs}")
    if not attributs["login"]:
        ecarts.append("adopter sans LOGIN")
    if droits["memberships"]:
        ecarts.append("adopter membre d'un autre rôle")
    for table, (lire, inserer, maj, suppr, tronquer) in droits["control_tables"].items():
        if maj or suppr or tronquer:
            ecarts.append(f"{table} : UPDATE/DELETE/TRUNCATE")
        if inserer and table not in INSERTABLES:
            ecarts.append(f"{table} : INSERT hors périmètre")
        if lire != (table in LISIBLES):
            ecarts.append(f"{table} : SELECT {'absent' if table in LISIBLES else 'hors périmètre'}")
    for table in INSERTABLES:
        if not droits["control_tables"].get(table, [False, False])[1]:
            ecarts.append(f"{table} : INSERT requis absent")
    if droits["product_writable"]:
        ecarts.append(f"écriture produit : {droits['product_writable']}")
    if droits["security_definer_executable"]:
        ecarts.append(f"fonctions SECURITY DEFINER exécutables : {droits['security_definer_executable']}")
    if droits["create_schemas"]:
        ecarts.append(f"CREATE sur schémas : {droits['create_schemas']}")
    if DATABASE not in droits["connectable_databases"]:
        ecarts.append("CONNECT absent sur la base cible")
    return ecarts


def constats_herites(droits: Mapping[str, Any]) -> list[str]:
    """Accès hérités de PUBLIC hors de ce mandat : rapportés, jamais corrigés."""
    constats = []
    autres = [b for b in droits["connectable_databases"] if b != DATABASE]
    if autres:
        constats.append(f"CONNECT hérité de PUBLIC sur {autres}")
    if droits["product_readable"]:
        constats.append(f"lecture produit héritée : {droits['product_readable']}")
    return constats


# ── apply ────────────────────────────────────────────────────────────────────


def _ligne(cle: str, **champs: object) -> None:
    print(f"HGGSP_CONTROL020_{cle} " + " ".join(f"{k}={v}" for k, v in champs.items()), flush=True)


def _exiger_sauvegarde(chemin: Path) -> str:
    try:
        etat = chemin.lstat()
    except FileNotFoundError as exc:
        raise Refus("sauvegarde de la base cible absente") from exc
    if not stat.S_ISREG(etat.st_mode) or stat.S_IMODE(etat.st_mode) != 0o600 or etat.st_size == 0:
        raise Refus("sauvegarde de la base cible vide, non ordinaire ou non 0600")
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def appliquer(
    env: Mapping[str, str], racine: Path, *, fichier_secret: Path, roles_dir: Path,
    sauvegarde: Path,
) -> dict[str, Any]:
    observation = observer(env, racine)
    exiger_prevol(observation)
    _ligne("PREFLIGHT", head=observation["head"], adopter=observation["adopter_role_exists"],
           v2=observation["v2_adoptions"])
    secret = lire_secret(fichier_secret)
    if observation["adopter_role_exists"]:
        if secret is None:
            raise Refus("rôle adopter présent mais secret conservé introuvable : "
                        "aucune réinitialisation automatique")
        if not connexion_adopter(env, secret):
            raise Refus("rôle adopter présent et secret conservé incohérents : "
                        "aucune réinitialisation automatique")
        etat_secret = "reused_verified"
    elif secret is None:
        secret = creer_secret(fichier_secret)
        etat_secret = "created"
    else:
        etat_secret = "reused_before_role"
    _ligne("SECRET", state=etat_secret, mode="0600")
    avant = empreintes(env)
    if observation["head"] == HEAD_AVANT:
        empreinte_sauvegarde = _exiger_sauvegarde(sauvegarde)
        _ligne("BACKUP", sha256=empreinte_sauvegarde)
        migration = subprocess.run(
            [str(racine / BOOTSTRAP)], env=dict(env), capture_output=True, text=True,
            check=False, timeout=600,
        )
        if migration.returncode != 0 or "BOOTSTRAP_COMPLETE" not in migration.stdout:
            raise Refus(f"migration 020 refusée : {migration.stderr.strip()[-400:]}")
        _ligne("MIGRATED", **{"from": HEAD_AVANT, "to": HEAD_APRES})
    else:
        _ligne("MIGRATED", state="already_020")
    apres_migration = observer(env, racine)
    if apres_migration["head"] != HEAD_APRES or apres_migration["registry_mismatches"]:
        raise Refus("tête 020 non prouvée après migration")
    contraintes = {r[0] for r in _psql(
        "SELECT conname FROM pg_constraint WHERE connamespace = 'ingestion_control'::regnamespace",
        env=env)}
    if not CONTRAINTES_020 <= contraintes:
        raise Refus(f"contraintes 020 absentes : {sorted(CONTRAINTES_020 - contraintes)}")
    provision = subprocess.run(
        [str(racine / PROVISIONNEUR)],
        env={**env, "INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER": verificateur_scram(secret)},
        capture_output=True, text=True, check=False, timeout=120,
    )
    if provision.returncode != 0 or "ADOPTER_ROLE_PROVISIONED" not in provision.stdout:
        raise Refus(f"provisionnement adopter refusé : {provision.stderr.strip()[-400:]}")
    if not connexion_adopter(env, secret):
        raise Refus("connexion adopter impossible avec le secret conservé")
    _ligne("ROLE", role=ADOPTER, login="verified")
    etats = role_env.ecrire(
        role_env.contenus(
            {"PGVECTOR_PORT": env.get("PGPORT", ""), "INGESTION_CONTROL_ADOPTER_PASSWORD": secret},
            database=DATABASE, fichiers=role_env.FICHIER_ADOPTER,
        ),
        dossier=roles_dir,
    )
    _ligne("DSN", file=FICHIER_DSN, state=etats[FICHIER_DSN], mode="0600")
    droits = droits_effectifs(env)
    ecarts = exiger_moindre_privilege(droits)
    if ecarts:
        raise Refus("droits adopter hors périmètre : " + "; ".join(ecarts))
    constats = constats_herites(droits)
    _ligne("PRIVILEGES", least_privilege="verified", inherited=json.dumps(constats, ensure_ascii=False))
    apres = empreintes(env)
    if apres != avant:
        change = sorted(t for t in avant if avant[t] != apres[t])
        raise Refus(f"données de contrôle modifiées : {change}")
    final = observer(env, racine)
    if final["v2_adoptions"] != observation["v2_adoptions"]:
        raise Refus("adoption V2 créée par l'étape préparatoire")
    _ligne("OK", head=HEAD_APRES, adopter=ADOPTER, v2=final["v2_adoptions"],
           control_fingerprints=hashlib.sha256(json.dumps(apres, sort_keys=True).encode()).hexdigest())
    return {"secret": etat_secret, "dsn": etats[FICHIER_DSN], "inherited": constats,
            "fingerprints": apres}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("observe", "apply"))
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--roles-dir", type=Path)
    parser.add_argument("--backup-file", type=Path)
    args = parser.parse_args(argv)
    env = dict(os.environ)
    try:
        if env.get("PGDATABASE") != DATABASE:
            raise Refus(f"PGDATABASE doit valoir {DATABASE}")
        if args.command == "observe":
            observation = observer(env, args.repository_root)
            print("HGGSP_CONTROL020_OBSERVED " + json.dumps(observation, sort_keys=True))
            exiger_prevol(observation)
            return 0
        if not (args.secret_file and args.roles_dir and args.backup_file):
            parser.error("apply : --secret-file, --roles-dir et --backup-file requis")
        appliquer(env, args.repository_root, fichier_secret=args.secret_file,
                  roles_dir=args.roles_dir, sauvegarde=args.backup_file)
    except (Refus, role_env.DerivationRefusee, OSError) as exc:
        print(f"HGGSP_CONTROL020_REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
