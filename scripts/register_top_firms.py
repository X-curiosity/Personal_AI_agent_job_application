"""Register ATS boards for curated top firms (consulting, banking, PE, VC, trading).

Detects Greenhouse / Lever / Ashby / Workable / Recruitee / Teamtailor boards from
each firm's website and careers pages, and registers them in the job_sources
store. Companies that use Workday / SuccessFactors / a custom portal yield
nothing here (they have no public feed), which is the documented bottleneck.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tau_job_application.job_sources import JobSource, JobSourceStore, detect_company_ats

FIRMS: list[tuple[str, str, str, str]] = [
    # (name, website, company_type, region_hint)
    # Consulting
    ("McKinsey & Company", "https://www.mckinsey.com", "private", "United States"),
    ("Boston Consulting Group", "https://www.bcg.com", "private", "United States"),
    ("Bain & Company", "https://www.bain.com", "private", "United States"),
    ("Deloitte", "https://www.deloitte.com", "private", "United States"),
    ("PwC", "https://www.pwc.com", "private", "United States"),
    ("EY", "https://www.ey.com", "private", "United States"),
    ("KPMG", "https://kpmg.com", "private", "United States"),
    ("Accenture", "https://www.accenture.com", "public", "United States"),
    ("Oliver Wyman", "https://www.oliverwyman.com", "private", "United States"),
    ("L.E.K. Consulting", "https://www.lek.com", "private", "United States"),
    ("Roland Berger", "https://www.rolandberger.com", "private", "Germany"),
    ("Kearney", "https://www.kearney.com", "private", "United States"),
    ("Alvarez & Marsal", "https://www.alvarezandmarsal.com", "private", "United States"),
    # Banking / investment banking
    ("Goldman Sachs", "https://www.goldmansachs.com", "public", "United States"),
    ("JPMorgan Chase", "https://www.jpmorganchase.com", "public", "United States"),
    ("Morgan Stanley", "https://www.morganstanley.com", "public", "United States"),
    ("Citigroup", "https://www.citigroup.com", "public", "United States"),
    ("Bank of America", "https://www.bankofamerica.com", "public", "United States"),
    ("Barclays", "https://home.barclays", "public", "United Kingdom"),
    ("UBS", "https://www.ubs.com", "public", "Switzerland"),
    ("Deutsche Bank", "https://www.db.com", "public", "Germany"),
    ("HSBC", "https://www.hsbc.com", "public", "United Kingdom"),
    ("BNP Paribas", "https://www.bnpparibas.com", "public", "France"),
    ("Jefferies", "https://www.jefferies.com", "public", "United States"),
    ("Lazard", "https://www.lazard.com", "public", "United States"),
    ("Evercore", "https://www.evercore.com", "public", "United States"),
    ("Moelis & Company", "https://www.moelis.com", "public", "United States"),
    ("Centerview Partners", "https://centerview.com", "private", "United States"),
    # Private equity
    ("Blackstone", "https://www.blackstone.com", "public", "United States"),
    ("KKR", "https://www.kkr.com", "public", "United States"),
    ("The Carlyle Group", "https://www.carlyle.com", "public", "United States"),
    ("Apollo Global Management", "https://www.apollo.com", "public", "United States"),
    ("TPG", "https://www.tpg.com", "public", "United States"),
    ("Warburg Pincus", "https://warburgpincus.com", "private", "United States"),
    ("CVC Capital Partners", "https://www.cvc.com", "public", "United Kingdom"),
    ("EQT", "https://www.eqtgroup.com", "public", "Sweden"),
    ("Thoma Bravo", "https://www.thomabravo.com", "private", "United States"),
    ("Silver Lake", "https://www.silverlake.com", "private", "United States"),
    ("Bain Capital", "https://www.baincapital.com", "private", "United States"),
    ("Advent International", "https://www.adventinternational.com", "private", "United States"),
    ("Permira", "https://www.permira.com", "private", "United Kingdom"),
    ("General Atlantic", "https://www.generalatlantic.com", "private", "United States"),
    # Venture capital / big funds
    ("Sequoia Capital", "https://www.sequoiacap.com", "private", "United States"),
    ("Andreessen Horowitz", "https://a16z.com", "private", "United States"),
    ("Insight Partners", "https://www.insightpartners.com", "private", "United States"),
    ("Index Ventures", "https://www.indexventures.com", "private", "United Kingdom"),
    ("Accel", "https://www.accel.com", "private", "United States"),
    ("Lightspeed Venture Partners", "https://lsvp.com", "private", "United States"),
    ("Kleiner Perkins", "https://www.kleinerperkins.com", "private", "United States"),
    ("Bessemer Venture Partners", "https://www.bvp.com", "private", "United States"),
    ("Founders Fund", "https://foundersfund.com", "private", "United States"),
    # Trading / quant
    ("Jane Street", "https://www.janestreet.com", "private", "United States"),
    ("Citadel", "https://www.citadel.com", "private", "United States"),
    ("Two Sigma", "https://www.twosigma.com", "private", "United States"),
    ("Hudson River Trading", "https://www.hudsonrivertrading.com", "private", "United States"),
    ("Jump Trading", "https://www.jumptrading.com", "private", "United States"),
    ("DRW", "https://drw.com", "private", "United States"),
    ("Optiver", "https://www.optiver.com", "private", "Netherlands"),
    ("IMC Trading", "https://www.imc.com", "private", "Netherlands"),
    ("Susquehanna International Group", "https://www.sig.com", "private", "United States"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / ".job_assistant" / "assistant.sqlite")
    args = parser.parse_args()

    # Fund careers pages link to portfolio-company boards; attribute them to the
    # real company instead of the fund (verified board identifiers).
    board_company = {
        "andurilindustries": "Anduril Industries",
        "shieldai": "Shield AI",
        "exa": "Exa",
        "harvey": "Harvey",
        "lime": "Lime",
        "ambiencehealthcare": "Ambience Healthcare",
        "fal-ai": "Fal",
        "ideogram": "Ideogram",
        "apex-technology-inc": "Apex",
    }

    store = JobSourceStore(args.database)
    found = 0
    tried = 0
    for name, website, company_type, region in FIRMS:
        tried += 1
        try:
            boards = detect_company_ats(website)
        except Exception as exc:  # unreachable site
            print(f"  ! {name}: {exc}")
            continue
        if not boards:
            print(f"  - {name}: no public ATS detected")
            continue
        for board in boards:
            owner = board_company.get(board["board_identifier"].casefold(), name)
            store.register(JobSource(
                company=owner,
                source=board["source"],
                board_identifier=board["board_identifier"],
                board_url=board["board_url"],
                company_type=company_type,
                region_hint=region,
                website=website,
                detected_from=website,
            ))
            found += 1
            print(f"  + {owner}: {board['source']} {board['board_identifier']}")
    print(f"\nRegistered {found} boards from {tried} top firms (total sources now {store.count()}).")


if __name__ == "__main__":
    sys.exit(main())
