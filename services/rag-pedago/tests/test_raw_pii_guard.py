"""Garde « aucune matière brute dans un artefact de gouvernance » (ADR-0047).

**Le piège que ce module doit éviter.** Un artefact de gouvernance est fait
d'empreintes : SHA-256 de contenu, de politique, de scanner, de paquet de
revue, SHA-1 de blob Git. Un digest hexadécimal contient, statistiquement,
des suites de chiffres — et une suite de dix chiffres se lit comme un numéro
de téléphone français. Scanner un tel artefact sans précaution produit des
faux positifs qui font croire à une fuite.

**Mais neutraliser trop est pire que ne pas neutraliser.** Si l'on efface
« tout ce qui ressemble à de l'hexadécimal », alors `0612345678` — dix
chiffres, donc dix caractères de l'alphabet hexadécimal — disparaît aussi, et
la garde devient un angle mort qui certifie l'absence de ce qu'elle a
elle-même effacé.

La règle tenue ici est donc étroite : on ne neutralise qu'un **token de digest
complet et bien délimité** (64 hex, ou 40 hex pour un blob Git), éventuellement
préfixé `sha256:`. Ni 63, ni 65, ni une courte chaîne hexadécimale.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from rag_pedago.imports.pii_scanner import PIIPattern
from rag_pedago.imports.raw_pii_guard import (
    RawPiiLeakError,
    _scan_units,
    _string_values,
    find_raw_pii,
    neutralise_digest_tokens,
    require_no_raw_pii,
)

SHA_WITH_DIGEST_RUN = "b418fc211fa20174e72117826550375b0387715203d38cd8f99588ee8e10dc42"
SHA_WITH_DIGEST_RUN_2 = "c21dd6166d8fe164ed0622989644b38851809b23e9a0176f4c7d8e2b1a3f5069"
BLOB_SHA1 = "684e09d015ff7c53e1ee315977ffe0cb476bda37"


class TestNeutralisationIsNarrow:
    """Ce qui est neutralisé, et surtout ce qui ne l'est pas."""

    def test_full_sha256_token_is_neutralised(self) -> None:
        assert SHA_WITH_DIGEST_RUN not in neutralise_digest_tokens(SHA_WITH_DIGEST_RUN)

    def test_neutralisation_preserves_length(self) -> None:
        """Les offsets restent lisibles : un masque de même longueur."""
        text = f'"sha": "{SHA_WITH_DIGEST_RUN}",'
        assert len(neutralise_digest_tokens(text)) == len(text)

    def test_prefixed_sha256_token_is_neutralised(self) -> None:
        masked = neutralise_digest_tokens(f"sha256:{SHA_WITH_DIGEST_RUN}")
        assert SHA_WITH_DIGEST_RUN not in masked

    def test_git_blob_sha1_token_is_neutralised(self) -> None:
        assert BLOB_SHA1 not in neutralise_digest_tokens(BLOB_SHA1)

    @pytest.mark.parametrize("length", [39, 41, 63, 65])
    def test_near_miss_hex_runs_are_never_neutralised(self, length: int) -> None:
        """39, 41, 63, 65 : ce ne sont pas des digests, on n'y touche pas.

        Un masquage « à peu près » laisserait passer une matière brute
        adjacente à un digest tronqué."""
        run = "a1b2c3d4e5" * 10
        run = run[:length]
        assert neutralise_digest_tokens(run) == run

    @pytest.mark.parametrize("token", ["1234567890", "abcdef1234", "0612345678", "deadbeef"])
    def test_short_hex_alphabet_strings_are_never_neutralised(self, token: str) -> None:
        """Appartenir à l'alphabet hexadécimal n'est pas être un digest."""
        assert neutralise_digest_tokens(token) == token

    def test_a_digest_does_not_swallow_its_neighbours(self) -> None:
        text = f"contact: 0612345678 sha={SHA_WITH_DIGEST_RUN} fin"
        masked = neutralise_digest_tokens(text)
        assert "0612345678" in masked
        assert SHA_WITH_DIGEST_RUN not in masked


class TestFindRawPii:
    """Le verdict, sur du texte plutôt que sur des empreintes."""

    def test_digest_with_internal_digit_run_yields_no_finding(self) -> None:
        assert find_raw_pii(SHA_WITH_DIGEST_RUN) == []
        assert find_raw_pii(SHA_WITH_DIGEST_RUN_2) == []

    def test_isolated_phone_number_yields_a_finding(self) -> None:
        findings = find_raw_pii("0612345678")
        assert [f.pattern_id for f in findings] == ["phone_french"]

    def test_phone_number_in_a_sentence_yields_a_finding(self) -> None:
        findings = find_raw_pii("contact: 0612345678")
        assert any(f.pattern_id == "phone_french" for f in findings)

    def test_phone_number_next_to_a_digest_still_yields_a_finding(self) -> None:
        """Le cas qui aurait rendu la garde aveugle."""
        text = f'{{"sha": "{SHA_WITH_DIGEST_RUN}", "note": "appeler le 0612345678"}}'
        findings = find_raw_pii(text)
        assert [f.pattern_id for f in findings] == ["phone_french"]

    def test_email_address_yields_a_finding(self) -> None:
        findings = find_raw_pii("ecrire a jean.dupont@example.org")
        assert any(f.pattern_id == "email_address" for f in findings)

    def test_findings_never_carry_the_matched_material(self) -> None:
        """La garde ne recopie pas ce qu'elle dénonce : elle en rend
        l'empreinte, la classe et la position. Sinon son propre rapport
        deviendrait la fuite qu'elle cherchait."""
        findings = find_raw_pii("contact: 0612345678")
        assert findings
        for finding in findings:
            assert "0612345678" not in repr(finding)
            assert len(finding.match_sha256) == 64


class TestGovernanceArtifactsAreClean:
    """La mesure réelle, sur les artefacts scellés du candidat."""

    ROOT = Path(__file__).resolve().parents[3]

    @pytest.mark.parametrize(
        "relative",
        [
            "governance/pii-review-decisions/pii-review-2026-09-03-final.json",
            "governance/pii-review-bindings/pii-review-2026-09-03-final.json",
            "docs/reports/evidence-index/pii_review_index_20260903.json",
        ],
    )
    def test_sealed_artifact_carries_no_raw_pii(self, relative: str) -> None:
        findings = find_raw_pii((self.ROOT / relative).read_text(encoding="utf-8"))
        assert findings == [], f"{relative}: {[f.pattern_id for f in findings]}"


class TestADigestNeverDestroysSurroundingPiiSyntax:
    """P1 — masquer d'abord, chercher ensuite, détruisait des adresses.

    Le garde remplaçait les digests par un masque PUIS cherchait la PII dans
    le texte amputé. Une adresse dont le domaine ou la partie locale contient
    un composant hexadécimal de 40 caractères perdait alors sa syntaxe, et
    n'était plus détectée : la garde certifiait l'absence de ce qu'elle venait
    d'effacer.

    Le principe est inversé : on cherche dans le texte D'ORIGINE, et l'on
    n'écarte une correspondance que si elle est ENTIÈREMENT contenue dans un
    token de digest. Un digest ne peut plus absorber ce qui le déborde."""

    HEX40 = "a1b2c3d4e5" * 4
    HEX64 = "a1b2c3d4e5" * 6 + "f1b2"

    def test_email_whose_domain_holds_a_40_hex_component_is_detected(self) -> None:
        findings = find_raw_pii(f"ecrire a jean@{self.HEX40}.example")
        assert any(f.pattern_id == "email_address" for f in findings)

    def test_email_whose_local_part_is_a_40_hex_token_is_detected(self) -> None:
        findings = find_raw_pii(f"{self.HEX40}@example.com")
        assert any(f.pattern_id == "email_address" for f in findings)

    def test_email_whose_domain_holds_a_64_hex_component_is_detected(self) -> None:
        findings = find_raw_pii(f"jean@{self.HEX64}.example")
        assert any(f.pattern_id == "email_address" for f in findings)

    def test_a_digit_run_strictly_inside_a_digest_is_still_ignored(self) -> None:
        """La propriété d'origine ne doit pas être perdue au passage."""
        assert find_raw_pii(SHA_WITH_DIGEST_RUN) == []

    def test_a_phone_adjacent_to_a_digest_is_still_detected(self) -> None:
        assert any(
            f.pattern_id == "phone_french"
            for f in find_raw_pii(f'{{"sha": "{SHA_WITH_DIGEST_RUN}", "tel": "0612345678"}}')
        )


class TestValuesAreScannedBeforeSerialisation:
    """P1 — `json.dumps` échappait le séparateur avant le scan.

    `require_no_raw_pii` sérialisait le document puis cherchait la PII dans le
    JSON. Une valeur dont le motif est séparé par un saut de ligne ou une
    tabulation voyait ce séparateur transformé en `\\n` / `\\t` littéraux :
    le motif ne correspondait plus, et la garde attestait une sortie propre.

    C'est le MÊME défaut que celui corrigé sur les digests — transformer le
    texte avant d'y chercher — réintroduit par la sérialisation. Les valeurs
    sont donc parcourues et scannées telles qu'elles sont, avant tout encodage.
    """

    def test_a_plain_phone_value_is_refused(self) -> None:
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"note": "0612345678"}, label="t")

    def test_a_spaced_phone_value_is_refused(self) -> None:
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"note": "06 12 34 56 78"}, label="t")

    def test_a_phone_split_by_a_newline_is_refused(self) -> None:
        """Le cas exact que l'échappement JSON faisait disparaître.

        Le séparateur est DANS le numéro : le motif l'accepte comme espace en
        texte brut, mais `json.dumps` le transforme en deux caractères
        littéraux `\\` et `n`, et la correspondance est perdue. Mesuré :
        1 finding sur le texte brut, 0 après sérialisation."""
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"note": "06\n12 34 56 78"}, label="t")

    def test_a_phone_split_by_a_tab_is_refused(self) -> None:
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"note": "06\t12 34 56 78"}, label="t")

    def test_a_phone_split_by_a_carriage_return_is_refused(self) -> None:
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"note": "06\r12 34 56 78"}, label="t")

    def test_a_phone_in_a_nested_value_split_by_a_newline_is_refused(self) -> None:
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii({"a": [{"b": "06\n12 34 56 78"}]}, label="t")

    def test_nested_structures_are_traversed(self) -> None:
        document = {"a": [{"b": ("x", {"c": "ecrire a jean@example.org"})}]}
        with pytest.raises(RawPiiLeakError):
            require_no_raw_pii(document, label="t")

    def test_clean_nested_structures_pass(self) -> None:
        require_no_raw_pii(
            {"results": [{"sha": SHA_WITH_DIGEST_RUN, "status": "CLEARED"}]}, label="t"
        )

    def test_non_string_scalars_do_not_break_the_walk(self) -> None:
        require_no_raw_pii({"n": 3, "b": True, "z": None, "f": 1.5}, label="t")


class TestTheTraversalLosesNothingTheSerialisationWouldHaveCaught:
    """Ne pas sérialiser ne doit pas COÛTER de la détection (re-review #144).

    Scanner les valeurs d'origine plutôt que le JSON a corrigé un vrai défaut :
    un séparateur situé DANS un motif y était échappé et la correspondance
    perdue. Mais le parcours écrit alors a introduit deux pertes en sens
    inverse, que `json.dumps` ne faisait pas :

    1. il rendait la clé et la valeur SÉPARÉMENT, si bien qu'un motif dont le
       contexte est porté par la clé ne pouvait plus se former ;
    2. il ignorait tout ce qui n'est pas une chaîne, alors qu'un identifiant
       PII sérialisé en nombre était auparavant rendu tel quel.

    La bonne mesure est l'union : tout ce que la sérialisation attrapait, plus
    ce qu'elle perdait — jamais l'un au prix de l'autre.
    """

    def test_a_numeric_scalar_carrying_an_identifier_is_seen(self) -> None:
        """Un NIR sérialisé en entier reste un NIR."""
        document = {"identifier": 199012345678901}
        findings = [
            finding
            for value in _string_values(document)
            for finding in find_raw_pii(value)
        ]
        # Asserter « au moins un finding » laissait passer une régression de
        # `french_ssn` dès qu'un AUTRE motif se déclenchait : le test serait
        # resté vert en cessant de prouver ce que sa docstring annonce.
        assert "french_ssn" in {finding.pattern_id for finding in findings}, (
            "un identifiant numérique n'est plus reconnu comme NIR : "
            f"{sorted({f.pattern_id for f in findings})}"
        )

    def test_the_key_still_lends_its_context_to_the_value(self) -> None:
        """Le contexte porté par la clé ne doit pas être perdu par le parcours."""
        rendered = list(_string_values({"adresse": "75001 paris"}))
        assert any(
            "adresse" in text and "75001 paris" in text for text in rendered
        ), "la clé et la valeur ne sont jamais rendues ensemble"

    def test_the_separator_inside_a_pattern_is_still_preserved(self) -> None:
        """La correction ne doit pas réintroduire l'échappement JSON."""
        document = {"tel": "06\n12 34 56 78"}
        rendered = list(_string_values(document))
        assert any("06\n12 34 56 78" in text for text in rendered)
        assert not any("06\\n12" in text for text in rendered)

    def test_booleans_and_none_do_not_manufacture_findings(self) -> None:
        rendered = list(_string_values({"a": True, "b": None, "c": 3}))
        assert not any(find_raw_pii(text) for text in rendered)


class TestTheReportedCountIsNotInflatedByTheKeyContext:
    """Un rapport de preuve qui double ses chiffres est faux (re-review #144).

    Le parcours rend chaque valeur deux fois — seule, puis précédée de sa clé —
    pour qu'un motif dont le contexte est porté par la clé puisse se former.
    Compter les deux faisait dire au refus qu'il y a deux fuites là où il y en
    a une. Le refus restait juste ; sa MESURE ne l'était pas.
    """

    def test_one_leak_under_a_key_is_reported_once(self) -> None:
        with pytest.raises(RawPiiLeakError, match=r"\b1 finding\(s\)"):
            require_no_raw_pii({"tel": "0612345678"}, label="t")

    def test_nesting_does_not_multiply_the_count_either(self) -> None:
        with pytest.raises(RawPiiLeakError, match=r"\b1 finding\(s\)"):
            require_no_raw_pii({"a": {"b": {"tel": "0612345678"}}}, label="t")

    def test_two_distinct_leaks_are_still_two(self) -> None:
        """La déduplication ne doit pas EFFACER une seconde fuite réelle."""
        with pytest.raises(RawPiiLeakError, match=r"\b2 finding\(s\)"):
            require_no_raw_pii(
                {"tel": "0612345678", "autre": "0698765432"}, label="t"
            )

    def test_distinct_pattern_classes_are_not_collapsed(self) -> None:
        """Deux CLASSES sur la même matière restent deux constats.

        N'asserter que `french_ssn` laissait le test vert si un refactor
        fusionnait les classes, pourvu que celle-là survive — il cessait alors
        de prouver ce que son nom annonce."""
        with pytest.raises(RawPiiLeakError) as leak:
            require_no_raw_pii({"identifier": 199012345678901}, label="t")
        message = str(leak.value)
        assert "french_ssn" in message
        assert "phone_french" in message, (
            f"la seconde classe a disparu du rapport : {message}"
        )
        assert "2 finding(s)" in message


class TestTheAncestorKeysLendTheirContext:
    """Le contexte utile peut être porté par une clé ÉLOIGNÉE (re-review #144).

    Une première version du parcours ne transmettait que la clé immédiate :
    dans `{"date_of_birth": {"value": "01/01/2000"}}`, le contexte utile était
    perdu et seul `value` subsistait. La garde pouvait alors attester une
    sortie propre sur une fuite que la sérialisation, elle, aurait exposée.
    """

    def test_an_outer_key_still_reaches_the_nested_value(self) -> None:
        rendered = [text for unit in _scan_units({"a": {"b": "x"}}) for text in unit]
        assert "a: x" in rendered, (
            f"la clé ancêtre ne prête plus son contexte : {rendered}"
        )
        assert "b: x" in rendered

    def test_every_key_of_the_path_gets_its_chance(self) -> None:
        rendered = [
            text for unit in _scan_units({"k1": {"k2": {"k3": "v"}}}) for text in unit
        ]
        assert {"v", "k1: v", "k2: v", "k3: v"} <= set(rendered)

    def test_a_key_carrying_pii_is_counted_once_not_once_per_descendant(self) -> None:
        """La clé est déjà scannée SEULE : la recompter dans chaque miroir la
        faisait apparaître autant de fois qu'elle a de feuilles.

        Mesuré avant correction : `{"0612345678": {"a":1,"b":2,"c":3}}`
        rapportait QUATRE fuites pour une seule."""
        with pytest.raises(RawPiiLeakError, match=r"\b1 finding\(s\)"):
            require_no_raw_pii({"0612345678": {"a": 1, "b": 2, "c": 3}}, label="t")

    def test_the_count_does_not_grow_with_the_number_of_descendants(self) -> None:
        """La propriété qui compte : le chiffre ne dépend pas de la forme."""
        import re as _re

        counts = set()
        for width in (1, 2, 5):
            payload = {"0612345678": {f"k{i}": i for i in range(width)}}
            with pytest.raises(RawPiiLeakError) as leak:
                require_no_raw_pii(payload, label="t")
            found = _re.search(r"(\d+) finding\(s\)", str(leak.value))
            assert found is not None
            counts.add(found.group(1))
        assert counts == {"1"}, f"le compte varie avec le nombre de feuilles : {counts}"

    def test_a_repeated_occurrence_is_still_counted_twice(self) -> None:
        """La déduplication des miroirs ne doit pas effacer une répétition."""
        with pytest.raises(RawPiiLeakError, match=r"\b2 finding\(s\)"):
            require_no_raw_pii({"tel": "0612345678 puis 0612345678"}, label="t")


class TestThePrefixFilterNeverHidesADetection:
    """Écarter une correspondance de préfixe exige une PREUVE (re-review #144).

    Le filtre était inconditionnel : toute correspondance confinée au préfixe
    `clé: ` du rendu miroir était écartée, au motif que la clé est déjà scannée
    seule. Vrai pour un motif que la clé seule produit — faux pour un motif qui
    ne se forme QUE dans le miroir, par exemple parce qu'il exige le
    séparateur. Un tel motif n'est comptabilisé nulle part ailleurs : le garde
    aurait attesté une sortie propre sur une détection que la politique
    demandait.

    L'écart n'a lieu, désormais, que si la clé SEULE produit la même
    correspondance — même classe, même longueur, même empreinte.
    """

    def test_a_pattern_that_needs_the_separator_is_not_dropped(self) -> None:
        """Motif qui ne se forme que dans le rendu miroir."""
        separator_pattern = [
            PIIPattern(
                pattern_id="cle_avec_separateur",
                description="motif exigeant le séparateur synthétique",
                regex=re.compile(r"secret: "),
            )
        ]
        findings = [
            finding
            for unit in _scan_units({"secret": "x"})
            for text in unit
            for finding in find_raw_pii(text, patterns=separator_pattern)
        ]
        assert findings, "le motif ne se forme dans aucun rendu — banc invalide"

        with pytest.raises(RawPiiLeakError, match="cle_avec_separateur"):
            require_no_raw_pii({"secret": "x"}, label="t", patterns=separator_pattern)

    def test_a_pattern_the_key_alone_produces_is_still_dropped(self) -> None:
        """Contrôle inverse : ce que la clé seule produit reste écarté du miroir."""
        with pytest.raises(RawPiiLeakError, match=r"\b1 finding\(s\)"):
            require_no_raw_pii({"0612345678": {"a": 1, "b": 2}}, label="t")
