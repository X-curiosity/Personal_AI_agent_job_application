from tau_job_application.people_finder import filter_people, is_recruiting_role, linkedin_url, normalize_person


def test_is_recruiting_role():
    assert is_recruiting_role("Senior Technical Recruiter")
    assert is_recruiting_role("Talent Acquisition Partner")
    assert is_recruiting_role("Head of People")
    assert not is_recruiting_role("Staff Software Engineer")


def test_linkedin_url_extraction():
    assert linkedin_url("See https://www.linkedin.com/in/jane-doe for more") == "https://www.linkedin.com/in/jane-doe"
    assert linkedin_url("no profile here") is None


def test_normalize_person_requires_name_linkedin_and_company():
    ok = {"name": "Jane Doe", "role": "Technical Recruiter", "url": "https://www.linkedin.com/in/jane-doe", "note": "Recruiter at Acme"}
    assert normalize_person(ok, "Acme")["linkedin"] == "https://www.linkedin.com/in/jane-doe"
    assert normalize_person({**ok, "url": "https://example.com/x"}, "Acme") is None  # no LinkedIn
    assert normalize_person({**ok, "role": "Engineer"}, "Acme") is None  # not recruiting
    assert normalize_person({**ok, "note": "works at OtherCo"}, "Acme") is None  # company mismatch


def test_filter_people_deduplicates():
    hit = {"name": "Jane Doe", "role": "Recruiter", "url": "https://www.linkedin.com/in/jane-doe", "note": "Acme"}
    people = filter_people([hit, hit], "Acme")
    assert len(people) == 1
    assert people[0]["name"] == "Jane Doe"
