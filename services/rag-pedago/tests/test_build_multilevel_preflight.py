"""Producteur canonique du préflight multi-niveaux.

Ce qui est éprouvé ici : le préflight que la release consomme est DÉRIVÉ, dans
ce dépôt, des autorités d'aujourd'hui — extracteur PDF, politique de pages,
chunker de publication, registre de profils, autorités versionnées — et non
recopié d'un fichier produit ailleurs par un outil que personne ne peut relire.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import load_script_module
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_build_multilevel_release import _module as _release_module
from test_build_multilevel_release import _synthetic_release_inputs

SERVICE_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SERVICE_ROOT / "scripts" / "build_multilevel_preflight.py"


def _producer() -> Any:
    return load_script_module(PRODUCER_PATH, "build_multilevel_preflight")


def _pdf_with_physical_pages(*texts: str | None) -> bytes:
    """PDF réel : ``None`` désigne une page structurellement vide conservée."""
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _token_counter(release: Any) -> SimpleNamespace:
    """Compteur qui DÉCLARE l'identité canonique du modèle scellé.

    Le producteur refuse tout compteur qui ne la déclare pas : le nombre de
    tokens inscrit dans la preuve n'a de sens que rapporté à un tokenizer."""
    return SimpleNamespace(
        model_id=release.EMBEDDING_MODEL,
        model_revision=release.EMBEDDING_MODEL_REVISION,
        inventory_sha256=release.EMBEDDING_INVENTORY_SHA256,
        max_sequence_length=512,
        passage_token_count=lambda text: len(text.split()) + 2,
    )


def _corpus(
    release: Any,
    mirror: Path,
    *,
    pages_by_index: dict[int, tuple[str | None, ...]] | None = None,
) -> dict[str, tuple[str, int]]:
    """Écrit un PDF réel par collection et rend les faits qu'il porte."""
    overrides = pages_by_index or {}
    facts: dict[str, tuple[str, int]] = {}
    for index, target in enumerate(release.TARGET_MATRIX, start=1):
        collection = target["collection"]
        pages = overrides.get(
            index, (f"Programme officiel {collection} page une", f"Suite {collection}")
        )
        content = _pdf_with_physical_pages(*pages)
        sha = hashlib.sha256(content).hexdigest()
        path = mirror / "01_EDUSCOL_OFFICIEL" / collection / f"{sha}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        # Le scan PII ne voit que les pages porteuses de texte : la politique de
        # pages écarte les autres, et le producteur exige que les deux mesures
        # du même document coïncident.
        facts[collection] = (sha, sum(1 for page in pages if page is not None))
    return facts


def _producer_inputs(release: Any, mirror: Path, **kwargs: Any) -> dict[str, Any]:
    facts = _corpus(release, mirror, **kwargs)
    inputs = _synthetic_release_inputs(release, artifact_facts=facts)
    return {key: value for key, value in inputs.items() if not key.startswith("preflight")}


def _emit(release: Any, producer: Any, mirror: Path, **kwargs: Any) -> dict[str, Any]:
    inputs = _producer_inputs(release, mirror, **kwargs)
    requirements = release.derive_preflight_requirements(**inputs)
    return producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )


def test_le_preflight_produit_ici_est_accepte_par_le_consommateur_de_release(
    tmp_path: Path,
) -> None:
    """Le tour complet : dérivation locale, puis release construite dessus.

    C'est la propriété que le dépôt n'avait pas. Le préflight consommé venait
    d'un outil externe : rien, dans le dépôt, ne pouvait le reproduire ni le
    contredire."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"

    facts = _corpus(release, mirror)
    inputs = _synthetic_release_inputs(release, artifact_facts=facts)
    without_preflight = {
        key: value for key, value in inputs.items() if not key.startswith("preflight")
    }
    requirements = release.derive_preflight_requirements(**without_preflight)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )

    assert document["evidence_kind"] == "MULTILEVEL_RELEASE_PREFLIGHT_V2"
    assert len(document["artifacts"]) == len(release.TARGET_MATRIX)

    inputs["preflight_evidence"] = document
    inputs["preflight_evidence_sha256"] = hashlib.sha256(
        release.canonical_json_bytes(document)
    ).hexdigest()
    bundle = release.build_release_bundle(**inputs)

    assert bundle["eligibility"]["counts"]["release_eligible"] == len(release.TARGET_MATRIX)
    assert len(bundle["subject_releases"]) == len(release.TARGET_MATRIX)


def test_le_preflight_declare_le_runtime_dont_ses_empreintes_de_chunks_dependent(
    tmp_path: Path,
) -> None:
    """D-41 : la version de pypdf et la politique de pages sont des ENTRÉES.

    Le découpage — donc chaque `chunk_sha256` — dépend de l'une et de l'autre.
    V1 n'avait aucun emplacement pour les nommer : deux préflights V1 issus de
    deux extracteurs différents sont indiscernables. C'est exactement la panne
    observée, la release servie et le banc actuel divergeant sans qu'aucune
    preuve ne dise sous quel extracteur elle avait été scellée."""
    import nexus_pdf_page_policy as page_policy

    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    document = _emit(release, producer, mirror)

    assert document["extraction_runtime"] == {
        "pypdf_version": page_policy.CANONICAL_PYPDF_VERSION,
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
    }
    assert document["chunk_target_tokens"] == 384
    assert document["embedding_model_revision"] == release.EMBEDDING_MODEL_REVISION


@pytest.mark.parametrize(
    "field, value",
    [
        ("pypdf_version", "4.2.0"),
        ("page_policy_id", "NEXUS-PDF-PAGE-POLICY-V0"),
        ("page_policy_sha256", "f" * 64),
    ],
)
def test_le_consommateur_refuse_un_preflight_issu_d_un_autre_runtime(
    tmp_path: Path, field: str, value: str
) -> None:
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )
    document["extraction_runtime"][field] = value

    with pytest.raises(ValueError, match="preflight extraction runtime differs"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_le_consommateur_refuse_le_schema_v1_qui_ne_nomme_pas_son_extracteur(
    tmp_path: Path,
) -> None:
    """V1 reste lisible ; il n'est plus recevable, et le refus est nommé."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )
    document["evidence_kind"] = "MULTILEVEL_RELEASE_PREFLIGHT_V1"

    with pytest.raises(ValueError, match="preflight evidence authority is invalid"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_une_page_structurellement_vide_est_nommee_et_reste_refusee_par_la_porte(
    tmp_path: Path,
) -> None:
    """V2 DÉCLARE la page ignorée ; il ne l'autorise pas pour autant.

    Depuis la politique de pages, une page sans texte extractible peut être
    structurellement incapable de porter un glyphe : l'extracteur la conserve
    et le document reste complet. V1 n'avait pas de mot pour cela — il ne
    connaissait qu'un compteur de pages vides dont toute valeur non nulle
    signifiait « extraction incomplète ». V2 nomme les pages concernées, ce qui
    rend la preuve lisible ; ADMETTRE un artefact qui en porte reste une
    décision de gouvernance que ce lot ne prend pas, et la porte de release la
    refuse toujours."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    document = _emit(release, producer, mirror, pages_by_index={1: ("Texte page une", None)})

    porteuse = [row for row in document["artifacts"] if row["ignored_empty_pages"]]
    assert len(porteuse) == 1
    assert porteuse[0]["ignored_empty_pages"] == [2]
    assert porteuse[0]["empty_extracted_pages"] == 1
    assert porteuse[0]["page_count"] == 2

    inputs = _producer_inputs(release, mirror, pages_by_index={1: ("Texte page une", None)})
    requirements = release.derive_preflight_requirements(**inputs)
    with pytest.raises(ValueError, match="preflight artifact gate is not clear"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )

    # Et le refus ne repose pas sur la seule couverture déclarée : une preuve
    # qui annoncerait une couverture pleine tout en nommant une page ignorée
    # reste refusée. La partition, elle, resterait satisfaite — couvertes ∪
    # ignorées = toutes les pages — et laisserait donc passer ce mensonge si la
    # porte ne s'exerçait pas aussi sur le compteur de pages vides.
    porteuse[0]["page_coverage"] = 1.0
    with pytest.raises(ValueError, match="preflight artifact gate is not clear"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_le_consommateur_refuse_un_preflight_decoupe_sur_un_autre_budget(
    tmp_path: Path,
) -> None:
    """Le budget de découpage est celui du chunker gouverné, ou rien.

    Un préflight découpé à 512 tokens et un autre à 384 ne décrivent pas le
    même corpus de chunks. Le budget est donc DÉCLARÉ dans la preuve, et
    confronté à celui que le chunker de publication expose."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )
    document["chunk_target_tokens"] = 512

    with pytest.raises(ValueError, match="preflight chunk budget differs"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_le_consommateur_refuse_un_preflight_lie_a_d_autres_index_de_programme(
    tmp_path: Path,
) -> None:
    """Les index de programme du préflight sont ceux du registre, exactement.

    Le contrôle vivait dans la validation du registre de programmes, qui devait
    pour cela connaître un préflight ; il s'exerce désormais là où le préflight
    est validé. Déplacé, pas affaibli — cette épreuve le montre."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )
    premier = sorted(document["programme_index_sha256_by_path"])[0]
    document["programme_index_sha256_by_path"][premier] = "a" * 64

    with pytest.raises(ValueError, match="preflight programme index authority differs"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_le_producteur_refuse_un_miroir_dont_les_octets_ne_font_pas_l_empreinte(
    tmp_path: Path,
) -> None:
    """Le nom d'un fichier n'est jamais une preuve de son contenu."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    victime = sorted(requirements.physical_path_by_sha.values())[0]
    (mirror / victime).write_bytes(_pdf_with_physical_pages("Contenu substitue"))

    with pytest.raises(ValueError, match="PDF mirror digest differs"):
        producer.build_preflight_evidence(
            requirements=requirements,
            pdf_mirror=mirror,
            token_counter=_token_counter(release),
        )


def test_le_producteur_refuse_un_pdf_absent_du_miroir(tmp_path: Path) -> None:
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    victime = sorted(requirements.physical_path_by_sha.values())[0]
    (mirror / victime).unlink()

    with pytest.raises(ValueError, match="PDF mirror is missing"):
        producer.build_preflight_evidence(
            requirements=requirements,
            pdf_mirror=mirror,
            token_counter=_token_counter(release),
        )


def test_le_producteur_refuse_un_scan_pii_qui_ne_decrit_pas_le_meme_document(
    tmp_path: Path,
) -> None:
    """Les pages scannées et les pages extraites sont deux mesures d'un seul objet.

    `pages_scanned` est le nombre de pages que le scan PII a réellement lues,
    c'est-à-dire les pages moins celles que la politique a écartées. Si la
    somme ne retombe pas sur le nombre de pages extraites, la preuve PII et le
    préflight décrivent deux documents, et la clairance PII ne couvre plus ce
    qui sera indexé."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    facts = _corpus(release, mirror)
    fausses = dict(facts)
    premiere = release.TARGET_MATRIX[0]["collection"]
    sha, pages = fausses[premiere]
    fausses[premiere] = (sha, pages - 1)
    inputs = _synthetic_release_inputs(release, artifact_facts=fausses)
    requirements = release.derive_preflight_requirements(
        **{key: value for key, value in inputs.items() if not key.startswith("preflight")}
    )

    with pytest.raises(ValueError, match="PII scan page count differs"):
        producer.build_preflight_evidence(
            requirements=requirements,
            pdf_mirror=mirror,
            token_counter=_token_counter(release),
        )


@pytest.mark.parametrize(
    "field, value",
    [
        ("model_id", "intfloat/multilingual-e5-base"),
        ("model_revision", "0" * 40),
        ("inventory_sha256", "3" * 64),
    ],
)
def test_le_producteur_refuse_un_compteur_qui_n_est_pas_le_modele_scelle(
    tmp_path: Path, field: str, value: str
) -> None:
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    counter = _token_counter(release)
    setattr(counter, field, value)

    with pytest.raises(ValueError, match="token counter"):
        producer.build_preflight_evidence(
            requirements=requirements,
            pdf_mirror=mirror,
            token_counter=counter,
        )


def test_le_preflight_est_reproductible_octet_pour_octet(tmp_path: Path) -> None:
    """Aucun horodatage : deux dérivations des mêmes entrées sont identiques.

    Un `generated_at` rendrait le producteur incapable de démontrer qu'il
    reproduit ce qu'il a scellé — la propriété même qui manquait."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)

    premier = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )
    second = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )

    assert release.canonical_json_bytes(premier) == release.canonical_json_bytes(second)
    assert "generated_at" not in premier


def test_les_digests_d_ensemble_sont_ceux_du_scelleur_de_release(tmp_path: Path) -> None:
    """Le préflight et la release scellent les mêmes ensembles, par construction."""
    release = _release_module()
    producer = _producer()
    mirror = tmp_path / "corpus"
    inputs = _producer_inputs(release, mirror)
    requirements = release.derive_preflight_requirements(**inputs)
    document = producer.build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=mirror,
        token_counter=_token_counter(release),
    )

    for row in document["artifacts"]:
        assert row["chunk_id_set_digest"] == release._set_digest(
            [chunk["chunk_id"] for chunk in row["chunks"]]
        )
        assert row["chunk_sha256_set_digest"] == release._set_digest(
            [chunk["chunk_sha256"] for chunk in row["chunks"]]
        )
        assert row["page_coverage_digest"] == release._set_digest(
            list(range(1, row["page_count"] + 1))
        )

    document["artifacts"][0]["chunk_id_set_digest"] = "9" * 64
    with pytest.raises(ValueError, match="preflight chunk set digest differs"):
        release._validate_preflight_document(
            document,
            preflight_sha256=hashlib.sha256(
                release.canonical_json_bytes(document)
            ).hexdigest(),
            requirements=requirements,
        )


def test_l_instantane_du_modele_doit_etre_l_artefact_scelle(tmp_path: Path) -> None:
    """Le tokenizer est chargé depuis un instantané vérifié, jamais deviné."""
    release = _release_module()
    producer = _producer()
    snapshot = tmp_path / "e5"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "canonical_dim": 1024,
                "model_id": release.EMBEDDING_MODEL,
                "upstream_revision": release.EMBEDDING_MODEL_REVISION,
            }
        ),
        encoding="utf-8",
    )
    inventaire = "".join(
        f"{hashlib.sha256((snapshot / name).read_bytes()).hexdigest()}  {name}\n"
        for name in sorted(("config.json", "manifest.json"))
    )
    (snapshot / "SHA256SUMS").write_text(inventaire, encoding="utf-8")

    with pytest.raises(ValueError, match="embedding inventory digest differs"):
        producer.verify_embedding_snapshot(snapshot)


def test_l_instantane_du_modele_refuse_un_fichier_altere_sous_le_bon_inventaire(
    tmp_path: Path,
) -> None:
    """Un inventaire d'empreinte conforme ne dispense pas de relire les octets."""
    release = _release_module()
    producer = _producer()
    snapshot = tmp_path / "e5"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "canonical_dim": 1024,
                "model_id": release.EMBEDDING_MODEL,
                "upstream_revision": release.EMBEDDING_MODEL_REVISION,
            }
        ),
        encoding="utf-8",
    )
    inventaire = "".join(
        f"{hashlib.sha256((snapshot / name).read_bytes()).hexdigest()}  {name}\n"
        for name in sorted(("config.json", "manifest.json"))
    )
    (snapshot / "SHA256SUMS").write_text(inventaire, encoding="utf-8")
    (snapshot / "config.json").write_text('{"altere": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="embedding snapshot differs from its inventory"):
        producer.verify_embedding_snapshot(
            snapshot,
            expected_inventory_sha256=hashlib.sha256(
                (snapshot / "SHA256SUMS").read_bytes()
            ).hexdigest(),
        )
