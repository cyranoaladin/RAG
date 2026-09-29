"""Décisions pures de l'opération 020/adopter, sans PostgreSQL ni réseau."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import hggsp_control_schema_020 as op  # noqa: E402


def _observation(**changes: object) -> dict:
    base = {"database": op.DATABASE, "admin_is_superuser": True, "head": 19,
            "registry_contiguous": True, "registry_mismatches": [], "running_jobs": 0,
            "v2_adoptions": 0, "adopter_role_exists": False}
    base.update(changes)
    return base


@pytest.mark.parametrize(("changes", "motif"), [
    ({"database": "ragdb"}, "base"),
    ({"admin_is_superuser": False}, "superutilisateur"),
    ({"head": 18}, "tête"),
    ({"head": 21}, "tête"),
    ({"registry_contiguous": False}, "registre"),
    ({"registry_mismatches": ["migration 019 : altérée"]}, "registre"),
    ({"running_jobs": 1}, "concurrence"),
    ({"v2_adoptions": 1}, "V2 observée sur 019"),
])
def test_prevol_refuse_avant_toute_ecriture(changes: dict, motif: str) -> None:
    with pytest.raises(op.Refus, match=motif):
        op.exiger_prevol(_observation(**changes))


def test_prevol_accepte_019_et_reprise_sur_020() -> None:
    op.exiger_prevol(_observation())
    op.exiger_prevol(_observation(head=20, v2_adoptions=74))


def _droits() -> dict:
    tables = {t: [t in op.LISIBLES, t in op.INSERTABLES, False, False, False]
              for t in (*op.TABLES_PRESERVEES, "schema_migrations", "revoked_review_evidence")}
    return {
        "attributes": {"superuser": False, "createrole": False, "createdb": False,
                       "replication": False, "bypassrls": False, "inherit": False, "login": True},
        "memberships": 0, "control_tables": tables, "product_writable": [],
        "product_readable": [], "security_definer_executable": [],
        "connectable_databases": [op.DATABASE, "ragdb"], "create_schemas": [],
    }


def test_moindre_privilege_accepte_et_herite_rapporte() -> None:
    droits = _droits()
    assert op.exiger_moindre_privilege(droits) == []
    assert op.constats_herites(droits) == ["CONNECT hérité de PUBLIC sur ['ragdb']"]


@pytest.mark.parametrize("mutation", [
    "superuser", "membership", "update_resources", "insert_jobs", "insert_attestations",
    "select_jobs", "missing_insert", "product_write", "security_definer", "create_schema",
    "no_connect",
])
def test_moindre_privilege_refuse_tout_exces(mutation: str) -> None:
    droits = copy.deepcopy(_droits())
    tables = droits["control_tables"]
    if mutation == "superuser":
        droits["attributes"]["superuser"] = True
    elif mutation == "membership":
        droits["memberships"] = 1
    elif mutation == "update_resources":
        tables["resources"][2] = True
    elif mutation == "insert_jobs":
        tables["jobs"][1] = True
    elif mutation == "insert_attestations":
        tables["publication_attestations"][1] = True
    elif mutation == "select_jobs":
        tables["jobs"][0] = True
    elif mutation == "missing_insert":
        tables["sealed_release_adoptions"][1] = False
    elif mutation == "product_write":
        droits["product_writable"] = ["rag_chunks"]
    elif mutation == "security_definer":
        droits["security_definer_executable"] = ["ingestion_control.f()"]
    elif mutation == "create_schema":
        droits["create_schemas"] = ["public"]
    else:
        droits["connectable_databases"] = ["ragdb"]
    assert op.exiger_moindre_privilege(droits)


def test_secret_suspect_ou_repertoire_permissif_refuse(tmp_path: Path) -> None:
    dossier = tmp_path / "secrets"
    dossier.mkdir(mode=0o700)
    secret = dossier / "adopter.password"
    assert op.lire_secret(secret) is None
    valeur = op.creer_secret(secret)
    assert op.lire_secret(secret) == valeur
    with pytest.raises(FileExistsError):
        op.creer_secret(secret)  # jamais d'écrasement
    secret.chmod(0o644)
    with pytest.raises(op.Refus, match="0600"):
        op.lire_secret(secret)
    secret.chmod(0o600)
    secret.write_text("court\n")
    with pytest.raises(op.Refus, match="valeur non affichée") as refus:
        op.lire_secret(secret)
    assert "court" not in str(refus.value)
    dossier.chmod(0o755)
    with pytest.raises(op.Refus, match="0700"):
        op.lire_secret(secret)
    dossier.chmod(0o700)
    lien = dossier / "lien.password"
    os.symlink(secret, lien)
    with pytest.raises(op.Refus, match="ordinaire"):
        op.lire_secret(lien)


def test_verificateur_scram_deterministe_et_sans_clair() -> None:
    secret = "a" * 64
    verificateur = op.verificateur_scram(secret, sel=b"\x00" * 16)
    assert verificateur == op.verificateur_scram(secret, sel=b"\x00" * 16)
    assert verificateur.startswith("SCRAM-SHA-256$4096:") and secret not in verificateur
    assert op.verificateur_scram(secret) != op.verificateur_scram(secret)  # sel aléatoire


def test_mauvaise_base_refusee_par_la_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PGDATABASE", "ragdb")
    assert op.main(["observe", "--repository-root", str(ROOT)]) == 1
    assert "PGDATABASE doit valoir ragdb_profile_gate_v4" in capsys.readouterr().err
