import io
import json

from PIL import Image

from scripts.recover_official_logos import AssetParser, is_public_destination, structured_logo_candidates, validate_image


def _png(size=(32, 24)) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", size, (20, 40, 60, 255)).save(output, format="PNG")
    return output.getvalue()


def test_extracts_only_declared_page_assets_and_structured_logo():
    parser = AssetParser("https://company.example/about")
    parser.feed("""
      <link rel="icon" href="/favicon.png">
      <link rel="stylesheet" href="/brand.css">
      <meta property="og:logo" content="https://cdn.company.example/logo.png">
      <script type="application/ld+json">{"@type":"Organization","logo":{"url":"/official.svg"}}</script>
    """)
    candidates = structured_logo_candidates(parser)
    assert candidates[0] == ("jsonld_logo", "https://company.example/official.svg")
    assert ("declared_icon", "https://company.example/favicon.png") in candidates
    assert ("og:logo", "https://cdn.company.example/logo.png") in candidates
    assert all("brand.css" not in url for _, url in candidates)


def test_image_validation_uses_decoded_content_not_headers_or_suffixes():
    assert validate_image(_png()) == (".png", 32, 24)
    assert validate_image(b"<html>not an image</html>") is None
    assert validate_image(_png((8, 8))) is None


def test_public_destination_rejects_private_or_failed_dns():
    private = lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))]
    public = lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))]
    assert not is_public_destination("https://example.com/logo.png", resolver=private)
    assert is_public_destination("https://example.com/logo.png", resolver=public)
    assert not is_public_destination("http://example.com/logo.png", resolver=public)
    assert not is_public_destination("https://user:pass@example.com/logo.png", resolver=public)


def test_json_ld_graph_logo_is_discovered():
    parser = AssetParser("https://example.com/")
    parser.feed('<script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "Organization", "logo": "/logo.webp"}]}) + "</script>")
    assert structured_logo_candidates(parser) == [("jsonld_logo", "https://example.com/logo.webp")]
