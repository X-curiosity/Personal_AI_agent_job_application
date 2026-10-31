from pathlib import Path

from tau_job_application.job_sources import fetch_feed_openings, _parse_feed
from tau_job_application.job_submissions import add_submission, load_submissions, validate_submission


RSS = """<?xml version="1.0"?>
<rss><channel><item>
  <title>Backend Engineer</title><link>https://jobs.example.com/1</link>
  <description>Build the core API.</description><pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
</item><item>
  <title>Frontend Engineer</title><link>https://jobs.example.com/2</link>
  <description>Ship the web app.</description>
</item></channel></rss>"""


ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
  <title>Data Scientist</title><link href="https://jobs.example.com/3"/>
  <summary>Analyze data.</summary><published>2026-01-01T00:00:00Z</published>
</entry></feed>"""


JSON_FEED = '{"items":[{"title":"Designer","url":"https://jobs.example.com/4","content_text":"Design systems","location":"Lagos, Nigeria"}]}'


def test_parse_feed_rss_atom_json():
    assert _parse_feed(RSS, "Kenya")[0]["title"] == "Backend Engineer"
    assert _parse_feed(RSS, "Kenya")[1]["location"] == "Kenya"  # fallback country
    assert _parse_feed(ATOM, "")[0]["url"] == "https://jobs.example.com/3"
    assert _parse_feed(JSON_FEED, "")[0]["location"] == "Lagos, Nigeria"


def test_validate_submission_requires_fields():
    assert validate_submission({"title": "T", "company": "C", "url": "https://x.com/1", "location": "Paris, France"})["company"] == "C"
    for missing in ({"company": "C", "url": "https://x.com/1", "location": "Paris, France"},
                    {"title": "T", "url": "https://x.com/1", "location": "Paris, France"},
                    {"title": "T", "company": "C", "location": "Paris, France"},
                    {"title": "T", "company": "C", "url": "http://x.com/1", "location": "Paris, France"}):
        try:
            validate_submission(missing)
            raise AssertionError("expected rejection")
        except ValueError:
            pass


def test_submission_roundtrip_and_dedupe(tmp_path):
    path = tmp_path / "submitted_jobs.json"
    add_submission(path, {"title": "Eng", "company": "Acme", "url": "https://acme.example/1", "location": "Berlin, Germany"})
    assert len(load_submissions(path)) == 1
    try:
        add_submission(path, {"title": "Eng2", "company": "Acme", "url": "https://acme.example/1", "location": "Berlin, Germany"})
        raise AssertionError("expected duplicate rejection")
    except ValueError:
        pass
    assert len(load_submissions(path)) == 1
