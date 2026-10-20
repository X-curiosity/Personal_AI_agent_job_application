"""Offline city/country geocoding for the hiring-company map.

Directory locations arrive as free text ("San Francisco, CA, USA", "Berlin,
Germany", "USA"). This module resolves them against a curated gazetteer of the
cities that dominate the local YC/Atlas/CompaniesMarketCap data, falling back
to country centroids. Every result carries its precision so the map can render
country-level pins visibly differently instead of pretending they are exact.
No network, no geocoding API, no dependency.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Precision = Literal["city", "country"]


class GeocodeResult(BaseModel):
    latitude: float
    longitude: float
    precision: Precision
    label: str  # the place name that produced the coordinates


# (latitude, longitude) keyed by "city, country" plus common aliases.
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    # North America
    "san francisco, usa": (37.7749, -122.4194), "san francisco, ca, usa": (37.7749, -122.4194),
    "san francisco, united states": (37.7749, -122.4194), "san francisco bay area, usa": (37.7749, -122.4194),
    "bay area, usa": (37.7749, -122.4194), "sf, usa": (37.7749, -122.4194),
    "new york, usa": (40.7128, -74.0060), "new york, ny, usa": (40.7128, -74.0060),
    "new york city, usa": (40.7128, -74.0060), "nyc, usa": (40.7128, -74.0060),
    "new york, united states": (40.7128, -74.0060),
    "los angeles, usa": (34.0522, -118.2437), "los angeles, ca, usa": (34.0522, -118.2437), "la, usa": (34.0522, -118.2437),
    "palo alto, usa": (37.4419, -122.1430), "palo alto, ca, usa": (37.4419, -122.1430),
    "mountain view, usa": (37.3861, -122.0839), "mountain view, ca, usa": (37.3861, -122.0839),
    "san mateo, usa": (37.5630, -122.3255),
    "menlo park, usa": (37.4530, -122.1817),
    "redwood city, usa": (37.4852, -122.2364),
    "sunnyvale, usa": (37.3688, -122.0363),
    "santa clara, usa": (37.3541, -121.9552),
    "san jose, usa": (37.3382, -121.8863),
    "cupertino, usa": (37.3230, -122.0322),
    "oakland, usa": (37.8044, -122.2712),
    "seattle, usa": (47.6062, -122.3321), "seattle, wa, usa": (47.6062, -122.3321),
    "redmond, usa": (47.6740, -122.1215), "bellevue, usa": (47.6101, -122.2015),
    "boston, usa": (42.3601, -71.0589), "boston, ma, usa": (42.3601, -71.0589),
    "cambridge, usa": (42.3736, -71.1097), "cambridge, ma, usa": (42.3736, -71.1097),
    "austin, usa": (30.2672, -97.7431), "austin, tx, usa": (30.2672, -97.7431),
    "denver, usa": (39.7392, -104.9903), "boulder, usa": (40.0150, -105.2705),
    "chicago, usa": (41.8781, -87.6298), "chicago, il, usa": (41.8781, -87.6298),
    "atlanta, usa": (33.7490, -84.3880),
    "miami, usa": (25.7617, -80.1918),
    "washington, usa": (38.9072, -77.0369), "washington dc, usa": (38.9072, -77.0369), "washington, dc, usa": (38.9072, -77.0369),
    "philadelphia, usa": (39.9526, -75.1652),
    "san diego, usa": (32.7157, -117.1611),
    "rochester, usa": (43.1566, -77.6088),
    "salt lake city, usa": (40.7608, -111.8910),
    "raleigh, usa": (35.7796, -78.6382), "durham, usa": (35.9940, -78.8986),
    "pittsburgh, usa": (40.4406, -79.9959),
    "detroit, usa": (42.3314, -83.0458),
    "minneapolis, usa": (44.9778, -93.2650),
    "nashville, usa": (36.1627, -86.7816),
    "dallas, usa": (32.7767, -96.7970),
    "houston, usa": (29.7604, -95.3698),
    "phoenix, usa": (33.4484, -112.0740), "scottsdale, usa": (33.4942, -111.9261),
    "portland, usa": (45.5152, -122.6784),
    "toronto, canada": (43.6532, -79.3832), "toronto, on, canada": (43.6532, -79.3832), "toronto, ontario, canada": (43.6532, -79.3832),
    "vancouver, canada": (49.2827, -123.1207),
    "montreal, canada": (45.5017, -73.5673), "montréal, canada": (45.5017, -73.5673),
    "waterloo, canada": (43.4643, -80.5204), "kitchener, canada": (43.4516, -80.4925),
    "ottawa, canada": (45.4215, -75.6972),
    "calgary, canada": (51.0447, -114.0719),
    "mexico city, mexico": (19.4326, -99.1332), "ciudad de méxico, mexico": (19.4326, -99.1332),
    "guadalajara, mexico": (20.6597, -103.3496), "monterrey, mexico": (25.6866, -100.3161),
    # Central & South America
    "são paulo, brazil": (-23.5505, -46.6333), "sao paulo, brazil": (-23.5505, -46.6333),
    "rio de janeiro, brazil": (-22.9068, -43.1729),
    "bogotá, colombia": (4.7110, -74.0721), "bogota, colombia": (4.7110, -74.0721),
    "buenos aires, argentina": (-34.6037, -58.3816),
    "santiago, chile": (-33.4489, -70.6693),
    "lima, peru": (-12.0464, -77.0428),
    "medellín, colombia": (6.2476, -75.5658), "medellin, colombia": (6.2476, -75.5658),
    # Europe
    "london, united kingdom": (51.5072, -0.1276), "london, uk": (51.5072, -0.1276),
    "london, england": (51.5072, -0.1276), "london, england, united kingdom": (51.5072, -0.1276), "london, gb": (51.5072, -0.1276),
    "cambridge, united kingdom": (52.2053, 0.1218), "oxford, united kingdom": (51.7520, -1.2577),
    "manchester, united kingdom": (53.4808, -2.2426), "edinburgh, united kingdom": (55.9533, -3.1883),
    "bristol, united kingdom": (51.4545, -2.5879),
    "berlin, germany": (52.5200, 13.4050),
    "munich, germany": (48.1351, 11.5820), "münchen, germany": (48.1351, 11.5820),
    "hamburg, germany": (53.5511, 9.9937),
    "cologne, germany": (50.9375, 6.9603), "köln, germany": (50.9375, 6.9603),
    "frankfurt, germany": (50.1109, 8.6821),
    "stuttgart, germany": (48.7758, 9.1829),
    "düsseldorf, germany": (51.2277, 6.7735), "dusseldorf, germany": (51.2277, 6.7735),
    "heidelberg, germany": (49.3988, 8.6724),
    "paris, france": (48.8566, 2.3522), "paris, fr": (48.8566, 2.3522),
    "lyon, france": (45.7640, 4.8357),
    "toulouse, france": (43.6047, 1.4442),
    "sophia antipolis, france": (43.6165, 7.0552),
    "amsterdam, netherlands": (52.3676, 4.9041),
    "rotterdam, netherlands": (51.9244, 4.4777),
    "eindhoven, netherlands": (51.4416, 5.4697),
    "the hague, netherlands": (52.0705, 4.3007),
    "utrecht, netherlands": (52.0907, 5.1214),
    "zurich, switzerland": (47.3769, 8.5417), "zürich, switzerland": (47.3769, 8.5417), "zurich, ch": (47.3769, 8.5417),
    "geneva, switzerland": (46.2044, 6.1432), "genève, switzerland": (46.2044, 6.1432),
    "lausanne, switzerland": (46.5197, 6.6323), "basel, switzerland": (47.5596, 7.5886), "zug, switzerland": (47.1662, 8.5155),
    "stockholm, sweden": (59.3293, 18.0686),
    "gothenburg, sweden": (57.7089, 11.9746), "göteborg, sweden": (57.7089, 11.9746),
    "malmö, sweden": (55.6050, 13.0038), "malmo, sweden": (55.6050, 13.0038),
    "copenhagen, denmark": (55.6761, 12.5683), "københavn, denmark": (55.6761, 12.5683),
    "oslo, norway": (59.9139, 10.7522),
    "helsinki, finland": (60.1699, 24.9384), "espoo, finland": (60.2055, 24.6559),
    "dublin, ireland": (53.3498, -6.2603),
    "madrid, spain": (40.4168, -3.7038), "madrid, es": (40.4168, -3.7038),
    "barcelona, spain": (41.3874, 2.1686),
    "valencia, spain": (39.4699, -0.3763),
    "bilbao, spain": (43.2630, -2.9350),
    "lisbon, portugal": (38.7223, -9.1393), "lisboa, portugal": (38.7223, -9.1393),
    "porto, portugal": (41.1579, -8.6291),
    "milan, italy": (45.4642, 9.1900), "milano, italy": (45.4642, 9.1900),
    "rome, italy": (41.9028, 12.4964), "roma, italy": (41.9028, 12.4964),
    "turin, italy": (45.0703, 7.6869),
    "vienna, austria": (48.2082, 16.3738), "wien, austria": (48.2082, 16.3738),
    "brussels, belgium": (50.8503, 4.3517), "bruxelles, belgium": (50.8503, 4.3517),
    "luxembourg, luxembourg": (49.6116, 6.1319),
    "warsaw, poland": (52.2297, 21.0122), "warszawa, poland": (52.2297, 21.0122),
    "kraków, poland": (50.0647, 19.9450), "krakow, poland": (50.0647, 19.9450), "cracow, poland": (50.0647, 19.9450),
    "wrocław, poland": (51.1079, 17.0385), "wroclaw, poland": (51.1079, 17.0385),
    "prague, czech republic": (50.0755, 14.4378), "prague, czechia": (50.0755, 14.4378), "praha, czech republic": (50.0755, 14.4378),
    "brno, czech republic": (49.1951, 16.6068),
    "bratislava, slovakia": (48.1486, 17.1077),
    "budapest, hungary": (47.4979, 19.0402),
    "bucharest, romania": (44.4268, 26.1025), "bucurești, romania": (44.4268, 26.1025),
    "cluj-napoca, romania": (46.7712, 23.6236), "cluj, romania": (46.7712, 23.6236),
    "sofia, bulgaria": (42.6977, 23.3219),
    "athens, greece": (37.9838, 23.7275),
    "tallinn, estonia": (59.4370, 24.7536),
    "riga, latvia": (56.9496, 24.1052),
    "vilnius, lithuania": (54.6872, 25.2797),
    "zagreb, croatia": (45.8150, 15.9819),
    "ljubljana, slovenia": (46.0569, 14.5058),
    "reykjavik, iceland": (64.1466, -21.9426),
    # Middle East & Africa
    "tel aviv, israel": (32.0853, 34.7818), "tel aviv-yafo, israel": (32.0853, 34.7818),
    "jerusalem, israel": (31.7683, 35.2137), "haifa, israel": (32.7940, 34.9896), "herzliya, israel": (32.1624, 34.8447),
    "amman, jordan": (31.9454, 35.9284),
    "dubai, united arab emirates": (25.2048, 55.2708), "dubai, uae": (25.2048, 55.2708),
    "abu dhabi, united arab emirates": (24.4539, 54.3773),
    "riyadh, saudi arabia": (24.7136, 46.6753),
    "doha, qatar": (25.2854, 51.5310),
    "cairo, egypt": (30.0444, 31.2357),
    "lagos, nigeria": (6.5244, 3.3792),
    "nairobi, kenya": (-1.2921, 36.8219),
    "cape town, south africa": (-33.9249, 18.4241),
    "johannesburg, south africa": (-26.2041, 28.0473),
    "accra, ghana": (5.6037, -0.1870),
    "casablanca, morocco": (33.5731, -7.5898),
    # Asia & Oceania
    "bangalore, india": (12.9716, 77.5946), "bengaluru, india": (12.9716, 77.5946),
    "mumbai, india": (19.0760, 72.8777),
    "delhi, india": (28.7041, 77.1025), "new delhi, india": (28.6139, 77.2090),
    "hyderabad, india": (17.3850, 78.4867),
    "gurgaon, india": (28.4595, 77.0266), "gurugram, india": (28.4595, 77.0266),
    "pune, india": (18.5204, 73.8567),
    "chennai, india": (13.0827, 80.2707),
    "noida, india": (28.5355, 77.3910),
    "singapore, singapore": (1.3521, 103.8198),
    "hong kong, hong kong": (22.3193, 114.1694), "hong kong, china": (22.3193, 114.1694),
    "tokyo, japan": (35.6762, 139.6503),
    "osaka, japan": (34.6937, 135.5023),
    "seoul, south korea": (37.5665, 126.9780), "seoul, korea": (37.5665, 126.9780),
    "taipei, taiwan": (25.0330, 121.5654),
    "beijing, china": (39.9042, 116.4074),
    "shanghai, china": (31.2304, 121.4737),
    "shenzhen, china": (22.5431, 114.0579),
    "hangzhou, china": (30.2741, 120.1551),
    "jakarta, indonesia": (-6.2088, 106.8456),
    "kuala lumpur, malaysia": (3.1390, 101.6869),
    "bangkok, thailand": (13.7563, 100.5018),
    "ho chi minh city, vietnam": (10.8231, 106.6297), "hanoi, vietnam": (21.0278, 105.8342),
    "manila, philippines": (14.5995, 120.9842),
    "sydney, australia": (-33.8688, 151.2093),
    "melbourne, australia": (-37.8136, 144.9631),
    "brisbane, australia": (-27.4698, 153.0251),
    "auckland, new zealand": (-36.8509, 174.7645),
    "wellington, new zealand": (-41.2865, 174.7762),
}

# Unambiguous bare-city aliases (checked only when no "city, country" key hits).
CITY_ALIASES: dict[str, str] = {
    "san francisco": "san francisco, usa", "new york": "new york, usa", "nyc": "new york, usa",
    "new york city": "new york, usa", "rochester": "rochester, usa",
    "los angeles": "los angeles, usa", "palo alto": "palo alto, usa", "mountain view": "mountain view, usa",
    "seattle": "seattle, usa", "boston": "boston, usa", "austin": "austin, usa", "chicago": "chicago, usa",
    "denver": "denver, usa", "miami": "miami, usa", "atlanta": "atlanta, usa", "dallas": "dallas, usa",
    "houston": "houston, usa", "toronto": "toronto, canada", "vancouver": "vancouver, canada",
    "montreal": "montreal, canada", "waterloo": "waterloo, canada", "mexico city": "mexico city, mexico",
    "são paulo": "são paulo, brazil", "sao paulo": "sao paulo, brazil", "bogotá": "bogotá, colombia",
    "buenos aires": "buenos aires, argentina", "santiago": "santiago, chile",
    "london": "london, united kingdom", "berlin": "berlin, germany", "munich": "munich, germany",
    "hamburg": "hamburg, germany", "paris": "paris, france", "amsterdam": "amsterdam, netherlands",
    "zurich": "zurich, switzerland", "zürich": "zurich, switzerland", "geneva": "geneva, switzerland",
    "stockholm": "stockholm, sweden", "copenhagen": "copenhagen, denmark", "oslo": "oslo, norway",
    "helsinki": "helsinki, finland", "dublin": "dublin, ireland", "madrid": "madrid, spain",
    "barcelona": "barcelona, spain", "lisbon": "lisbon, portugal", "milan": "milan, italy",
    "rome": "rome, italy", "vienna": "vienna, austria", "brussels": "brussels, belgium",
    "warsaw": "warsaw, poland", "kraków": "kraków, poland", "krakow": "kraków, poland",
    "prague": "prague, czech republic", "budapest": "budapest, hungary", "bucharest": "bucharest, romania",
    "athens": "athens, greece", "tallinn": "tallinn, estonia", "vilnius": "vilnius, lithuania",
    "riga": "riga, latvia", "tel aviv": "tel aviv, israel", "dubai": "dubai, united arab emirates",
    "cairo": "cairo, egypt", "lagos": "lagos, nigeria", "nairobi": "nairobi, kenya",
    "cape town": "cape town, south africa", "bangalore": "bangalore, india", "bengaluru": "bengaluru, india",
    "mumbai": "mumbai, india", "delhi": "delhi, india", "hyderabad": "hyderabad, india",
    "gurgaon": "gurgaon, india", "singapore": "singapore, singapore", "hong kong": "hong kong, hong kong",
    "tokyo": "tokyo, japan", "seoul": "seoul, south korea", "taipei": "taipei, taiwan",
    "beijing": "beijing, china", "shanghai": "shanghai, china", "shenzhen": "shenzhen, china",
    "jakarta": "jakarta, indonesia", "bangkok": "bangkok, thailand", "sydney": "sydney, australia",
    "melbourne": "melbourne, australia", "auckland": "auckland, new zealand",
}

COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "usa": (39.8283, -98.5795), "united states": (39.8283, -98.5795), "us": (39.8283, -98.5795),
    "united states of america": (39.8283, -98.5795), "canada": (56.1304, -106.3468),
    "mexico": (23.6345, -102.5528), "brazil": (-14.2350, -51.9253), "argentina": (-38.4161, -63.6167),
    "colombia": (4.5709, -74.2973), "chile": (-35.6751, -71.5430), "peru": (-9.1900, -75.0152),
    "united kingdom": (55.3781, -3.4360), "uk": (55.3781, -3.4360), "great britain": (55.3781, -3.4360),
    "england": (52.3555, -1.1743), "germany": (51.1657, 10.4515), "france": (46.2276, 2.2137),
    "netherlands": (52.1326, 5.2913), "switzerland": (46.8182, 8.2275), "sweden": (60.1282, 18.6435),
    "norway": (60.4720, 8.4689), "denmark": (56.2639, 9.5018), "finland": (61.9241, 25.7482),
    "ireland": (53.4129, -8.2439), "spain": (40.4637, -3.7492), "portugal": (39.3999, -8.2245),
    "italy": (41.8719, 12.5674), "austria": (47.5162, 14.5501), "belgium": (50.5039, 4.4699),
    "luxembourg": (49.8153, 6.1296), "poland": (51.9194, 19.1451), "czech republic": (49.8175, 15.4730),
    "czechia": (49.8175, 15.4730), "slovakia": (48.6690, 19.6990), "hungary": (47.1625, 19.5033),
    "romania": (45.9432, 24.9668), "bulgaria": (42.7339, 25.4858), "greece": (39.0742, 21.8243),
    "estonia": (58.5953, 25.0136), "latvia": (56.8796, 24.6032), "lithuania": (55.1694, 23.8813),
    "croatia": (45.1000, 15.2000), "slovenia": (46.1512, 14.9955), "iceland": (64.9631, -19.0208),
    "israel": (31.0461, 34.8516), "jordan": (30.5852, 36.2384), "united arab emirates": (23.4241, 53.8478), "uae": (23.4241, 53.8478),
    "saudi arabia": (23.8859, 45.0792), "qatar": (25.3548, 51.1839), "egypt": (26.8206, 30.8025),
    "nigeria": (9.0820, 8.6753), "kenya": (-0.0236, 37.9062), "south africa": (-30.5595, 22.9375),
    "ghana": (7.9465, -1.0232), "morocco": (31.7917, -7.0926),
    "india": (20.5937, 78.9629), "singapore": (1.3521, 103.8198), "hong kong": (22.3193, 114.1694),
    "japan": (36.2048, 138.2529), "south korea": (35.9078, 127.7669), "korea": (35.9078, 127.7669),
    "taiwan": (23.6978, 120.9605), "china": (35.8617, 104.1954), "indonesia": (-0.7893, 113.9213),
    "malaysia": (4.2105, 101.9758), "thailand": (15.8700, 100.9925), "vietnam": (14.0583, 108.2772),
    "philippines": (12.8797, 121.7740), "australia": (-25.2744, 133.7751), "new zealand": (-40.9006, 174.8860),
}

# Locations that are deliberately not mappable: they describe no place.
_UNMAPPABLE = {
    "remote", "remote (global)", "global", "worldwide", "anywhere", "distributed",
    "remote - global", "multiple locations", "various", "n/a", "unknown", "",
    "hybrid", "onsite", "on-site", "flexible",
}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def geocode_location(locations: str | None) -> GeocodeResult | None:
    """Resolve a free-text location to coordinates with an honesty label.

    City keys are tried first (full string, then first+last segment, then a
    bare-city alias); the country centroid is the declared fallback. Remote or
    unplaceable text returns ``None`` — the map counts these openly instead of
    inventing a point.
    """

    if not locations:
        return None
    text = _normalize(locations.replace(";", ",").replace("•", ",").replace("|", ","))
    if text in _UNMAPPABLE or text.startswith("remote"):
        return None

    segments = [segment.strip(" .") for segment in text.split(",") if segment.strip(" .")]
    # A trailing "remote" segment describes no place; drop it before matching.
    segments = [segment for segment in segments if segment != "remote"] or segments
    candidates = [", ".join(segments)] if segments else [text]
    if len(segments) >= 2:
        candidates.append(f"{segments[0]}, {segments[-1]}")
        if len(segments) >= 3:
            candidates.append(f"{segments[0]}, {segments[-2]}")
    for key in candidates:
        if key in CITY_COORDINATES:
            latitude, longitude = CITY_COORDINATES[key]
            return GeocodeResult(latitude=latitude, longitude=longitude, precision="city", label=segments[0].title())
    alias = CITY_ALIASES.get(segments[0])
    if alias and alias in CITY_COORDINATES:
        latitude, longitude = CITY_COORDINATES[alias]
        return GeocodeResult(latitude=latitude, longitude=longitude, precision="city", label=segments[0].title())

    country_keys = [segments[-1]] if segments else []
    if len(segments) >= 2:
        country_keys.append(text)
    for key in country_keys:
        if key in COUNTRY_CENTROIDS:
            latitude, longitude = COUNTRY_CENTROIDS[key]
            return GeocodeResult(latitude=latitude, longitude=longitude, precision="country", label=segments[-1].title())
    return None
