"""Préparation du staging : ce que le producteur refuse, et ce qu'il rend.

Un générateur de secrets se juge d'abord sur ses refus. Ceux-ci sont donc
éprouvés un par un, sur des sorties réelles écrites dans un `tmp_path`, jamais
sur un simulacre.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))
sys.path.insert(0, str(ENGINE_ROOT / "src"))

import prepare_staging_environment as producer  # noqa: E402

from ingestor.api_scopes import (  # noqa: E402
    API_CLIENTS_ENV,
    API_CLIENTS_FILE_ENV,
    ApiScope,
    load_api_clients,
    resolve_api_client,
)

SHA256_ZERO = "0" * 64


def _arguments(destination: Path) -> list[str]:
    return [
        "--destination", str(destination),
        "--embedding-artifact-dir", "/srv/nexus/models/e5-large",
        "--embedding-inventory-sha256", SHA256_ZERO,
        "--reranker-artifact-dir", "/srv/nexus/models/reranker",
        "--reranker-inventory-sha256", SHA256_ZERO,
        "--release-registry-sha256", SHA256_ZERO,
        "--servable-corpus-dir", "/srv/nexus/servable-corpus",
        "--servable-corpus-index-sha256", SHA256_ZERO,
        "--sso-issuer", "https://sso.staging.example/",
        "--sso-audience", "nexus-cockpit-staging",
    ]


@pytest.fixture
def prepared(tmp_path: Path) -> Path:
    destination = tmp_path / "secrets"
    assert producer.main(_arguments(destination)) == 0
    return destination


def test_aucun_secret_ne_peut_etre_ecrit_dans_le_depot(tmp_path: Path) -> None:
    """Le refus qui compte le plus : un secret committé ne se rotate pas.

    Il se rattrape par une réécriture d'historique — donc il ne doit jamais
    être écrit.
    """
    for interdit in (
        REPOSITORY_ROOT,
        REPOSITORY_ROOT / "services" / "rag-engine" / "infra",
        REPOSITORY_ROOT / "docs" / "reports" / "staging",
    ):
        with pytest.raises(producer.StagingPreparationError) as refus:
            producer._refuse_repository_destination(interdit)
        assert "sous le dépôt" in str(refus.value)

    # Contrôle positif : hors dépôt, la destination est acceptée.
    assert producer._refuse_repository_destination(tmp_path / "ailleurs")


def test_le_registre_ne_porte_que_des_empreintes(prepared: Path) -> None:
    registre = json.loads((prepared / "api-clients.json").read_text(encoding="utf-8"))
    credentials = (prepared / "credentials.env").read_text(encoding="utf-8")

    jetons = [
        ligne.split("=", 1)[1]
        for ligne in credentials.splitlines()
        if ligne.startswith(("COCKPIT_", "AGENT_", "OPS_", "RAG_BFF_"))
    ]
    assert jetons

    rendu = json.dumps(registre)
    for jeton in jetons:
        assert jeton not in rendu, "un jeton en clair est entré dans le registre"

    for entree in registre:
        assert set(entree) == {"client_id", "token_sha256", "scopes"}
        assert len(entree["token_sha256"]) == 64


def test_le_runtime_accepte_le_registre_rendu(
    prepared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le seul juge du registre est le lecteur du runtime, pas ce banc."""
    monkeypatch.delenv(API_CLIENTS_ENV, raising=False)
    monkeypatch.setenv(API_CLIENTS_FILE_ENV, str(prepared / "api-clients.json"))

    clients = load_api_clients()
    par_id = {client.client_id: client for client in clients}
    assert set(par_id) == {"cockpit-staging", "agent-externe-staging", "ops-staging"}

    # Chaque jeton en clair résout bien SON client, et lui seul.
    credentials = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "credentials.env").read_text(encoding="utf-8").splitlines()
        if "=" in ligne and not ligne.startswith("#")
    )
    resolu = resolve_api_client(credentials["COCKPIT_STAGING_API_KEY"], clients)
    assert resolu is not None and resolu.client_id == "cockpit-staging"
    assert resolu.allows(ApiScope.SEARCH)
    assert not resolu.allows(ApiScope.ADMIN)

    ops = resolve_api_client(credentials["OPS_STAGING_API_KEY"], clients)
    assert ops is not None and ops.allows(ApiScope.ADMIN)
    assert not ops.allows(ApiScope.SEARCH)


def test_l_environnement_couvre_exactement_ce_que_le_compose_exige(
    prepared: Path,
) -> None:
    """Ni trou, ni surplus — et la liste vient du Compose, pas d'une copie."""
    rendu = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "staging.env").read_text(encoding="utf-8").splitlines()
        if ligne
    )
    exigees = set(producer.required_compose_variables())
    assert exigees, "aucune variable exigée trouvée : le motif de lecture a dérivé"
    assert exigees <= set(rendu)
    # `RAG_API_CLIENTS` n'est pas exigé : il est rendu VIDE, délibérément.
    assert set(rendu) - exigees == {"RAG_API_CLIENTS"}
    assert rendu["RAG_API_CLIENTS"] == ""


def test_une_seule_autorite_de_registre_gouverne(
    prepared: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le Compose fixe déjà le chemin conteneur ; en déclarer un second casse.

    Le runtime refuse deux sources — c'est voulu. Ce banc mesure que le
    producteur ne l'y met pas.
    """
    rendu = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "staging.env").read_text(encoding="utf-8").splitlines()
        if ligne
    )
    assert rendu["RAG_API_CLIENTS"] == ""
    assert "RAG_API_CLIENTS_FILE" not in rendu
    assert Path(rendu["RAG_API_CLIENTS_HOST_FILE"]).name == "api-clients.json"
    assert producer.container_registry_path() == "/app/api-clients/api-clients.json"


def test_les_dsn_portent_le_mot_de_passe_de_leur_propre_role(prepared: Path) -> None:
    """Un DSN qui porterait le mot de passe d'un autre rôle échouerait tard."""
    rendu = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "staging.env").read_text(encoding="utf-8").splitlines()
        if ligne
    )
    assert rendu["PGVECTOR_RETRIEVAL_PASSWORD"] in rendu["PG_RAG_DSN"]
    assert rendu["PGVECTOR_REVIEW_PASSWORD"] in rendu["PG_REVIEW_DSN"]
    assert rendu["PGVECTOR_REVIEW_PASSWORD"] not in rendu["PG_RAG_DSN"]
    assert rendu["PGVECTOR_RETRIEVAL_PASSWORD"] not in rendu["PG_REVIEW_DSN"]


def test_tous_les_secrets_fabriques_sont_distincts(prepared: Path) -> None:
    """Deux rôles derrière un même secret rendraient le journal ambigu."""
    rendu = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "staging.env").read_text(encoding="utf-8").splitlines()
        if ligne
    )
    fabriques = [
        rendu[name]
        for name in (
            "RAG_BFF_SERVICE_TOKEN",
            "RAG_ACCESS_LOG_HMAC_SECRET",
            "NEXUS_INTERNAL_TOKEN_SECRET",
            "PGVECTOR_PASSWORD",
            "PGVECTOR_RETRIEVAL_PASSWORD",
            "PGVECTOR_REVIEW_PASSWORD",
            "PGVECTOR_PUBLISHER_PASSWORD",
        )
    ]
    assert len(set(fabriques)) == len(fabriques)
    assert all(len(secret) >= 32 for secret in fabriques)


def test_les_fichiers_produits_ne_sont_lisibles_que_par_leur_proprietaire(
    prepared: Path,
) -> None:
    for nom in ("api-clients.json", "staging.env", "credentials.env"):
        mode = stat.S_IMODE(os.stat(prepared / nom).st_mode)
        assert mode == 0o600, (nom, oct(mode))


def test_une_empreinte_inventee_est_refusee(tmp_path: Path) -> None:
    """Le producteur fabrique des secrets ; il ne fabrique pas de preuves.

    Une empreinte d'inventaire est un FAIT du déploiement : en générer une
    plausible reviendrait à fabriquer la preuve que le runtime vérifiera.
    """
    for option, valeur in (
        ("--embedding-inventory-sha256", "pas-une-empreinte"),
        ("--release-registry-sha256", "ABCDEF" * 10 + "abcd"),
        ("--servable-corpus-index-sha256", "0" * 63),
    ):
        arguments = _arguments(tmp_path / "secrets")
        arguments[arguments.index(option) + 1] = valeur
        assert producer.main(arguments) == 2


def test_un_repertoire_hote_relatif_est_refuse(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path / "secrets")
    arguments[arguments.index("--embedding-artifact-dir") + 1] = "models/e5-large"
    assert producer.main(arguments) == 2


def test_le_producteur_echoue_si_le_compose_exige_une_variable_de_plus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un environnement incomplet doit échouer ici, pas au démarrage.

    Sans ce refus, l'ajout d'une variable au Compose produirait un
    `staging.env` silencieusement amputé, et l'opérateur ne l'apprendrait
    qu'au premier `docker compose up`.
    """
    reelles = producer.required_compose_variables()
    monkeypatch.setattr(
        producer,
        "required_compose_variables",
        lambda: (*reelles, "RAG_UNE_VARIABLE_DE_PLUS"),
    )
    assert producer.main(_arguments(tmp_path / "secrets")) == 2


def test_aucun_secret_n_est_imprime_sur_la_sortie_standard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un secret imprimé finit dans un historique de shell ou un log de CI."""
    destination = tmp_path / "secrets"
    assert producer.main(_arguments(destination)) == 0
    sortie = capsys.readouterr().out

    credentials = (destination / "credentials.env").read_text(encoding="utf-8")
    environnement = (destination / "staging.env").read_text(encoding="utf-8")
    secrets_ecrits = [
        ligne.split("=", 1)[1]
        for ligne in (credentials + environnement).splitlines()
        if "=" in ligne and not ligne.startswith("#") and ligne.split("=", 1)[1]
    ]
    assert secrets_ecrits
    for secret in secrets_ecrits:
        if len(secret) < 32 or secret.startswith(("/", "postgresql://", "https://")):
            continue
        assert secret not in sortie, "un secret est passé par la sortie standard"


def test_le_credential_du_cockpit_est_celui_que_le_moteur_attend(
    prepared: Path,
) -> None:
    """Les deux credentials du Cockpit, et leur correspondance côté moteur."""
    credentials = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "credentials.env").read_text(encoding="utf-8").splitlines()
        if "=" in ligne and not ligne.startswith("#")
    )
    environnement = dict(
        ligne.split("=", 1)
        for ligne in (prepared / "staging.env").read_text(encoding="utf-8").splitlines()
        if ligne
    )
    # RAG_ENGINE_INTERNAL_TOKEN côté Cockpit == RAG_BFF_SERVICE_TOKEN côté moteur.
    assert credentials["RAG_BFF_SERVICE_TOKEN"] == environnement["RAG_BFF_SERVICE_TOKEN"]

    # RAG_ENGINE_API_KEY côté Cockpit == une entrée du registre, et distincte.
    registre = json.loads((prepared / "api-clients.json").read_text(encoding="utf-8"))
    empreintes = {entree["client_id"]: entree["token_sha256"] for entree in registre}
    cle = credentials["COCKPIT_STAGING_API_KEY"]
    assert hashlib.sha256(cle.encode("utf-8")).hexdigest() == empreintes["cockpit-staging"]
    assert cle != credentials["RAG_BFF_SERVICE_TOKEN"]
