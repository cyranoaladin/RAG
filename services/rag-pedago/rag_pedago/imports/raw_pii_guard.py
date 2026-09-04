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
    """Remplace chaque token de digest par un masque de même longueur."""
    return _DIGEST_TOKEN.sub(lambda m: _MASK_CHAR * len(m.group(0)), text)


def find_raw_pii(
    text: str, *, patterns: list[PIIPattern] | None = None
) -> list[RawPiiFinding]:
    """Rend les correspondances PII du texte, empreintes neutralisées.

    Le scan porte sur le texte masqué, mais les décalages restent ceux du
    texte d'origine — le masque conserve les longueurs."""
    if patterns is None:
        patterns = load_patterns_from_config(DEFAULT_POLICY_PATH)
    scanned = neutralise_digest_tokens(text)

    findings: list[RawPiiFinding] = []
    for pattern in patterns:
        for match in pattern.regex.finditer(scanned):
            matched = match.group(0)
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
    "audit_paths",
    "find_raw_pii",
    "neutralise_digest_tokens",
]
