"""Épreuves de la vectorisation phase A.

Le risque n'est pas de mal calculer un vecteur : c'est de produire un index
qui paraît couvrir le périmètre autorisé alors qu'il en laisse l'essentiel
inatteignable, ou d'apposer une provenance canonique sur un modèle que
personne n'a vérifié. Les épreuves portent donc d'abord sur les refus.

Aucun identifiant de connexion n'apparaît ici. Les DSN viennent de
l'environnement ; sans eux, les épreuves qui touchent une base sont ignorées,
jamais devinées.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import vectorize_phase_a as phase_a  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/vectorization_phase_a_execution.json"
ECART = RACINE / "docs/reports/go_live/rag_searchability_gap.json"
READINESS = RACINE / "docs/reports/go_live/go_live_readiness_state.json"

#: Noms LOGIQUES. Les valeurs ne sont pas dans le dépôt et ne doivent pas y être.
VAR_DEDIEE = "DEDICATED_VECTOR_DB_URL"
VAR_REVUE = "REVIEW_DB_READONLY_URL"


def _dsn(variable: str) -> str:
    valeur = os.environ.get(variable, "").strip()
    if not valeur:
        pytest.skip(f"{variable} non défini : aucune base n'est devinée ici")
    return valeur


def _psycopg():
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        pytest.skip("psycopg indisponible")
    return psycopg


def _etat_base(**surcharges):
    base = {
        "vector_rows": 0,
        "distinct_contents": 0,
        "authorized_with_chunks": 0,
        "authorized_without_chunks": 0,
        "pgvector_in_review": False,
    }
    base.update(surcharges)
    return base


PROVENANCE_VALIDE = {
    "artifact_logical_id": "staging-phase-a-e5-large-" + phase_a.REVISION,
    "artifact_revision": phase_a.REVISION,
    "artifact_inventory_sha256": "a" * 64,
    "artifact_root_env_var": phase_a.VARIABLE_RACINE_ARTEFACTS,
    "artifact_status": "VERIFIED_BY_CANONICAL_AUTHORITY",
    "artifact_verifier": "épreuve",
    "artifact_anchor": "épreuve",
}


# --- Aptitude : le contrôle qui empêche un index trompeur ------------------


def test_un_seul_chunk_trop_long_suffit_a_refuser():
    """Fail-closed : la majorité qui tient ne rachète pas la minorité qui non."""
    aptitude = phase_a.evaluer_aptitude([10] * 999 + [513], 512)
    assert aptitude["fit_for_vectorization"] is False
    assert aptitude["chunks_over_limit"] == 1


def test_un_corpus_entierement_dans_la_limite_est_apte():
    """Le refus doit discriminer, sinon il ne prouve rien."""
    aptitude = phase_a.evaluer_aptitude([10, 512, 200], 512)
    assert aptitude["fit_for_vectorization"] is True


def test_un_corpus_vide_n_est_pas_un_corpus_apte():
    with pytest.raises(phase_a.EntreeManquante):
        phase_a.evaluer_aptitude([], 512)


def test_la_part_de_texte_inatteignable_est_mesuree_pas_devinee():
    aptitude = phase_a.evaluer_aptitude([100, 900], 512)
    assert aptitude["tokens_in_over_limit_chunks"] == 900
    assert aptitude["share_of_text_unreachable"] == 90.0


def test_le_refus_nomme_les_deux_issues_fausses():
    raison = phase_a.raison_du_refus(phase_a.evaluer_aptitude([100, 900], 512))
    assert "tronquer" in raison
    assert "inatteignables" in raison


# --- Succès : complet, ou pas du tout -------------------------------------


def test_une_seule_ligne_vectorielle_ne_certifie_rien():
    """LE défaut relevé en revue.

    Le corpus est apte, 100 lignes sont attendues, une seule existe. Un
    `vector_rows > 0` faisait auparavant passer cela pour une phase A réussie.
    """
    aptitude = phase_a.evaluer_aptitude([10] * 100, 512)
    controles = phase_a.controles_de_couverture(
        aptitude=aptitude,
        etat_base=_etat_base(
            vector_rows=1, distinct_contents=1, authorized_with_chunks=50
        ),
    )
    succes, manquements = phase_a.succes_phase_a(aptitude, controles)
    assert succes is False
    assert any("couverture incomplète" in m for m in manquements)
    assert any("contenus couverts" in m for m in manquements)


def test_une_couverture_complete_est_un_succes():
    """Le refus doit discriminer."""
    aptitude = phase_a.evaluer_aptitude([10] * 100, 512)
    controles = phase_a.controles_de_couverture(
        aptitude=aptitude,
        etat_base=_etat_base(
            vector_rows=100, distinct_contents=50, authorized_with_chunks=50
        ),
    )
    succes, manquements = phase_a.succes_phase_a(aptitude, controles)
    assert succes is True, manquements


def test_un_contenu_autorise_manquant_fait_echouer():
    aptitude = phase_a.evaluer_aptitude([10] * 100, 512)
    controles = phase_a.controles_de_couverture(
        aptitude=aptitude,
        etat_base=_etat_base(
            vector_rows=100, distinct_contents=49, authorized_with_chunks=50
        ),
    )
    succes, manquements = phase_a.succes_phase_a(aptitude, controles)
    assert succes is False
    assert controles["missing_authorized_contents_with_chunks"] == 1
    assert any("missing_authorized_contents_with_chunks" in m for m in manquements)


@pytest.mark.parametrize(
    "compteur",
    [
        "unauthorized_content_rows",
        "gate_refused_rows",
        "dimension_mismatch",
        "null_vectors",
        "duplicates",
    ],
)
def test_un_seul_compteur_non_nul_fait_echouer(compteur):
    aptitude = phase_a.evaluer_aptitude([10] * 10, 512)
    controles = phase_a.controles_de_couverture(
        aptitude=aptitude,
        etat_base=_etat_base(
            vector_rows=10, distinct_contents=5, authorized_with_chunks=5
        ),
    )
    controles[compteur] = 1
    succes, manquements = phase_a.succes_phase_a(aptitude, controles)
    assert succes is False
    assert any(compteur in m for m in manquements)


def test_un_corpus_inapte_ne_peut_jamais_reussir():
    aptitude = phase_a.evaluer_aptitude([10, 9999], 512)
    controles = phase_a.controles_de_couverture(
        aptitude=aptitude,
        etat_base=_etat_base(vector_rows=2, distinct_contents=1, authorized_with_chunks=1),
    )
    succes, _ = phase_a.succes_phase_a(aptitude, controles)
    assert succes is False
    assert controles["expected_vector_rows"] == 0


# --- Provenance : vérifiée, jamais estampillée -----------------------------


def test_un_artefact_absent_ne_recoit_aucune_provenance(tmp_path):
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="absent"):
        phase_a.verifier_artefact(tmp_path / "nexistepas", verificateur=lambda *a, **k: a[0])


def test_un_artefact_sans_inventaire_est_refuse(tmp_path):
    (tmp_path / "art").mkdir()
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="inventaire absent"):
        phase_a.verifier_artefact(tmp_path / "art", verificateur=lambda *a, **k: a[0])


def _artefact_jouet(tmp_path, revision=None, dim=1024):
    art = tmp_path / f"staging-phase-a-e5-large-{phase_a.REVISION}"
    art.mkdir()
    (art / "SHA256SUMS").write_text("deadbeef  config.json\n", encoding="utf-8")
    (art / "manifest.json").write_text(
        json.dumps(
            {
                "model_id": phase_a.MODELE,
                "canonical_dim": dim,
                "revision_requested": revision or phase_a.REVISION,
            }
        ),
        encoding="utf-8",
    )
    return art


def test_un_refus_de_l_autorite_canonique_interdit_la_provenance(tmp_path):
    """Si le vérificateur refuse, rien ne doit être estampillé."""
    art = _artefact_jouet(tmp_path)

    def refuse(*_a, **_k):
        raise RuntimeError("EMBEDDING_MODEL_ARTIFACT_INVALID")

    with pytest.raises(phase_a.ProvenanceNonProuvee, match="refuse l'artefact"):
        phase_a.verifier_artefact(art, verificateur=refuse)


def test_une_mauvaise_revision_est_refusee(tmp_path):
    art = _artefact_jouet(tmp_path, revision="0" * 40)
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="révision non conforme"):
        phase_a.verifier_artefact(art, verificateur=lambda *a, **k: a[0])


def test_une_mauvaise_dimension_est_refusee(tmp_path):
    art = _artefact_jouet(tmp_path, dim=768)
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="dimension annoncée"):
        phase_a.verifier_artefact(art, verificateur=lambda *a, **k: a[0])


def test_un_inventaire_modifie_change_l_empreinte(tmp_path):
    """L'empreinte suit l'inventaire : le modifier ne passe pas inaperçu."""
    art = _artefact_jouet(tmp_path)
    avant = phase_a.verifier_artefact(art, verificateur=lambda *a, **k: a[0])
    (art / "SHA256SUMS").write_text("cafebabe  config.json\n", encoding="utf-8")
    apres = phase_a.verifier_artefact(art, verificateur=lambda *a, **k: a[0])
    assert avant["artifact_inventory_sha256"] != apres["artifact_inventory_sha256"]


def test_l_empreinte_passee_au_verificateur_est_celle_de_l_inventaire(tmp_path):
    """Le vérificateur doit recevoir l'empreinte réelle, pas une valeur choisie."""
    art = _artefact_jouet(tmp_path)
    recues = {}

    def espion(chemin, *, expected_inventory_sha256):
        recues["empreinte"] = expected_inventory_sha256
        return chemin

    phase_a.verifier_artefact(art, verificateur=espion)
    assert recues["empreinte"] == phase_a.empreinte_d_inventaire(art)


def test_une_provenance_non_verifiee_est_refusee_par_le_rapport():
    """Aucun état fourni par l'appelant ne peut se faire passer pour vérifié."""
    aptitude = phase_a.evaluer_aptitude([10], 512)
    fausse = dict(PROVENANCE_VALIDE, artifact_status="CALLER_SUPPLIED")
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="non vérifié"):
        phase_a.construire(
            RACINE,
            dsn_dedie="postgresql://role@127.0.0.1:55436/dediee",
            dsn_revue="postgresql://role@127.0.0.1:55435/drivestaging",
            aptitude=aptitude,
            perimetre={"count": 1, "digest": "x", "identifiants": [], "refuses": []},
            etat_base=_etat_base(),
            disque_avant=1,
            disque_apres=1,
            provenance=fausse,
        )


def test_une_provenance_incomplete_est_refusee():
    aptitude = phase_a.evaluer_aptitude([10], 512)
    incomplete = dict(PROVENANCE_VALIDE)
    incomplete.pop("artifact_inventory_sha256")
    with pytest.raises(phase_a.ProvenanceNonProuvee, match="provenance incomplète"):
        phase_a.construire(
            RACINE,
            dsn_dedie="postgresql://role@127.0.0.1:55436/dediee",
            dsn_revue="postgresql://role@127.0.0.1:55435/drivestaging",
            aptitude=aptitude,
            perimetre={"count": 1, "digest": "x", "identifiants": [], "refuses": []},
            etat_base=_etat_base(),
            disque_avant=1,
            disque_apres=1,
            provenance=incomplete,
        )


# --- Cible et absence de troncature ---------------------------------------


def test_viser_la_base_de_revue_est_refuse():
    with pytest.raises(Exception) as capture:
        phase_a.construire(
            RACINE,
            dsn_dedie="postgresql://role@127.0.0.1:55435/drivestaging",
            dsn_revue="postgresql://role@127.0.0.1:55435/drivestaging",
            aptitude=phase_a.evaluer_aptitude([10], 512),
            perimetre={"count": 1, "digest": "x", "identifiants": [], "refuses": []},
            etat_base=_etat_base(),
            disque_avant=1,
            disque_apres=1,
            provenance=dict(PROVENANCE_VALIDE),
        )
    assert "base de revue" in str(capture.value)


def test_le_module_ne_tronque_jamais():
    source = Path(phase_a.__file__).read_text(encoding="utf-8")
    for interdit in ("truncation=True", "[:512]", "max_length=512", "truncate("):
        assert interdit not in source, f"chemin de troncature présent : {interdit}"


def test_le_module_ne_telecharge_aucun_modele():
    source = Path(phase_a.__file__).read_text(encoding="utf-8")
    assert "snapshot_download" not in source
    assert "local_files_only=False" not in source


def test_la_dimension_et_la_revision_sont_epinglees():
    assert phase_a.DIMENSION == 1024
    assert phase_a.REVISION == "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
    assert phase_a.MODELE == "intfloat/multilingual-e5-large"


# --- Aucun secret, aucun chemin de poste, dans le dépôt -------------------

#: Un DSN porteur d'identifiants : schéma, utilisateur, deux-points, secret,
#: puis l'hôte, capturé pour être jugé.
DSN_AVEC_SECRET = re.compile(
    # Le port est exclu de l'hôte : sinon « hote.exemple:5433 » ne finirait
    # pas par « .exemple » et un domaine d'exemple serait pris pour un vrai.
    r"postgres(?:ql)?://[^:/@\s\"']+:[^@\s\"']+@(?P<hote>[^/:\s\"'?]+)"
)

#: La règle n'est pas une liste de chaînes jugées inoffensives — ce serait la
#: brèche par laquelle un vrai secret passerait en ressemblant à un exemple.
#: Elle porte sur l'HÔTE : un mot de passe ne peut cohabiter dans le dépôt
#: qu'avec un domaine réservé aux exemples (RFC 2606), qui n'authentifie
#: nulle part. Une épreuve a un besoin légitime d'un tel DSN : prouver que le
#: rapport d'audit ne recopie PAS le mot de passe.
HOTES_D_EXEMPLE = (".exemple", ".example", "example.com", "example.org", "invalid")


def _fichiers_versionnes(*prefixes: str) -> list[Path]:
    import subprocess

    sortie = subprocess.run(
        ["git", "ls-files", *prefixes],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [RACINE / chemin for chemin in sortie]


def test_aucun_identifiant_de_base_dans_les_epreuves_et_les_rapports():
    """Non-régression : un mot de passe versionné est récupérable par quiconque.

    Cette épreuve existe parce que la revue en a trouvé deux dans ce lot.
    """
    coupables = []
    for chemin in _fichiers_versionnes("scripts/tests", "docs/reports"):
        if not chemin.is_file():
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for trouve in DSN_AVEC_SECRET.finditer(texte):
            hote = trouve.group("hote")
            if any(hote.endswith(exemple) or hote == exemple for exemple in HOTES_D_EXEMPLE):
                continue
            coupables.append(
                f"{chemin.relative_to(RACINE)} : {trouve.group(0)[:48]}…"
            )
    assert not coupables, "identifiants versionnés : " + "; ".join(coupables)


def test_le_detecteur_d_identifiants_attrape_un_vrai_secret(tmp_path):
    """Sans ceci, le détecteur pourrait ne rien voir et rester vert à jamais."""
    # La sonde est ASSEMBLÉE, jamais écrite en littéral : un fichier qui
    # contiendrait un DSN complet serait lui-même attrapé par la règle qu'il
    # prétend éprouver — et il l'a été au premier essai.
    reel = "postgres" + "ql://role" + ":" + "secret-de-sonde" + "@" + "127.0.0.1:5432/b"
    trouve = DSN_AVEC_SECRET.search(reel)
    assert trouve is not None
    assert trouve.group("hote") == "127.0.0.1"
    assert not any(
        trouve.group("hote").endswith(exemple) for exemple in HOTES_D_EXEMPLE
    )


def test_le_detecteur_laisse_passer_un_hote_d_exemple():
    """Le détecteur doit discriminer, sinon il interdirait l'épreuve de
    non-divulgation qui a besoin d'un mot de passe factice."""
    factice = (
        "postgres" + "ql://utilisateur" + ":" + "motdepasse" + "@"
        + "hote.exemple:5433/labase"
    )
    trouve = DSN_AVEC_SECRET.search(factice)
    assert trouve is not None
    assert any(
        trouve.group("hote").endswith(exemple) for exemple in HOTES_D_EXEMPLE
    )


def test_aucun_chemin_de_poste_dans_les_rapports_go_live():
    """Une preuve qui nomme /home/<quelqu'un> n'est pas rejouable ailleurs."""
    coupables = []
    for chemin in _fichiers_versionnes("docs/reports/go_live"):
        if not chemin.is_file():
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"/home/[a-z0-9_-]+/", texte):
            coupables.append(str(chemin.relative_to(RACINE)))
    assert not coupables, "chemins de poste versionnés : " + ", ".join(coupables)


def test_le_module_n_ecrit_aucun_chemin_absolu_dans_la_preuve():
    source = Path(phase_a.__file__).read_text(encoding="utf-8")
    assert "/home/" not in source


# --- Le rapport VERSIONNÉ -------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    if not RAPPORT.is_file():
        pytest.skip("exécution phase A pas encore rapportée")
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucun_vecteur_n_a_ete_produit_sur_un_corpus_inapte(rapport):
    if rapport["embeddability"]["fit_for_vectorization"]:
        pytest.skip("le corpus est apte : ce cas ne s'applique pas")
    assert rapport["vectorization_executed"] is False
    assert rapport["vector_rows_after"] == 0
    assert rapport["expected_vector_rows"] == 0
    assert rapport["blocking_reason"]
    assert rapport["coverage_shortfalls"]


def test_la_provenance_du_rapport_est_derivee_d_une_verification(rapport):
    assert rapport["artifact_status"] == "VERIFIED_BY_CANONICAL_AUTHORITY"
    assert "verify_embedding_artifact" in rapport["artifact_verifier"]
    assert rapport["artifact_revision"] == phase_a.REVISION
    assert len(rapport["artifact_inventory_sha256"]) == 64
    assert rapport["artifact_root_env_var"] == phase_a.VARIABLE_RACINE_ARTEFACTS
    # L'ancre doit dire ce qu'elle n'est pas.
    assert "ancre externe" in rapport["artifact_anchor"]


def test_le_rapport_ne_surestime_pas_le_read_only(rapport):
    """La formulation ne doit pas être plus forte que la preuve."""
    assert rapport["review_db_readonly_enforced_by"] == "client_session_option"
    assert "côté client" in rapport["review_db_access"]
    assert "imposée par le serveur" not in rapport["review_db_access"]


def test_le_rapport_preserve_la_base_de_revue(rapport):
    assert rapport["review_db_written"] is False
    assert rapport["pgvector_installed_in_review_db"] is False
    assert rapport["production_touched"] is False
    assert rapport["current_switch"] is False
    assert rapport["pii_decision"] is False
    assert rapport["release_modified"] is False


def test_les_exclusions_restent_vides(rapport):
    for champ in phase_a.COMPTEURS_A_ZERO:
        assert rapport[champ] == 0, champ


def test_le_perimetre_du_rapport_est_celui_de_l_ecart(rapport):
    ecart = json.loads(ECART.read_text(encoding="utf-8"))["indexable_scope"]
    assert rapport["input_count"] == ecart["count"] == 2264
    assert rapport["input_digest"] == ecart["indexable_digest"]


def test_les_contenus_sans_chunk_sont_nommes_pas_oublies(rapport):
    total = (
        rapport["authorized_contents_with_chunks"]
        + rapport["authorized_contents_without_chunks"]
    )
    assert total == rapport["input_count"]


def test_le_piege_de_la_source_de_mesure_est_nomme(rapport):
    suites = " ".join(rapport["follow_up_required"])
    assert "staging_vectors_present" in suites
    assert "dédiée" in suites
    assert "chunk_publication" in suites


def test_la_source_de_mesure_de_l_ecart_est_bien_la_base_de_revue():
    audit = json.loads(
        (RACINE / "docs/reports/go_live/ingestion_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["source"]["dbname"] == "drivestaging"
    assert audit["source"]["port"] == 55435


def test_le_go_live_reste_refuse():
    etat = json.loads(READINESS.read_text(encoding="utf-8"))
    assert etat["go_live_ready"] is False
    assert etat["target_scope_searchable"] is False
    assert etat["rag_searchability_blocker"] is True


# --- Épreuves contre les bases réelles (ignorées sans DSN) ----------------


def test_un_contenu_hors_liste_blanche_ne_peut_pas_entrer():
    """La contrainte est dans le schéma, pas dans une consigne."""
    psycopg = _psycopg()
    try:
        connexion = psycopg.connect(_dsn(VAR_DEDIEE), autocommit=True, connect_timeout=3)
    except Exception:  # pragma: no cover - base absente
        pytest.skip("base dédiée injoignable")
    with connexion, connexion.cursor() as curseur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            curseur.execute(
                "INSERT INTO drive_staging.chunk_embeddings "
                "(chunk_id, content_sha256, embedding) VALUES "
                "(%s, %s, array_fill(0::real, ARRAY[1024])::vector)",
                ("epreuve-hors-liste", "0" * 64),
            )


def test_un_vecteur_d_une_autre_dimension_ne_peut_pas_entrer():
    psycopg = _psycopg()
    try:
        connexion = psycopg.connect(_dsn(VAR_DEDIEE), autocommit=True, connect_timeout=3)
    except Exception:  # pragma: no cover
        pytest.skip("base dédiée injoignable")
    with connexion, connexion.cursor() as curseur:
        curseur.execute(
            "SELECT content_sha256 FROM drive_staging.authorized_content LIMIT 1"
        )
        ligne = curseur.fetchone()
        if ligne is None:  # pragma: no cover
            pytest.skip("liste blanche vide")
        with pytest.raises(psycopg.errors.DataException):
            curseur.execute(
                "INSERT INTO drive_staging.chunk_embeddings "
                "(chunk_id, content_sha256, embedding) VALUES "
                "(%s, %s, array_fill(0::real, ARRAY[768])::vector)",
                ("epreuve-dimension", ligne[0]),
            )


def test_le_read_only_de_la_base_de_revue_est_bien_cote_client():
    """Mesure ce qui est réellement vrai, et le rapport dit la même chose.

    Sans l'option de session, le serveur accepte l'écriture : le read-only
    n'est donc PAS imposé par le serveur ni par le rôle. L'épreuve constate
    cet état de fait au lieu de laisser croire l'inverse, et elle annule sa
    propre écriture.
    """
    psycopg = _psycopg()
    dsn = _dsn(VAR_REVUE)
    try:
        connexion = psycopg.connect(dsn, connect_timeout=3)
    except Exception:  # pragma: no cover
        pytest.skip("base de revue injoignable")
    with connexion:
        with connexion.cursor() as curseur:
            curseur.execute("SHOW default_transaction_read_only")
            defaut_serveur = curseur.fetchone()[0]
        connexion.rollback()
    assert defaut_serveur == "off", (
        "le serveur impose désormais le read-only : le rapport doit être "
        "renforcé en conséquence"
    )

    with psycopg.connect(
        dsn, options="-c default_transaction_read_only=on", connect_timeout=3
    ) as connexion:
        with connexion.cursor() as curseur:
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                curseur.execute("CREATE TABLE drive_staging.epreuve_interdite (x int)")


def test_pgvector_reste_absent_de_la_base_de_revue():
    psycopg = _psycopg()
    try:
        connexion = psycopg.connect(_dsn(VAR_REVUE), connect_timeout=3)
    except Exception:  # pragma: no cover
        pytest.skip("base de revue injoignable")
    with connexion, connexion.cursor() as curseur:
        curseur.execute("SELECT count(*) FROM pg_extension WHERE extname='vector'")
        assert curseur.fetchone()[0] == 0


def test_la_base_dediee_reste_vide_de_vecteurs():
    psycopg = _psycopg()
    try:
        connexion = psycopg.connect(_dsn(VAR_DEDIEE), connect_timeout=3)
    except Exception:  # pragma: no cover
        pytest.skip("base dédiée injoignable")
    with connexion, connexion.cursor() as curseur:
        curseur.execute("SELECT count(*) FROM drive_staging.chunk_embeddings")
        assert curseur.fetchone()[0] == 0
        curseur.execute("SELECT count(*) FROM drive_staging.authorized_content")
        assert curseur.fetchone()[0] == 2264
