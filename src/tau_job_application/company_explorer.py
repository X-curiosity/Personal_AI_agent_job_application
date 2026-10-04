"""Transparent, local company exploration from a candidate's supplied profile.

The catalogue is deliberately small and curated.  It is a starting point for
research, not a live vacancy feed, a hiring prediction, or a claim that a
company is currently recruiting.  Each pin represents a selected company hub,
not necessarily a headquarters or every location where that company operates.
"""
from __future__ import annotations

from dataclasses import dataclass

from tau_job_application.matching import normalize_skill
from tau_job_application.parsing import parse_candidate_text


@dataclass(frozen=True)
class CompanyPin:
    company: str
    city: str
    country: str
    region: str
    latitude: float
    longitude: float
    focus: str
    skills: tuple[str, ...]
    careers_url: str


@dataclass(frozen=True)
class CompanyRecommendation:
    company: str
    city: str
    country: str
    region: str
    latitude: float
    longitude: float
    focus: str
    careers_url: str
    matching_skills: tuple[str, ...]


@dataclass(frozen=True)
class CompanyHub:
    """A selected, source-linked company location—not an exhaustive directory."""

    city: str
    country: str
    region: str
    latitude: float
    longitude: float
    site_type: str
    focus: str
    source_url: str
    source_year: int | None = None
    verification_note: str | None = None


# Locations are deliberately labelled as selected hubs in the UI. The skills
# describe broad areas that make a company worth researching, rather than an
# assertion about an open requisition or an individual team's stack.
COMPANY_PINS: tuple[CompanyPin, ...] = (
    CompanyPin("NVIDIA", "Santa Clara", "United States", "North America", 37.3541, -121.9552, "AI computing and accelerated systems", ("Python", "C++", "CUDA", "GPU programming", "PyTorch", "Linux"), "https://www.nvidia.com/en-us/about-nvidia/careers/"),
    CompanyPin("Google", "Mountain View", "United States", "North America", 37.4220, -122.0841, "Cloud, AI, and consumer products", ("Python", "C++", "Java", "Go", "TensorFlow", "Kubernetes", "GCP"), "https://www.google.com/about/careers/applications/jobs/results/"),
    CompanyPin("Microsoft", "Redmond", "United States", "North America", 47.6740, -122.1215, "Cloud platforms, AI, and developer tools", ("Python", "C++", "Azure", "TypeScript", "React", "Kubernetes"), "https://jobs.careers.microsoft.com/global/en/search"),
    CompanyPin("Apple", "Cupertino", "United States", "North America", 37.3349, -122.0090, "Devices, platforms, and product design", ("C", "C++", "Python", "Microcontrollers", "Figma"), "https://jobs.apple.com/en-us/search"),
    CompanyPin("Stripe", "San Francisco", "United States", "North America", 37.7749, -122.4194, "Financial infrastructure", ("Python", "Java", "Go", "TypeScript", "React", "PostgreSQL", "AWS"), "https://stripe.com/jobs/search"),
    CompanyPin("Cloudflare", "San Francisco", "United States", "North America", 37.7749, -122.4194, "Internet infrastructure and security", ("Go", "Rust", "Python", "C", "C++", "Linux", "Terraform"), "https://www.cloudflare.com/careers/jobs/"),
    CompanyPin("Datadog", "New York", "United States", "North America", 40.7128, -74.0060, "Cloud observability", ("Python", "Go", "Java", "Docker", "Kubernetes", "AWS", "Terraform"), "https://careers.datadoghq.com/"),
    CompanyPin("Figma", "San Francisco", "United States", "North America", 37.7749, -122.4194, "Collaborative product design", ("TypeScript", "React", "Figma", "Python", "GraphQL"), "https://boards.greenhouse.io/figma"),
    CompanyPin("Snowflake", "San Mateo", "United States", "North America", 37.56299, -122.32553, "Cloud data platforms", ("Python", "SQL", "Java", "C++", "AWS", "Kubernetes"), "https://careers.snowflake.com/"),
    CompanyPin("Shopify", "Toronto", "Canada", "North America", 43.6532, -79.3832, "Commerce platforms", ("TypeScript", "React", "Python", "GraphQL", "Docker"), "https://www.shopify.com/careers"),
    CompanyPin("ABB", "Zurich", "Switzerland", "Europe", 47.3769, 8.5417, "Industrial automation and electrification", ("Python", "C", "C++", "Machine Learning", "Linux", "Microcontrollers"), "https://careers.abb/global/en"),
    CompanyPin("Celonis", "Munich", "Germany", "Europe", 48.1351, 11.5820, "Process intelligence and data", ("Python", "SQL", "Data Analysis", "Spark", "Airflow"), "https://www.celonis.com/careers/"),
    CompanyPin("Siemens", "Munich", "Germany", "Europe", 48.1351, 11.5820, "Industrial software and automation", ("Python", "C++", "C", "Machine Learning", "Embedded Linux", "Docker"), "https://jobs.siemens.com/careers"),
    CompanyPin("Bosch", "Stuttgart", "Germany", "Europe", 48.7758, 9.1829, "Mobility, IoT, and embedded systems", ("C", "C++", "Python", "RTOS", "Microcontrollers", "Embedded Linux"), "https://www.bosch.com/careers/"),
    CompanyPin("SAP", "Walldorf", "Germany", "Europe", 49.3061, 8.6424, "Enterprise applications and cloud", ("Java", "Python", "SQL", "AWS", "Kubernetes"), "https://jobs.sap.com/"),
    CompanyPin("ARM", "Cambridge", "United Kingdom", "Europe", 52.2053, 0.1218, "Semiconductor IP and systems", ("C", "C++", "Python", "Embedded Linux", "RTOS", "Microcontrollers"), "https://careers.arm.com/"),
    CompanyPin("Google DeepMind", "London", "United Kingdom", "Europe", 51.5072, -0.1276, "AI research and engineering", ("Python", "C++", "PyTorch", "TensorFlow", "Machine Learning"), "https://deepmind.google/careers/"),
    CompanyPin("Revolut", "London", "United Kingdom", "Europe", 51.5072, -0.1276, "Financial technology", ("Python", "Java", "SQL", "AWS", "Docker"), "https://www.revolut.com/careers/"),
    CompanyPin("Wise", "London", "United Kingdom", "Europe", 51.5072, -0.1276, "International payments", ("Java", "Python", "SQL", "AWS"), "https://wise.jobs/"),
    CompanyPin("Spotify", "Stockholm", "Sweden", "Europe", 59.3293, 18.0686, "Audio, data, and consumer products", ("Python", "Java", "Data Analysis", "Spark", "Airflow"), "https://www.lifeatspotify.com/jobs"),
    CompanyPin("Klarna", "Stockholm", "Sweden", "Europe", 59.3293, 18.0686, "Consumer financial technology", ("Python", "Java", "SQL", "AWS", "Docker", "Kubernetes"), "https://www.klarna.com/careers/"),
    CompanyPin("Mistral AI", "Paris", "France", "Europe", 48.8566, 2.3522, "Foundation models and AI platforms", ("Python", "C++", "PyTorch", "Machine Learning", "CUDA", "GPU programming"), "https://jobs.lever.co/mistral"),
    CompanyPin("Hugging Face", "Paris", "France", "Europe", 48.8566, 2.3522, "Open machine-learning tools", ("Python", "PyTorch", "TensorFlow", "Machine Learning", "JavaScript"), "https://apply.workable.com/huggingface/"),
    CompanyPin("ASML", "Veldhoven", "Netherlands", "Europe", 51.4070, 5.3966, "Semiconductor manufacturing systems", ("Python", "C++", "C", "Linux", "MATLAB"), "https://www.asml.com/en/careers"),
    CompanyPin("Adyen", "Amsterdam", "Netherlands", "Europe", 52.3676, 4.9041, "Payments technology", ("Java", "Python", "SQL", "AWS"), "https://careers.adyen.com/"),
    CompanyPin("NXP", "Eindhoven", "Netherlands", "Europe", 51.4416, 5.4697, "Embedded and semiconductor systems", ("C", "C++", "Python", "RTOS", "Microcontrollers", "Embedded Linux"), "https://www.nxp.com/company/about-nxp/careers:CAREERS"),
    CompanyPin("TSMC", "Hsinchu", "Taiwan", "Asia-Pacific", 24.8138, 120.9675, "Semiconductor technology", ("Python", "C++", "C", "Verilog", "FPGA"), "https://www.tsmc.com/english/careers"),
    CompanyPin("Samsung", "Seoul", "South Korea", "Asia-Pacific", 37.5665, 126.9780, "Devices, electronics, and platforms", ("C", "C++", "Python", "Machine Learning", "Embedded Linux"), "https://www.samsung.com/us/careers/"),
    CompanyPin("Grab", "Singapore", "Singapore", "Asia-Pacific", 1.3521, 103.8198, "Mobility, payments, and delivery", ("Python", "Java", "SQL", "Data Analysis", "AWS", "Kubernetes"), "https://www.grab.careers/"),
    CompanyPin("Canva", "Sydney", "Australia", "Asia-Pacific", -33.8688, 151.2093, "Visual collaboration and product design", ("TypeScript", "React", "Python", "Figma", "GraphQL"), "https://www.canva.com/careers/"),
    CompanyPin("Atlassian", "Sydney", "Australia", "Asia-Pacific", -33.8688, 151.2093, "Developer tools and collaboration", ("Java", "TypeScript", "React", "Python", "AWS"), "https://www.atlassian.com/company/careers"),
    CompanyPin("Nubank", "São Paulo", "Brazil", "South America", -23.5505, -46.6333, "Digital financial services", ("Python", "SQL", "AWS", "Kubernetes", "Data Analysis"), "https://international.nubank.com.br/careers/"),
    CompanyPin("Mercado Libre", "Buenos Aires", "Argentina", "South America", -34.6037, -58.3816, "Commerce and financial technology", ("Python", "Java", "SQL", "AWS", "Docker"), "https://careers-meli.mercadolibre.com/"),
    CompanyPin("Andela", "Nairobi", "Kenya", "Africa", -1.2864, 36.8172, "Global software talent network", ("Python", "JavaScript", "TypeScript", "React", "Docker", "AWS"), "https://www.andela.com/careers"),
)


# Focus descriptions below are deliberately conservative summaries of a linked
# public source. A source can describe a research lab or an illustrative role,
# rather than a permanent mandate for every team at that location. The UI makes
# that distinction visible and does not treat a hub as evidence of an open job.
COMPANY_HUBS: dict[str, tuple[CompanyHub, ...]] = {
    "NVIDIA": (
        CompanyHub("Santa Clara", "United States", "North America", 37.3541, -121.9552, "Global HQ", "Corporate headquarters; company-wide accelerated-computing platform context.", "https://www.nvidia.com/en-in/contact/"),
        CompanyHub("Yokneam", "Israel", "Middle East", 32.6595, 35.1090, "Engineering hub", "Networking systems for AI data centers, including switches, NICs, and DPUs.", "https://jobs.nvidia.com/careers/job/893397566390"),
        CompanyHub("Bengaluru", "India", "Asia-Pacific", 12.9716, 77.5946, "Engineering hub", "GPU and SoC performance architecture, based on current-role evidence.", "https://jobs.nvidia.com/careers/job/893397676108-architect-gpu-performance-india-bengaluru?domain=nvidia.com", verification_note="Current-role evidence; verify before treating this as a durable site-wide mandate."),
    ),
    "Google": (
        CompanyHub("Mountain View", "United States", "North America", 37.4220, -122.0841, "Global HQ", "Google labels this location as its Global HQ.", "https://www.google.com/about/careers/applications/locations"),
        CompanyHub("Zurich", "Switzerland", "Europe", 47.3769, 8.5417, "Engineering and research hub", "Product engineering and machine-learning research.", "https://blog.google/company-news/inside-google/around-the-globe/google-europe/zurich-expanding-our-european-tech-hub/", 2017, "Google described this focus in 2017; verify current teams and openings."),
        CompanyHub("Bengaluru", "India", "Asia-Pacific", 12.9716, 77.5946, "Research hub", "Fundamental computer-science and AI research, with applied work in healthcare, agriculture, and education.", "https://blog.google/intl/en-in/company-news/technology/google-research-india-ai-lab-in/", 2019, "Google described this focus in 2019; verify current teams and openings."),
    ),
    "Microsoft": (
        CompanyHub("Redmond", "United States", "North America", 47.6740, -122.1215, "Research hub", "Research in AI interaction, networking, and software engineering.", "https://www.microsoft.com/en-us/research/lab/microsoft-research-redmond/"),
        CompanyHub("Cambridge", "United Kingdom", "Europe", 52.2053, 0.1218, "Research hub", "AI infrastructure, machine intelligence, people-centred AI, and research engineering.", "https://www.microsoft.com/en-us/research/lab/microsoft-research-cambridge/"),
        CompanyHub("Bengaluru", "India", "Asia-Pacific", 12.9716, 77.5946, "Research hub", "Algorithms, ML/AI, systems, and societal-impact cloud/AI research.", "https://www.microsoft.com/en-us/research/careers/"),
    ),
    "ABB": (
        CompanyHub("Zurich", "Switzerland", "Europe", 47.3769, 8.5417, "Group HQ", "Group headquarters and corporate stewardship.", "https://global.abb/content/dam/abb/global/group/investors/results-and-reports/2021/abb-ltd-2021-form-20f.pdf", 2021, "Use as corporate-location context; verify any current local team focus."),
        CompanyHub("Bengaluru", "India", "Asia-Pacific", 12.9716, 77.5946, "Corporate research centre", "Industrial software, analytics, process optimization, automation engineering, communications, and cybersecurity research.", "https://new.abb.com/es/tecnologia/centros-de-investigaciones-corporativas/corporate-research-center-india"),
    ),
}


def detected_profile_skills(cv_text: str, links: dict[str, str] | None = None) -> tuple[str, ...]:
    """Return the finite local skill vocabulary found in a supplied CV."""
    if not cv_text.strip():
        return ()
    candidate = parse_candidate_text(cv_text, links=links)
    return tuple(candidate.skills)


def recommend_companies(
    cv_text: str,
    *,
    links: dict[str, str] | None = None,
    regions: tuple[str, ...] | None = None,
    limit: int | None = 24,
) -> list[CompanyRecommendation]:
    """Rank only catalogue companies with a transparent profile-skill overlap."""
    skills = detected_profile_skills(cv_text, links)
    by_key = {normalize_skill(skill): skill for skill in skills}
    accepted_regions = set(regions or ())
    recommendations: list[CompanyRecommendation] = []
    for pin in COMPANY_PINS:
        if accepted_regions and pin.region not in accepted_regions:
            continue
        matching = tuple(by_key[normalize_skill(skill)] for skill in pin.skills if normalize_skill(skill) in by_key)
        if matching:
            recommendations.append(CompanyRecommendation(
                company=pin.company,
                city=pin.city,
                country=pin.country,
                region=pin.region,
                latitude=pin.latitude,
                longitude=pin.longitude,
                focus=pin.focus,
                careers_url=pin.careers_url,
                matching_skills=matching,
            ))
    recommendations.sort(key=lambda item: (-len(item.matching_skills), item.company.casefold()))
    return recommendations[:limit] if limit is not None else recommendations


def company_footprint(company: str) -> tuple[CompanyHub, ...]:
    """Return all curated source-linked hubs for one catalogue company.

    Companies without a dedicated footprint still expose their selected explorer
    pin so the UI never silently implies a complete office list.
    """
    pin = next((item for item in COMPANY_PINS if item.company.casefold() == company.casefold()), None)
    if pin is None:
        raise ValueError("Company is not in the explorer catalogue")
    hubs = COMPANY_HUBS.get(pin.company)
    if hubs:
        return hubs
    return (
        CompanyHub(
            city=pin.city,
            country=pin.country,
            region=pin.region,
            latitude=pin.latitude,
            longitude=pin.longitude,
            site_type="Selected explorer hub",
            focus=pin.focus,
            source_url=pin.careers_url,
            verification_note="This catalogue currently has one selected hub for this company; it is not a complete footprint.",
        ),
    )
