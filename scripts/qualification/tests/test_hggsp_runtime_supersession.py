"""Supersession du runtime HGGSP (amendement après #279) : hermétique, sans SSH ni serveur.

Les deux scripts sont exécutés réellement, sur des répertoires temporaires. Ce que l'on
prouve : l'ancienne paire n'est jamais perdue, le remplacement n'a lieu que dans le cas
pinné, et tout autre état refuse SANS rien modifier.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REMOTE = ROOT / "scripts/go_live/readiness_install_remote.sh"
MARQUEURS = ROOT / "scripts/go_live/retire_runtime_markers.sh"
ORCHESTRATEUR = ROOT / "scripts/go_live/staging_hggsp_complementary.sh"
M, B = "staging-readiness-hggsp-successor.json", "staging-readiness-hggsp-successor-binding.json"


def sha(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


ANCIEN_M, ANCIEN_B = b'{"readiness":"ancienne","image":"2228650e"}\n', b'{"binding":"ancienne"}\n'
NOUVEAU_M, NOUVEAU_B = b'{"readiness":"nouvelle","image":"318ef584"}\n', b'{"binding":"nouvelle"}\n'


def dossiers(tmp_path: Path) -> tuple[Path, Path]:
    d = tmp_path / "readiness"
    d.mkdir()
    incoming = d / ".incoming-test"
    incoming.mkdir()
    return d, incoming


def deposer(incoming: Path, m: bytes = NOUVEAU_M, b: bytes = NOUVEAU_B) -> None:
    (incoming / M).write_bytes(m)
    (incoming / B).write_bytes(b)


def poser(d: Path, m: bytes, b: bytes) -> None:
    (d / M).write_bytes(m)
    (d / B).write_bytes(b)


def lancer(d: Path, incoming: Path, *, new: tuple[bytes, bytes] = (NOUVEAU_M, NOUVEAU_B),
           old: tuple[bytes, bytes] | None = (ANCIEN_M, ANCIEN_B), stamp: str = "20261003T100000Z",
           **surcharge: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"], "D": str(d), "M": M, "B": B, "INCOMING": str(incoming), "STAMP": stamp,
        "NEW_M": sha(new[0]), "NEW_B": sha(new[1]),
        "OLD_M": sha(old[0]) if old else "", "OLD_B": sha(old[1]) if old else "",
    }
    env.update(surcharge)
    return subprocess.run(["bash", str(REMOTE)], env=env, capture_output=True, text=True, check=False)


def instantane(d: Path) -> dict[str, str]:
    """Contenu, noms et type de tout l'arbre sauf le dépôt entrant : pour prouver « rien n'a changé »."""
    return {
        str(p.relative_to(d)): ("lien" if p.is_symlink() else sha(p.read_bytes()) if p.is_file() else "dir")
        for p in sorted(d.rglob("*")) if ".incoming" not in str(p)
    }


def sans_depot_entrant(incoming: Path) -> None:
    """Sur refus comme sur succès, le dépôt entrant (une copie) est nettoyé ; jamais l'état distant."""
    assert not incoming.exists()


# ── installation, rejeu, supersession ────────────────────────────────────────


def test_installation_quand_aucune_paire_distante(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    deposer(incoming)
    resultat = lancer(d, incoming, old=None)
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.startswith("READINESS_INSTALLED ")
    assert (d / M).read_bytes() == NOUVEAU_M and (d / B).read_bytes() == NOUVEAU_B
    assert stat.S_IMODE((d / M).stat().st_mode) == 0o600
    assert not (d / "superseded").exists() and not incoming.exists()


def test_rejeu_deja_installee_n_ecrit_rien(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, NOUVEAU_M, NOUVEAU_B)
    deposer(incoming)
    avant = instantane(d)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 0 and resultat.stdout.startswith("READINESS_ALREADY_INSTALLED ")
    assert instantane(d) == avant and not (d / "superseded").exists()


def test_supersession_archive_l_ancienne_paire_puis_remplace(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.startswith("READINESS_SUPERSEDED ")
    assert (d / M).read_bytes() == NOUVEAU_M and (d / B).read_bytes() == NOUVEAU_B
    archive = d / "superseded" / f"20261003T100000Z-{sha(ANCIEN_M)[:12]}"
    assert (archive / M).read_bytes() == ANCIEN_M and (archive / B).read_bytes() == ANCIEN_B
    assert stat.S_IMODE((archive / M).stat().st_mode) == 0o400  # preuve en lecture seule
    assert stat.S_IMODE((archive / B).stat().st_mode) == 0o400
    assert stat.S_IMODE((d / M).stat().st_mode) == 0o600
    assert not incoming.exists()
    assert f"archive={archive}" in resultat.stdout


def test_la_supersession_n_est_pas_rejouable_comme_une_nouvelle_supersession(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming)
    assert lancer(d, incoming).returncode == 0
    incoming.mkdir()
    deposer(incoming)
    rejeu = lancer(d, incoming, stamp="20261003T110000Z")
    assert rejeu.returncode == 0 and rejeu.stdout.startswith("READINESS_ALREADY_INSTALLED ")
    assert len(list((d / "superseded").iterdir())) == 1  # aucune seconde archive


# ── refus : l'état distant reste identique, octet pour octet ──────────────────

AUTRE_M, AUTRE_B = b'{"readiness":"inconnue"}\n', b'{"binding":"inconnue"}\n'


@pytest.mark.parametrize(
    ("distant", "pins", "motif"),
    [
        ((AUTRE_M, AUTRE_B), (ANCIEN_M, ANCIEN_B), "divergente et non supersédable"),
        ((ANCIEN_M, AUTRE_B), (ANCIEN_M, ANCIEN_B), "divergente et non supersédable"),  # paire mixte
        ((AUTRE_M, ANCIEN_B), (ANCIEN_M, ANCIEN_B), "divergente et non supersédable"),  # paire mixte
        ((NOUVEAU_M, ANCIEN_B), (ANCIEN_M, ANCIEN_B), "divergente et non supersédable"),  # remplacement interrompu
        ((ANCIEN_M, NOUVEAU_B), (ANCIEN_M, ANCIEN_B), "divergente et non supersédable"),
        ((ANCIEN_M, ANCIEN_B), None, "divergente et non supersédable"),  # aucun pin : jamais d'écrasement
    ],
    ids=["inconnue", "mixte-m-ancien", "mixte-b-ancien", "interrompue-m-nouveau", "interrompue-b-nouveau", "sans-pin"],
)
def test_etat_distant_non_supersedable_refuse_sans_rien_modifier(
    tmp_path: Path, distant: tuple[bytes, bytes], pins: tuple[bytes, bytes] | None, motif: str,
) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, *distant)
    deposer(incoming)
    avant = instantane(d)
    resultat = lancer(d, incoming, old=pins)
    assert resultat.returncode == 4 and motif in resultat.stderr
    assert instantane(d) == avant and not (d / "superseded").exists()
    sans_depot_entrant(incoming)
    assert (d / M).read_bytes() == distant[0] and (d / B).read_bytes() == distant[1]


@pytest.mark.parametrize("present", [M, B])
def test_paire_distante_partielle_refuse(tmp_path: Path, present: str) -> None:
    d, incoming = dossiers(tmp_path)
    (d / present).write_bytes(ANCIEN_M)
    deposer(incoming)
    avant = instantane(d)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 4 and "partielle" in resultat.stderr
    assert instantane(d) == avant
    sans_depot_entrant(incoming)


def test_nouvelle_paire_alteree_refuse_avant_tout_remplacement(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming, m=NOUVEAU_M + b" ", b=NOUVEAU_B)  # octets ≠ empreinte annoncée
    avant = instantane(d)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 4 and "différent de l'empreinte" in resultat.stderr
    assert instantane(d) == avant


def test_nouvelle_paire_absente_refuse(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    (incoming / M).write_bytes(NOUVEAU_M)  # liaison absente
    avant = instantane(d)
    assert lancer(d, incoming).returncode == 4 and instantane(d) == avant


def test_archive_deja_presente_refuse_sans_remplacer(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming)
    (d / "superseded" / f"20261003T100000Z-{sha(ANCIEN_M)[:12]}").mkdir(parents=True)
    avant = instantane(d)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 4 and "archive de supersession déjà présente" in resultat.stderr
    assert instantane(d) == avant


@pytest.mark.parametrize(
    "surcharge",
    [{"OLD_M": "x" * 64}, {"OLD_M": "A" * 64}, {"OLD_B": ""}, {"NEW_M": "zz"}, {"STAMP": "a/b"}, {"STAMP": "a b"}],
    ids=["pin-non-hex", "pin-majuscules", "pin-incomplet", "nouvelle-non-hex", "horodatage-chemin", "horodatage-espace"],
)
def test_parametres_invalides_refusent(tmp_path: Path, surcharge: dict[str, str]) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming)
    avant = instantane(d)
    resultat = lancer(d, incoming, **surcharge)
    assert resultat.returncode == 4 and instantane(d) == avant


def test_ancienne_et_nouvelle_identiques_refuse(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming, m=ANCIEN_M, b=ANCIEN_B)
    resultat = lancer(d, incoming, new=(ANCIEN_M, ANCIEN_B))
    assert resultat.returncode == 4 and "identiques" in resultat.stderr


# ── anomalies de fichiers, remplacement interrompu, dépôt entrant ───────────────


@pytest.mark.parametrize("liens", [(True, True), (True, False), (False, True)], ids=["deux", "manifeste", "liaison"])
def test_lien_symbolique_casse_est_une_anomalie_pas_une_absence(tmp_path: Path, liens: tuple[bool, bool]) -> None:
    """Deux liens cassés : `-e` les croirait absents et l'installation les remplacerait en silence."""
    d, incoming = dossiers(tmp_path)
    for nom, octets, lien in ((M, ANCIEN_M, liens[0]), (B, ANCIEN_B, liens[1])):
        if lien:
            (d / nom).symlink_to(tmp_path / "cible-inexistante")
        else:
            (d / nom).write_bytes(octets)
    deposer(incoming)
    avant = instantane(d)
    resultat = lancer(d, incoming, old=None)
    assert resultat.returncode == 4 and instantane(d) == avant
    assert (d / M).is_symlink() == liens[0] and (d / B).is_symlink() == liens[1]  # rien n'a été remplacé
    assert resultat.stdout == ""  # ni READINESS_INSTALLED ni READINESS_SUPERSEDED
    sans_depot_entrant(incoming)


def test_paire_distante_en_liens_symboliques_refuse(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    (tmp_path / "m").write_bytes(ANCIEN_M)
    (tmp_path / "b").write_bytes(ANCIEN_B)
    (d / M).symlink_to(tmp_path / "m")
    (d / B).symlink_to(tmp_path / "b")
    deposer(incoming)
    resultat = lancer(d, incoming)
    assert resultat.returncode == 4 and "lien symbolique" in resultat.stderr
    assert (d / M).is_symlink() and (d / B).is_symlink() and not (d / "superseded").exists()


def test_lien_symbolique_dans_le_depot_entrant_refuse(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    (tmp_path / "vrai.json").write_bytes(NOUVEAU_M)
    (incoming / M).symlink_to(tmp_path / "vrai.json")
    (incoming / B).write_bytes(NOUVEAU_B)
    avant = instantane(d)
    assert lancer(d, incoming).returncode == 4 and instantane(d) == avant


def stub_mv(tmp_path: Path, *, echoue_pour: str) -> str:
    """`mv` qui échoue UNE fois quand sa destination finit par `echoue_pour`, puis délègue : simule
    un second renommage interrompu sans toucher au script."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    marque = tmp_path / "deja-echoue"
    (bin_ / "mv").write_text(
        "#!/usr/bin/env bash\n"
        f'for dernier; do :; done\n'
        f'if [[ "$dernier" == *{echoue_pour} && ! -e "{marque}" ]]; then : > "{marque}"; exit 1; fi\n'
        'exec /bin/mv "$@"\n'
    )
    (bin_ / "mv").chmod(0o755)
    return f"{bin_}:{os.environ['PATH']}"


def test_remplacement_interrompu_restaure_l_ancienne_paire_depuis_l_archive(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, ANCIEN_M, ANCIEN_B)
    deposer(incoming)
    resultat = lancer(d, incoming, PATH=stub_mv(tmp_path, echoue_pour=B))
    assert resultat.returncode == 4 and "remplacement interrompu" in resultat.stderr
    assert "ancienne paire restaurée" in resultat.stderr
    # jamais de paire mixte : l'ancienne paire est revenue, octet pour octet, en 0600
    assert (d / M).read_bytes() == ANCIEN_M and (d / B).read_bytes() == ANCIEN_B
    assert stat.S_IMODE((d / M).stat().st_mode) == 0o600
    archive = d / "superseded" / f"20261003T100000Z-{sha(ANCIEN_M)[:12]}"
    assert (archive / M).read_bytes() == ANCIEN_M and (archive / B).read_bytes() == ANCIEN_B
    assert not list(d.glob("*.restauration")) and not list(d.glob(".incoming*"))


def test_installation_interrompue_ne_laisse_pas_de_paire_partielle(tmp_path: Path) -> None:
    d, incoming = dossiers(tmp_path)
    deposer(incoming)
    resultat = lancer(d, incoming, old=None, PATH=stub_mv(tmp_path, echoue_pour=B))
    assert resultat.returncode == 4 and "installation interrompue" in resultat.stderr
    assert not (d / M).exists() and not (d / B).exists()


@pytest.mark.parametrize("entrant", ["{d}", "{d}/../ailleurs", "/tmp/x", "{d}/a/../.."])
def test_depot_entrant_hors_du_repertoire_refuse_sans_rien_supprimer(tmp_path: Path, entrant: str) -> None:
    d, incoming = dossiers(tmp_path)
    poser(d, NOUVEAU_M, NOUVEAU_B)  # la paire ACTIVE porte les mêmes noms que le dépôt entrant
    avant = instantane(d)
    cible = entrant.format(d=d)
    resultat = lancer(d, Path(cible))
    assert resultat.returncode == 4 and "hors de" in resultat.stderr
    assert instantane(d) == avant and (d / M).read_bytes() == NOUVEAU_M  # le nettoyage n'a rien supprimé


# ── marqueurs : renommés, jamais supprimés ────────────────────────────────────

TOUS = {
    "successor_readiness_install": "deux fichiers signés, V4 conservée",
    "successor_preflight": "V4=9/263/405/5678 HGGSP=0",
    "successor_control_schema_020_and_adopter_role": "head=20, adopter provisionné",
    "successor_scope_authorization_registration_r4": "count=2 review=278@dfe70d16",
}


def etat(tmp_path: Path, marqueurs: dict[str, str] | None = None) -> Path:
    e = tmp_path / "etat"
    e.mkdir()
    for op, contenu in (marqueurs if marqueurs is not None else TOUS).items():
        (e / f"{op}.done").write_text(contenu + "\n")
    (e / "execution.log").write_text("journal existant\n")
    return e


def retirer(e: Path, stamp: str = "20261003T120000Z") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(MARQUEURS), str(e), stamp], capture_output=True, text=True, check=False)


def test_les_marqueurs_runtime_sont_renommes_et_les_autres_intacts(tmp_path: Path) -> None:
    e = etat(tmp_path)
    resultat = retirer(e)
    assert resultat.returncode == 0, resultat.stderr
    for op in ("successor_readiness_install", "successor_preflight"):
        assert not (e / f"{op}.done").exists()
        assert (e / f"{op}.done.superseded-20261003T120000Z").read_text() == TOUS[op] + "\n"  # preuve conservée
    for op in ("successor_control_schema_020_and_adopter_role", "successor_scope_authorization_registration_r4"):
        assert (e / f"{op}.done").read_text() == TOUS[op] + "\n"  # faits persistants : intacts
    journal = (e / "execution.log").read_text()
    assert journal.startswith("journal existant\n") and journal.count("SUPERSEDE") == 2
    assert not list(e.glob("*.invalid-*"))


@pytest.mark.parametrize("absent", ["successor_readiness_install", "successor_preflight"])
def test_un_marqueur_absent_refuse_sans_renommage_partiel(tmp_path: Path, absent: str) -> None:
    e = etat(tmp_path, {k: v for k, v in TOUS.items() if k != absent})
    avant = sorted(p.name for p in e.iterdir())
    resultat = retirer(e)
    assert resultat.returncode == 3 and "rien à superséder" in resultat.stderr
    assert sorted(p.name for p in e.iterdir()) == avant


def test_cible_deja_presente_refuse_sans_renommage_partiel(tmp_path: Path) -> None:
    e = etat(tmp_path)
    (e / "successor_preflight.done.superseded-20261003T120000Z").write_text("autre preuve\n")
    avant = sorted(p.name for p in e.iterdir())
    assert retirer(e).returncode == 3
    assert sorted(p.name for p in e.iterdir()) == avant
    assert (e / "successor_preflight.done.superseded-20261003T120000Z").read_text() == "autre preuve\n"


@pytest.mark.parametrize("stamp", ["a/b", "a b", "", "../x"])
def test_horodatage_invalide_refuse(tmp_path: Path, stamp: str) -> None:
    e = etat(tmp_path)
    avant = sorted(p.name for p in e.iterdir())
    assert retirer(e, stamp).returncode != 0 and sorted(p.name for p in e.iterdir()) == avant


def test_repertoire_d_etat_introuvable_refuse(tmp_path: Path) -> None:
    assert retirer(tmp_path / "absent").returncode == 3


# ── câblage de l'orchestrateur (statique : jamais lancé) ───────────────────────


def orchestrateur() -> str:
    return ORCHESTRATEUR.read_text(encoding="utf-8")


def test_l_installation_passe_par_le_script_distant_et_les_pins_de_l_amendement() -> None:
    texte = orchestrateur()
    etape = texte.split("etape_successor_readiness_install() {", 1)[1].split("\netape_successor_preflight", 1)[0]
    assert 'cat "$ICI/readiness_install_remote.sh"' in etape
    assert "pin_readiness_supersedee manifest" in etape and "pin_readiness_supersedee binding" in etape
    assert "amendment.superseded_runtime.readiness." in texte
    assert "READINESS_(INSTALLED|ALREADY_INSTALLED|SUPERSEDED)" in etape
    # plus d'écrasement direct de la destination : on dépose dans un répertoire entrant
    assert '"$SSH_HOST:$READINESS_REMOTE/$file"' not in etape and ".incoming-" in etape
    assert "chmod 600 '$READINESS_REMOTE" not in etape
    # tout état distant divergent sans pin est refusé par le script distant, testé ci-dessus


def test_la_commande_supersede_runtime_est_bornee_et_ne_touche_pas_au_serveur() -> None:
    texte = orchestrateur()
    commande = texte.split("    supersede-runtime)", 1)[1].split("\n    *)", 1)[0]
    for exigence in ("charger_hggsp", "autoriser_hggsp successor_readiness_install", "readiness_locale",
                     "amendment.superseded_runtime.readiness.manifest_sha256",
                     "retire_runtime_markers.sh", "la paire distante n'est pas celle"):
        assert exigence in commande, exigence
    assert "scp " not in commande and "docker " not in commande and "psql" not in commande
    assert "supersede-runtime" in texte.split("usage:", 1)[1]
    # le mode simulation ne renomme rien
    assert commande.index('[ "$DRY_RUN" = 1 ]') < commande.index("retire_runtime_markers.sh")


def test_les_scripts_d_aide_ne_suppriment_aucune_preuve() -> None:
    marqueurs = MARQUEURS.read_text(encoding="utf-8")
    assert not re.search(r"\brm\b", marqueurs.replace("# ", "#"))  # renommage seulement
    distant = REMOTE.read_text(encoding="utf-8")
    assert "rm -f \"$INCOMING/$M\" \"$INCOMING/$B\"" in distant  # seul le dépôt entrant est nettoyé
    assert "trap nettoyer EXIT" in distant
    assert not re.search(r"rm\s+[^\n]*\$D/", distant)


def stub_mv_sans_deplacement(tmp_path: Path, op: str) -> str:
    """`mv -n` qui « réussit » sans rien déplacer pour un marqueur : la course dénoncée par la revue."""
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "mv").write_text(
        "#!/usr/bin/env bash\n"
        f'if [[ "$*" == *"{op}.done "* && "$1" == "-n" ]]; then exit 0; fi\n'
        'exec /bin/mv "$@"\n'
    )
    (bin_ / "mv").chmod(0o755)
    return f"{bin_}:{os.environ['PATH']}"


@pytest.mark.parametrize("op", ["successor_preflight", "successor_readiness_install"])
def test_un_renommage_qui_ne_deplace_rien_annule_tout_et_ne_journalise_pas(tmp_path: Path, op: str) -> None:
    e = etat(tmp_path)
    avant = {p.name: p.read_text() for p in e.iterdir()}
    env = {**os.environ, "PATH": stub_mv_sans_deplacement(tmp_path, op)}
    resultat = subprocess.run(["bash", str(MARQUEURS), str(e), "20261003T120000Z"],
                              env=env, capture_output=True, text=True, check=False)
    assert resultat.returncode == 3 and "renommage non effectué" in resultat.stderr
    assert {p.name: p.read_text() for p in e.iterdir()} == avant  # tout annulé, journal intact
    assert "SUPERSEDE" not in (e / "execution.log").read_text()


def test_journal_non_ecrivable_annule_les_renommages(tmp_path: Path) -> None:
    e = etat(tmp_path)
    (e / "execution.log").unlink()
    (e / "execution.log").mkdir()  # l'ajout au journal échouera
    resultat = retirer(e)
    assert resultat.returncode == 3 and "journal non écrit" in resultat.stderr
    for op in ("successor_readiness_install", "successor_preflight"):
        assert (e / f"{op}.done").read_text() == TOUS[op] + "\n"
        assert not (e / f"{op}.done.superseded-20261003T120000Z").exists()


def test_le_preflight_est_retire_avant_l_installation(tmp_path: Path) -> None:
    """Un état interrompu ne doit jamais rejouer l'installation en sautant le préflight."""
    texte = MARQUEURS.read_text(encoding="utf-8")
    ligne = next(ligne for ligne in texte.splitlines() if ligne.startswith("OPERATIONS="))
    assert ligne.index("successor_preflight") < ligne.index("successor_readiness_install")


def test_un_marqueur_lien_symbolique_refuse(tmp_path: Path) -> None:
    e = etat(tmp_path)
    (e / "successor_preflight.done").unlink()
    (tmp_path / "ailleurs").write_text("x\n")
    (e / "successor_preflight.done").symlink_to(tmp_path / "ailleurs")
    assert retirer(e).returncode == 3 and (e / "successor_readiness_install.done").exists()
