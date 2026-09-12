"""Épreuves de l'audit de récupération d'espace disque.

Le danger de ce lot n'est pas de mal compter des gigaoctets : c'est de
proposer une commande qui emporte la base de revue PII, la base dédiée ou un
artefact de modèle épinglé. Les épreuves portent donc sur ce qu'une commande
n'a pas le droit d'être.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import audit_disk_recovery as audit  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/disk_recovery_audit.json"

MESURES = {
    "disk_total_bytes": 980_000_000_000,
    "disk_free_bytes": 37_000_000_000,
    "docker_pools": {
        "Images": {"size_bytes": 109_000_000_000, "reclaimable_bytes": 78_000_000_000},
        "Build Cache": {
            "size_bytes": 137_000_000_000,
            "reclaimable_bytes": 67_000_000_000,
        },
    },
    "dangling_images": [
        {"id": "aaaa", "size_bytes": 3_180_000_000, "age": "2 hours ago"},
        {"id": "bbbb", "size_bytes": 3_180_000_000, "age": "5 hours ago"},
    ],
    "volumes_total": 205,
}


# --- Ce qu'une commande n'a pas le droit d'être -----------------------------


@pytest.mark.parametrize(
    "commande",
    [
        "docker rm -f nexus-drive-staging-v2",
        "docker volume rm e4eb093913421bb0f5605c4effc2a0b527facbc66a55978986e6a8b883a6de62",
        "dropdb drivestaging",
        "docker rm -f nexus-vector-staging-a-20260912T060731Z",
        "rm -rf /backup/rag",
        "rm -rf ~/nexus-backups",
        "rm -rf ~/rag-model-artifacts",
        "rm -rf ~/.cache/huggingface",
    ],
)
def test_une_commande_visant_une_ressource_protegee_est_refusee(commande):
    with pytest.raises(audit.RessourceProtegee):
        audit.verifier_commande(commande, "DELETE_CANDIDATE_SAFE")


@pytest.mark.parametrize(
    "commande",
    [
        "docker system prune -a",
        "docker volume prune",
        "docker image prune -a",
        "docker container prune -f",
    ],
)
def test_un_prune_global_est_refuse(commande):
    """Un prune n'énumère pas ce qu'il emporte : c'est ce qui le disqualifie."""
    with pytest.raises(audit.RessourceProtegee, match="prune global"):
        audit.verifier_commande(commande, "DELETE_CANDIDATE_SAFE")


def test_une_categorie_protegee_ne_peut_porter_aucune_commande():
    for categorie in sorted(audit.CATEGORIES_PROTEGEES):
        with pytest.raises(audit.RessourceProtegee):
            audit.element("x", 1, categorie, "raison", "docker rmi deadbeef")


def test_une_commande_ciblee_et_inoffensive_est_acceptee():
    """Le refus doit discriminer, sinon il ne prouve rien."""
    assert (
        audit.verifier_commande("docker rmi aaaa bbbb", "DELETE_CANDIDATE_SAFE")
        == "docker rmi aaaa bbbb"
    )


def test_une_categorie_inconnue_est_refusee():
    with pytest.raises(audit.EntreeManquante):
        audit.element("x", 1, "KEEP_PEUT_ETRE", "raison")


# --- Le plancher vient du gate, pas d'une copie -----------------------------


def test_le_plancher_est_lu_chez_le_gate(tmp_path):
    (tmp_path / "scripts/go_live").mkdir(parents=True)
    (tmp_path / audit.GATE).write_text(
        "DISQUE_LIBRE_MINIMUM_OCTETS = 55 * 1024**3\n", encoding="utf-8"
    )
    assert audit.plancher_du_gate(tmp_path) == 55 * 1024**3


def test_un_plancher_introuvable_n_est_pas_zero(tmp_path):
    (tmp_path / "scripts/go_live").mkdir(parents=True)
    (tmp_path / audit.GATE).write_text("rien ici\n", encoding="utf-8")
    with pytest.raises(audit.EntreeManquante):
        audit.plancher_du_gate(tmp_path)


def test_le_plancher_reel_est_celui_du_gate():
    assert audit.plancher_du_gate(RACINE) == 40 * 1024**3


# --- L'audit lui-même -------------------------------------------------------


@pytest.fixture(scope="module")
def etat() -> dict:
    return audit.construire(RACINE, mesures=MESURES)


def test_le_module_ne_sait_pas_supprimer(etat):
    """L'audit RAPPORTE des suppressions ; il n'en exécute aucune.

    `deletions_executed` compte ce qu'un humain a autorisé et lancé à la main,
    pas ce que ce code ferait. La distinction se prouve sur le code lui-même :
    aucun chemin d'exécution destructif n'y existe.
    """
    source = Path(audit.__file__).read_text(encoding="utf-8")
    for interdit in ('"rmi"', '"prune"', '"rm"', 'os.remove', 'shutil.rmtree'):
        assert interdit not in source, f"chemin destructif présent : {interdit}"
    assert etat["vectorization_executed"] is False
    assert etat["production_touched"] is False


def test_chaque_operation_rapportee_nomme_qui_l_a_autorisee(etat):
    for operation in etat["measured_history"]:
        assert operation["authorized_by"], operation["command"]
        assert operation["command"]
        assert "measured_gain_bytes" in operation


def test_une_estimation_dementie_est_dite_telle(etat):
    """Une estimation qu'un fait a démentie ne doit pas survivre en silence."""
    rmi = [op for op in etat["measured_history"] if op["command"].startswith("docker rmi")]
    assert rmi, "l'opération docker rmi n'est plus rapportée"
    operation = rmi[0]
    assert operation["measured_gain_bytes"] < operation["estimated_gain_bytes"] / 100
    assert operation["verdict"] == "ESTIMATION_DEMENTIE_PAR_LA_MESURE"
    assert operation["why"]


def test_aucune_operation_rapportee_n_aurait_ete_acceptable_sans_controle(etat):
    """Ce qui a été exécuté devait déjà passer le contrôle de protection."""
    for operation in etat["measured_history"]:
        if operation["command"].startswith("docker rmi"):
            assert (
                audit.verifier_commande(
                    operation["command"], "DELETE_CANDIDATE_SAFE"
                )
                == operation["command"]
            )


def test_les_deux_bases_sont_preservees(etat):
    assert etat["vector_db_preserved"] is True
    assert etat["review_db_preserved"] is True
    assert len(etat["volumes_protected"]) == 2


def test_aucune_ressource_protegee_ne_porte_de_commande(etat):
    for item in etat["protected_resources"]:
        assert item["proposed_command"] == "", item


def test_toute_commande_proposee_survit_a_sa_propre_verification(etat):
    """Ce qui sort du rapport doit repasser le contrôle sans broncher."""
    for commande in etat["commands_requiring_human_confirmation"]:
        assert audit.verifier_commande(commande, "DELETE_CANDIDATE_SAFE") == commande


def test_le_manque_est_nomme(etat):
    assert etat["disk_policy_ok_before"] is False
    assert etat["disk_shortfall_bytes"] > 0
    assert etat["disk_shortfall_bytes"] == etat["disk_required_floor"] - 37_000_000_000


def test_un_disque_au_dessus_du_plancher_ne_manque_de_rien():
    """Sans ce cas, on ne saurait pas si le calcul sait dire « rien à faire »."""
    large = {**MESURES, "disk_free_bytes": 500_000_000_000}
    etat = audit.construire(RACINE, mesures=large)
    assert etat["disk_policy_ok_after"] is True
    assert etat["disk_shortfall_bytes"] == 0


def test_avant_et_apres_ne_sont_pas_confondus():
    """Le piège de ce rapport : relire l'état corrigé comme l'état d'origine.

    On pose ici l'espace libre CONSTATÉ après nettoyage. « Avant » doit rester
    celui d'où la campagne est partie, pas celui-ci.
    """
    apres = {**MESURES, "disk_free_bytes": 108_489_826_304}
    etat = audit.construire(RACINE, mesures=apres)
    assert etat["disk_policy_ok_before"] is False
    assert etat["disk_policy_ok_after"] is True
    assert etat["disk_free_before"] == audit.OPERATIONS_EXECUTEES[0][
        "free_before_bytes"
    ]
    assert etat["disk_free_after"] > etat["disk_free_before"]
    assert etat["disk_recovered_bytes"] > 0


def test_le_gain_estime_est_annonce_comme_une_borne_haute(etat):
    assert etat["estimated_free_after"] >= etat["disk_free_before"]
    assert "borne HAUTE" in etat["estimated_free_after_note"]


def test_les_deux_unites_sont_reconciliees(etat):
    """34,85 Gio et 37,42 Go ne sont pas deux relevés : c'est le même."""
    assert "MÊME mesure" in etat["unit_note"]


# --- Le rapport VERSIONNÉ ---------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    if not RAPPORT.is_file():
        pytest.skip("audit pas encore produit")
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_le_rapport_versionne_ne_propose_rien_d_interdit(rapport):
    for item in rapport["inventory"]:
        commande = item["proposed_command"]
        if not commande:
            continue
        assert item["category"].startswith("DELETE_CANDIDATE")
        assert audit.verifier_commande(commande, item["category"]) == commande


def test_le_rapport_versionne_preserve_les_deux_bases(rapport):
    assert rapport["review_db_preserved"] is True
    assert rapport["vector_db_preserved"] is True
    assert rapport["vectorization_executed"] is False


def test_le_rapport_versionne_dit_le_gain_reel(rapport):
    """Le chiffre opposable est celui qui a été mesuré, pas celui espéré."""
    assert rapport["disk_policy_ok_before"] is False
    assert rapport["disk_policy_ok_after"] is True
    assert rapport["disk_recovered_bytes"] > 0
    for operation in rapport["measured_history"]:
        assert "measured_gain_bytes" in operation


def test_le_rapport_versionne_classe_tout(rapport):
    assert rapport["inventory"]
    for item in rapport["inventory"]:
        assert item["category"] in audit.CATEGORIES
        assert item["reason"]


def test_le_rapport_ne_nie_pas_ce_qu_il_consigne(etat):
    """Le défaut que la revue a attrapé : affirmer « aucune suppression »
    sur la même page qu'un historique de suppressions.

    Les deux énoncés étaient vrais séparément — le script ne supprime rien,
    l'humain a supprimé — et faux ensemble. Le rendu les avait mis sous le
    même titre.
    """
    rendu = audit.rendre_markdown(etat)
    assert "## Ce que ce script ne fait jamais" in rendu
    if etat["measured_history"]:
        assert "aucune suppression" not in rendu
        assert "aucune lancée" not in rendu
        # L'historique doit précéder les affirmations, pas s'y glisser.
        assert rendu.index("a autorisé et exécuté") < rendu.index(
            "## Ce que ce script ne fait jamais"
        )


def test_chaque_titre_du_rendu_est_suivi_de_son_contenu(etat):
    """Un titre suivi d'un autre titre est le symptôme d'une section insérée
    au mauvais endroit — exactement ce qui s'était produit."""
    rendu = audit.rendre_markdown(etat)
    lignes = [ligne for ligne in rendu.splitlines() if ligne.strip()]
    for precedent, suivant in zip(lignes, lignes[1:]):
        if precedent.startswith("## "):
            assert not suivant.startswith("## "), (
                f"section vide : « {precedent} » immédiatement suivi de "
                f"« {suivant} »"
            )
