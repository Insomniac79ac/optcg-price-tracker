"""Offline, deterministic tests for spike.find_embedded_json_blocks and
find_product_ld_node - object / array / @graph-wrapped JSON-LD shapes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spike import find_embedded_json_blocks, find_product_ld_node  # noqa: E402


def test_plain_object_json_ld():
    html = """
    <html><head>
    <script type="application/ld+json">{"@type": "Product", "name": "test", "image": "https://x/1.jpg"}</script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    assert [n.get("@type") for n in result["ld_json_nodes"]] == ["Product"]
    product = find_product_ld_node(result["ld_json_nodes"])
    assert product is not None
    assert product["name"] == "test"


def test_array_json_ld():
    html = """
    <html><head>
    <script type="application/ld+json">[{"@type": "Organization", "name": "SNKRDUNK"}, {"@type": "Product", "name": "card"}]</script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    types = [n.get("@type") for n in result["ld_json_nodes"]]
    assert types == ["Organization", "Product"]
    product = find_product_ld_node(result["ld_json_nodes"])
    assert product is not None
    assert product["name"] == "card"


def test_graph_wrapped_json_ld_no_product_node():
    # Real shape observed live on apparels/104428 (2026-08-09): @graph
    # wrapping Organization + WebSite only, no Product node on this page.
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"Organization","name":"SNKRDUNK"},
      {"@type":"WebSite","name":"SNKRDUNK"}
    ]}
    </script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    types = [n.get("@type") for n in result["ld_json_nodes"]]
    assert types == ["Organization", "WebSite"]
    assert find_product_ld_node(result["ld_json_nodes"]) is None


def test_graph_wrapped_json_ld_with_product_node():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@graph":[
      {"@type":"Organization","name":"SNKRDUNK"},
      {"@type":"Product","name":"ロロノア・ゾロ L-P","offers":{"price":"29000"}}
    ]}
    </script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    product = find_product_ld_node(result["ld_json_nodes"])
    assert product is not None
    assert product["offers"]["price"] == "29000"


def test_multi_type_product_node_is_found():
    html = """
    <html><head>
    <script type="application/ld+json">{"@type": ["Product", "Thing"], "name": "card"}</script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    product = find_product_ld_node(result["ld_json_nodes"])
    assert product is not None


def test_unparseable_json_ld_is_recorded_as_a_parse_error_not_a_crash():
    html = """
    <html><head>
    <script type="application/ld+json">{not valid json,,,}</script>
    </head></html>
    """
    result = find_embedded_json_blocks(html)
    assert result["ld_json_parse_errors"] == 1
    assert result["ld_json_nodes"] == []


def test_no_json_ld_present():
    html = "<html><head></head><body>no structured data</body></html>"
    result = find_embedded_json_blocks(html)
    assert result["ld_json_nodes"] == []
    assert result["ld_json_parse_errors"] == 0
    assert find_product_ld_node(result["ld_json_nodes"]) is None
