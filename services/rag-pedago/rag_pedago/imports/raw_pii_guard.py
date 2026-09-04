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
from collections.abc import Iterator, Mapping
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


def _scan_units(
    node: object, keys: tuple[str, ...] = ()
) -> Iterator[tuple[str, ...]]:
    """Rend les textes à scanner, GROUPÉS par valeur feuille.

    Une même valeur est rendue plusieurs fois — seule, puis précédée de chacune
    des clés qui la dominent — pour qu'un motif dont le contexte est porté par
    une clé puisse se former. Les rendre à plat faisait compter deux fois la
    même fuite ; les grouper laisse l'appelant dédoublonner à l'intérieur d'une
    valeur, sans jamais fusionner deux occurrences distinctes.

    **Toutes les clés ancêtres, pas seulement la plus proche.** Une première
    version ne transmettait que la clé immédiate : dans
    ``{"date_of_birth": {"value": "01/01/2000"}}`` le contexte utile
    (``date_of_birth``) était perdu, seul ``value`` subsistait, et la garde
    pouvait attester une sortie propre. Chaque clé du chemin a désormais sa
    chance de fournir le contexte.
    """
    if isinstance(node, bool) or node is None:
        # Ni l'un ni l'autre ne porte de matière ; les rendre n'ajouterait
        # que du bruit à mesurer.
        return
    if isinstance(node, (str, int, float)):
        rendered = node if isinstance(node, str) else str(node)
        yield (rendered, *(f"{key}: {rendered}" for key in keys))
        return
    if isinstance(node, Mapping):
        for child_key, value in node.items():
            if isinstance(child_key, str):
                yield (child_key,)
                yield from _scan_units(value, (*keys, child_key))
            else:
                yield from _scan_units(value, keys)
        return
    if isinstance(node, (list, tuple, set, frozenset)):
        for item in node:
            yield from _scan_units(item, keys)


def _string_values(node: object) -> Iterator[str]:
    """Parcourt un document et rend ses chaînes TELLES QU'ELLES SONT.

    **Pourquoi on ne scanne pas le JSON sérialisé.** La première version
    appelait `json.dumps` puis cherchait dans le résultat. Un séparateur situé à
    l'intérieur d'un motif — « 06 retour-ligne 12 34 56 78 » — y devient deux
    caractères littéraux, une barre oblique inverse suivie de « n » : la correspondance est perdue, et la garde atteste une
    sortie propre. Mesuré : un finding sur le texte brut, zéro après
    sérialisation.

    C'est le même défaut que celui corrigé sur les digests — transformer le
    texte avant d'y chercher — que la sérialisation avait réintroduit. Le JSON
    est une représentation de transport, pas la matière.

    **Ce que le parcours ne doit pas COÛTER.** Ne plus sérialiser a d'abord
    fait perdre deux choses que `json.dumps` rendait :

    1. la clé et la valeur sortaient SÉPARÉMENT, si bien qu'un motif dont le
       contexte est porté par la clé — `{"adresse": "75001 paris"}` — ne
       pouvait plus se former ;
    2. tout ce qui n'est pas une chaîne était ignoré, alors qu'un identifiant
       sérialisé en nombre — `{"identifier": 199012345678901}` — était
       auparavant rendu tel quel.

    La bonne mesure est l'UNION : la valeur seule, le couple `clé: valeur`, et
    la représentation des scalaires. Le couple est rendu avec `str()`, jamais
    avec un encodage JSON, pour ne pas réintroduire l'échappement qui avait
    motivé la correction initiale."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, bool) or node is None:
        # `True`/`None` ne portent aucune matière ; les rendre ne ferait
        # qu'ajouter du bruit à mesurer.
        return
    elif isinstance(node, (int, float)):
        yield str(node)
    elif isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(key, str):
                yield key
            for rendered in _string_values(value):
                yield rendered
                if isinstance(key, str):
                    # Le contexte que porte la clé, sans séparateur exotique :
                    # c'est celui que la sérialisation offrait aux motifs.
                    yield f"{key}: {rendered}"
    elif isinstance(node, (list, tuple, set, frozenset)):
        for item in node:
            yield from _string_values(item)


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
    # Le parcours rend chaque valeur DEUX fois — seule, puis précédée de sa
    # clé — pour qu'un motif dont le contexte est porté par la clé puisse se
    # former. Compter les deux ferait dire à ce refus qu'il y a deux fuites
    # là où il y en a une : un rapport de preuve qui double ses chiffres est
    # un rapport faux, même quand il refuse à bon droit.
    #
    # La déduplication porte sur l'IDENTITÉ de la correspondance — sa classe,
    # sa longueur et l'empreinte de sa matière — jamais sur sa position, qui
    # diffère justement entre les deux rendus. Deux occurrences réellement
    # distinctes de la même matière portent des empreintes identiques mais
    # sont comptées séparément si elles proviennent de valeurs différentes,
    # ce que la clé de dédoublonnage préserve en incluant la valeur source.
    findings: list[RawPiiFinding] = []
    for unit in _scan_units(document):
        # Longueur du préfixe `clé: ` de chaque rendu miroir. Une clé porteuse
        # de PII est déjà scannée SEULE, comme unité à part entière : la
        # recompter dans le miroir de chacun de ses descendants la faisait
        # apparaître autant de fois qu'elle a de feuilles. Mesuré :
        # `{"0612345678": {"a":1,"b":2,"c":3}}` rapportait quatre fuites pour
        # une seule.
        prefixes = [0] + [len(text) - len(unit[0]) for text in unit[1:]]
        # Les rendus d'une même valeur sont des MIROIRS : la même fuite y
        # apparaît, à des positions décalées par le préfixe de clé. Dédoublonner
        # par identité seule effacerait cependant une répétition réelle — deux
        # fois le même numéro dans un même texte est bien DEUX occurrences.
        #
        # On retient donc, pour chaque identité, la MULTIPLICITÉ la plus élevée
        # observée sur un rendu : deux occurrences restent deux, un motif que
        # seul le contexte de clé révèle est compté une fois, et le miroir
        # n'ajoute rien.
        best: dict[tuple[str, str, int], list[RawPiiFinding]] = {}
        for text, prefix in zip(unit, prefixes, strict=True):
            grouped: dict[tuple[str, str, int], list[RawPiiFinding]] = {}
            for finding in find_raw_pii(text, patterns=patterns):
                # Correspondance entièrement contenue dans le préfixe de clé :
                # elle appartient à la clé, comptée ailleurs.
                if finding.char_offset + finding.match_length <= prefix:
                    continue
                identity = (finding.pattern_id, finding.match_sha256, finding.match_length)
                grouped.setdefault(identity, []).append(finding)
            for identity, occurrences in grouped.items():
                if len(occurrences) > len(best.get(identity, ())):
                    best[identity] = occurrences
        for occurrences in best.values():
            findings.extend(occurrences)
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
