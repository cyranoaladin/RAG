"""Test d'acceptation du parcours BATCH, depuis le vrai CLI (lot CU).

Il part de données au **format historique** — celles qu'écrit le point
d'entrée de release scellée — et exige qu'un job batch parcoure la chaîne
jusqu'à l'index produit, puis que son contenu soit récupérable.

Il commence en échec : c'est ce qui montre quel maillon manque réellement.
Chaque refus rencontré est consigné tel quel, jamais maquillé en succès
attendu.

Les autorités utilisées ici sont des **données de test**, explicitement
nommées comme telles. Elles n'autorisent aucune publication réelle.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    app_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_BATCH_CLI_ACCEPTANCE") != "1":
    pytest.skip(
        "batch CLI acceptance not requested (NEXUS_BATCH_CLI_ACCEPTANCE=1)",
        allow_module_level=True,
    )

#: Périmètre de la release scellée réelle — ses OCTETS servent de matière,
#: ses autorités ne sont pas rejouées comme autorités de publication.
RELEASE_DIR = REPOSITORY_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)
TRANSFER_MANIFEST = REPOSITORY_ROOT / (
    "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("batch-cli-acceptance")


def _run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    child_env = {
        **os.environ,
        **env,
        "PYTHONPATH": f"{ENGINE_ROOT / 'src'}:{REPOSITORY_ROOT / 'packages/contracts/src'}",
    }
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env,
        cwd=REPOSITORY_ROOT,
        check=False,
    )


def test_les_prerequis_du_banc_sont_reunis() -> None:
    """Un skip n'est pas une exécution : les prérequis sont vérifiés ici."""
    assert RELEASE_DIR.is_dir(), RELEASE_DIR
    assert (RELEASE_DIR / "production-profile-gate.release.json").is_file()
    assert (RELEASE_DIR / "artifacts.release.json").is_file()
    assert TRANSFER_MANIFEST.is_file(), TRANSFER_MANIFEST
    assert PROFILES_DIR.is_dir(), PROFILES_DIR
    assert len(list(PROFILES_DIR.glob("*.yml"))) == 11


def test_le_catalogue_scelle_se_charge_depuis_le_manifeste(
    control_pg: dict[str, str],
) -> None:
    """Maillon 1 — le catalogue vient du fichier que le manifeste nomme."""
    from ingestor.ingestion_control.sealed_release_catalog import (
        load_sealed_release_catalog,
    )

    manifeste = RELEASE_DIR / "production-profile-gate.release.json"
    catalogue = load_sealed_release_catalog(
        RELEASE_DIR,
        expected_release_manifest_sha256=_sha(manifeste),
        transfer_manifest_path=TRANSFER_MANIFEST,
        expected_transfer_manifest_sha256=_sha(TRANSFER_MANIFEST),
    )
    assert len(catalogue) == 315
    assert catalogue.media_type_invariant == "application/pdf"


def test_le_producteur_d_attestation_batch_existe() -> None:
    """Maillon 2 — l'outil qui produit l'artefact de revue batch.

    Le protocole ``LOT42-RELEASE-BATCH-V1`` a son contrat et son stockage.
    Cette épreuve établit si un PRODUCTEUR existe : sans lui, aucune
    attestation batch ne peut être proposée ni enregistrée, et la chaîne
    s'arrête avant le job.
    """
    aide = _run("ingestor.ingestion_worker.attest_publication_cli", ["--help"], {})
    assert aide.returncode == 0, aide.stderr
    sous_commandes = aide.stdout
    assert "release-batch" in sous_commandes or "batch" in sous_commandes, (
        "aucune sous-commande batch dans attest_publication_cli — le "
        "producteur d'attestation batch n'existe pas encore.\n"
        f"sous-commandes disponibles :\n{sous_commandes}"
    )


def test_un_job_batch_sans_identite_d_artefact_est_refuse(
    control_pg: dict[str, str],
) -> None:
    """Maillon 3 — « le plus récent » n'est pas une règle d'autorité."""
    from ingestor.ingestion_control.provisioning import (
        SealedReleaseRowError,
        find_authorised_artifact,
    )

    inconnu = uuid.uuid4()
    with psycopg.connect(app_dsn(control_pg)) as conn:
        with pytest.raises(SealedReleaseRowError, match="does not belong to resource"):
            find_authorised_artifact(
                conn, resource_id=uuid.uuid4(), artifact_id=inconnu
            )
        conn.rollback()


def test_le_schema_porte_l_identite_de_release_pour_une_attestation_batch(
    control_pg: dict[str, str],
) -> None:
    """Maillon 4 — la migration additive.

    Une ligne d'attestation batch doit pouvoir dire de QUELLE release elle
    relève. Sans colonne d'identité, ``require_release_batch_review_matches_release``
    n'aurait aucune donnée persistée à relire.
    """
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        colonnes = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ingestion_control' "
                "  AND table_name='publication_attestations'"
            ).fetchall()
        }
        conn.rollback()
    assert "release_id" in colonnes, (
        "publication_attestations ne porte aucune identité de release : une "
        "attestation batch ne pourrait pas nommer la release qu'elle atteste.\n"
        f"colonnes présentes : {sorted(colonnes)}"
    )


def test_le_parcours_batch_atteint_l_index_produit() -> None:
    """Maillon final — le job batch traverse la chaîne et publie.

    Cette épreuve reste rouge tant que les maillons ci-dessus manquent.
    Elle n'est pas neutralisée : son échec EST le résultat de départ.
    """
    pytest.fail(
        "parcours batch non exécutable : les maillons 2 (producteur "
        "d'attestation batch) et 4 (identité de release en base) manquent. "
        "Cette épreuve sera complétée dès qu'ils existeront."
    )
