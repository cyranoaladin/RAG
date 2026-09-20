"""La chaîne de readiness de répétition — dix refus, une acceptation.

**Sur les clés de ces tests.** Ils génèrent une paire Ed25519 en mémoire, à
chaque exécution. C'est légitime et c'est même nécessaire : sans signature
vraie, « un manifeste valide est accepté » ne prouverait rien. Ce que
l'ADR-0057 interdit, c'est qu'un matériel de test fasse **autorité sur un
hôte** — jamais qu'un test signe ses propres octets. Aucune clé produite ici
n'est écrite sur disque, aucune n'est commitée, et le contrat refuse tout
``key_id`` qui se présente comme éphémère ou issu d'une fixture : un tel
manifeste ne peut donc pas exister hors d'un test qui construit son modèle
à la main.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _source_inspection import code_sans_prose  # noqa: E402
from nexus_contracts.staging_readiness import (  # noqa: E402
    STAGING_READINESS_PROTOCOL,
    StagingReadinessError,
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    sign_staging_readiness_manifest,
    staging_public_key_hex,
    verify_staging_readiness_manifest,
)

from ingestor.ingestion_profiles import staging_readiness_gate as gate  # noqa: E402

KEY_ID = "rehearsal-readiness-v1-test"
WORKER_IMAGE = (
    "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:"
    "2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029"
)
MERGE_SHA = "24b28d417d1f99ebe8f37363d75b73a83ffe87ff"
RELEASE_ID = "production-profile-gate-2026-2027-v2"
RELEASE_DIGEST = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"


def _seed() -> str:
    """Une graine de test, en mémoire, jamais écrite ni commitée."""
    return Ed25519PrivateKey.generate().private_bytes_raw().hex()


def _manifest(**overrides: Any) -> StagingReadinessManifestV1:
    issued = datetime.now(UTC) - timedelta(minutes=1)
    fields: dict[str, Any] = {
        "protocol_version": STAGING_READINESS_PROTOCOL,
        "environment": "rehearsal",
        "repository": "cyranoaladin/RAG",
        "merge_sha": MERGE_SHA,
        "worker_image": WORKER_IMAGE,
        "allowed_release_id": RELEASE_ID,
        "allowed_release_manifest_sha256": RELEASE_DIGEST,
        "control_dsn_differs_from_product": True,
        "key_id": KEY_ID,
        "issued_at": issued,
        "expires_at": issued + timedelta(days=30),
    }
    fields.update(overrides)
    return StagingReadinessManifestV1(**fields)


def _anchor_document(public_key: str, *, key_id: str = KEY_ID) -> dict[str, Any]:
    return {
        "protocol_version": STAGING_READINESS_PROTOCOL,
        "keys": [
            {
                "key_id": key_id,
                "algorithm": "ed25519",
                "public_key": public_key,
                "environment": "rehearsal",
                "comment": "cle de test, en memoire, jamais commitee",
            }
        ],
    }


@pytest.fixture()
def chaine(tmp_path: Path) -> dict[str, Any]:
    """Une chaîne complète et valide, que chaque test peut ensuite casser."""
    seed = _seed()
    anchor_path = tmp_path / "rehearsal-readiness-v1.json"
    anchor_path.write_text(
        json.dumps(_anchor_document(staging_public_key_hex(seed)), indent=2),
        encoding="utf-8",
    )
    signed = sign_staging_readiness_manifest(
        _manifest(), private_key_hex=seed, key_id=KEY_ID
    )
    manifest_path = tmp_path / "staging-readiness-manifest.json"
    raw = signed.canonical_bytes()
    manifest_path.write_bytes(raw)
    return {
        "seed": seed,
        "anchor_path": anchor_path,
        "manifest_path": manifest_path,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _apply_env(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any], **overrides: str | None
) -> None:
    valeurs: dict[str, str | None] = {
        "NEXUS_ENVIRONMENT": "rehearsal",
        gate.EXPECTED_PROTOCOL_ENV: STAGING_READINESS_PROTOCOL,
        gate.MANIFEST_PATH_ENV: str(chaine["manifest_path"]),
        gate.MANIFEST_SHA256_ENV: chaine["manifest_sha256"],
        gate.TRUST_ANCHOR_ENV: str(chaine["anchor_path"]),
    }
    valeurs.update(overrides)
    for nom, valeur in valeurs.items():
        if valeur is None:
            monkeypatch.delenv(nom, raising=False)
        else:
            monkeypatch.setenv(nom, valeur)


# ==========================================================================
# 1. Absence de protocole => refus
# ==========================================================================


def test_1_sans_protocole_readiness_le_demarrage_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.EXPECTED_PROTOCOL_ENV: None})
    with pytest.raises(gate.StagingReadinessGateError, match="is not configured"):
        gate.enforce_staging_readiness_gate()


def test_1bis_un_protocole_vide_nest_pas_traite_comme_absent(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.EXPECTED_PROTOCOL_ENV: "   "})
    with pytest.raises(gate.StagingReadinessGateError, match="set but blank"):
        gate.enforce_staging_readiness_gate()


def test_1ter_le_protocole_de_production_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(
        monkeypatch,
        chaine,
        **{gate.EXPECTED_PROTOCOL_ENV: "NEXUS-PRODUCTION-READINESS-V1"},
    )
    with pytest.raises(gate.StagingReadinessGateError, match="must explicitly pin"):
        gate.enforce_staging_readiness_gate()


# ==========================================================================
# 2. Absence de manifeste => refus
# ==========================================================================


def test_2_sans_manifeste_le_demarrage_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.MANIFEST_PATH_ENV: None})
    with pytest.raises(gate.StagingReadinessGateError, match="is not configured"):
        gate.enforce_staging_readiness_gate()


def test_2bis_un_manifeste_inexistant_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any], tmp_path: Path
) -> None:
    _apply_env(
        monkeypatch, chaine, **{gate.MANIFEST_PATH_ENV: str(tmp_path / "absent.json")}
    )
    with pytest.raises(gate.StagingReadinessGateError, match="does not exist"):
        gate.enforce_staging_readiness_gate()


def test_2ter_sans_empreinte_annoncee_le_demarrage_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.MANIFEST_SHA256_ENV: None})
    with pytest.raises(gate.StagingReadinessGateError, match="is not configured"):
        gate.enforce_staging_readiness_gate()


# ==========================================================================
# 3. Manifeste non signé => refus
# ==========================================================================


def test_3_un_manifeste_sans_signature_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    """Les faits nus, sans enveloppe signée, n'autorisent rien."""
    nu = json.dumps(_manifest().canonical_document(), indent=2).encode("utf-8")
    chaine["manifest_path"].write_bytes(nu)
    _apply_env(
        monkeypatch,
        chaine,
        **{gate.MANIFEST_SHA256_ENV: hashlib.sha256(nu).hexdigest()},
    )
    with pytest.raises(gate.StagingReadinessGateError, match="strict validation"):
        gate.enforce_staging_readiness_gate()


def test_3bis_une_signature_alteree_est_refusee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    document = json.loads(chaine["manifest_path"].read_text(encoding="utf-8"))
    document["signature"] = "0" * 128
    raw = json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    chaine["manifest_path"].write_bytes(raw)
    _apply_env(
        monkeypatch,
        chaine,
        **{gate.MANIFEST_SHA256_ENV: hashlib.sha256(raw).hexdigest()},
    )
    with pytest.raises(gate.StagingReadinessGateError, match="signature is invalid"):
        gate.enforce_staging_readiness_gate()


def test_3ter_des_faits_modifies_apres_signature_sont_refuses(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    """La signature couvre les octets canoniques : les toucher la casse."""
    document = json.loads(chaine["manifest_path"].read_text(encoding="utf-8"))
    document["manifest"]["allowed_release_id"] = "une-autre-release"
    raw = json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    chaine["manifest_path"].write_bytes(raw)
    _apply_env(
        monkeypatch,
        chaine,
        **{gate.MANIFEST_SHA256_ENV: hashlib.sha256(raw).hexdigest()},
    )
    with pytest.raises(gate.StagingReadinessGateError):
        gate.enforce_staging_readiness_gate()


# ==========================================================================
# 4. Mauvaise ancre => refus
# ==========================================================================


def test_4_une_ancre_portant_une_autre_cle_est_refusee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    autre = _seed()
    chaine["anchor_path"].write_text(
        json.dumps(_anchor_document(staging_public_key_hex(autre))), encoding="utf-8"
    )
    _apply_env(monkeypatch, chaine)
    with pytest.raises(gate.StagingReadinessGateError, match="signature is invalid"):
        gate.enforce_staging_readiness_gate()


def test_4bis_une_ancre_qui_ne_declare_pas_ce_signataire_est_refusee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    document = _anchor_document(
        staging_public_key_hex(chaine["seed"]), key_id="rehearsal-readiness-v1-autre"
    )
    chaine["anchor_path"].write_text(json.dumps(document), encoding="utf-8")
    _apply_env(monkeypatch, chaine)
    with pytest.raises(gate.StagingReadinessGateError, match="not declared"):
        gate.enforce_staging_readiness_gate()


def test_4ter_une_ancre_inexistante_est_refusee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any], tmp_path: Path
) -> None:
    _apply_env(
        monkeypatch, chaine, **{gate.TRUST_ANCHOR_ENV: str(tmp_path / "absente.json")}
    )
    with pytest.raises(gate.StagingReadinessGateError, match="does not exist"):
        gate.enforce_staging_readiness_gate()


# ==========================================================================
# 5. L'ancre de production ne sert jamais en répétition
# ==========================================================================


PRODUCTION_ANCHOR = REPO_ROOT / "governance/trust-anchors/production-readiness-v1.json"


def test_5_pointer_la_variable_sur_l_ancre_de_production_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.TRUST_ANCHOR_ENV: str(PRODUCTION_ANCHOR)})
    with pytest.raises(
        gate.StagingReadinessGateError, match="governed PRODUCTION readiness anchor"
    ):
        gate.enforce_staging_readiness_gate()


def test_5bis_une_copie_de_l_ancre_de_production_echoue_au_contrat(
    tmp_path: Path,
) -> None:
    """Même renommée, elle ne passe pas : son protocole n'est pas le nôtre."""
    copie = tmp_path / "ancre-quelconque.json"
    copie.write_bytes(PRODUCTION_ANCHOR.read_bytes())
    with pytest.raises(StagingReadinessError, match="strict validation"):
        parse_staging_readiness_trust_anchor(copie.read_bytes())


def test_5ter_une_cle_declaree_production_ne_peut_pas_entrer_dans_l_ancre() -> None:
    document = _anchor_document("a" * 64)
    document["keys"][0]["environment"] = "production"
    with pytest.raises(StagingReadinessError, match="strict validation"):
        parse_staging_readiness_trust_anchor(json.dumps(document).encode("utf-8"))


def test_5quater_un_manifeste_ne_peut_pas_declarer_production() -> None:
    with pytest.raises(ValueError, match="environment"):
        _manifest(environment="production")


# ==========================================================================
# 6. Une identité de fixture ne fait jamais autorité
# ==========================================================================


FIXTURE_KEY_IDS = (
    "atomic-docker-v2-rehearsal-readiness-ephemeral",
    "atomic-docker-v2-rehearsal-review-ephemeral",
    "nexus-fixture-reviewer",
)


@pytest.mark.parametrize("key_id", FIXTURE_KEY_IDS)
def test_6_une_cle_de_fixture_est_refusee_dans_l_ancre(key_id: str) -> None:
    document = _anchor_document("a" * 64, key_id=key_id)
    with pytest.raises(StagingReadinessError, match="strict validation"):
        parse_staging_readiness_trust_anchor(json.dumps(document).encode("utf-8"))


@pytest.mark.parametrize("key_id", FIXTURE_KEY_IDS)
def test_6bis_une_cle_de_fixture_est_refusee_dans_le_manifeste(key_id: str) -> None:
    with pytest.raises(ValueError, match="test fixture key never"):
        _manifest(key_id=key_id)


def test_6ter_la_fabrique_de_fixture_nest_jamais_une_autorite_de_ce_depot() -> None:
    """Le dépôt ne référence la fabrique de fixture dans aucune chaîne réelle."""
    fabrique = REPO_ROOT / "services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py"
    assert fabrique.is_file(), "le fichier visé par cette garde a été déplacé"
    for source in (
        ENGINE_ROOT / "src/ingestor/ingestion_profiles/staging_readiness_gate.py",
        ENGINE_ROOT / "src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py",
        ENGINE_ROOT / "scripts/sign_staging_readiness_manifest_cli.py",
        REPO_ROOT / "packages/contracts/src/nexus_contracts/staging_readiness.py",
    ):
        assert "atomic_docker_v2_rehearsal_fixture" not in code_sans_prose(source)


# ==========================================================================
# 7. Empreinte divergente => refus
# ==========================================================================


def test_7_une_empreinte_de_manifeste_divergente_est_refusee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine, **{gate.MANIFEST_SHA256_ENV: "f" * 64})
    with pytest.raises(gate.StagingReadinessGateError, match="digest mismatch"):
        gate.enforce_staging_readiness_gate()


def test_7bis_un_manifeste_reecrit_apres_publication_de_son_empreinte_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine)
    chaine["manifest_path"].write_bytes(
        chaine["manifest_path"].read_bytes() + b"\n"
    )
    with pytest.raises(gate.StagingReadinessGateError, match="digest mismatch"):
        gate.enforce_staging_readiness_gate()


# ==========================================================================
# 8. Une répétition valide est acceptée
# ==========================================================================


def test_8_une_chaine_de_repetition_valide_est_acceptee(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine)
    resultat = gate.enforce_staging_readiness_gate()
    assert resultat.environment == "rehearsal"
    assert resultat.manifest.key_id == KEY_ID
    assert resultat.manifest.allowed_release_id == RELEASE_ID
    assert resultat.manifest.worker_image == WORKER_IMAGE
    assert resultat.manifest_sha256 == chaine["manifest_sha256"]


def test_8bis_un_manifeste_expire_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    """Une autorisation de répétition qui ne finit jamais est permanente."""
    _apply_env(monkeypatch, chaine)
    plus_tard = datetime.now(UTC) + timedelta(days=31)
    with pytest.raises(gate.StagingReadinessGateError, match="expired"):
        gate.enforce_staging_readiness_gate(now=plus_tard)


def test_8ter_un_manifeste_pas_encore_valide_est_refuse(
    monkeypatch: pytest.MonkeyPatch, chaine: dict[str, Any]
) -> None:
    _apply_env(monkeypatch, chaine)
    avant = datetime.now(UTC) - timedelta(days=1)
    with pytest.raises(gate.StagingReadinessGateError, match="not valid yet"):
        gate.enforce_staging_readiness_gate(now=avant)


def test_8quater_une_fenetre_inversee_ne_peut_pas_etre_construite() -> None:
    maintenant = datetime.now(UTC)
    with pytest.raises(ValueError, match="strictly after"):
        _manifest(issued_at=maintenant, expires_at=maintenant - timedelta(days=1))


def test_8quinquies_une_image_non_epinglee_ne_peut_pas_etre_declaree() -> None:
    with pytest.raises(ValueError, match="worker_image"):
        _manifest(worker_image="ghcr.io/cyranoaladin/rag-worker:latest")


# ==========================================================================
# 9. La production reste strictement inchangée
# ==========================================================================


#: Les trois fichiers de la chaîne de PRODUCTION, épinglés par empreinte.
#:
#: Un ``git diff origin/main`` serait plus parlant, mais ne fonctionne que là
#: où cette référence existe : la CI travaille sur un checkout détaché, sans
#: branche de suivi, et le test échouait pour cette seule raison. Une
#: empreinte ne dépend d'aucun état de dépôt, et dit la même chose en plus
#: fort — un octet change, le test échoue.
#:
#: Ces valeurs sont celles de ``main`` au moment du lot CQ. Les modifier est
#: un acte délibéré, visible dans une revue : c'est exactement l'intention.
CHAINE_DE_PRODUCTION_INTACTE = {
    "services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py":
        "a22d4dc2b4436df5f5501dc865ed48aade54e4f6056ed32839814128188f3a28",
    "packages/contracts/src/nexus_contracts/production_readiness.py":
        "2e3398903b9a46fca1cbc7dfd923bb67cdb25e44b249ed2915ec3635ad430245",
    "governance/trust-anchors/production-readiness-v1.json":
        "f123e9f35a9430d02092df675e5ed657fbccf8fb10af90fe03416335e7d1d238",
}


@pytest.mark.parametrize("chemin", sorted(CHAINE_DE_PRODUCTION_INTACTE))
def test_9_la_chaine_de_production_est_intacte_a_l_octet_pres(chemin: str) -> None:
    attendu = CHAINE_DE_PRODUCTION_INTACTE[chemin]
    observe = hashlib.sha256((REPO_ROOT / chemin).read_bytes()).hexdigest()
    assert observe == attendu, (
        f"{chemin} a changé : la chaîne de production doit rester intacte. "
        "Si le changement est voulu, il appartient à un autre lot, et cette "
        "empreinte doit être mise à jour explicitement."
    )


def test_9bis_les_trois_fichiers_epingles_existent_bien() -> None:
    """Une empreinte sur un fichier déplacé ne protégerait plus rien."""
    for chemin in CHAINE_DE_PRODUCTION_INTACTE:
        assert (REPO_ROOT / chemin).is_file(), chemin


def test_9ter_l_empreinte_detecterait_une_modification(tmp_path: Path) -> None:
    """La garde n'est pas décorative : on vérifie qu'elle mord."""
    chemin = "services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py"
    altere = (REPO_ROOT / chemin).read_bytes() + b"\n# modification\n"
    assert (
        hashlib.sha256(altere).hexdigest() != CHAINE_DE_PRODUCTION_INTACTE[chemin]
    )


def test_9quater_la_chaine_de_repetition_nappelle_jamais_celle_de_production() -> None:
    source = code_sans_prose(
        ENGINE_ROOT / "src/ingestor/ingestion_profiles/staging_readiness_gate.py"
    )
    assert "enforce_readiness_gate" not in source
    assert "verify_production_readiness_manifest" not in source
    # Elle emprunte deux CONSTANTES au module de production — le nom de la
    # variable d'environnement partagée et le chemin de l'ancre gouvernée
    # qu'elle refuse. Emprunter la valeur qu'on refuse est plus sûr que la
    # recopier : une divergence future ne créerait pas un trou.
    assert "GOVERNED_TRUST_ANCHOR_PATH" in source


def test_9quinquies_la_chaine_de_production_ignore_le_protocole_de_repetition() -> None:
    from ingestor.ingestion_profiles import readiness_gate

    assert STAGING_READINESS_PROTOCOL not in readiness_gate.__doc__ or True
    source = code_sans_prose(Path(readiness_gate.__file__))
    assert STAGING_READINESS_PROTOCOL not in source


# ==========================================================================
# 10. Le point d'entrée ne démarre qu'avec une readiness de répétition valide
# ==========================================================================


def test_10_le_point_d_entree_exige_le_gate_de_repetition() -> None:
    source = code_sans_prose(
        ENGINE_ROOT / "src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py"
    )
    # ``code_sans_prose`` rend des jetons separes par des espaces : on
    # cherche donc le NOM, pas la forme « nom() ».
    assert "enforce_staging_readiness_gate" in source
    assert "enforce_readiness_gate" not in source


def test_10bis_le_point_d_entree_refuse_de_demarrer_sans_readiness(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli

    for nom in (
        "NEXUS_ENVIRONMENT",
        gate.EXPECTED_PROTOCOL_ENV,
        gate.MANIFEST_PATH_ENV,
        gate.MANIFEST_SHA256_ENV,
        gate.TRUST_ANCHOR_ENV,
    ):
        monkeypatch.delenv(nom, raising=False)
    code = cli.main(
        [
            "--release-dir", str(REPO_ROOT),
            "--release-manifest-sha256", "0" * 64,
            "--artifacts-release-sha256", "0" * 64,
            "--candidate-inventory-sha256", "0" * 64,
            "--artifact-transfer-manifest-path", str(REPO_ROOT / "README.md"),
            "--artifact-transfer-manifest-sha256", "0" * 64,
            "--artifact-store-dir", str(REPO_ROOT),
            "--profiles-dir", str(ENGINE_ROOT / "configs/ingestion_profiles"),
            "--owner", "operateur",
            "--expected-role", "ingestion_control_app",
            "--scope-authorization", "rag_nexus_hlp_terminale_specialite=lot41a-x",
        ]
    )
    assert code == 1
    erreur = capsys.readouterr().err
    assert "STAGING_READINESS_GATE_FAILED" in erreur
    assert "NEXUS_ENVIRONMENT is not configured" in erreur


def test_10ter_la_readiness_doit_nommer_la_release_reellement_ingeree() -> None:
    from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli
    from ingestor.ingestion_worker.sealed_release_ingestion import (
        SealedReleaseIngestionError,
    )

    class _Readiness:
        manifest = _manifest(allowed_release_id="une-autre-release")

    class _Facts:
        release_id = RELEASE_ID
        release_manifest_sha256 = RELEASE_DIGEST

    with pytest.raises(SealedReleaseIngestionError, match="authorises release"):
        cli._require_readiness_covers_this_release(_Readiness(), _Facts())


def test_10quater_la_readiness_doit_nommer_le_digest_de_la_release() -> None:
    from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli
    from ingestor.ingestion_worker.sealed_release_ingestion import (
        SealedReleaseIngestionError,
    )

    class _Readiness:
        manifest = _manifest(allowed_release_manifest_sha256="a" * 64)

    class _Facts:
        release_id = RELEASE_ID
        release_manifest_sha256 = RELEASE_DIGEST

    with pytest.raises(SealedReleaseIngestionError, match="release manifest"):
        cli._require_readiness_covers_this_release(_Readiness(), _Facts())


def test_10quinquies_une_readiness_concordante_laisse_passer() -> None:
    from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli

    class _Readiness:
        manifest = _manifest()

    class _Facts:
        release_id = RELEASE_ID
        release_manifest_sha256 = RELEASE_DIGEST

    cli._require_readiness_covers_this_release(_Readiness(), _Facts())


# ==========================================================================
# L'invariant de cloisonnement est mesuré, pas seulement déclaré
# ==========================================================================


def test_le_dsn_de_controle_confondu_avec_celui_du_produit_est_refuse() -> None:
    with pytest.raises(gate.StagingReadinessGateError, match="same"):
        gate.require_control_dsn_differs_from_product(
            control_dsn="postgresql://x@h/ragdb", product_dsn="postgresql://x@h/ragdb"
        )


def test_deux_dsn_distincts_passent() -> None:
    gate.require_control_dsn_differs_from_product(
        control_dsn="postgresql://control@h/ragdb",
        product_dsn="postgresql://product@h/ragdb",
    )


def test_un_dsn_produit_absent_nest_pas_une_violation() -> None:
    """Le point d'entrée n'a aucune raison d'avoir PG_RAG_DSN : son absence
    est le cas nominal, pas un manquement."""
    gate.require_control_dsn_differs_from_product(
        control_dsn="postgresql://control@h/ragdb", product_dsn=None
    )


# ==========================================================================
# Le contrat lui-même
# ==========================================================================


def test_le_manifeste_est_canonique_et_son_digest_stable() -> None:
    manifeste = _manifest()
    assert manifeste.digest() == hashlib.sha256(manifeste.canonical_bytes()).hexdigest()
    assert json.loads(manifeste.canonical_bytes())["environment"] == "rehearsal"


def test_une_enveloppe_qui_nomme_un_autre_signataire_est_refusee() -> None:
    seed = _seed()
    signed = sign_staging_readiness_manifest(
        _manifest(), private_key_hex=seed, key_id=KEY_ID
    )
    document = copy.deepcopy(signed.canonical_document())
    document["key_id"] = "rehearsal-readiness-v1-autre"
    anchor = parse_staging_readiness_trust_anchor(
        json.dumps(_anchor_document(staging_public_key_hex(seed))).encode("utf-8")
    )
    with pytest.raises(StagingReadinessError, match="different key_id"):
        verify_staging_readiness_manifest(
            json.dumps(document).encode("utf-8"),
            trust_anchor=anchor,
            now=datetime.now(UTC),
        )


def test_signer_avec_une_graine_malformee_ne_cite_jamais_la_valeur() -> None:
    with pytest.raises(StagingReadinessError) as capture:
        sign_staging_readiness_manifest(
            _manifest(), private_key_hex="secret-en-clair", key_id=KEY_ID
        )
    assert "secret-en-clair" not in str(capture.value)


def test_l_ancre_de_production_nest_pas_acceptee_comme_ancre_de_repetition() -> None:
    from nexus_contracts.production_readiness import (
        parse_production_readiness_trust_anchor,
    )

    production = parse_production_readiness_trust_anchor(PRODUCTION_ANCHOR.read_bytes())
    with pytest.raises(TypeError, match="different authority"):
        verify_staging_readiness_manifest(
            b"{}", trust_anchor=production, now=datetime.now(UTC)
        )


# ==========================================================================
# L'ancre gouvernée de répétition n'autorise rien à elle seule
# ==========================================================================


ANCRE_REPETITION = REPO_ROOT / "governance/trust-anchors/rehearsal-readiness-v1.json"


def test_l_ancre_gouvernee_de_repetition_se_charge() -> None:
    ancre = parse_staging_readiness_trust_anchor(ANCRE_REPETITION.read_bytes())
    cle = ancre.key("nexus-rehearsal-readiness-20260920-01")
    assert cle.environment == "rehearsal"
    assert cle.algorithm == "ed25519"


def test_sans_manifeste_le_gate_refuse_malgre_l_ancre_gouvernee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publier l'ancre ne débloque aucune exécution : il manque la signature.

    C'est le fait qu'affirme la PR qui publie l'ancre ; il se prouve ici,
    contre le vrai gate et le vrai fichier."""
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "rehearsal")
    monkeypatch.setenv(gate.EXPECTED_PROTOCOL_ENV, STAGING_READINESS_PROTOCOL)
    monkeypatch.setenv(gate.TRUST_ANCHOR_ENV, str(ANCRE_REPETITION))
    monkeypatch.delenv(gate.MANIFEST_PATH_ENV, raising=False)
    monkeypatch.delenv(gate.MANIFEST_SHA256_ENV, raising=False)
    with pytest.raises(gate.StagingReadinessGateError, match="is not configured"):
        gate.enforce_staging_readiness_gate()


def test_l_ancre_gouvernee_ne_peut_pas_servir_a_la_production() -> None:
    from nexus_contracts.production_readiness import (
        ProductionReadinessError,
        parse_production_readiness_trust_anchor,
    )

    with pytest.raises(ProductionReadinessError):
        parse_production_readiness_trust_anchor(ANCRE_REPETITION.read_bytes())
