# Public explorer assets

All runtime assets are self-hosted. The browser requests no external tiles,
fonts, logos or geocoding APIs. Outbound company/source links are user-initiated.

- `leaflet.js` / `leaflet.css`: Leaflet 1.9.4 from
  https://unpkg.com/leaflet@1.9.4/dist/ (BSD-2-Clause; see `LEAFLET-LICENSE`).
  Used for pan/zoom, geographic projection, vector rendering and keyboard pins.
  We use custom HTML markers, not Leaflet's image-marker assets.
- `../data/world.geojson`: Natural Earth 1:110m admin-0 country outlines from
  https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
  (public domain: https://www.naturalearthdata.com/about/terms-of-use/).
  Only English names and geometry retained; coordinates rounded to three
  decimals; Antarctica omitted. These are overview boundaries, not street maps
  or statements of political sovereignty.
- `../data/companies.json`: explicit allowlisted export of public catalogue
  facts. Not copied from StartupMap and not a database dump. To regenerate:
  `python scripts/export_public_map.py` from the repository root. Review the
  output before publication. Personal records are never queried. This static
  snapshot does not automatically refresh when the local scheduler runs.

- `../data/wikidata_hq.json`: headquarters coordinates from Wikidata
  (CC0, https://www.wikidata.org/wiki/Wikidata:Licensing), matched only by
  exact official-website statements, regenerated with
  `python scripts/fetch_wikidata_hq.py`. No StartupMap API data is used.

No StartupMap code, logos, photographs, company database, coordinates, or map
styles are bundled. Observed interactions informed an independently written
interface.
