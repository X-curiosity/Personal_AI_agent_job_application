# Design questions for the next explorations

Questions raised by exploring the current app. Each is a decision with concrete options — answer the ones you care about and I'll implement the chosen direction. Current state is summarized so choices are grounded, not guesses.

## A. Map & discovery

1. **What should the map land on first?**
   - A) A world/continent view of country cards (current).
   - B) A zoomed "your region" default (e.g. Europe) with cities visible immediately.
   - C) A full-screen map with a search-first overlay (StartupMap style).

2. **Country cards now show a flag. Should clicking a country also filter the side list to that country, or only zoom?**
   - A) Zoom only (current).
   - B) Zoom + set a country filter so the list shows that country's companies.
   - C) Open a country page with sectors and a "top companies" summary.

3. **City cards group by city. Do we show the country flag on city cards too?**
   - A) Yes, small flag + city name.
   - B) No, keep city cards clean.
   - C) Only when two cities share a name (Cambridge, GB vs Cambridge, US).

4. **Company pin on hover: what's most useful?**
   - A) Nothing (click to see detail).
   - B) A tooltip: name + "N open roles".
   - C) A mini card with logo, stage, and hiring badge.

## B. Jobs & search

5. **The search box searches roles AND companies. Should it be split?**
   - A) Keep one combined search.
   - B) A "role vs company" toggle.
   - C) Two fields (search roles, search companies).

6. **Results are capped at ~120 roles for diversity. What matters more?**
   - A) Breadth (more companies, fewer roles each) — current.
   - B) Depth (full role list for fewer, higher-quality companies).
   - C) Recency (newest roles first, regardless of company).

7. **Hiring status has three states (Hiring now / Lists hiring / No open roles). Is this clear enough?**
   - A) Yes, keep.
   - B) Simplify to two: "Hiring" vs "Not in snapshot".
   - C) Add a date ("hiring as of …") to every flag.

## C. Personal folders & agent

8. **A folder = one role target (region + company type + keywords). Should folders also hold "deal-breakers"?**
   - A) Add exclusions (e.g. exclude "agency", require remote).
   - B) Add salary/seniority ranges.
   - C) Keep folders simple; add a separate "preferences" profile.

9. **The agent scores roles by CV skill coverage. What should a match card emphasize?**
   - A) Score + missing skills (current).
   - B) Score + a one-line "why this role fits you".
   - C) Score + the 2 project ideas directly in the card.

10. **Project PDFs: one per role. Do you want them to feel more "personal"?**
    - A) Keep deterministic, factual (current).
    - B) Incorporate your letter of intention into the project framing.
    - C) Add a cover page with your name and the role.

11. **Should folders run on a schedule, or only when you click "Run"?**
    - A) Manual only (current).
    - B) Manual + a "check daily" toggle that refreshes when the app is open.
    - C) True background schedule (needs the hosted worker).

## D. Onboarding & preferences

12. **First-time experience: what should a new user see?**
    - A) The public map immediately.
    - B) A 3-step "what are you looking for" flow that seeds a first folder.
    - C) A "create your first folder" prompt over a blank personal page.

13. **Preferences (sector, sub-sector, region, company type) are per-folder. Do you also want global defaults?**
    - A) Yes, a profile with default region/type reused by new folders.
    - B) No, each folder is fully self-contained.
    - C) Optional defaults with a "copy from profile" button.

## E. Branding & visual

14. **The app is orange/yellow. Is the visual direction right?**
    - A) Keep as-is.
    - B) Muted/neutral with orange as accent only.
    - C) A different palette entirely (suggest one).

15. **Logos: many companies show no logo. What's the right fallback?**
    - A) Initials monogram (current).
    - B) Leave blank; show only when a verified logo exists.
    - C) A subtle "no logo" placeholder.

## F. Scope & coverage

16. **The public vacancy snapshot is European and small. What's the priority?**
    - A) Expand European sources (more companies) first.
    - B) Go global (US + Europe + others) now.
    - C) Add company self-serve first (startups submit their own jobs).

17. **"Every ML role in Europe" is the goal. Do we accept showing "N roles found across M sources" even when incomplete?**
    - A) Yes, with a clear coverage note (current).
    - B) Only if we can promise near-completeness for the region.
    - C) Show completeness as a percentage estimate.

18. **Private preparation is local-only (CVs, folders, matching). Confirm this stays local for now?**
    - A) Yes — local app only, nothing private on the public site.
    - B) Add optional cloud sync later with your approval.
    - C) Move folders to the hosted Supabase version now.

---

Answer as many or as few as you like (e.g. "1B, 3A, 8A, 14B"). I'll batch the chosen directions into the next implementation pass.
