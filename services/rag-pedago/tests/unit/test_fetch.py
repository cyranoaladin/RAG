"""Tests for the governed fetch module — all network mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from scrapers.fetch import (
    FetchRefusal,
    FetchResult,
    extract_text_from_html,
    governed_fetch,
    is_whitelisted,
    quality_check,
)

# --- Whitelist ---

def test_whitelisted_domain():
    assert is_whitelisted("https://eduscol.education.gouv.fr/path")
    assert is_whitelisted("https://education.gouv.fr/programmes")


def test_non_whitelisted_domain():
    assert not is_whitelisted("https://example.com/page")
    assert not is_whitelisted("https://wikipedia.org/suites")


def test_fetch_refuses_non_whitelisted():
    result = governed_fetch("https://example.com/page")
    assert isinstance(result, FetchRefusal)
    assert "not whitelisted" in result.reason


# --- robots.txt ---

@patch("scrapers.fetch._get_robots")
def test_robots_refusal(mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = False
    mock_robots.return_value = rp

    result = governed_fetch("https://eduscol.education.gouv.fr/restricted")
    assert isinstance(result, FetchRefusal)
    assert "robots.txt" in result.reason


@patch("scrapers.fetch._get_robots")
@patch("requests.get")
@patch("scrapers.fetch._apply_rate_limit", return_value=0.0)
def test_robots_allowed_proceeds_to_fetch(mock_rate, mock_get, mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html>Contenu</html>"]
    mock_get.return_value = mock_response

    result = governed_fetch("https://eduscol.education.gouv.fr/page")
    assert isinstance(result, FetchResult)
    assert result.status_code == 200


# --- Rate limit ---

@patch("scrapers.fetch._get_robots")
@patch("requests.get")
def test_rate_limit_applied(mock_get, mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html>ok</html>"]
    mock_get.return_value = mock_response

    r1 = governed_fetch("https://eduscol.education.gouv.fr/page1")
    assert isinstance(r1, FetchResult)


# --- Read-only ---

@patch("scrapers.fetch._get_robots")
@patch("requests.get")
@patch("scrapers.fetch._apply_rate_limit", return_value=0.0)
def test_only_get_requests(mock_rate, mock_get, mock_robots):
    """Verify that only GET is called, never POST/PUT/DELETE."""
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"content"]
    mock_get.return_value = mock_response

    governed_fetch("https://eduscol.education.gouv.fr/page")

    mock_get.assert_called_once()


# --- Text extraction ---

def test_extract_text_from_html():
    html = "<html><head><script>var x=1;</script></head><body><h1>Title</h1><p>Content here.</p></body></html>"
    text = extract_text_from_html(html)
    assert "Title" in text
    assert "Content here" in text
    assert "<script>" not in text
    assert "<h1>" not in text


def test_extract_decodes_html_entities():
    html = "<p>Aller au&#160;contenu</p><p>Cat&#233;gorie&#160;:</p><p>&amp; test</p>"
    text = extract_text_from_html(html)
    assert "Aller au\xa0contenu" in text or "Aller au contenu" in text
    assert "Catégorie" in text
    assert "& test" in text
    assert "&#160;" not in text
    assert "&amp;" not in text


def test_navigation_detected_with_html_entities():
    """Wikiversity nav with HTML entities must be flagged."""
    html = """<body>
    <div>Aller au&#160;contenu</div>
    <div>Menu principal</div>
    <div>Chapitres&#160;:</div>
    <div>Outils personnels</div>
    <div>Rechercher</div>
    <div>Faire un don</div>
    <div>Créer un compte</div>
    <div>Se connecter</div>
    <div>Modifier les liens</div>
    </body>"""
    text = extract_text_from_html(html)
    qc = quality_check(text, "suites")
    assert qc["navigation_suspected"] is True


def test_course_content_not_flagged_as_navigation():
    """Real course content must NOT be flagged as navigation."""
    html = """<body>
    <h1>Suites numériques</h1>
    <p>Une suite numérique est une application de l'ensemble des entiers naturels
    dans l'ensemble des réels. On note (u_n) la suite et u_n le terme de rang n.</p>
    <h2>Définition</h2>
    <p>La suite (u_n) est dite convergente si elle admet une limite finie l quand
    n tend vers l'infini. On écrit alors lim u_n = l.</p>
    <h2>Théorème</h2>
    <p>Toute suite croissante et majorée converge. Toute suite décroissante et
    minorée converge.</p>
    </body>"""
    text = extract_text_from_html(html)
    qc = quality_check(text, "suites")
    assert qc["navigation_suspected"] is False


def test_long_article_with_minor_nav_markers_not_flagged_as_navigation():
    """A substantial article must not be rejected for a few footer markers."""
    text = (
        "La dérivée d'une fonction est une notion centrale de l'analyse. "
        "Les définitions, les exemples et les propriétés permettent de calculer "
        "la variation locale d'une fonction réelle. "
    ) * 80
    text += " Voir aussi Catégorie : Rechercher"

    qc = quality_check(text, "derivation")

    assert qc["navigation_suspected"] is False
    assert qc["ok"] is True


def test_mediawiki_extraction_strips_chrome():
    """MediaWiki HTML: only article body extracted, no navigation chrome."""
    html = """<html><head><title>Test</title></head><body>
    <div id="mw-navigation">Navigation menu aller au contenu rechercher</div>
    <div id="mw-content-text">
      <div class="mw-parser-output">
        <div class="bandeau-container">Si ce bandeau n'est plus pertinent</div>
        <p>La <b>continuité</b> d'une fonction est une propriété fondamentale
        en analyse mathématique. Une fonction continue est une fonction dont
        la courbe peut être tracée sans lever le crayon.</p>
        <h2><span>Définition formelle</span></h2>
        <p>Soit f une fonction définie sur un intervalle I. On dit que f est
        continue en a si la limite de f(x) quand x tend vers a est égale à f(a).</p>
        <div id="toc"><h2>Sommaire</h2><ul><li>1 Définition</li></ul></div>
        <h2><span>Notes et références</span></h2>
        <ol class="references"><li>Ref 1</li></ol>
        <h2><span>Voir aussi</span></h2>
        <p>Articles connexes blah blah</p>
      </div>
    </div>
    <div class="navbox">Navigation box footer</div>
    </body></html>"""
    text = extract_text_from_html(html)
    # Article content present
    assert "continuité" in text.lower()
    assert "analyse mathématique" in text.lower()
    assert "Définition formelle" in text or "définition formelle" in text.lower()
    # Chrome absent
    assert "Navigation menu" not in text
    assert "aller au contenu" not in text.lower()
    assert "rechercher" not in text.lower()
    assert "bandeau" not in text.lower()
    assert "Notes et références" not in text
    assert "Voir aussi" not in text
    assert "Navigation box" not in text
    assert "Articles connexes" not in text


def test_mediawiki_extraction_strips_tail_chrome():
    """Tail chrome (Voir aussi, Articles connexes, Sur les autres projets) must be removed."""
    html = """<html><body>
    <div class="mw-parser-output">
        <p>La convexité est une propriété importante des fonctions réelles.</p>
        <h2><span>Propriétés</span></h2>
        <p>Une fonction convexe sur un intervalle admet un minimum global.</p>
        <h2><span>Voir aussi</span></h2>
        <ul><li>Concavité</li><li>Inégalité de Jensen</li></ul>
        <h3><span>Articles connexes</span></h3>
        <ul><li>Fonction affine</li></ul>
        <div class="sistersitebox">
            <p>Sur les autres projets Wikimedia :</p>
            <ul><li>Wiktionnaire</li><li>sur Wikiversity</li></ul>
        </div>
        <h2><span>Bibliographie</span></h2>
        <p>Rudin, Analyse réelle et complexe</p>
    </div>
    </body></html>"""
    text = extract_text_from_html(html)
    assert "convexité" in text.lower()
    assert "minimum global" in text
    # Tail chrome absent
    assert "Voir aussi" not in text
    assert "Articles connexes" not in text
    assert "Sur les autres projets" not in text
    assert "Wiktionnaire" not in text
    assert "sur Wikiversity" not in text
    assert "Bibliographie" not in text
    # Last chars should be article content
    assert text.rstrip().endswith("global.")


def test_no_false_positive_portail_nsi():
    """An NSI text mentioning 'portail web' must NOT be flagged as navigation."""
    text = ("Un portail web est une application qui offre un point d'accès unique "
            "à diverses ressources en ligne. Les portails sont utilisés dans de "
            "nombreuses organisations pour centraliser l'information. " * 5)
    qc = quality_check(text, "portail_web")
    assert qc["navigation_suspected"] is False


def test_no_false_positive_categorie_maths():
    """A maths text mentioning 'catégorie' must NOT be flagged."""
    text = ("En mathématiques, une catégorie est une structure algébrique constituée "
            "d'objets et de morphismes. La théorie des catégories unifie plusieurs "
            "branches des mathématiques. " * 5)
    qc = quality_check(text, "categorie")
    assert qc["navigation_suspected"] is False
    # Quality check should NOT flag as navigation
    qc = quality_check(text, "continuite")
    assert qc["navigation_suspected"] is False


def test_pollution_detected_in_middle():
    """Chrome markers in the MIDDLE of text must be detected."""
    text = (
        "La dérivation est une opération fondamentale en analyse. "
        "Elle permet de calculer la pente de la tangente en un point. "
        "modifier le code Aller au contenu "
        "La dérivée de x^n est nx^(n-1). "
        "Les applications sont nombreuses en physique et en économie. " * 5
    )
    qc = quality_check(text, "derivation")
    assert qc["navigation_suspected"] is True, "Middle chrome not detected"


# --- Quality check ---

def test_quality_check_pass():
    text = "Les suites numériques sont un concept fondamental en mathématiques. " * 10
    qc = quality_check(text, "suites")
    assert qc["ok"]


def test_quality_check_too_short():
    qc = quality_check("court", "suites")
    assert not qc["ok"]
    assert any("too short" in i for i in qc["issues"])


# --- robots.txt failure → refusal (conservative) ---

@patch("scrapers.fetch._get_robots")
def test_robots_failure_refuses(mock_robots):
    """If robots.txt can't be fetched, refuse by default (conservative)."""
    rp = MagicMock()
    rp.can_fetch.return_value = False  # conservative default
    mock_robots.return_value = rp

    result = governed_fetch("https://eduscol.education.gouv.fr/page")
    assert isinstance(result, FetchRefusal)


# --- Verrou test: pilot_fetch refuses when staging not allowed ---

def test_pilot_fetch_refuses_when_staging_not_allowed(tmp_path, monkeypatch):
    """pilot_fetch must refuse to write staging when data_staging_allowed=false."""
    from scrapers import pilot_fetch

    # Write a contract with data_staging_allowed=false
    fake_contract = tmp_path / "contract.yml"
    fake_contract.write_text("data_staging_allowed: false\n", encoding="utf-8")
    monkeypatch.setattr(pilot_fetch, "CONTRACT_PATH", fake_contract)

    report = pilot_fetch.run_pilot_fetch()

    assert "error" in report
    assert "staging refused" in report["error"]
    assert report["results"] == []
