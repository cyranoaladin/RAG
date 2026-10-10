#!/usr/bin/env python3
"""Pin indépendant de la cible staging publique, lié à une review GitHub exacte.

Le mode capture est une observation locale non approuvée. Seul le mode verify
retourne un digest utilisable par un signer, après relecture live et approbation
GitHub du blob exact dans le HEAD. Aucun secret ou DSN n'est journalisé.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
from typing import Mapping


PIN_KIND = "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1"
REPOSITORY = "cyranoaladin/RAG"
REVIEWER = "abenrhouma"
PIN_DIRECTORY = Path("governance/staging_target_pins")
MAX_VALIDITY = timedelta(hours=24)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
CONTAINER_IDENTITY = re.compile(r"docker:([0-9a-f]{64})\Z")
SYSTEM_IDENTIFIER = re.compile(r"[0-9]{1,20}\Z")
PIN_FIELDS = frozenset({
    "kind", "content_anchor_sha256", "release_id", "target_identity",
    "hostname", "host_machine_id_sha256", "postgres_system_identifier",
    "database_name", "destination_realpath", "destination_device",
    "destination_inode", "pinned_at_utc", "expires_at_utc",
})
IDENTITY_SQL = (
    "SELECT system_identifier::pg_catalog.text, "
    "pg_catalog.current_database(), pg_catalog.inet_server_addr()::pg_catalog.text "
    "FROM pg_catalog.pg_control_system()"
)


class PinRefused(ValueError):
    """Le pin, sa cible ou son approbation ne sont pas opposables."""


@dataclass(frozen=True)
class LiveTargetObservation:
    hostname: str
    host_machine_id_sha256: str
    container_id: str
    postgres_system_identifier: str
    database_name: str
    destination_realpath: str
    destination_device: int
    destination_inode: int


def canonical(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PinRefused("fenêtre UTC absente")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise PinRefused("fenêtre UTC invalide") from error
    if result.tzinfo != UTC:
        raise PinRefused("fenêtre UTC invalide")
    return result


def _directory_snapshot(path: Path) -> tuple[str, tuple[tuple[int, int], ...]]:
    if not path.is_absolute() or ".." in path.parts:
        raise PinRefused("destination non absolue ou non normalisée")
    current = Path(path.anchor)
    chain: list[tuple[int, int]] = []
    try:
        for component in path.parts[1:]:
            current /= component
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise PinRefused("destination contenant un symlink ou non répertoire")
            chain.append((metadata.st_dev, metadata.st_ino))
        if not chain:
            raise PinRefused("destination racine interdite")
        return str(path.resolve(strict=True)), tuple(chain)
    except OSError as error:
        raise PinRefused("destination indisponible") from error


def _directory_identity(path: Path) -> str:
    return _directory_snapshot(path)[0]


def verify_target_pin(
    raw: bytes, *, expected_sha256: str, expected_content_anchor_sha256: str,
    destination_root: Path, observation: LiveTargetObservation, now: datetime,
) -> str:
    """Comparer les octets approuvables au vivant; ne prononce pas l'approbation."""
    if not SHA256.fullmatch(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise PinRefused("digest du pin divergent")
    if not SHA256.fullmatch(expected_content_anchor_sha256):
        raise PinRefused("ancre A invalide")
    try:
        pin = json.loads(raw)
        if not isinstance(pin, dict):
            raise PinRefused("pin JSON non objet")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PinRefused("pin JSON invalide") from error
    if not isinstance(pin, dict) or set(pin) != PIN_FIELDS or canonical(pin) != raw:
        raise PinRefused("pin non canonique ou schéma divergent")
    container_match = CONTAINER_IDENTITY.fullmatch(str(pin["target_identity"]))
    if (pin["kind"] != PIN_KIND
            or pin["content_anchor_sha256"] != expected_content_anchor_sha256
            or not isinstance(pin["release_id"], str)
            or not pin["release_id"].startswith("student-public-")
            or container_match is None
            or not isinstance(pin["hostname"], str) or not pin["hostname"]
            or not isinstance(pin["host_machine_id_sha256"], str)
            or SHA256.fullmatch(pin["host_machine_id_sha256"]) is None
            or not isinstance(pin["postgres_system_identifier"], str)
            or SYSTEM_IDENTIFIER.fullmatch(pin["postgres_system_identifier"]) is None
            or not isinstance(pin["database_name"], str) or not pin["database_name"]):
        raise PinRefused("identité du pin invalide")
    if (type(pin["destination_device"]) is not int or pin["destination_device"] < 0
            or type(pin["destination_inode"]) is not int or pin["destination_inode"] <= 0):
        raise PinRefused("identité physique du pin invalide")
    pinned = _utc(pin["pinned_at_utc"])
    expires = _utc(pin["expires_at_utc"])
    if now.tzinfo != UTC or not pinned <= now < expires or expires - pinned > MAX_VALIDITY:
        raise PinRefused("pin hors fenêtre UTC courte")
    snapshot = _directory_snapshot(destination_root)
    destination, chain = snapshot
    if (pin["destination_realpath"] != destination
            or observation.destination_realpath != destination
            or (pin["destination_device"], pin["destination_inode"]) != chain[-1]
            or (observation.destination_device, observation.destination_inode) != chain[-1]
            or pin["hostname"] != observation.hostname
            or pin["host_machine_id_sha256"] != observation.host_machine_id_sha256
            or container_match.group(1) != observation.container_id
            or pin["postgres_system_identifier"] != observation.postgres_system_identifier
            or pin["database_name"] != observation.database_name):
        raise PinRefused("cible observée différente du pin")
    if _directory_snapshot(destination_root) != snapshot:
        raise PinRefused("destination remplacée pendant la vérification")
    return expected_sha256


def _git_blob(repo: Path, head: str, relative: Path) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{head}:{relative.as_posix()}"],
            check=True, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise PinRefused("blob du pin absent du HEAD approuvé") from error
    return result.stdout


def approved_pin_sha256(
    repo: Path, pin_path: Path, raw: bytes, *, decision: Mapping[str, object],
    challenges: Mapping[str, str], expected_base_sha: str,
    expected_head_sha: str, pull_request: int,
) -> str:
    """Lier le pin local au blob du HEAD dont la review canonique est valide."""
    if (pin_path.is_absolute() or ".." in pin_path.parts
            or pin_path.parent != PIN_DIRECTORY or pin_path.suffix != ".json"
            or not SHA40.fullmatch(expected_base_sha)
            or not SHA40.fullmatch(expected_head_sha)
            or type(pull_request) is not int or pull_request <= 0):
        raise PinRefused("portée Git du pin invalide")
    local = repo / pin_path
    if local.is_symlink() or not local.is_file() or local.read_bytes() != raw:
        raise PinRefused("pin local substitué")
    if _git_blob(repo, expected_head_sha, pin_path) != raw:
        raise PinRefused("pin non couvert par le HEAD approuvé")
    if (decision.get("approved") is not True
            or decision.get("repository") != REPOSITORY
            or decision.get("pull_request") != pull_request
            or decision.get("base_sha") != expected_base_sha
            or decision.get("head_sha") != expected_head_sha
            or decision.get("reviewer") != REVIEWER
            or type(decision.get("review_id")) is not int
            or decision["review_id"] <= 0
            or not isinstance(decision.get("challenge"), str)
            or decision["challenge"] != challenges.get(REVIEWER)):
        raise PinRefused("review humaine exacte absente ou divergente")
    return hashlib.sha256(raw).hexdigest()


def verify_docker_postgres_binding(container: Mapping[str, object],
                                   container_id: str, server_ip: str | None) -> None:
    """Le serveur SQL atteint doit être l'adresse du conteneur épinglé."""
    try:
        networks = container["NetworkSettings"]["Networks"]
        ips = {value[key] for value in networks.values()
               for key in ("IPAddress", "GlobalIPv6Address") if value.get(key)}
        running = container["State"]["Running"] is True
    except (KeyError, TypeError, AttributeError) as error:
        raise PinRefused("preuve réseau Docker malformée") from error
    if container.get("Id") != container_id or not running or not ips:
        raise PinRefused("conteneur PostgreSQL absent, arrêté ou sans réseau")
    if server_ip is None or server_ip not in ips:
        raise PinRefused("PostgreSQL connecté hors du conteneur épinglé")


def observe_live_target(*, container_id: str, destination_root: Path,
                        database_dsn: str) -> LiveTargetObservation:
    """Sondes locales lecture seule; PostgreSQL natif et socket sont refusés."""
    if not re.fullmatch(r"[0-9a-f]{64}", container_id) or not database_dsn:
        raise PinRefused("cible conteneur ou DSN de lecture absent")
    before = _directory_snapshot(destination_root)
    try:
        inspection = subprocess.run(
            ["docker", "inspect", "--type", "container", container_id],
            check=True, capture_output=True, timeout=10,
        )
        containers = json.loads(inspection.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError) as error:
        raise PinRefused("inspection Docker indisponible") from error
    if not isinstance(containers, list) or len(containers) != 1:
        raise PinRefused("conteneur PostgreSQL ambigu")
    container = containers[0]
    machine_id_path = Path("/etc/machine-id")
    if machine_id_path.is_symlink() or not machine_id_path.is_file():
        raise PinRefused("machine-id de l'hôte indisponible")
    machine_id = machine_id_path.read_bytes().strip().lower()
    if re.fullmatch(rb"[0-9a-f]{32}", machine_id) is None:
        raise PinRefused("machine-id de l'hôte invalide")
    try:
        import psycopg  # noqa: PLC0415

        with psycopg.connect(
            database_dsn, connect_timeout=3,
            options=("-c default_transaction_read_only=on -c statement_timeout=3000 "
                     "-c search_path=pg_catalog"),
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(IDENTITY_SQL)
                row = cursor.fetchone()
    except Exception as error:
        raise PinRefused("identité PostgreSQL en lecture seule indisponible") from error
    if (not isinstance(row, tuple) or len(row) != 3
            or not isinstance(row[0], str) or not isinstance(row[1], str)):
        raise PinRefused("identité PostgreSQL malformée")
    verify_docker_postgres_binding(container, container_id, row[2])
    after = _directory_snapshot(destination_root)
    if after != before:
        raise PinRefused("destination modifiée pendant l'observation")
    return LiveTargetObservation(
        hostname=socket.gethostname(),
        host_machine_id_sha256=hashlib.sha256(machine_id).hexdigest(),
        container_id=container_id,
        postgres_system_identifier=row[0], database_name=row[1],
        destination_realpath=after[0],
        destination_device=after[1][-1][0],
        destination_inode=after[1][-1][1],
    )


def _write_new_file(path: Path, raw: bytes) -> None:
    """Créer seulement un nouveau fichier dans un parent stable sans symlink."""
    if path.name in {"", ".", ".."} or ".." in path.parts:
        raise PinRefused("chemin de sortie invalide")
    parent = path.parent if path.is_absolute() else Path.cwd() / path.parent
    before = _directory_snapshot(parent)
    directory_fd = -1
    file_fd = -1
    created = False
    try:
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(directory_fd)
        if (metadata.st_dev, metadata.st_ino) != before[1][-1]:
            raise PinRefused("parent de sortie remplacé")
        file_fd = os.open(
            path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        created = True
        with os.fdopen(file_fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(file_fd)
        if _directory_snapshot(parent) != before:
            raise PinRefused("parent de sortie remplacé pendant l'écriture")
    except OSError as error:
        if created:
            try:
                os.unlink(path.name, dir_fd=directory_fd)
            except OSError:
                pass
        raise PinRefused("sortie absente, déjà existante ou symbolique") from error
    except PinRefused:
        if created:
            os.unlink(path.name, dir_fd=directory_fd)
        raise
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    capture = sub.add_parser("capture", help="émettre un pin non approuvé")
    capture.add_argument("--content-anchor-sha256", required=True)
    capture.add_argument("--release-id", required=True)
    capture.add_argument("--container-id", required=True)
    capture.add_argument("--destination-root", type=Path, required=True)
    capture.add_argument("--database-dsn-env", required=True)
    capture.add_argument("--valid-hours", type=int, default=12)
    capture.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify", help="sortir le digest seulement après review live")
    verify.add_argument("--repository-root", type=Path, required=True)
    verify.add_argument("--pin-path", type=Path, required=True)
    verify.add_argument("--content-anchor-sha256", required=True)
    verify.add_argument("--destination-root", type=Path, required=True)
    verify.add_argument("--database-dsn-env", required=True)
    verify.add_argument("--pull-request", type=int, required=True)
    verify.add_argument("--expected-base-sha", required=True)
    verify.add_argument("--expected-head-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dsn = os.environ.get(args.database_dsn_env, "")
        if args.action == "capture":
            if not 1 <= args.valid_hours <= 24:
                raise PinRefused("validité du pin hors 1-24 h")
            observed = observe_live_target(
                container_id=args.container_id,
                destination_root=args.destination_root, database_dsn=dsn,
            )
            now = datetime.now(UTC)
            pin = {
                "kind": PIN_KIND,
                "content_anchor_sha256": args.content_anchor_sha256,
                "release_id": args.release_id,
                "target_identity": f"docker:{observed.container_id}",
                "hostname": observed.hostname,
                "host_machine_id_sha256": observed.host_machine_id_sha256,
                "postgres_system_identifier": observed.postgres_system_identifier,
                "database_name": observed.database_name,
                "destination_realpath": observed.destination_realpath,
                "destination_device": observed.destination_device,
                "destination_inode": observed.destination_inode,
                "pinned_at_utc": now.isoformat().replace("+00:00", "Z"),
                "expires_at_utc": (now + timedelta(hours=args.valid_hours)).isoformat().replace("+00:00", "Z"),
            }
            raw = canonical(pin)
            verify_target_pin(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                              expected_content_anchor_sha256=args.content_anchor_sha256,
                              destination_root=args.destination_root,
                              observation=observed, now=now)
            _write_new_file(args.output, raw)
            print("PIN_CAPTURED_UNAPPROVED=true")
            print(f"TARGET_PIN_SHA256={hashlib.sha256(raw).hexdigest()}")
            return 0

        raw = (args.repository_root / args.pin_path).read_bytes()
        pin = json.loads(raw)
        match = CONTAINER_IDENTITY.fullmatch(str(pin.get("target_identity")))
        if match is None:
            raise PinRefused("pin sans conteneur épinglé")
        observed = observe_live_target(
            container_id=match.group(1), destination_root=args.destination_root,
            database_dsn=dsn,
        )
        pin_sha = hashlib.sha256(raw).hexdigest()
        verify_target_pin(raw, expected_sha256=pin_sha,
                          expected_content_anchor_sha256=args.content_anchor_sha256,
                          destination_root=args.destination_root,
                          observation=observed, now=datetime.now(UTC))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github"))
        from trusted_human_review_github import check_github_review  # noqa: PLC0415

        reviewed = check_github_review(
            repository=REPOSITORY, pull_request_number=args.pull_request,
            expected_head=args.expected_head_sha,
        )
        approved_pin_sha256(
            args.repository_root, args.pin_path, raw,
            decision=asdict(reviewed.decision), challenges=reviewed.challenges,
            expected_base_sha=args.expected_base_sha,
            expected_head_sha=args.expected_head_sha,
            pull_request=args.pull_request,
        )
        observed_final = observe_live_target(
            container_id=match.group(1), destination_root=args.destination_root,
            database_dsn=dsn,
        )
        verify_target_pin(raw, expected_sha256=pin_sha,
                          expected_content_anchor_sha256=args.content_anchor_sha256,
                          destination_root=args.destination_root,
                          observation=observed_final, now=datetime.now(UTC))
        print("INDEPENDENT_STAGING_TARGET_PIN_PASS=true")
        print(f"EXPECTED_TARGET_PIN_SHA256={pin_sha}")
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(f"PIN_REFUSED={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
