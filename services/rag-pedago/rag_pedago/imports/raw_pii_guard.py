"""Vérifier qu'un artefact de gouvernance ne porte aucune donnée personnelle brute.

**Pourquoi ce module existe.** Les artefacts de gouvernance déclarent
`raw_pii_in_output: false`. Une déclaration n'est pas une mesure : rien, jusqu'ici,
ne confrontait ce drapeau au contenu réel du fichier. Ce module fait la mesure.

**La difficulté propre à ces artefacts.** Ils sont presque entièrement composés
d'empreintes — SHA-256 de contenu, de politique, de scanner, de paquet de revue,
SHA-1 de blob Git. Un digest hexadécimal contient, par construction, des suites
de chiffres, et une suite de dix chiffres commençant par 0 se lit exactement
comme un numéro de téléphone français. Scanner sans précaution fait crier la
garde sur ses propres empreintes.

**Le remède, et sa limite.** On neutralise les digests avant de scanner. Mais
neutraliser trop serait bien pire que ne rien neutraliser : effacer « tout ce
qui appartient à l'alphabet hexadécimal » effacerait aussi `0612345678`, et la
garde certifierait alors l'absence de ce qu'elle vient d'effacer. La règle est
donc étroite et se lit comme telle : un token de **digest complet et délimité**
— 64 caractères hexadécimaux, ou 40 pour un blob Git, éventuellement préfixé
`sha256:`. Ni 63, ni 65, ni une chaîne courte.

**La garde ne recopie jamais ce qu'elle dénonce.** Un finding porte la classe,
la position et l'empreinte de la correspondance, jamais sa matière : autrement
le rapport de la garde deviendrait lui-même la fuite qu'il signale.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from rag_pedago.imports.pii_scanner import (
    PIIPattern,
    is_allowlisted,
    load_patterns_from_config,
)

#: Politique canonique. Le garde ne définit pas ses propres motifs : il
#: réutilise ceux sous lesquels le corpus a été scanné et la revue rendue.
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "pii_gate_policy.yml"
)

#: Masque de même longueur que le digest remplacé, pour que les positions
#: rapportées restent celles du fichier. Le caractère n'appartient à l'alphabet
#: d'aucun motif de la politique : il ne peut donc pas fabriquer de
#: correspondance qui n'existait pas.
_MASK_CHAR = "█"

#: Un digest, et rien qui lui ressemble. Les bornes interdisent qu'une suite
#: hexadécimale plus longue (65, 104…) soit rognée à la bonne taille : c'est
#: ce qui distingue « reconnaître un digest » de « effacer de l'hexadécimal ».
_DIGEST_TOKEN = re.compile(
    r"(?<![0-9A-Za-z])(?:sha256:)?(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9A-Za-z])"
)


@dataclass(frozen=True)
class RawPiiFinding:
    """Une correspondance, décrite sans sa matière."""

    pattern_id: str
    description: str
    char_offset: int
    match_length: int
    match_sha256: str


def neutralise_digest_tokens(text: str) -> str:
    """Remplace chaque token de digest par un masque de même longueur.

    Conservée pour ce qu'elle montre, et utilisée par les tests qui fixent la
    frontière exacte d'un token. `find_raw_pii` ne s'en sert PLUS pour décider :
    voir la note qui y est portée."""
    return _DIGEST_TOKEN.sub(lambda m: _MASK_CHAR * len(m.group(0)), text)


def digest_token_spans(text: str) -> list[tuple[int, int]]:
    """Positions des tokens de digest, dans le texte d'origine."""
    return [(m.start(), m.end()) for m in _DIGEST_TOKEN.finditer(text)]


def find_raw_pii(
    text: str, *, patterns: list[PIIPattern] | None = None
) -> list[RawPiiFinding]:
    """Rend les correspondances PII du texte, hors empreintes.

    **Pourquoi on ne masque plus avant de chercher.** La première version
    remplaçait les digests par un masque, puis cherchait la PII dans le texte
    amputé. Une adresse dont la partie locale ou le domaine contient un
    composant hexadécimal de quarante caractères — `<40hex>@example.com`,
    `jean@<40hex>.example` — y perdait sa syntaxe et cessait d'être détectée.
    La garde certifiait alors l'absence de ce qu'elle venait elle-même
    d'effacer, ce qui est la seule façon de rendre une garde pire qu'inexistante.

    Le principe est donc inversé : on cherche dans le texte D'ORIGINE, et l'on
    n'écarte une correspondance que si elle est ENTIÈREMENT contenue dans un
    token de digest. Un digest ne peut plus absorber ce qui le déborde ; une
    suite de chiffres interne à une empreinte reste, elle, écartée."""
    if patterns is None:
        patterns = load_patterns_from_config(DEFAULT_POLICY_PATH)
    spans = digest_token_spans(text)

    def inside_a_digest(start: int, end: int) -> bool:
        return any(begin <= start and end <= stop for begin, stop in spans)

    findings: list[RawPiiFinding] = []
    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            matched = match.group(0)
            if inside_a_digest(match.start(), match.end()):
                continue
            if is_allowlisted(matched):
                continue
            findings.append(
                RawPiiFinding(
                    pattern_id=pattern.pattern_id,
                    description=pattern.description,
                    char_offset=match.start(),
                    match_length=len(matched),
                    match_sha256=sha256(matched.encode("utf-8")).hexdigest(),
                )
            )
    return sorted(findings, key=lambda f: (f.char_offset, f.pattern_id))


class RawPiiLeakError(ValueError):
    """Un artefact de gouvernance porte de la matière brute — refus."""


def require_no_raw_pii(
    document: object, *, label: str, patterns: list[PIIPattern] | None = None
) -> None:
    """Mesure un document AVANT qu'il n'atteste ne rien porter.

    **Pourquoi cette fonction existe.** Les preuves de gouvernance déclarent
    `raw_pii_in_output: false`. C'était une CONSTANTE : le producteur affirmait
    que sa preuve ne porte aucune donnée personnelle sans jamais l'avoir
    regardée. Une attestation qu'aucune mesure ne fonde dit ce que son auteur
    croit, pas ce que le fichier contient — et c'est précisément la famille de
    défauts que ce dépôt cherche à éliminer.

    L'attestation ne peut désormais être émise qu'après cette mesure, et un
    finding est un refus.

    Le refus lui-même ne recopie jamais la matière : il en donne la classe, la
    position et l'empreinte. Un rapport de fuite qui cite la fuite EST la
    fuite."""
    if patterns is None:
        patterns = load_patterns_from_config(DEFAULT_POLICY_PATH)
    rendered = json.dumps(document, ensure_ascii=False, sort_keys=True, default=str)
    findings = find_raw_pii(rendered, patterns=patterns)
    if findings:
        classes = sorted({finding.pattern_id for finding in findings})
        first = findings[0]
        raise RawPiiLeakError(
            f"{label} carries raw personal data and cannot attest otherwise: "
            f"{len(findings)} finding(s), classes {classes}, first at offset "
            f"{first.char_offset} (match {first.match_sha256[:16]}…)"
        )


def audit_paths(paths: list[Path]) -> dict[Path, list[RawPiiFinding]]:
    """Mesure plusieurs artefacts d'un coup, en chargeant la politique une fois."""
    patterns = load_patterns_from_config(DEFAULT_POLICY_PATH)
    return {
        path: find_raw_pii(path.read_text(encoding="utf-8"), patterns=patterns)
        for path in paths
    }


__all__ = [
    "DEFAULT_POLICY_PATH",
    "RawPiiFinding",
    "RawPiiLeakError",
    "audit_paths",
    "digest_token_spans",
    "find_raw_pii",
    "require_no_raw_pii",
    "neutralise_digest_tokens",
]
