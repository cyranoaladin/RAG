"""Centralized role-based security helpers for v2 endpoints."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
from enum import Enum

from fastapi import HTTPException, Request


class SecurityRole(str, Enum):
    """Supported v2 actor roles."""

    ADMIN = "admin"
    REVIEWER = "reviewer"
    TEACHER = "teacher"
    INGEST_AGENT = "ingest_agent"
    STUDENT = "student"


_ROLE_TOKEN_ENV = {
    SecurityRole.ADMIN: ("RAG_ADMIN_TOKEN",),
    SecurityRole.REVIEWER: ("RAG_REVIEWER_TOKEN", "REVIEWER_API_TOKEN"),
    SecurityRole.TEACHER: ("RAG_TEACHER_TOKEN",),
    SecurityRole.INGEST_AGENT: (
        "RAG_INGEST_AGENT_TOKEN",
        "INGESTOR_API_TOKEN",
        "INGEST_AUTH_TOKEN",
    ),
    SecurityRole.STUDENT: ("RAG_STUDENT_TOKEN",),
}


def _read_tokens_for_role(role: SecurityRole) -> tuple[str, ...]:
    """Return all configured tokens for a role."""
    tokens: list[str] = []
    seen: set[str] = set()
    for var_name in _ROLE_TOKEN_ENV[role]:
        token = (os.getenv(var_name) or "").strip()
        if token and token not in seen:
            tokens.append(token)
            seen.add(token)
    return tuple(tokens)


def _token_roles() -> dict[str, set[SecurityRole]]:
    roles_by_token: dict[str, set[SecurityRole]] = {}
    for role in _ROLE_TOKEN_ENV:
        for token in _read_tokens_for_role(role):
            roles_by_token.setdefault(token, set()).add(role)
    return roles_by_token


def _has_role_token_collision() -> bool:
    """Return True when one configured token maps to multiple roles."""
    return any(len(roles) > 1 for roles in _token_roles().values())


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    trusted_proxy_cidrs = (os.getenv("INGESTOR_TRUSTED_PROXY_CIDRS") or "").strip()
    if not trusted_proxy_cidrs:
        return ()

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for network in trusted_proxy_cidrs.split(","):
        candidate = network.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    if not networks:
        raise HTTPException(
            status_code=503,
            detail="trusted proxy configuration invalid",
        )
    return tuple(networks)


def _is_ip_in_networks(
    candidate_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    return any(candidate_ip in network for network in networks)


def _is_trusted_proxy(peer_ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return _is_ip_in_networks(peer_ip, _trusted_proxy_networks())


def _client_ip_from_x_forwarded_for(
    value: str,
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value.strip():
        return None

    parsed_chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for raw_candidate in value.split(","):
        candidate_value = raw_candidate.strip()
        if not candidate_value:
            return None
        parsed = _parse_ip(candidate_value)
        if parsed is None:
            return None
        parsed_chain.append(parsed)

    for candidate_ip in reversed(parsed_chain):
        if _is_ip_in_networks(candidate_ip, trusted_proxy_networks):
            continue
        return candidate_ip
    return None


def token_hash(token: str) -> str:
    """Return a short irreversible token fingerprint for provenance-only logs."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def extract_token(request: Request) -> str:
    """Extract Bearer token from headers."""
    headers = request.headers
    header_token = headers.get("x-api-token") or headers.get("X-API-Token")
    if isinstance(header_token, str) and header_token.strip():
        return header_token.strip()

    auth = headers.get("authorization") or headers.get("Authorization")
    if isinstance(auth, str) and auth.strip():
        value = auth.strip()
        if value.lower().startswith("bearer "):
            return value.split(" ", 1)[1].strip()
        return value

    return ""


def _token_matches(candidate: str, configured: str) -> bool:
    try:
        return hmac.compare_digest(
            candidate.encode("utf-8"),
            configured.encode("utf-8"),
        )
    except (TypeError, UnicodeError):
        return False


def _match_role(token: str) -> SecurityRole | None:
    if not token:
        return None

    for role in _ROLE_TOKEN_ENV:
        for configured_token in _read_tokens_for_role(role):
            if _token_matches(token, configured_token):
                return role
    return None


def _configured_roles(roles: set[SecurityRole]) -> list[SecurityRole]:
    return [role for role in roles if _read_tokens_for_role(role)]


def require_role(
    request: Request,
    *,
    allowed_roles: set[SecurityRole],
    endpoint: str,
    enforce_ip_allowlist: bool = False,
) -> tuple[SecurityRole, str]:
    """Validate request actor role for a secured endpoint.

    Returns:
        Tuple (resolved_role, token) when authorized.
    """

    if _has_role_token_collision():
        raise HTTPException(
            status_code=503,
            detail=f"{endpoint}: security token configuration invalid",
        )

    configured = _configured_roles(allowed_roles)
    if not configured:
        raise HTTPException(
            status_code=503,
            detail=f"{endpoint}: security token not configured",
        )

    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    role = _match_role(token)
    if role is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Forbidden")

    if enforce_ip_allowlist:
        enforce_ingestor_ip_allowlist(request)

    return role, token


def _resolve_client_ip(request: Request) -> str | None:
    client_host = request.client.host if request.client else ""
    peer_ip = _parse_ip(client_host)

    if peer_ip:
        trusted_proxy_networks = _trusted_proxy_networks()
        if not _is_ip_in_networks(peer_ip, trusted_proxy_networks):
            return str(peer_ip)
        forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
        forwarded_client_ip = _client_ip_from_x_forwarded_for(
            forwarded_for,
            trusted_proxy_networks,
        )
        if forwarded_client_ip:
            return str(forwarded_client_ip)

        return None
    return None


def enforce_ingestor_ip_allowlist(request: Request) -> None:
    """Enforce the ingestion allowlist with hardened trusted-proxy resolution."""
    allowlist = (os.getenv("INGESTOR_IP_ALLOWLIST") or "").strip()
    if not allowlist:
        return

    client_ip = _resolve_client_ip(request)
    if not client_ip:
        raise HTTPException(status_code=403, detail="Forbidden")

    client_address = ipaddress.ip_address(client_ip)

    for network in allowlist.split(","):
        candidate = network.strip()
        if not candidate:
            continue
        try:
            if client_address in ipaddress.ip_network(candidate, strict=False):
                return
        except ValueError:
            continue

    raise HTTPException(status_code=403, detail="Forbidden")


def configured_tokens() -> dict[str, list[str]]:
    """Expose configured tokens for diagnostics/tests (hashed only)."""
    return {
        role.value: [token_hash(token) for token in _read_tokens_for_role(role)]
        for role in _ROLE_TOKEN_ENV
    }
