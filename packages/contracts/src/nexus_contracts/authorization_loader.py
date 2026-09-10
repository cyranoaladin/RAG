"""Le chargeur canonique d autorisation — un seul, et il accepte les deux.

Pourquoi un chargeur, et pas un `if` dans chaque consommateur
-------------------------------------------------------------

Neuf consommateurs runtime lisent des documents d autorisation. Leur faire
choisir eux-memes entre V1 et V2 donnerait neuf endroits ou la regle de choix
peut diverger — et le jour ou deux d entre eux ne choisissent pas pareil, le
meme document est autorise ici et refuse la. Le choix se fait donc UNE fois.

Ce que ce chargeur garantit
---------------------------

Il accepte les deux protocoles. Refuser la V1 rejetterait tout artefact
operateur existant ; ne pas accepter la V2 rendrait le producteur inutile.

Il prefere la V2 quand le document en est un, sans jamais deviner : le
protocole est LU dans le document, jamais infere de sa forme. Un document dont
le protocole est inconnu est refuse, pas rattrape par un essai successif qui
finirait par accepter n importe quoi.

Il ne verifie rien. Charger n est pas autoriser : la verification appartient
au gate, qui differe entre les deux protocoles, et melanger les deux ici
recreerait la confusion que ce module existe pour supprimer.

Pourquoi il vit dans le contrat, et pas dans la chaine de release
-----------------------------------------------------------------

Choisir entre deux versions d un contrat est une affaire de contrat. Le mettre
ailleurs avait une consequence tres concrete : l image du worker d ingestion
n embarque PAS `nexus-release-chain`, et le gate de readiness, qui tourne dans
cette image, ne pouvait plus s importer. Une epreuve d image reelle l a montre.

Elargir l image pour y faire entrer la chaine de release aurait resolu le
symptome en alourdissant le conteneur pour une fonction qui ne parle que du
contrat.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from nexus_contracts.authorization_set import (
    AUTHORIZATION_SET_PROTOCOL_VERSION,
    AUTHORIZATION_SET_PROTOCOL_VERSION_V2,
    AuthorizationSetError,
    AuthorizationSetV1,
    AuthorizationSetV2,
    parse_authorization_set,
    parse_authorization_set_v2,
)

__all__ = [
    "AUTHORIZATION_PROTOCOLS_ACCEPTED",
    "LoadedAuthorizationSet",
    "NEW_RELEASE_AUTHORIZATION_PROTOCOL",
    "load_authorization_set",
]

#: Le protocole d une release NEUVE. Une release neuve ne retombe jamais en V1.
NEW_RELEASE_AUTHORIZATION_PROTOCOL = AUTHORIZATION_SET_PROTOCOL_VERSION_V2

#: Les deux protocoles lisibles. La V1 reste lisible parce que des artefacts
#: historiques existent, pas parce qu elle reste un choix pour du neuf.
AUTHORIZATION_PROTOCOLS_ACCEPTED = (
    AUTHORIZATION_SET_PROTOCOL_VERSION,
    AUTHORIZATION_SET_PROTOCOL_VERSION_V2,
)


@dataclass(frozen=True)
class LoadedAuthorizationSet:
    """Un document charge, et la version sous laquelle il a ete lu."""

    protocol_version: str
    authorization_set: AuthorizationSetV1 | AuthorizationSetV2

    @property
    def is_v2(self) -> bool:
        return self.protocol_version == AUTHORIZATION_SET_PROTOCOL_VERSION_V2

    @property
    def is_historical_v1(self) -> bool:
        return self.protocol_version == AUTHORIZATION_SET_PROTOCOL_VERSION

    def require_v2(self, *, because: str) -> AuthorizationSetV2:
        """Exige la V2 la ou la V1 n est pas acceptable — une release neuve.

        `because` nomme l exigence dans le message : un refus qui ne dit pas
        au nom de quoi il refuse est un refus qu on contourne.
        """
        if not self.is_v2:
            raise AuthorizationSetError(
                f"{because} exige {AUTHORIZATION_SET_PROTOCOL_VERSION_V2}, "
                f"document lu en {self.protocol_version}. Une release neuve ne "
                "retombe pas sur une autorisation historique."
            )
        assert isinstance(self.authorization_set, AuthorizationSetV2)
        return self.authorization_set


def _protocole_declare(raw: bytes) -> str:
    """Lit le protocole DECLARE. Ne devine pas, n essaie pas successivement.

    Un essai V2 puis repli V1 finirait par accepter un document V2 malforme
    comme un V1 invalide, et le message d erreur parlerait du mauvais
    protocole.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationSetError(
            f"authorization set is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise AuthorizationSetError("authorization set must be a JSON object")
    declare = document.get("protocol_version")
    if declare not in AUTHORIZATION_PROTOCOLS_ACCEPTED:
        raise AuthorizationSetError(
            "authorization set declares an unsupported protocol_version: "
            f"{declare!r}. Protocoles lisibles : "
            f"{list(AUTHORIZATION_PROTOCOLS_ACCEPTED)!r}."
        )
    assert isinstance(declare, str)
    return declare


def load_authorization_set(raw: bytes) -> LoadedAuthorizationSet:
    """Charge un document d autorisation sous le protocole qu il declare."""
    protocole = _protocole_declare(raw)
    if protocole == AUTHORIZATION_SET_PROTOCOL_VERSION_V2:
        return LoadedAuthorizationSet(
            protocol_version=protocole, authorization_set=parse_authorization_set_v2(raw)
        )
    return LoadedAuthorizationSet(
        protocol_version=protocole, authorization_set=parse_authorization_set(raw)
    )
