"""Calcule l'ensemble des contenus que la lignée ACTIVE promeut aujourd'hui.

`pii_review_index_20260903.json` scelle l'ensemble d'une revue humaine passée
— il ne dit rien de ce que la lignée courante sert. Ce script part donc de
l'autorité qui désigne les releases actives : celle que le déploiement
sélectionne, ou, quand aucun déploiement ne parle, le **registre canonique**.

**Il ne décide rien de la structure des releases.** Toute la sémantique —
quelles natures de release existent, comment leurs sujets sont scellés, où
vivent les contenus, quels comptes doivent tomber juste — appartient à
``nexus_release_chain.release_readiness``, que le RUNTIME de production
consomme déjà. La réimplémenter ici produisait un second runtime : chaque
règle omise devenait un faux vert, chaque règle ajoutée en amont demandait
d'être redécouverte ici. Onze rondes de revue ont mesuré ce coût.

**Il ne décide rien non plus de QUEL mécanisme désigne les releases.** Le
runtime en reconnaît trois — registre canonique, liste explicite de manifests,
manifest historique unique — et refuse qu'ils parlent à deux. Ce script n'en
connaissait qu'un : sous un manifest Wave 0, il retombait sur le registre par
défaut et certifiait 319 contenus là où le service en servait 2 ; sous deux
mécanismes simultanés, il acceptait ce que le service refuse. La sélection
est désormais celle du contrat, ``select_release_authority``, consommée telle
quelle.

Une seule autorité, donc. Ce fichier ne fait plus que deux choses que le
chargeur ne peut pas faire à sa place :

1. borner le chemin de l'autorité d'entrée à la racine gouvernée — une
   autorité extérieure au périmètre qu'elle prétend gouverner ne le gouverne
   pas, et ses empreintes internes fussent-elles cohérentes ne prouveraient
   que la lecture du fichier désigné ;
2. réduire ce que le chargeur rend à l'ensemble des ``content_sha256``
   distincts, avec la formule d'empreinte du vérificateur CAS.

Ce script ne lit que des données publiques du dépôt — jamais le store privé.

Usage :
    python scripts/qualification/compute_promoted_content_set.py \\
        --output /tmp/promoted-content-set.json
    python scripts/qualification/compute_promoted_content_set.py \\
        --release-registry <registre figé de la candidate> --output …
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nexus_release_chain.deployment_binding import (  # noqa: E402
    REGISTRY_PATH_ENV,
    RELEASE_AUTHORITY_REGISTRY_FILE,
    DeploymentBindingError,
    ReleaseAuthoritySelection,
    select_release_authority,
)
from nexus_release_chain.release_readiness import (  # noqa: E402
    ReleaseReadinessError,
    ReleaseRegistryExpectation,
    load_release_registry,
    load_release_registry_file,
)
from verify_corpus_cas import content_set_digest  # noqa: E402

#: Racine gouvernée, quand l'autorité vient d'un déploiement. La borne reste
#: exercée — mais contre la racine de CE déploiement, pas celle du dépôt,
#: qu'un conteneur ne connaît pas.
GOVERNED_ROOT_ENV = "NEXUS_C1_GOVERNED_ROOT"

#: Registre canonique de l'année scolaire servie. C'est un DÉFAUT, pas une
#: vérité en dur : `--release-registry` permet de qualifier une candidate
#: figée sans réécrire ce script.
DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "release-registry.json"
)

#: Racine sous laquelle le registre doit se résoudre.
GOVERNED_ROOT = (
    Path(__file__).resolve().parents[2] / "services" / "rag-pedago" / "data" / "releases"
)


class PromotedContentSetError(RuntimeError):
    """L'ensemble promu n'est pas celui que les autorités déclarent — refus."""


def racine_gouvernee_pour(mode: str, registre: Path) -> Path:
    """La racine contre laquelle borner — elle DÉPEND du mode.

    Une racine unique, celle du dépôt, faisait échouer le mode déploiement
    avant toute lecture : un conteneur qui monte
    ``/app/release/release-registry.json`` ne possède pas le checkout hôte, et
    la borne refusait donc le seul registre qu'il ait à servir.

    * racine DÉCLARÉE (``NEXUS_C1_GOVERNED_ROOT``) — elle prime toujours, y
      compris en déploiement : c'est ainsi qu'un exploitant restreint le
      périmètre monté, et un registre hors d'elle reste refusé ;
    * ``DEPLOYMENT`` sans racine déclarée — le namespace monté est le
      répertoire que la liaison désigne. Le déploiement a NOMMÉ ce chemin ;
      ici la borne sert à refuser une redirection, pas à deviner un point de
      montage. La même règle s'applique à chaque manifest d'une liaison par
      manifests : le fichier désigné est borné à son propre répertoire ;
    * ``DEFAULT`` et ``EXPLICIT_CANDIDATE`` — le registre est un artefact du
      dépôt, borné à la racine des releases.
    """
    declaree = os.environ.get(GOVERNED_ROOT_ENV)
    if declaree:
        return Path(declaree)
    if mode in (MODE_DEPLOYMENT, MODE_DEPLOYMENT_MANIFESTS):
        # La racine est DÉRIVÉE du chemin : elle ne peut donc pas servir de
        # borne si ce chemin sait remonter. `/app/release/../../etc/r.json`
        # aurait donné la racine `/etc`, et le bornage — comme la marche qui
        # cherche les liens symboliques, qui s'arrête à la racine — aurait été
        # vrai par construction. Une borne dérivée d'une valeur que la borne
        # est censée contrôler ne contrôle rien.
        if not registre.is_absolute():
            raise PromotedContentSetError(
                f"{REGISTRY_PATH_ENV} : {registre.as_posix()} n'est pas absolu — "
                "un déploiement désigne un chemin monté, pas un chemin relatif "
                "au répertoire courant du processus"
            )
        if ".." in registre.parts:
            raise PromotedContentSetError(
                f"{REGISTRY_PATH_ENV} : {registre.as_posix()} remonte hors de "
                "son propre répertoire — la racine gouvernée en serait dérivée, "
                "et la borne serait vraie par construction. Déclarez "
                f"{GOVERNED_ROOT_ENV} si le montage est ailleurs."
            )
        return registre.parent
    return GOVERNED_ROOT


def _borner(chemin: Path, racine: Path) -> Path:
    """Prouve que le registre est DANS le périmètre gouverné, avant lecture.

    `..`, chemin absolu et lien symbolique sur n'importe quel composant sont
    refusés. Un lien vers l'extérieur est déjà attrapé par la borne de racine ;
    un lien INTERNE ne l'est pas — sa résolution reste à l'intérieur — et
    seule l'inspection de chaque composant le voit."""
    ancre = racine.resolve(strict=False)
    resolu = chemin.resolve(strict=False)
    try:
        resolu.relative_to(ancre)
    except ValueError as exc:
        raise PromotedContentSetError(
            f"registre : {chemin.as_posix()} se résout hors de la racine "
            f"gouvernée ({ancre.as_posix()})"
        ) from exc

    courant = chemin if chemin.is_absolute() else Path.cwd() / chemin
    vus: set[Path] = set()
    while courant not in vus:
        vus.add(courant)
        if courant.is_symlink():
            raise PromotedContentSetError(
                f"registre : {courant.as_posix()} est un lien symbolique — un "
                "chemin gouverné ne redirige sur aucun de ses composants"
            )
        if courant.resolve(strict=False) == ancre or courant.parent == courant:
            break
        courant = courant.parent

    if not resolu.is_file():
        raise PromotedContentSetError(f"registre : {chemin.as_posix()} est introuvable")
    return resolu


def _un_deploiement_parle() -> bool:
    """Un déploiement désigne-t-il des releases — par n'importe quel mécanisme ?

    Une configuration incohérente (paire incomplète, mécanismes concurrents)
    est un déploiement qui parle, même de travers : on ne se scelle pas contre
    soi-même sous prétexte qu'il bafouille."""
    try:
        return select_release_authority() is not None
    except DeploymentBindingError:
        return True


def _empreinte_attendue(resolu: Path, fournie: str | None) -> str:
    """L'empreinte contre laquelle le chargeur confrontera le registre.

    En mode DÉPLOIEMENT, elle est fournie et exigée telle quelle : la calculer
    nous-mêmes ferait du fichier observé sa propre autorité, et C1 rendrait
    vert sur un registre que le runtime refuserait.

    En mode dépôt — aucun déploiement ne parle — le registre EST l'autorité
    d'entrée, et le sceller contre lui-même ne prouve rien de plus que le
    bornage à la racine gouvernée.
    """
    if fournie:
        return fournie
    if _un_deploiement_parle():
        raise PromotedContentSetError(
            "un déploiement désigne un registre mais aucune empreinte n'a été "
            "transmise — le calculer ici ferait du fichier observé sa propre "
            "autorité"
        )
    return hashlib.sha256(resolu.read_bytes()).hexdigest()


def charger_registre_promu(
    registry_path: Path,
    expected_sha256: str | None = None,
    *,
    governed_root: Path | None = None,
) -> ReleaseRegistryExpectation:
    """Le registre canonique, borné puis chargé par le chargeur du runtime.

    La validation entière — natures supportées, sceaux, comptes, autorités,
    partitions de pages, collisions — est celle du chargeur canonique, celui
    que le runtime consomme. On n'en refait aucune."""
    resolu = _borner(
        registry_path,
        governed_root if governed_root is not None else GOVERNED_ROOT,
    )
    attendue = _empreinte_attendue(resolu, expected_sha256)
    try:
        return load_release_registry_file(resolu, attendue)
    except (ReleaseReadinessError, OSError, ValueError) as exc:
        raise PromotedContentSetError(
            f"{registry_path.name} : {type(exc).__name__}: {exc}"
        ) from exc


def charger_manifestes_promus(
    liaisons: tuple[tuple[Path, str], ...],
) -> ReleaseRegistryExpectation:
    """Les manifests qu'un déploiement désigne — liste explicite ou couple
    historique — bornés un par un, puis chargés par le chargeur du runtime.

    L'empreinte de chaque manifest est celle que le déploiement a transmise :
    rien n'est calculé ici. Le chargeur est ``load_release_registry``, le même
    appel que le runtime fait sur ces mêmes couples ; les collisions, le
    contrat modèle unique et l'année scolaire commune sont ses règles."""
    bornees: list[tuple[Path, str]] = []
    for chemin, empreinte in liaisons:
        racine = racine_gouvernee_pour(MODE_DEPLOYMENT_MANIFESTS, chemin)
        bornees.append((_borner(chemin, racine), empreinte))
    try:
        return load_release_registry(tuple(bornees))
    except (ReleaseReadinessError, OSError, ValueError) as exc:
        raise PromotedContentSetError(f"manifests : {type(exc).__name__}: {exc}") from exc


def reduire_aux_contenus(registre: ReleaseRegistryExpectation) -> set[str]:
    """L'union des contenus que TOUTES les releases chargées servent."""
    contenus = {
        artefact.content_sha256
        for manifeste in registre.manifests
        for artefact in manifeste.expectation.artifacts
    }
    if not contenus:
        raise PromotedContentSetError(
            "aucun contenu promu : le contrôle de couverture serait vrai par vacuité"
        )
    return contenus


def collect_promoted_content_set(
    registry_path: Path,
    expected_sha256: str | None = None,
    *,
    governed_root: Path | None = None,
) -> set[str]:
    """L'union des contenus que TOUTES les releases actives du registre servent."""
    return reduire_aux_contenus(
        charger_registre_promu(registry_path, expected_sha256, governed_root=governed_root)
    )


def collect_promoted_collections(
    registry_path: Path,
    expected_sha256: str | None = None,
    *,
    governed_root: Path | None = None,
) -> set[str]:
    """Les collections que la lignée active sert, telles que le chargeur les rend."""
    return set(
        charger_registre_promu(
            registry_path, expected_sha256, governed_root=governed_root
        ).collections
    )


#: Les SOURCES possibles de l'autorité, mutuellement exclusives. Sans ces
#: noms, elles se recouvraient en silence : un déploiement pouvait désigner un
#: registre et un argument de ligne de commande en imposer un autre, sans que
#: rien ne dise lequel avait décidé du périmètre servi.
MODE_DEFAULT = "DEFAULT"
MODE_DEPLOYMENT = "DEPLOYMENT"
MODE_DEPLOYMENT_MANIFESTS = "DEPLOYMENT_MANIFESTS"
MODE_EXPLICIT_CANDIDATE = "EXPLICIT_CANDIDATE"


def resoudre_source_du_registre(
    *,
    registre_demande: Path | None,
    empreinte_demandee: str | None,
    liaison: ReleaseAuthoritySelection | None,
) -> tuple[str, Path | None, str | None]:
    """Rend (mode, registre, empreinte attendue) — ou refuse.

    La matrice, en toutes lettres :

    ==================  ====================  ==============================
    déploiement lié     ``--release-registry``  mode
    ==================  ====================  ==============================
    non                 non                   ``DEFAULT``
    oui, registre       non                   ``DEPLOYMENT``
    oui, manifests      non                   ``DEPLOYMENT_MANIFESTS``
    non                 oui                   ``EXPLICIT_CANDIDATE``
    oui                 oui                   **refus** — deux autorités
    ==================  ====================  ==============================

    ``liaison`` est la sélection du CONTRAT — ``select_release_authority`` —
    jamais une lecture d'environnement faite ici. En ``DEPLOYMENT_MANIFESTS``
    le registre rendu est ``None`` : ce sont les couples de la liaison qui
    désignent les releases, et ``--release-registry-sha256`` n'a rien à
    sceller.

    En ``EXPLICIT_CANDIDATE``, ``--release-registry-sha256`` est EXIGÉE :
    hacher le fichier observé ferait de la candidate sa propre autorité, et
    qualifier une candidate contre elle-même ne prouve rien.
    """
    if liaison is not None and registre_demande is not None:
        raise PromotedContentSetError(
            "un déploiement désigne des releases ET --release-registry en impose "
            "d'autres : deux autorités pour un même périmètre, rien ne dirait "
            "laquelle a décidé de ce qui est servi"
        )
    if registre_demande is not None:
        if not empreinte_demandee:
            raise PromotedContentSetError(
                "--release-registry sans --release-registry-sha256 : hacher le "
                "fichier observé ferait de la candidate sa propre autorité"
            )
        return MODE_EXPLICIT_CANDIDATE, registre_demande, empreinte_demandee
    if liaison is not None:
        if liaison.mechanism == RELEASE_AUTHORITY_REGISTRY_FILE:
            chemin, sceau = liaison.bindings[0]
            if empreinte_demandee and empreinte_demandee != sceau:
                raise PromotedContentSetError(
                    "--release-registry-sha256 contredit l'empreinte du déploiement"
                )
            return MODE_DEPLOYMENT, chemin, sceau
        if empreinte_demandee:
            raise PromotedContentSetError(
                "--release-registry-sha256 ne s'applique pas : le déploiement "
                "désigne des manifests, chacun avec sa propre empreinte"
            )
        return MODE_DEPLOYMENT_MANIFESTS, None, None
    if empreinte_demandee:
        raise PromotedContentSetError(
            "--release-registry-sha256 sans registre désigné : l'empreinte ne "
            "porterait sur rien de nommé"
        )
    return MODE_DEFAULT, DEFAULT_REGISTRY, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        binding = select_release_authority()
    except DeploymentBindingError as exc:
        # Exactement la sémantique du runtime : une paire incomplète, deux
        # mécanismes concurrents ou une liste malformée sont un refus, jamais
        # un repli sur le défaut du dépôt.
        print(f"::error::PROMOTED_CONTENT_SET_INVALID: {exc}", file=sys.stderr)
        return 2
    # Aucun défaut ici : le défaut est une DÉCISION de la matrice de
    # précédence, pas un effet de bord de l'analyse des arguments. Laisser
    # `default=` porter la liaison de déploiement rendait indiscernables « le
    # déploiement a décidé » et « l'appelant a imposé ».
    parser.add_argument(
        "--release-registry",
        type=Path,
        default=None,
        help=(
            "registre figé d'une candidate à qualifier ; exige "
            "--release-registry-sha256 et exclut toute liaison de déploiement"
        ),
    )
    parser.add_argument(
        "--release-registry-sha256",
        default=None,
        help="empreinte externe du registre désigné",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        mode, registre, empreinte = resoudre_source_du_registre(
            registre_demande=args.release_registry,
            empreinte_demandee=args.release_registry_sha256,
            liaison=binding,
        )
        if mode == MODE_DEPLOYMENT_MANIFESTS:
            assert binding is not None  # la matrice ne rend ce mode que lié
            charge = charger_manifestes_promus(binding.bindings)
        else:
            assert registre is not None  # les modes registre nomment un fichier
            charge = charger_registre_promu(
                registre,
                empreinte,
                governed_root=racine_gouvernee_pour(mode, registre),
            )
        contents = reduire_aux_contenus(charge)
    except (PromotedContentSetError, KeyError, TypeError, ValueError, OSError) as exc:
        # Une trace Python en CI dit où le code s'est arrêté, pas ce qui est
        # faux dans la lignée. Le gate doit nommer le défaut.
        print(f"::error::PROMOTED_CONTENT_SET_INVALID: {exc}", file=sys.stderr)
        return 2

    mecanisme = binding.mechanism if binding is not None else RELEASE_AUTHORITY_REGISTRY_FILE
    payload = {
        "content_sha256": sorted(contents),
        "count": len(contents),
        "content_set_sha256": content_set_digest(contents),
        "release_registry": registre.name if registre is not None else None,
        # Le mode est PUBLIÉ : une preuve qui ne dit pas quelle autorité a
        # désigné le registre ne se relit pas.
        "release_registry_source": mode,
        # L'autorité RÉELLEMENT interprétée : le mécanisme du contrat et les
        # manifests que le chargeur a liés, avec leurs empreintes. C'est
        # exactement ce que le runtime tient en main pour la même
        # configuration — la parité se lit ici, couple par couple.
        "release_authority": {
            "mechanism": mecanisme,
            "bindings": sorted(
                [str(manifeste.path), manifeste.expected_sha256]
                for manifeste in charge.manifests
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PROMOTED_CONTENT_SET_COUNT={payload['count']}")
    print(f"PROMOTED_CONTENT_SET_SHA256={payload['content_set_sha256']}")
    print(f"RELEASE_REGISTRY_SOURCE={mode}")
    print(f"RELEASE_AUTHORITY_MECHANISM={mecanisme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
