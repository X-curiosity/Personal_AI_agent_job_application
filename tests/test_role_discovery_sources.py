import pytest

from tau_job_application import sources


def test_public_board_openings_keep_greenhouse_roles_without_inferable_skills(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_get_json(url: str) -> dict:
        requested_urls.append(url)
        return {
            "jobs": [
                {
                    "id": 42,
                    "title": "Tea Programme Steward",
                    "company_name": "Payload Company",
                    "location": {"name": "Zurich, Switzerland"},
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/42",
                    "content": "Coordinate &amp;lt;strong&amp;gt;tea&amp;lt;/strong&amp;gt; tastings &amp; seasonal menus.",
                    "updated_at": "2026-10-04T08:00:00Z",
                    "workplace_type": "On-site",
                }
            ]
        }

    monkeypatch.setattr(sources, "_get_json", fake_get_json)

    openings = sources.fetch_public_board_openings("Greenhouse", "tea-house", company="Tea House")

    assert requested_urls == ["https://boards-api.greenhouse.io/v1/boards/tea-house/jobs?content=true"]
    assert openings == [
        {
            "source": "Greenhouse",
            "source_id": "42",
            "board_identifier": "tea-house",
            "company": "Tea House",
            "title": "Tea Programme Steward",
            "location": "Zurich, Switzerland",
            "url": "https://boards.greenhouse.io/example/jobs/42",
            "description": "Coordinate  tea  tastings & seasonal menus.",
            "source_timestamp": "2026-10-04T08:00:00Z",
            "source_timestamp_kind": "updated",
            "workplace_type": "On-site",
            "employment_type": None,
        }
    ]


def test_public_board_openings_keep_lever_roles_without_inferable_skills(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_get_json(url: str) -> list[dict]:
        requested_urls.append(url)
        return [
            {
                "id": "lever-9",
                "text": "Urban Garden Coordinator",
                "categories": {
                    "location": "Berlin, Germany",
                    "allLocations": ["Berlin, Germany", "Paris, France"],
                    "commitment": "Full-time",
                },
                "hostedUrl": "https://jobs.lever.co/example/lever-9",
                "descriptionPlain": "Coordinate community gardens and local harvests.",
                "lists": [{"text": "What you will do", "content": "Plan seed exchanges."}],
                "createdAt": "2026-10-03T09:00:00Z",
            }
        ]

    monkeypatch.setattr(sources, "_get_json", fake_get_json)

    openings = sources.fetch_public_board_openings("Lever", "garden-co", company="Garden Co")

    assert requested_urls == ["https://api.lever.co/v0/postings/garden-co?mode=json"]
    assert openings == [
        {
            "source": "Lever",
            "source_id": "lever-9",
            "board_identifier": "garden-co",
            "company": "Garden Co",
            "title": "Urban Garden Coordinator",
            "location": "Berlin, Germany • Paris, France",
            "url": "https://jobs.lever.co/example/lever-9",
            "description": "Coordinate community gardens and local harvests.\nWhat you will do: Plan seed exchanges.",
            "source_timestamp": "2026-10-03T09:00:00Z",
            "source_timestamp_kind": "created",
            "workplace_type": None,
            "employment_type": "Full-time",
        }
    ]


def test_public_board_openings_keep_ashby_secondary_locations(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_get_json(url: str) -> dict:
        requested_urls.append(url)
        return {
            "jobs": [
                {
                    "id": "ashby-7",
                    "title": "Machine Learning Engineer",
                    "location": "Paris",
                    "address": {"postalAddress": {"addressLocality": "Paris", "addressCountry": "France"}},
                    "secondaryLocations": [
                        {
                            "location": "London",
                            "address": {"addressLocality": "London", "addressCountry": "United Kingdom"},
                        }
                    ],
                    "jobUrl": "https://jobs.ashbyhq.com/example/ashby-7",
                    "descriptionPlain": "Build applied machine-learning systems.",
                    "publishedAt": "2026-10-04T10:00:00Z",
                    "workplaceType": "Hybrid",
                    "employmentType": "Full-time",
                }
            ]
        }

    monkeypatch.setattr(sources, "_get_json", fake_get_json)

    openings = sources.fetch_public_board_openings("Ashby", "example", company="Example AI")

    assert requested_urls == ["https://api.ashbyhq.com/posting-api/job-board/example?includeCompensation=false"]
    assert openings == [
        {
            "source": "Ashby",
            "source_id": "ashby-7",
            "board_identifier": "example",
            "company": "Example AI",
            "title": "Machine Learning Engineer",
            "location": "Paris, France • London, United Kingdom",
            "url": "https://jobs.ashbyhq.com/example/ashby-7",
            "description": "Build applied machine-learning systems.",
            "source_timestamp": "2026-10-04T10:00:00Z",
            "source_timestamp_kind": "published",
            "workplace_type": "Hybrid",
            "employment_type": "Full-time",
        }
    ]


def test_public_board_openings_rejects_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="registered Greenhouse, Lever, and Ashby"):
        sources.fetch_public_board_openings("LinkedIn", "example", company="Example")


def test_checked_redirect_validates_every_hop() -> None:
    handler = sources._CheckedRedirect()
    with pytest.raises(ValueError):
        handler.redirect_request(None, None, 302, "", {}, "http://127.0.0.1/admin")
    with pytest.raises(ValueError):
        handler.redirect_request(None, None, 302, "", {}, "https://not-allowlisted.example.com/x")


def test_get_json_rejects_oversized_responses(monkeypatch) -> None:
    monkeypatch.setattr(sources, "_assert_public_https_url", lambda url: None)

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://boards-api.greenhouse.io/x"

        def read(self, limit=-1):
            assert limit == sources.MAX_SOURCE_BYTES + 1
            return b"x" * (sources.MAX_SOURCE_BYTES + 1)

    monkeypatch.setattr(sources._opener, "open", lambda *args, **kwargs: OversizedResponse())
    with pytest.raises(RuntimeError, match="MB safety limit"):
        sources._get_json("https://boards-api.greenhouse.io/x")
