"""Producteur du reçu de liaison de revue scellé (ADR-0035).

**Ce que cet outil fait.** Il traduit une vérification GitHub *en ligne*,
rendue par le vérificateur canonique d'ADR-0025, en une preuve *hors ligne*
que le plan de contrôle pédagogique peut vérifier sans réseau et sans
importer ce service.

**Ce qu'il ne fait pas.** Il ne décide rien sur la review : la décision
vient toujours de ``github_authority.verify_review``, elle-même adossée à
``trusted_human_review.evaluate_trusted_review``. Cet outil ne connaît ni
la politique de reviewers, ni la construction du challenge — il constate,
recoupe, et scelle. Aucun argument ne permet d'affirmer un fait : chaque
champ du reçu est lu depuis GitHub ou dérivé des octets relus.

**Fail-closed.** GitHub inaccessible, PR fermée, review non approuvée,
head divergent, artefact absent, reviewer égal à l'auteur, permission
insuffisante, challenge divergent : chacun de ces cas fait échouer l'outil
sans rien émettre. Il n'existe aucun chemin par lequel un reçu partiel ou
« best effort » soit écrit.

**Secrets.** La clé de signature n'est lue que dans
``NEXUS_REVIEW_BINDING_SIGNING_KEY``, jamais depuis un fichier du dépôt,
jamais générée, jamais imprimée — pas même tronquée. Le token GitHub reste
géré par ``github_authority`` et n'est jamais journalisé ici.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from ingestor.ingestion_control.github_authority import (
        GitHubAuthorityError,
        fetch_blob_at_ref,
        pull_request_actor_context,
        verify_review,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) — même discipline que
    # attest_publication_cli.py.
    from ingestion_control.github_authority import (
        GitHubAuthorityError,
        fetch_blob_at_ref,
        pull_request_actor_context,
        verify_review,
    )

from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
    parse_scope_authorization_artifact,
)
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ReviewBindingError,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    parse_trust_anchor,
    public_key_hex,
    require_challenge_is_bound,
    require_matches_authorization,
    sign_review_binding,
)

#: Version de CE producteur, inscrite dans chaque reçu. Un consommateur peut
#: ainsi refuser les reçus émis par une version qu'il sait défectueuse.
VERIFIER_VERSION = "nexus-review-binding-producer/1"

#: Durée de vie par défaut d'un reçu. Une preuve de revue vieillit : au-delà,
#: il faut la réémettre, ce qui suppose que la PR reste approuvée à son HEAD.
DEFAULT_VALIDITY_DAYS = 30

SIGNING_KEY_ENV = "NEXUS_REVIEW_BINDING_SIGNING_KEY"


class ReviewBindingProductionError(RuntimeError):
    """Le reçu ne peut pas être produit — aucun octet n'est émis."""


#: Motifs de refus du préflight. Déterministes et stables : un opérateur, un
#: script de bundle et la CI doivent pouvoir brancher dessus sans lire de prose.
REASON_ANCHOR_ROTATED = "trust_anchor_rotated"
REASON_ANCHOR_UNREADABLE = "trust_anchor_unreadable"
REASON_ANCHOR_ENVIRONMENT = "trust_anchor_environment_mismatch"
REASON_PROTOCOL_MISMATCH = "review_binding_protocol_mismatch"
REASON_HEAD_DRIFTED = "pull_request_head_drifted"
REASON_CHALLENGE_MISMATCH = "challenge_mismatch"
REASON_KEY_UNDECLARED = "signing_key_not_declared_by_trust_anchor"


class SigningPreflightRefusal(ReviewBindingProductionError):
    """Refus du préflight, porteur d'un motif déterministe."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _load_current_trust_anchor(path: str) -> tuple[TrustAnchor, str]:
    """Lire l'ancre **canonique courante**, jamais celle d'un worktree figé.

    C'est le coeur du défaut fermé ici : un bundle validé contre l'arbre
    producteur qui l'a créé reste éternellement cohérent avec lui-même, y
    compris après qu'une clé a été déclarée perdue et remplacée. La seule
    autorité acceptable est le fichier d'ancre courant.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise SigningPreflightRefusal(REASON_ANCHOR_UNREADABLE, str(exc)) from exc
    try:
        anchor = parse_trust_anchor(raw)
    except ReviewBindingError as exc:
        message = str(exc)
        if "protocol_version" in message:
            raise SigningPreflightRefusal(REASON_PROTOCOL_MISMATCH, message) from exc
        raise SigningPreflightRefusal(REASON_ANCHOR_UNREADABLE, message) from exc
    if anchor.protocol_version != REVIEW_BINDING_PROTOCOL_VERSION:  # pragma: no cover
        raise SigningPreflightRefusal(REASON_PROTOCOL_MISMATCH, anchor.protocol_version)
    return anchor, hashlib.sha256(raw).hexdigest()


def _declared_key(anchor: TrustAnchor, key_id: str, environment: str):
    """Résoudre la clé dans l'ancre courante, en distinguant les deux refus.

    Un ``key_id`` absent est la signature exacte d'une rotation ; un
    environnement divergent est une erreur de cible, pas une rotation.
    """
    try:
        return anchor.key(key_id, environment=environment)
    except ReviewBindingError as exc:
        if "is not declared in the trust anchor" in str(exc):
            raise SigningPreflightRefusal(
                REASON_ANCHOR_ROTATED,
                f"key_id {key_id!r} is no longer declared by the current trust "
                f"anchor (declared: {', '.join(key.key_id for key in anchor.keys)})",
            ) from exc
        raise SigningPreflightRefusal(REASON_ANCHOR_ENVIRONMENT, str(exc)) from exc


def _require_anchor_declares_signing_key(
    anchor: TrustAnchor, key_id: str, environment: str, signing_key: str
) -> None:
    """Porte non contournable : l'émission consulte l'ancre elle-même.

    Le préflight est une commodité opérateur. Un bundle qui l'omettrait ne
    doit pas pouvoir sceller un reçu avec une clé que l'ancre ne déclare pas.
    """
    declared = _declared_key(anchor, key_id, environment)
    if public_key_hex(signing_key) != declared.public_key:
        raise SigningPreflightRefusal(
            REASON_KEY_UNDECLARED,
            f"the configured signing key does not match the public key declared "
            f"for {key_id!r} by the current trust anchor",
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Émet un reçu de liaison de revue scellé (ADR-0035) depuis une PR "
            "d'autorisation approuvée. Outil opérateur/CI uniquement : jamais "
            "un endpoint réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    issue = subparsers.add_parser(
        "issue",
        help=(
            "Vérifie la review en direct, relit l'autorisation au HEAD approuvé, "
            "puis écrit le reçu signé sur la sortie standard."
        ),
    )
    issue.add_argument("--repository", required=True)
    issue.add_argument("--pull-request", required=True, type=int)
    issue.add_argument(
        "--expected-head",
        required=True,
        help="SHA (40 hex) du HEAD exact de la PR d'autorisation.",
    )
    issue.add_argument(
        "--authorization-id",
        required=True,
        help=(
            "Identifiant canonique de l'autorisation. Son chemin Git en est "
            "dérivé — il n'est jamais fourni en argument."
        ),
    )
    issue.add_argument(
        "--validity-days",
        type=int,
        default=DEFAULT_VALIDITY_DAYS,
        help=f"Durée de vie du reçu en jours (défaut {DEFAULT_VALIDITY_DAYS}).",
    )
    issue.add_argument(
        "--key-id",
        required=True,
        help="Identifiant de la clé de signature, déclaré dans l'ancre de confiance.",
    )
    issue.add_argument(
        "--trust-anchor",
        required=True,
        help=(
            "Chemin de l'ancre de confiance CANONIQUE COURANTE. Jamais celle "
            "d'un worktree producteur figé : une ancre tournée doit rester "
            "visible."
        ),
    )
    issue.add_argument(
        "--environment",
        default="production",
        choices=("production", "test"),
        help="Environnement attendu de la clé (défaut production).",
    )

    preflight = subparsers.add_parser(
        "preflight",
        help=(
            "Vérifie, sans clé privée et sans rien émettre, qu'un bundle de "
            "signature est encore aligné sur l'état canonique courant."
        ),
    )
    preflight.add_argument("--repository", required=True)
    preflight.add_argument("--pull-request", required=True, type=int)
    preflight.add_argument("--expected-head", required=True)
    preflight.add_argument("--key-id", required=True)
    preflight.add_argument(
        "--trust-anchor",
        required=True,
        help="Ancre de confiance CANONIQUE COURANTE.",
    )
    preflight.add_argument(
        "--expected-anchor-sha256",
        default=None,
        help=(
            "SHA-256 de l'ancre contre laquelle le bundle a été construit. Une "
            "rotation qui conserverait le key_id reste ainsi détectable."
        ),
    )
    preflight.add_argument(
        "--expected-public-key",
        default=None,
        help="Clé publique que le bundle a enregistrée pour ce key_id.",
    )
    preflight.add_argument(
        "--expected-challenge",
        default=None,
        help="Challenge exact attendu, tel qu'il figure dans la review.",
    )
    preflight.add_argument(
        "--environment",
        default="production",
        choices=("production", "test"),
    )
    preflight.add_argument(
        "--offline",
        action="store_true",
        help="Ne pas interroger GitHub : ne vérifie alors que l'ancre.",
    )

    public = subparsers.add_parser(
        "public-key",
        help=(
            "Affiche la clé publique de la clé de signature configurée, pour "
            "alimenter un fichier d'ancre de confiance. N'affiche jamais la "
            "clé privée."
        ),
    )
    public.add_argument("--key-id", required=True)
    public.add_argument(
        "--environment",
        required=True,
        choices=("production", "test"),
        help="Environnement déclaré pour cette clé dans l'ancre de confiance.",
    )

    return parser


def _signing_key() -> str:
    key = os.environ.get(SIGNING_KEY_ENV, "").strip()
    if not key:
        raise ReviewBindingProductionError(
            f"{SIGNING_KEY_ENV} is not configured — the signing key is injected "
            "as a runtime secret only. It is never read from a repository file "
            "and never generated automatically."
        )
    return key


def _issue_binding(args: argparse.Namespace, *, now: datetime) -> bytes:
    """Produit les octets du reçu, ou lève. Aucune écriture partielle."""
    if args.validity_days <= 0 or args.validity_days > 365:
        raise ReviewBindingProductionError(
            "validity-days must be between 1 and 365 — an unbounded proof of "
            "review is not a proof"
        )
    signing_key = _signing_key()

    # 0. Ancre de confiance canonique COURANTE. Cette porte précède tout : une
    #    clé que l'ancre ne déclare plus ne doit sceller aucun reçu, même si le
    #    bundle qui l'invoque reste cohérent avec l'arbre qui l'a produit.
    anchor, _anchor_digest = _load_current_trust_anchor(args.trust_anchor)
    _require_anchor_declares_signing_key(
        anchor,
        args.key_id,
        getattr(args, "environment", "production"),
        signing_key,
    )

    # 1. Décision de review : rendue par le vérificateur canonique d'ADR-0025,
    #    jamais recalculée ici.
    try:
        live = verify_review(
            repository=args.repository,
            pull_request=args.pull_request,
            expected_head=args.expected_head,
        )
    except GitHubAuthorityError as exc:
        raise ReviewBindingProductionError(
            f"LIVE_REVIEW_VERIFICATION_FAILED: {exc} — failing closed, no receipt "
            "is emitted when GitHub cannot be reached or answered"
        ) from exc
    if not live.approved:
        raise ReviewBindingProductionError(
            f"REVIEW_NOT_APPROVED: PR #{args.pull_request} is not APPROVED at "
            f"{args.expected_head} (reason={live.reason})"
        )
    if live.reviewer is None or live.review_id is None or live.challenge is None:
        raise ReviewBindingProductionError(  # pragma: no cover - approved implique ces champs
            "APPROVED_REVIEW_IS_INCOMPLETE: the canonical verifier returned an "
            "approval without reviewer, review_id or challenge"
        )
    if live.submitted_at is None:  # pragma: no cover - idem
        raise ReviewBindingProductionError(
            "APPROVED_REVIEW_IS_INCOMPLETE: missing submitted_at"
        )

    # 2. Auteur et permission : deux faits que la décision ne rend pas, mais
    #    que le reçu doit nommer pour être vérifiable hors ligne.
    try:
        context = pull_request_actor_context(
            repository=args.repository,
            pull_request=args.pull_request,
            reviewer=live.reviewer,
        )
    except GitHubAuthorityError as exc:
        raise ReviewBindingProductionError(
            f"ACTOR_CONTEXT_UNAVAILABLE: {exc}"
        ) from exc
    if context.base_ref != "main":
        raise ReviewBindingProductionError(
            f"BASE_REF_UNSUPPORTED: {context.base_ref!r} — the trusted review "
            "protocol is bound to 'main'"
        )
    if context.author == live.reviewer:
        raise ReviewBindingProductionError(
            f"SELF_APPROVAL: {live.reviewer!r} authored this pull request — "
            "self-approval is never a human review"
        )
    if context.reviewer_permission not in ("admin", "write"):
        raise ReviewBindingProductionError(
            f"INSUFFICIENT_PERMISSION: {live.reviewer!r} holds "
            f"{context.reviewer_permission!r}"
        )

    # 3. Les octets réellement relus au HEAD approuvé — jamais un fichier
    #    local fourni par l'opérateur.
    path = canonical_authorization_path(args.authorization_id)
    try:
        blob = fetch_blob_at_ref(
            repository=args.repository, path=path, ref=live.head_sha
        )
    except GitHubAuthorityError as exc:
        raise ReviewBindingProductionError(
            f"AUTHORIZATION_UNREADABLE: {path}@{live.head_sha}: {exc}"
        ) from exc
    try:
        artifact = parse_scope_authorization_artifact(blob.content)
    except CanonicalArtifactError as exc:
        raise ReviewBindingProductionError(
            f"AUTHORIZATION_NOT_CANONICAL: {path}@{live.head_sha}: {exc}"
        ) from exc
    if not isinstance(artifact, ScopeAuthorizationArtifactV2):
        raise ReviewBindingProductionError(
            "AUTHORIZATION_PROTOCOL_UNSUPPORTED: the final gate binds only "
            f"LOT41A-V2 authorizations, got {artifact.protocol_version!r}"
        )
    if artifact.authorization_id != args.authorization_id:
        raise ReviewBindingProductionError(
            f"AUTHORIZATION_ID_MISMATCH: {path} declares "
            f"{artifact.authorization_id!r}"
        )
    if git_blob_sha1(blob.content) != blob.blob_sha:
        raise ReviewBindingProductionError(
            "AUTHORIZATION_BLOB_MISMATCH: the bytes GitHub returned do not hash "
            f"to the blob SHA-1 it reported ({blob.blob_sha})"
        )

    # 4. Le challenge doit être celui que les dimensions observées produisent —
    #    jamais celui que la review affiche pris pour argent comptant.
    recomputed = expected_challenge_digest(
        repository=args.repository,
        pull_request=args.pull_request,
        base_ref=context.base_ref,
        base_sha=live.base_sha,
        head_sha=live.head_sha,
        author=context.author,
        reviewer=live.reviewer,
    )
    if live.challenge != f"{TRUSTED_REVIEW_PROTOCOL}:{recomputed}":
        raise ReviewBindingProductionError(
            "CHALLENGE_MISMATCH: the approved review carries a challenge that "
            "the observed pull-request dimensions do not produce"
        )

    binding = ScopeAuthorizationReviewBindingV1(
        protocol_version=REVIEW_BINDING_PROTOCOL_VERSION,
        repository=args.repository,
        pull_request=args.pull_request,
        base_ref=context.base_ref,
        base_sha=live.base_sha,
        head_sha=live.head_sha,
        authorization_artifact_path=path,
        authorization_artifact_sha256=hashlib.sha256(blob.content).hexdigest(),
        authorization_artifact_git_blob_sha1=blob.blob_sha,
        authorization_id=artifact.authorization_id,
        authorization_decision=artifact.decision,
        review_id=int(live.review_id),
        reviewer_login=live.reviewer,
        reviewer_permission=context.reviewer_permission,
        author_login=context.author,
        submitted_at=datetime.fromisoformat(
            str(live.submitted_at).replace("Z", "+00:00")
        ),
        challenge_protocol=TRUSTED_REVIEW_PROTOCOL,
        challenge_digest=recomputed,
        verified_at=now,
        verifier_version=VERIFIER_VERSION,
        expires_at=now + timedelta(days=args.validity_days),
    )

    # 5. Auto-contrôle avant scellement : le reçu doit satisfaire le
    #    vérificateur hors ligne dès sa production. Un producteur qui émet
    #    une preuve que le consommateur refusera est un bug silencieux.
    require_challenge_is_bound(binding)
    require_matches_authorization(
        binding,
        authorization_id=artifact.authorization_id,
        authorization_bytes=blob.content,
        authorization_git_blob_sha1=blob.blob_sha,
        expected_repository=args.repository,
    )

    # ``nexus_contracts`` ne publie pas de marqueur ``py.typed`` : mypy voit
    # donc ``Any`` derrière cette frontière. Plutôt que de le masquer par un
    # ``cast`` non vérifié, la sortie du sceau est contrôlée à l'exécution —
    # ce producteur n'écrit jamais sur stdout autre chose que des octets.
    raw = sign_review_binding(
        binding, private_key_hex=signing_key, key_id=args.key_id
    ).canonical_bytes()
    if not isinstance(raw, bytes):
        raise ReviewBindingProductionError(
            "the signed receipt serializer returned "
            f"{type(raw).__name__}, not bytes — refusing to emit a receipt "
            "whose canonical form cannot be trusted"
        )
    return raw


def _cmd_issue(args: argparse.Namespace) -> int:
    try:
        raw = _issue_binding(args, now=datetime.now(UTC))
    except (ReviewBindingProductionError, ReviewBindingError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(raw.decode("utf-8"))
    return 0


def _cmd_public_key(args: argparse.Namespace) -> int:
    try:
        public = public_key_hex(_signing_key())
    except (ReviewBindingProductionError, ValueError):
        # Le message ne cite jamais la clé, même mal formée.
        print(
            f"{SIGNING_KEY_ENV} is missing or is not a 64-character lowercase "
            "hexadecimal Ed25519 seed",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "key_id": args.key_id,
                "algorithm": "ed25519",
                "public_key": public,
                "environment": args.environment,
            },
            sort_keys=True,
        )
    )
    return 0


def _run_preflight(args: argparse.Namespace) -> dict[str, str]:
    """Confronter le bundle à l'état canonique courant. N'émet aucun octet."""
    anchor, anchor_digest = _load_current_trust_anchor(args.trust_anchor)

    if (
        args.expected_anchor_sha256 is not None
        and args.expected_anchor_sha256.strip().lower() != anchor_digest
    ):
        raise SigningPreflightRefusal(
            REASON_ANCHOR_ROTATED,
            "the trust anchor changed since this bundle was produced",
        )

    declared = _declared_key(anchor, args.key_id, args.environment)

    if (
        args.expected_public_key is not None
        and args.expected_public_key.strip().lower() != declared.public_key
    ):
        raise SigningPreflightRefusal(
            REASON_ANCHOR_ROTATED,
            f"the public key declared for {args.key_id!r} is not the one this "
            "bundle recorded",
        )

    observed = {
        "TRUST_ANCHOR_KEY_ID": declared.key_id,
        "TRUST_ANCHOR_PUBLIC_KEY": declared.public_key,
        "TRUST_ANCHOR_ENVIRONMENT": declared.environment,
        "TRUST_ANCHOR_SHA256": anchor_digest,
    }
    if args.offline:
        observed["PULL_REQUEST_VERIFIED"] = "false"
        return observed

    try:
        live = verify_review(
            repository=args.repository,
            pull_request=args.pull_request,
            expected_head=args.expected_head,
        )
    except GitHubAuthorityError as exc:
        raise SigningPreflightRefusal(
            REASON_HEAD_DRIFTED,
            f"the pull request could not be verified live: {exc}",
        ) from exc

    if live.head_sha != args.expected_head:
        raise SigningPreflightRefusal(
            REASON_HEAD_DRIFTED,
            "the pull request head is no longer the reviewed one",
        )
    if not live.approved:
        raise SigningPreflightRefusal(
            REASON_HEAD_DRIFTED,
            f"the pull request is not approved at this head ({live.reason})",
        )
    if args.expected_challenge is not None and live.challenge != args.expected_challenge:
        raise SigningPreflightRefusal(
            REASON_CHALLENGE_MISMATCH,
            "the live review challenge is not the one this bundle recorded",
        )

    observed["PULL_REQUEST_VERIFIED"] = "true"
    observed["PULL_REQUEST_HEAD"] = live.head_sha
    return observed


def _cmd_preflight(args: argparse.Namespace) -> int:
    try:
        observed = _run_preflight(args)
    except SigningPreflightRefusal as refusal:
        print("SIGNING_PREFLIGHT_PASS=false", file=sys.stderr)
        print(f"REASON={refusal.reason}", file=sys.stderr)
        print(f"DETAIL={refusal}", file=sys.stderr)
        return 1
    except (ReviewBindingProductionError, ReviewBindingError, ValueError) as exc:
        print("SIGNING_PREFLIGHT_PASS=false", file=sys.stderr)
        print(f"REASON={REASON_ANCHOR_UNREADABLE}", file=sys.stderr)
        print(f"DETAIL={exc}", file=sys.stderr)
        return 1
    print("SIGNING_PREFLIGHT_PASS=true")
    for key, value in observed.items():
        print(f"{key}={value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "issue":
        return _cmd_issue(args)
    if args.command == "preflight":
        return _cmd_preflight(args)
    if args.command == "public-key":
        return _cmd_public_key(args)
    raise AssertionError(f"unreachable: unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main()
    sys.exit(main())


__all__ = [
    "DEFAULT_VALIDITY_DAYS",
    "REASON_ANCHOR_ROTATED",
    "SigningPreflightRefusal",
    "SIGNING_KEY_ENV",
    "VERIFIER_VERSION",
    "ReviewBindingProductionError",
    "main",
]
