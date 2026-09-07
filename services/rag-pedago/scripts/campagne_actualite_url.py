#!/usr/bin/env python3
"""Campagne d'OBSERVATION réseau des URL de provenance.

Ce script observe. Il ne conclut pas.

Un `200` prouve au mieux que quelque chose répond à cette URL — pas que le
document qu'on sert en est la version courante. Confondre les deux ferait
d'une page d'accueil la preuve d'actualité de tout ce qu'elle a un jour
référencé. Quatre dimensions sont donc tenues séparées : accessibilité,
provenance, identité de contenu, actualité.

Ce que ce script ne fait jamais :

* **contourner une protection** — un 403 est une observation, pas un obstacle à
  franchir. L'agent utilisateur est honnête et s'identifie ;
* **parcourir le site** — une URL demandée est une URL du registre, jamais un
  lien découvert ;
* **comparer l'empreinte d'une page HTML à celle d'un PDF** — ce serait une
  comparaison entre deux choses différentes, rendue vraie ou fausse par hasard ;
* **conclure « obsolète »** d'un 403, d'un 429 ou d'une panne réseau. Ne pas
  pouvoir vérifier n'est pas vérifier le contraire.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

KIND = "NEXUS-URL-CURRENTNESS-OBSERVATION-V1"

#: La politique de requête, SCELLÉE. Son empreinte entre dans l'identité du
#: run : deux campagnes menées sous des délais ou des limites différents ne
#: sont pas comparables, et un rapport qui ne la nomme pas ne se relit pas.
POLITIQUE = {
    "policy_id": "NEXUS-URL-CURRENTNESS-REQUEST-POLICY-V1",
    "connect_timeout": 10,
    "read_timeout": 20,
    "max_redirects": 5,
    "retry_count": 2,
    "retry_statuses": [429, 500, 502, 503, 504],
    "retry_backoff_seconds": [2, 5],
    "max_response_bytes": 1_048_576,
    "concurrency": 1,
    "per_host_rate_limit_seconds": 1.0,
    "user_agent": (
        "nexus-currentness/1.0 (+provenance verification of already-held "
        "documents; no crawling; contact via repository owner)"
    ),
    "tls_verification": True,
    "method_chain": "HEAD then bounded GET",
    "authentication": "none",
    "protection_bypass": "forbidden",
}

# --- dispositions d'OBSERVATION (accessibilité), jamais d'actualité ----
OBS_REACHABLE = "REACHABLE"
OBS_REDIRECT = "REDIRECT_OBSERVED"
OBS_UNVERIFIABLE = "UNVERIFIABLE_WITH_EVIDENCE"
OBS_INDISPONIBLE = "URL_NOT_AVAILABLE"
OBS_RESEAU = "NETWORK_ERROR"

# --- dispositions d'ACTUALITÉ, séparées -------------------------------
CUR_VERIFIED = "VERIFIED_CURRENT"
CUR_UNVERIFIED = "UNVERIFIED"
CUR_ERREUR = "ERROR"

#: Rôle OBSERVÉ de l'URL, et seulement observé.
#:
#: Une URL sans `.pdf` peut parfaitement servir un PDF, rediriger vers lui,
#: négocier le contenu, ou l'exposer par une route sans extension. Conclure du
#: seul suffixe serait une inférence lexicale — la même faute que déduire une
#: URL d'un slug. Et sur une réponse d'ERREUR, le `Content-Type` est celui de
#: la page d'erreur : il ne dit rien de la ressource. Le rôle n'est donc
#: observable que sur une réponse réussie.
ROLE_DIRECT = "CONFIRMED_DIRECT_RESOURCE"
ROLE_NAVIGATION = "CONFIRMED_NAVIGATION"
ROLE_INOBSERVABLE = "ROLE_UNOBSERVABLE"

#: Ce que le CATALOGUE dit du rôle, distinct de ce que HTTP montre. Les deux
#: sont conservés séparément : une sémantique documentaire n'est pas une
#: observation réseau.
INDICE_CATALOGUE_NAVIGATION = "NAVIGATION"


def normaliser(url: str) -> tuple[str, str | None]:
    """Rend (url normalisée, raison de la fusion) — sans jamais fusionner ce
    qui porte du sens.

    Le schéma, la casse du chemin, la requête et le fragment sont CONSERVÉS :
    `http` et `https`, deux chemins différents, ou un fragment métier ne
    désignent pas forcément la même ressource, et les confondre effacerait des
    relations distinctes. Seuls l'hôte — insensible à la casse par la norme —
    et un port par défaut explicite sont normalisés."""
    parts = urlsplit(url)
    hote = parts.netloc.lower()
    raison = None
    if hote != parts.netloc:
        raison = "HOST_CASE_FOLDED"
    for schema, port in (("https", ":443"), ("http", ":80")):
        if parts.scheme == schema and hote.endswith(port):
            hote = hote[: -len(port)]
            raison = "DEFAULT_PORT_REMOVED"
    return parts._replace(netloc=hote).geturl(), raison


def _role_observe(statut: int | None, content_type: str | None) -> str:
    """Le rôle n'est OBSERVÉ que sur une réponse réussie.

    Sur un 403, le `Content-Type` décrit la page de refus, pas la ressource :
    l'employer ferait dire à 110 refus qu'ils sont des pages de navigation.
    Et l'absence de `.pdf` dans l'URL ne prouve rien — une route sans extension
    peut servir un PDF."""
    if statut is None or not (200 <= statut < 300) or not content_type:
        return ROLE_INOBSERVABLE
    principal = content_type.split(";", 1)[0].strip().lower()
    if principal in ("application/pdf", "application/octet-stream"):
        return ROLE_DIRECT
    if principal.startswith("text/html"):
        return ROLE_NAVIGATION
    return ROLE_INOBSERVABLE


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Suit les redirections À LA MAIN, pour en conserver la chaîne.

    Un client qui les suit tout seul rend une URL finale sans dire par où il
    est passé : une redirection vers une page d'erreur devient alors
    indiscernable d'un accès direct."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def observer(url: str, *, politique: dict) -> dict[str, object]:
    """Une observation complète d'UNE URL, erreurs comprises."""
    # Le contexte TLS est porté par le HANDLER, pas passé à `open()` :
    # `OpenerDirector.open()` n'accepte pas `context`, et le lui donner lève un
    # TypeError que la boucle de reprise enregistrait comme NETWORK_ERROR — un
    # défaut de code se lisant comme une panne du serveur observé. C'est
    # exactement la confusion qu'une campagne d'observation ne doit pas produire.
    contexte = ssl.create_default_context()
    contexte.check_hostname = True
    contexte.verify_mode = ssl.CERT_REQUIRED
    ouvreur = urllib.request.build_opener(
        _SansRedirection, urllib.request.HTTPSHandler(context=contexte)
    )
    normalisee, fusion = normaliser(url)
    chaine: list[dict[str, object]] = []
    observation: dict[str, object] = {
        "original_url": url,
        "normalized_url": normalisee,
        "normalization_reason": fusion,
        "request_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "redirect_chain": chaine,
        "final_url": normalisee,
        "method": None,
        "status_code": None,
        "content_type": None,
        "etag": None,
        "last_modified": None,
        "content_length": None,
        "response_entity_sha256": None,
        "error_class": None,
        "attempts": 0,
    }

    courante = normalisee
    for _saut in range(int(politique["max_redirects"]) + 1):
        statut = corps = entetes = None
        derniere_erreur = None
        for methode in ("HEAD", "GET"):
            for essai in range(int(politique["retry_count"]) + 1):
                observation["attempts"] += 1
                requete = urllib.request.Request(
                    courante,
                    method=methode,
                    headers={"User-Agent": politique["user_agent"], "Accept": "*/*"},
                )
                try:
                    with ouvreur.open(
                        requete, timeout=politique["read_timeout"]
                    ) as reponse:
                        statut = reponse.status
                        entetes = reponse.headers
                        corps = (
                            reponse.read(int(politique["max_response_bytes"]))
                            if methode == "GET"
                            else None
                        )
                        derniere_erreur = None
                        break
                except urllib.error.HTTPError as exc:
                    statut, entetes, derniere_erreur = exc.code, exc.headers, None
                    if exc.code in politique["retry_statuses"] and essai < politique["retry_count"]:
                        time.sleep(politique["retry_backoff_seconds"][essai])
                        continue
                    break
                except Exception as exc:  # noqa: BLE001 - toute panne est une observation
                    derniere_erreur = f"{type(exc).__name__}"
                    if essai < politique["retry_count"]:
                        time.sleep(politique["retry_backoff_seconds"][essai])
                        continue
                    break
            observation["method"] = methode
            # `HEAD` est une optimisation, jamais une preuve suffisante : un
            # serveur peut le traiter autrement que `GET`. On passe au `GET`
            # borné dès que le HEAD ne donne pas une réponse exploitable.
            if statut is not None and 200 <= statut < 300 and methode == "HEAD":
                continue
            if statut is not None and not (300 <= statut < 400):
                break
            if statut is not None and 300 <= statut < 400:
                break
        if derniere_erreur is not None:
            observation["error_class"] = derniere_erreur
            return observation
        observation["status_code"] = statut
        if entetes is not None:
            observation["content_type"] = entetes.get("Content-Type")
            observation["etag"] = entetes.get("ETag")
            observation["last_modified"] = entetes.get("Last-Modified")
            observation["content_length"] = entetes.get("Content-Length")
        if corps is not None:
            observation["response_entity_sha256"] = hashlib.sha256(corps).hexdigest()
            observation["response_bytes_read"] = len(corps)
        if statut is not None and 300 <= statut < 400 and entetes is not None:
            cible = entetes.get("Location")
            if not cible:
                break
            cible = urllib.request.urljoin(courante, cible)
            chaine.append({"from": courante, "status": statut, "to": cible})
            courante = cible
            observation["final_url"] = cible
            time.sleep(politique["per_host_rate_limit_seconds"])
            continue
        break
    return observation


def qualifier(observation: dict[str, object], *, source_sha: str | None = None) -> dict[str, object]:
    """Sépare l'ACCESSIBILITÉ de l'ACTUALITÉ. Jamais `200 → VERIFIED_CURRENT`."""
    statut = observation.get("status_code")
    erreur = observation.get("error_class")
    role = _role_observe(statut, observation.get("content_type"))  # type: ignore[arg-type]
    resultat = {
        "http_observed_role": role,
        # Le catalogue documente `url_source` comme page de publication ; c'est
        # une sémantique DOCUMENTAIRE, enregistrée séparément et jamais
        # présentée comme une observation HTTP.
        "catalogue_role_hint": INDICE_CATALOGUE_NAVIGATION,
        "content_identity_match": None,
    }

    if erreur:
        resultat["observation"] = OBS_RESEAU
        resultat["currentness"] = CUR_ERREUR
        return resultat
    if statut is None:
        resultat["observation"] = OBS_RESEAU
        resultat["currentness"] = CUR_ERREUR
        return resultat
    if statut in (401, 403, 429):
        # Ne pas pouvoir vérifier n'est pas vérifier le contraire.
        resultat["observation"] = OBS_UNVERIFIABLE
        resultat["currentness"] = CUR_UNVERIFIED
        return resultat
    if statut in (404, 410):
        # L'URL ne rend rien. Cela ne dit RIEN du document qu'on détient :
        # une page peut disparaître sans que son contenu soit périmé.
        resultat["observation"] = OBS_INDISPONIBLE
        resultat["currentness"] = CUR_UNVERIFIED
        return resultat
    if 400 <= statut < 600:
        resultat["observation"] = OBS_UNVERIFIABLE if statut < 500 else OBS_RESEAU
        resultat["currentness"] = CUR_UNVERIFIED if statut < 500 else CUR_ERREUR
        return resultat

    resultat["observation"] = OBS_REDIRECT if observation["redirect_chain"] else OBS_REACHABLE
    if role == ROLE_DIRECT and source_sha and observation.get("response_entity_sha256"):
        # Comparer les octets N'A DE SENS que si l'URL rend le document
        # lui-même. Comparer une page de navigation au PDF serait une
        # comparaison entre deux choses différentes.
        identique = observation["response_entity_sha256"] == source_sha
        resultat["content_identity_match"] = identique
        resultat["currentness"] = CUR_VERIFIED if identique else CUR_UNVERIFIED
    else:
        # Une page institutionnelle accessible n'est pas la ressource.
        resultat["currentness"] = CUR_UNVERIFIED
    return resultat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0, help="0 = toutes")
    args = parser.parse_args(argv)

    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    relations = reconciliation["relations"]
    urls = sorted(
        {p["url_source"] for r in relations for p in r["url_evidence"] if p.get("url_source")}
    )
    if args.limit:
        urls = urls[: args.limit]

    gel = json.loads(args.freeze.read_text(encoding="utf-8"))
    normalisees = [normaliser(u) for u in urls]
    fusions = [
        {"original_url": u, "normalized_url": n, "reason": r}
        for u, (n, r) in zip(urls, normalisees, strict=True)
        if r
    ]

    par_hote_dernier: dict[str, float] = defaultdict(float)
    observations: list[dict[str, object]] = []
    for index, url in enumerate(urls, start=1):
        hote = urlsplit(url).netloc.lower()
        attente = par_hote_dernier[hote] + POLITIQUE["per_host_rate_limit_seconds"] - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        observation = observer(url, politique=POLITIQUE)
        par_hote_dernier[hote] = time.monotonic()
        observation.update(qualifier(observation))
        observation["evidence_id"] = f"{gel['CURRENTNESS_CAMPAIGN_RUN_ID'][:16]}:{index:04d}"
        observations.append(observation)
        print(
            f"  {index}/{len(urls)} {observation['status_code'] or observation['error_class']}"
            f" {observation['observation']} {url[:70]}",
            flush=True,
        )

    # Le dénominateur est la PAIRE (contenu, url), pas la ligne de preuve : un
    # même contenu peut être décrit par plusieurs lignes de catalogue portant
    # la même URL sous des scopes différents. Compter les lignes gonflait le
    # dénominateur — 2929 au lieu de 2542 — et faisait mentir la couverture.
    par_url = {str(o["original_url"]): o for o in observations}
    paires: set[tuple[str, str]] = set()
    paires_observees: set[tuple[str, str]] = set()
    for relation in relations:
        for preuve in relation["url_evidence"]:
            url = preuve.get("url_source")
            if not url:
                continue
            paire = (str(relation["content_sha256"]), str(url))
            paires.add(paire)
            if url in par_url:
                paires_observees.add(paire)
    avec = len(paires_observees)
    sans = len(paires - paires_observees)

    statuts = Counter(
        (o["status_code"] // 100 if isinstance(o["status_code"], int) else None)
        for o in observations
    )
    obs = Counter(str(o["observation"]) for o in observations)
    cur = Counter(str(o["currentness"]) for o in observations)
    roles = Counter(str(o["http_observed_role"]) for o in observations)

    verifies = cur[CUR_VERIFIED]
    rendu = {
        "kind": KIND,
        **gel,
        "EDUSCOL_DISTINCT_URLS": len(urls),
        "EDUSCOL_URLS_ATTEMPTED": len(observations),
        "EDUSCOL_URLS_UNACCOUNTED": len(urls) - len(observations),
        "RAW_DISTINCT_URLS": len(urls),
        "REQUEST_DISTINCT_URLS": len({n for n, _ in normalisees}),
        "URL_NORMALIZATION_COLLAPSES": len(urls) - len({n for n, _ in normalisees}),
        "normalization_ledger": fusions,
        "HTTP_2XX": statuts[2],
        "HTTP_3XX": statuts[3],
        "HTTP_4XX": statuts[4],
        "HTTP_5XX": statuts[5],
        "NETWORK_ERRORS_FINAL": obs[OBS_RESEAU],
        "REDIRECTED_URLS": sum(1 for o in observations if o["redirect_chain"]),
        "FINAL_DISTINCT_URLS": len({str(o["final_url"]) for o in observations}),
        "CONFIRMED_DIRECT_RESOURCE_URLS": roles[ROLE_DIRECT],
        "CONFIRMED_NAVIGATION_URLS": roles[ROLE_NAVIGATION],
        "ROLE_UNOBSERVABLE": roles[ROLE_INOBSERVABLE],
        "CATALOGUE_SEMANTIC_ROLE": INDICE_CATALOGUE_NAVIGATION,
        "DIRECT_CONTENT_MATCH": sum(1 for o in observations if o["content_identity_match"] is True),
        "DIRECT_CONTENT_MISMATCH": sum(
            1 for o in observations if o["content_identity_match"] is False
        ),
        "NAVIGATION_PAGE_REACHABLE": sum(
            1
            for o in observations
            if o["http_observed_role"] == ROLE_NAVIGATION
            and o["observation"] in (OBS_REACHABLE, OBS_REDIRECT)
        ),
        "UNVERIFIABLE_WITH_EVIDENCE": obs[OBS_UNVERIFIABLE],
        "URL_NOT_AVAILABLE": obs[OBS_INDISPONIBLE],
        "EDUSCOL_VERIFIED_CURRENT": verifies,
        "EDUSCOL_CURRENTNESS_UNVERIFIED": cur[CUR_UNVERIFIED],
        "EDUSCOL_CURRENTNESS_ERRORS": cur[CUR_ERREUR],
        "EDUSCOL_CURRENTNESS_UNACCOUNTED": len(observations) - sum(cur.values()),
        "EDUSCOL_ARTIFACT_URL_RELATIONS": len(paires),
        "RELATIONS_WITH_OBSERVATION": avec,
        "RELATIONS_WITHOUT_OBSERVATION": sans,
        # Compter n'est pas vérifier : les deux pourcentages sont publiés
        # séparément, pour qu'un dénominateur fermé ne se lise jamais comme une
        # vérification réussie.
        "EDUSCOL_CURRENTNESS_ACCOUNTED_PERCENT": (
            100 if len(observations) == sum(cur.values()) else 0
        ),
        "EDUSCOL_CURRENTNESS_VERIFIED_PERCENT": (
            round(100 * verifies / len(observations), 2) if observations else 0
        ),
        "observations": observations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rendu, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for cle, valeur in rendu.items():
        if not isinstance(valeur, (list, dict)):
            print(f"{cle}={valeur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
