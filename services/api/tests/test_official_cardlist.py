"""Coverage for the official JP Card List reader (app.services.official_cardlist).

Hermetic: every test parses markup written here, shaped like the pages the
catalogue actually serves (verified against the live OP-01 series page and the
OP01-001 freewords result on 2026-08-22). Nothing in this module reaches the
network or a database.
"""

from app.services.official_cardlist import (
    SOURCE_CATALOGUE,
    card_list_url,
    parse_card_list,
    product_code_from_display_name,
)

# The page's real shape, trimmed to two cards. Note the void <img> and <br>
# tags written without a closing slash - the depth tracking has to survive
# them, and got this wrong first time round.
PAGE = """
<html><body>
<select id="series">
  <option value="">Select</option>
  <option value="550101">&#12502;&#12540;&#12473;&#12479;&#12540;&#12497;&#12483;&#12463; ROMANCE DAWN&#12304;OP-01&#12305;</option>
  <option value="569901">&#36913;&#20124;&#12472;&#12515;&#12531;&#12503;&#24540;&#21215;</option>
</select>

<dl class="modalCol" id="OP01-001">
  <dt>
    <div class="infoCol"><span>OP01-001</span> | <span>L</span> | <span>LEADER</span></div>
    <div class="cardName">Roronoa Zoro</div>
  </dt>
  <dd>
    <div class="frontCol">
      <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/OP01-001.png?260821" alt="x">
    </div>
    <div class="backCol">
      <div class="cost"><h3>Life</h3>5</div>
      <div class="getInfo"><h3>&#20837;&#25163;&#24773;&#22577;</h3>ROMANCE DAWN&#12304;OP-01&#12305;</div>
    </div>
  </dd>
</dl>

<a class="modalOpen" data-src="#OP01-001_p2"><img class="lazy" data-src="../images/cardlist/card/OP01-001_p2.png?260821"></a>

<dl class="modalCol" id="OP01-001_p2">
  <dt>
    <div class="infoCol"><span>OP01-001</span> | <span>L</span> | <span>LEADER</span></div>
    <div class="cardName">Roronoa Zoro</div>
  </dt>
  <dd>
    <div class="frontCol">
      <img class="lazy" src="/images/cardlist/dummy.gif" data-src="../images/cardlist/card/OP01-001_p2.png?260821">
    </div>
    <div class="backCol">
      <div class="getInfo"><h3>&#20837;&#25163;&#24773;&#22577;</h3>Premium Collection<br>Jump Campaign</div>
    </div>
  </dd>
</dl>
</body></html>
"""


def test_series_index_is_read_with_its_official_codes():
    page = parse_card_list(PAGE, "550101")
    assert page.source_catalogue == SOURCE_CATALOGUE
    codes = {s.series_id: s.official_code for s in page.series_index}
    assert codes == {"550101": "OP-01", "569901": None}
    assert page.series is not None
    assert page.series.display_name.endswith("【OP-01】")


def test_the_prompt_option_is_not_a_series():
    page = parse_card_list(PAGE, "550101")
    assert all(s.series_id.isdigit() for s in page.series_index)
    assert len(page.series_index) == 2


def test_every_entry_is_read_with_its_own_fields():
    page = parse_card_list(PAGE, "550101")
    assert [e.entry_id for e in page.entries] == ["OP01-001", "OP01-001_p2"]
    base = page.entries[0]
    assert base.card_code == "OP01-001"
    assert base.rarity == "L"
    assert base.category == "LEADER"
    assert base.card_name == "Roronoa Zoro"
    assert base.product_names == ("ROMANCE DAWN【OP-01】",)
    assert base.is_wellformed


def test_the_thumbnail_between_entries_is_not_read_as_an_entrys_artwork():
    """The <a class="modalOpen"> link carries the *next* artwork's address.

    Reading it would silently give every entry its sibling's asset, which is
    the exact mistake that makes two variants collapse into one identity.
    """
    page = parse_card_list(PAGE, "550101")
    assert page.entries[0].image_url.endswith("card/OP01-001.png?260821")
    assert page.entries[1].image_url.endswith("card/OP01-001_p2.png?260821")


def test_relative_asset_addresses_are_resolved_and_the_cache_buster_is_kept():
    page = parse_card_list(PAGE, "550101")
    url = page.entries[0].image_url
    assert url.startswith("https://www.onepiece-cardgame.com/images/cardlist/card/")
    # Bandai's ?260821 is evidence about the page, and discarding it here
    # would quietly alter what was read.
    assert url.endswith("?260821")


def test_an_entry_can_name_several_products():
    page = parse_card_list(PAGE, "550101")
    assert page.entries[1].product_names == ("Premium Collection", "Jump Campaign")


def test_entries_for_card_returns_every_official_artwork():
    page = parse_card_list(PAGE, "550101")
    assert len(page.entries_for_card("OP01-001")) == 2
    assert len(page.entries_for_card("op01-001")) == 2
    assert page.entries_for_card("OP01-999") == ()


def test_product_code_is_read_from_the_brackets_never_from_the_prose():
    assert product_code_from_display_name("ブースターパック ROMANCE DAWN【OP-01】") == "OP-01"
    # Composite codes are real (EN ships OP14-EB04) and must survive.
    assert product_code_from_display_name("Something【OP14-EB04】") == "OP14-EB04"
    # An uncoded product is normal data, and its prose is never a code.
    assert product_code_from_display_name("週刊少年ジャンプ応募者全員サービス") is None
    assert product_code_from_display_name("") is None
    assert product_code_from_display_name(None) is None


def test_card_list_url_is_the_canonical_series_address():
    assert card_list_url("550101") == "https://www.onepiece-cardgame.com/cardlist/?series=550101"


def test_a_malformed_entry_is_returned_rather_than_repaired():
    """An entry missing its code is reported as-is, for the caller to refuse."""
    broken = """
    <dl class="modalCol" id="">
      <dt><div class="infoCol"></div><div class="cardName"></div></dt>
      <dd><div class="frontCol"><img data-src="../images/cardlist/card/OP01-009.png"></div></dd>
    </dl>
    """
    page = parse_card_list(broken, "550101")
    assert len(page.entries) == 1
    assert page.entries[0].is_wellformed is False
    assert page.entries[0].card_code == ""
