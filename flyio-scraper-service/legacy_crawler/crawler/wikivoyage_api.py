"""
Wikivoyage & Wikipedia Crawler — dual-mode entrypoint.

Mode 1 (raw crawl, called from main.py via source_cfg):
  Returns [{title, url, html}] pages for the modular pipeline.

Mode 2 (Crawler v2 standalone, called with no args):
  Fetches structured listings for 27 Indian cities, enriches via
  Wikipedia GeoSearch + Wikidata, and writes:
    output/listings.jsonl, output/chunks.jsonl, output/dead_letter.jsonl
"""
import os
import re
import json
import math
import hashlib
import requests
import mwparserfromhell
import sys
import time
import random
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

# Ensure parent directory is in sys.path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    WIKIVOYAGE_CITIES,
    USER_AGENT,
    REQUEST_TIMEOUT,
    OUTPUT_DIR,
    RAW_CACHE_DIR,
    REQUEST_DELAY_SECONDS,
    REQUEST_DELAY_JITTER,
    USER_AGENTS
)

# Category default visit durations (documented heuristics)
CATEGORY_DURATIONS = {
    "historical": 2.5,
    "nature": 3.0,
    "adventure": 3.0,
    "food": 1.5,
    "shopping": 2.0,
    "relaxation": 2.0,
    "hotels": 0.0
}

def cached_api_get(url: str, params: dict, headers: dict = None, timeout: int = 15) -> dict:
    """
    Play 1: Content-addressable raw response cache.
    Saves and loads raw API payloads to raw_cache/<key>.json to avoid network round-trips.
    """
    if headers is None:
        headers = {"User-Agent": USER_AGENT}
    else:
        headers = dict(headers)
        if "User-Agent" not in headers:
            headers["User-Agent"] = USER_AGENT

    # Compute content key
    param_str = json.dumps(params, sort_keys=True)
    key_input = f"{url}||{param_str}"
    key = hashlib.sha256(key_input.encode('utf-8')).hexdigest()

    # Resolve cache path
    repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(repo_dir, "travel_pipeline", RAW_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{key}.json")

    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # Call network
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    # Save cache
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data

WIKIDATA_LABEL_CACHE = {
    "Q4989906": "monument",
    "Q8567": "temple",
    "Q12555507": "palace",
    "Q23442": "fort",
    "Q32900": "mosque",
    "Q48310": "museum",
    "Q570": "park",
    "Q18763": "lake",
    "Q4022": "river",
    "Q49437": "bridge",
    "Q515097": "waterfall",
    "Q105869408": "tourist attraction",
    "Q54065": "Rajput architecture",
    "Q9259": "UNESCO World Heritage Site",
    "Q10967": "Hindu temple",
    "Q34627": "synagogue",
    "Q2222718": "palace of Jaipur",
    "Q112112695": "embassy",
    "Q24033715": "diplomatic mission",
    "Q16247328": "park",
    "Q108439897": "dam",
    "Q7285820": "legislature building",
    "Q7428548": "stadium"
}

def resolve_wikidata_label(qid: str) -> str:
    """Resolves label for a Wikidata ID, using local cache or API call."""
    if qid in WIKIDATA_LABEL_CACHE:
        return WIKIDATA_LABEL_CACHE[qid]
    
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "format": "json",
        "props": "labels",
        "languages": "en"
    }
    try:
        data = cached_api_get("https://www.wikidata.org/w/api.php", params, timeout=10)
        entity = data.get("entities", {}).get(qid, {})
        label = entity.get("labels", {}).get("en", {}).get("value")
        if label:
            WIKIDATA_LABEL_CACHE[qid] = label
            return label
    except Exception as e:
        print(f"    [Wikidata Label Error] {qid}: {e}")
    return qid

def get_wikidata_claims(qid: str) -> dict:
    """
    Task 7.1: Fetches Wikidata claims (P31, P149, P1435, P571, P18, P625) for the given QID.
    """
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "format": "json",
        "props": "claims"
    }
    claims_dict = {
        "instance_of": [],
        "architectural_style": [],
        "heritage_designation": [],
        "inception": None,
        "image_url": None,
        "latitude": None,
        "longitude": None
    }
    try:
        data = cached_api_get("https://www.wikidata.org/w/api.php", params, timeout=10)
        entity = data.get("entities", {}).get(qid, {})
        claims = entity.get("claims", {})
        
        # P625 (coordinate location)
        p625 = claims.get("P625", [])
        if p625:
            mainsnak = p625[0].get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "latitude" in value and "longitude" in value:
                claims_dict["latitude"] = float(value["latitude"])
                claims_dict["longitude"] = float(value["longitude"])
                
        # P31 (instance of)
        p31 = claims.get("P31", [])
        for c in p31:
            mainsnak = c.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "id" in value:
                label = resolve_wikidata_label(value["id"])
                claims_dict["instance_of"].append(label)
                
        # P149 (architectural style)
        p149 = claims.get("P149", [])
        for c in p149:
            mainsnak = c.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "id" in value:
                label = resolve_wikidata_label(value["id"])
                claims_dict["architectural_style"].append(label)
                
        # P1435 (heritage designation)
        p1435 = claims.get("P1435", [])
        for c in p1435:
            mainsnak = c.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "id" in value:
                label = resolve_wikidata_label(value["id"])
                claims_dict["heritage_designation"].append(label)
                
        # P571 (inception)
        p571 = claims.get("P571", [])
        if p571:
            mainsnak = p571[0].get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and "time" in value:
                t = value["time"]
                match = re.search(r'\+?(-?\d+)', t)
                if match:
                    claims_dict["inception"] = match.group(1).lstrip('0') or '0'
                    
        # P18 (image)
        p18 = claims.get("P18", [])
        if p18:
            mainsnak = p18[0].get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            image_name = datavalue.get("value", "")
            if image_name:
                name = image_name.replace(" ", "_")
                m = hashlib.md5(name.encode('utf-8')).hexdigest()
                claims_dict["image_url"] = f"https://upload.wikimedia.org/wikipedia/commons/{m[0]}/{m[:2]}/{name}"
                
    except Exception as e:
        print(f"    [Wikidata Claims Error] {qid}: {e}")
        
    return claims_dict

def fetch_wikipedia_qid(title: str) -> str | None:
    """Task 7.1: Fetches Wikidata QID for a given Wikipedia page title."""
    params = {
        "action": "query",
        "prop": "pageprops",
        "titles": title,
        "format": "json",
        "redirects": 1
    }
    try:
        data = cached_api_get("https://en.wikipedia.org/w/api.php", params, timeout=10)
        pages = data.get("query", {}).get("pages", {})
        for pid, pdata in pages.items():
            if pid != "-1" and "pageprops" in pdata:
                return pdata["pageprops"].get("wikibase_item")
    except Exception as e:
        print(f"    [Wikipedia QID Error] {title}: {e}")
    return None

def _fetch_page(api_base: str, title: str) -> dict | None:
    """
    Raw page fetch for Mode 1 (called from crawl_wikivoyage with source_cfg).
    Returns {title, url, html, links} for the modular pipeline.
    """
    _SKIP_TITLE_PREFIXES = ("Wikivoyage:", "Talk:", "User:", "Wikipedia:", "File:",
                            "Template:", "Help:", "Category:", "Portal:")
    params = {
        "action": "parse",
        "page": title,
        "format": "json",
        "prop": "text|links|displaytitle",
        "redirects": 1
    }
    try:
        data = cached_api_get(api_base, params, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        print(f"  [fetch error] {title}: {e}")
        return None

    if "error" in data:
        print(f"  [page missing] {title}: {data['error'].get('info', '')}")
        return None

    parsed = data["parse"]
    links = [
        l["*"] for l in parsed.get("links", [])
        if l.get("ns") == 0 and not l["*"].startswith(_SKIP_TITLE_PREFIXES)
    ]
    return {
        "title": BeautifulSoup(parsed.get("displaytitle", title), "lxml").get_text(" ", strip=True),
        "url": api_base.replace("/w/api.php", f"/wiki/{title.replace(' ', '_')}"),
        "html": parsed["text"]["*"],
        "links": links,
    }

def fetch_page_coordinates(title: str) -> tuple[float, float] | None:
    """Fetches latitude/longitude coordinates for a Wikivoyage/Wikipedia title."""
    params = {
        "action": "query",
        "prop": "coordinates",
        "titles": title,
        "format": "json",
        "redirects": 1
    }
    try:
        data = cached_api_get("https://en.wikivoyage.org/w/api.php", params, timeout=10)
        pages = data.get("query", {}).get("pages", {})
        for pid, pdata in pages.items():
            if pid != "-1" and "coordinates" in pdata:
                coords = pdata["coordinates"][0]
                return float(coords["lat"]), float(coords["lon"])
    except Exception as e:
        print(f"    [Coordinates Error] {title}: {e}")
    return None


def fetch_wikivoyage_page(title: str) -> dict | None:
    """
    Task 2.2: Fetch wikitext and HTML text in a single API call.
    """
    params = {
        "action": "parse",
        "page": title,
        "format": "json",
        "prop": "text|wikitext|displaytitle",
        "redirects": 1
    }
    try:
        data = cached_api_get("https://en.wikivoyage.org/w/api.php", params, timeout=REQUEST_TIMEOUT)
        if "error" in data:
            print(f"  [Wikivoyage Page Missing] {title}: {data['error'].get('info', '')}")
            return None
        parsed = data["parse"]
        return {
            "title": parsed.get("title", title),
            "html": parsed["text"]["*"],
            "wikitext": parsed["wikitext"]["*"],
            "url": f"https://en.wikivoyage.org/wiki/{title.replace(' ', '_')}"
        }
    except Exception as e:
        print(f"  [Wikivoyage Fetch Error] {title}: {e}")
        return None

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    R = 6371.0  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def normalize_title(text: str) -> str:
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'[^\w\s]', '', text).lower()
    return " ".join(text.split())

def is_confident_wikipedia_match(
    candidate_title: str,
    poi_name: str,
    poi_lat: float = None,
    poi_lon: float = None,
    cand_lat: float = None,
    cand_lon: float = None
) -> bool:
    """
    Task 2.7: Verifies that a candidate Wikipedia article reasonably matches the POI listing name
    and is located within a valid geographical radius (<= 15km).
    """
    norm_cand = normalize_title(candidate_title)
    norm_poi = normalize_title(poi_name)

    # 1. String ratio similarity check
    sim = SequenceMatcher(None, norm_poi, norm_cand).ratio()
    
    # 2. Token overlap check
    stop_words = {"the", "and", "for", "in", "at", "of", "a", "an", "is", "to", "by", "with", "hotel", "resort", "restaurant", "cafe", "lounge", "bar"}
    poi_tokens = [w for w in norm_poi.split() if w not in stop_words and len(w) >= 3]
    cand_tokens = [w for w in norm_cand.split() if w not in stop_words and len(w) >= 3]
    
    token_match = False
    if poi_tokens and cand_tokens:
        common = set(poi_tokens).intersection(set(cand_tokens))
        if len(common) > 0 and (len(common) / len(poi_tokens) >= 0.5 or len(common) / len(cand_tokens) >= 0.5):
            token_match = True

    title_match = (sim >= 0.6) or token_match

    # 3. Distance check if candidate coordinates exist
    dist_ok = True
    if poi_lat is not None and poi_lon is not None and cand_lat is not None and cand_lon is not None:
        dist_km = haversine_distance(poi_lat, poi_lon, cand_lat, cand_lon)
        if dist_km is not None and dist_km > 15.0:  # Reject if candidate is >15km away
            dist_ok = False

    return title_match and dist_ok

def fetch_wikipedia_extract_details(title: str) -> dict | None:
    """
    Task 2.7: Target Wikipedia Extracts API returning extract and optional coordinates.
    """
    params = {
        "action": "query",
        "prop": "extracts|coordinates",
        "exintro": 1,
        "explaintext": 1,
        "titles": title,
        "format": "json",
        "redirects": 1
    }
    try:
        data = cached_api_get("https://en.wikipedia.org/w/api.php", params, timeout=10)
        pages = data.get("query", {}).get("pages", {})
        for pid, pdata in pages.items():
            if pid != "-1" and "extract" in pdata:
                extract = pdata["extract"].strip()
                coords_list = pdata.get("coordinates", [])
                cand_lat = coords_list[0].get("lat") if coords_list else None
                cand_lon = coords_list[0].get("lon") if coords_list else None
                return {
                    "title": pdata.get("title", title),
                    "extract": extract,
                    "latitude": cand_lat,
                    "longitude": cand_lon
                }
    except Exception as e:
        print(f"    [Wikipedia Extract Error] {title}: {e}")
    return None

def fetch_wikipedia_extract(title: str) -> str | None:
    """
    Legacy wrapper for fetch_wikipedia_extract_details.
    """
    details = fetch_wikipedia_extract_details(title)
    return details["extract"] if details else None

def search_wikipedia_by_name(poi_name: str, city_name: str, poi_lat: float = None, poi_lon: float = None) -> str | None:
    """
    Task 2.7: Searches Wikipedia by POI name + City to locate extract with confidence validation.
    """
    query_str = f"{poi_name} {city_name}"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query_str,
        "format": "json",
        "srlimit": 5
    }
    try:
        data = cached_api_get("https://en.wikipedia.org/w/api.php", params, timeout=10)
        search_results = data.get("query", {}).get("search", [])
        for hit in search_results:
            cand_title = hit.get("title")
            if not cand_title:
                continue
            
            details = fetch_wikipedia_extract_details(cand_title)
            if not details or not details.get("extract"):
                continue

            if is_confident_wikipedia_match(
                cand_title,
                poi_name,
                poi_lat=poi_lat,
                poi_lon=poi_lon,
                cand_lat=details.get("latitude"),
                cand_lon=details.get("longitude")
            ):
                return details["extract"]
    except Exception as e:
        print(f"    [Wikipedia Search Error] {poi_name}: {e}")
    return None

def wikipedia_geosearch(lat: float, lon: float, radius_meters: int = 10000) -> list[dict]:
    """
    Task 2.8: Wikipedia GeoSearch to fill coverage gaps.
    """
    params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": radius_meters,
        "gslimit": 25,
        "format": "json"
    }
    try:
        data = cached_api_get("https://en.wikipedia.org/w/api.php", params, timeout=10)
        hits = data.get("query", {}).get("geosearch", [])
        return [{
            "title": h["title"],
            "latitude": h["lat"],
            "longitude": h["lon"],
            "pageid": h["pageid"]
        } for h in hits]
    except Exception as e:
        print(f"    [Wikipedia GeoSearch Error] {lat},{lon}: {e}")
        return []

def parse_listings(wikitext: str, city_name: str, source_url: str) -> list[dict]:
    """
    Task 2.3 - 2.6: Parse listings templates using mwparserfromhell.
    Supports see, do, buy, eat, drink, sleep, listing templates.
    """
    parsed = mwparserfromhell.parse(wikitext)
    listings = []
    target_templates = {"see", "do", "buy", "eat", "drink", "sleep", "listing"}

    for template in parsed.filter_templates():
        tname = template.name.strip().lower()
        if tname not in target_templates:
            continue

        # Convert parameters to dictionary
        params = {}
        for p in template.params:
            p_name = p.name.strip().lower()
            p_val = p.value.strip()
            params[p_name] = p_val

        name = params.get("name", "").strip()
        if not name:
            continue

        # Task 2.4: Parse Price -> INR
        raw_price = params.get("price", "").strip()
        price_inr = None
        if raw_price:
            match = re.search(r'₹\s*([\d,]+)', raw_price)
            if match:
                try:
                    price_inr = int(match.group(1).replace(",", ""))
                except Exception:
                    pass

        # Task 2.5: Category from listing type
        category = "relaxation"
        if tname == "buy":
            category = "shopping"
        elif tname in ("eat", "drink"):
            category = "food"
        elif tname == "sleep":
            category = "hotels"
        elif tname == "see":
            name_lower = name.lower()
            if any(k in name_lower for k in ["fort", "palace", "museum", "temple", "tomb", "mosque", "monument", "ruins", "church", "cathedral", "kila"]):
                category = "historical"
            elif any(k in name_lower for k in ["lake", "park", "beach", "waterfall", "wildlife", "sanctuary", "valley", "viewpoint", "hill", "garden", "backwaters"]):
                category = "nature"
            else:
                category = "historical"
        elif tname == "do":
            name_lower = name.lower()
            if any(k in name_lower for k in ["trek", "hike", "rafting", "climb", "safari", "ride", "sport", "adventure", "camp"]):
                category = "adventure"
            else:
                category = "relaxation"

        # Task 2.6: Duration Heuristic
        duration_hrs = CATEGORY_DURATIONS.get(category, 2.0)
        if category == "historical":
            if any(k in name.lower() for k in ["temple", "church", "mosque", "gurudwara"]):
                duration_hrs = 1.0
            elif "museum" in name.lower() or "gallery" in name.lower():
                duration_hrs = 1.5
            else:
                duration_hrs = 2.5

        # Coordinates parsing
        lat = None
        lon = None
        try:
            if "lat" in params and params["lat"]:
                lat = float(params["lat"])
            if "long" in params and params["long"]:
                lon = float(params["long"])
        except ValueError:
            pass

        qid = params.get("wikidata", "").strip()
        wikipedia_title = params.get("wikipedia", "").strip()

        wikidata_claims = None
        if qid.startswith("Q"):
            wikidata_claims = get_wikidata_claims(qid)
            # Task 2.3 Coordinate Backfilling from Wikidata Q-ID
            if (lat is None or lon is None):
                if wikidata_claims["latitude"] is not None and wikidata_claims["longitude"] is not None:
                    lat = wikidata_claims["latitude"]
                    lon = wikidata_claims["longitude"]

        description = params.get("description", "").strip()

        listings.append({
            "name": name,
            "city": city_name,
            "type": tname,
            "category": category,
            "duration_hrs": duration_hrs,
            "price_inr": price_inr,
            "raw_price": raw_price,
            "latitude": lat,
            "longitude": lon,
            "wikidata": qid if qid.startswith("Q") else None,
            "wikidata_claims": wikidata_claims,
            "wikipedia": wikipedia_title or None,
            "description": description,
            "source_url": f"{source_url}#{tname}_{name.replace(' ', '_')}"
        })

    return listings

def infer_category_from_text(title: str, text: str) -> str:
    """Helper to guess category for GeoSearch hits based on text content."""
    text_to_match = f"{title} {text}".lower()
    if any(k in text_to_match for k in ["fort", "palace", "museum", "temple", "tomb", "mosque", "monument", "ruins", "history", "ancient"]):
        return "historical"
    elif any(k in text_to_match for k in ["lake", "park", "beach", "waterfall", "wildlife", "sanctuary", "valley", "viewpoint", "hill", "garden"]):
        return "nature"
    elif any(k in text_to_match for k in ["trek", "climb", "hike", "adventure", "rafting", "safari", "sport"]):
        return "adventure"
    elif any(k in text_to_match for k in ["shop", "market", "bazaar", "mall"]):
        return "shopping"
    elif any(k in text_to_match for k in ["food", "eat", "restaurant", "dining"]):
        return "food"
    return "relaxation"

def process_city(city_name: str, listings_out: list, chunks_out: list, dead_letter_out: list):
    """
    Crawls and enriches a single city's POIs.
    """
    print(f"\nProcessing city: {city_name}")
    city_coords = fetch_page_coordinates(city_name)
    
    page = fetch_wikivoyage_page(city_name)
    if not page:
        return

    # Parse Wikivoyage listings
    listings = parse_listings(page["wikitext"], city_name, page["url"])
    print(f"  Found {len(listings)} listings in Wikivoyage wikitext")

    valid_poi_count = 0
    seen_names = set()

    for item in listings:
        name = item["name"]
        seen_names.add(name.lower())

        # Task 8 Play 4 Quality Gate: Reject if coordinates are missing
        if item["latitude"] is None or item["longitude"] is None:
            dead_letter_out.append(item)
            continue

        # Task 8 Play 4 Bounding Bounding distance-to-centroid check
        if city_coords:
            c_lat, c_lon = city_coords
            dist_km = 111.0 * (((item["latitude"] - c_lat) ** 2) + ((item["longitude"] - c_lon) ** 2)) ** 0.5
            if dist_km > 60.0:  # Allow 60km radius from city centroid
                print(f"    [Quality Gate Rejected] {name} is off-center ({dist_km:.1f}km from {city_name} centroid). Sending to dead-letter.")
                dead_letter_out.append(item)
                continue

        # Task 2.7: Wikipedia Enrichment with Strict Confidence Verification
        wiki_extract = None
        if item["wikipedia"]:
            details = fetch_wikipedia_extract_details(item["wikipedia"])
            if details and details.get("extract"):
                if is_confident_wikipedia_match(
                    details.get("title", item["wikipedia"]),
                    name,
                    poi_lat=item["latitude"],
                    poi_lon=item["longitude"],
                    cand_lat=details.get("latitude"),
                    cand_lon=details.get("longitude")
                ):
                    wiki_extract = details["extract"]
                else:
                    print(f"    [Wikipedia Enrichment Rejected] Explicit title '{item['wikipedia']}' failed confidence check for POI '{name}'")

        if not wiki_extract:
            # Fallback to search by name with strict confidence matching
            wiki_extract = search_wikipedia_by_name(name, city_name, poi_lat=item["latitude"], poi_lon=item["longitude"])

        # Build full narrative (One POI per chunk)
        narrative_parts = []
        if item["description"]:
            narrative_parts.append(item["description"])
        if wiki_extract:
            narrative_parts.append(wiki_extract)

        # Quality check: ensure we have some text content
        full_narrative = "\n\n".join(narrative_parts).strip()
        if not full_narrative:
            full_narrative = f"{name} is an attraction located in {city_name}."

        # Add listing
        listings_out.append(item)
        valid_poi_count += 1

        # Add chunk (exactly one POI per chunk)
        chunks_out.append({
            "name": name,
            "city": city_name,
            "wikidata": item["wikidata"],
            "content_text": full_narrative,
            "source_url": item["source_url"]
        })

    # Task 2.8: Wikipedia GeoSearch for coverage gaps (if < 10 POIs found)
    if valid_poi_count < 10 and city_coords:
        c_lat, c_lon = city_coords
        print(f"  Coverage gap detected for {city_name} ({valid_poi_count} POIs). Initiating Wikipedia GeoSearch...")
        geo_hits = wikipedia_geosearch(c_lat, c_lon)
        
        added_from_geo = 0
        for hit in geo_hits:
            hit_name = hit["title"]
            if hit_name.lower() in seen_names:
                continue
            
            # Fetch extract
            extract = fetch_wikipedia_extract(hit_name)
            if not extract:
                continue

            # Determine category
            category = infer_category_from_text(hit_name, extract)
            if category == "hotels":
                continue  # GeoSearch shouldn't find generic hotels easily

            duration_hrs = CATEGORY_DURATIONS.get(category, 2.0)
            
            # Resolve Q-ID and claims for GeoSearch hits
            qid = fetch_wikipedia_qid(hit_name)
            wikidata_claims = None
            if qid:
                wikidata_claims = get_wikidata_claims(qid)

            # Generate listing
            item = {
                "name": hit_name,
                "city": city_name,
                "type": "see",
                "category": category,
                "duration_hrs": duration_hrs,
                "price_inr": None,
                "raw_price": "",
                "latitude": hit["latitude"],
                "longitude": hit["longitude"],
                "wikidata": qid,
                "wikidata_claims": wikidata_claims,
                "wikipedia": hit_name,
                "description": "",
                "source_url": f"https://en.wikipedia.org/wiki/{hit_name.replace(' ', '_')}"
            }
            
            listings_out.append(item)
            seen_names.add(hit_name.lower())
            added_from_geo += 1

            chunks_out.append({
                "name": hit_name,
                "city": city_name,
                "wikidata": qid,
                "wikidata_claims": wikidata_claims,
                "content_text": extract,
                "source_url": item["source_url"]
            })

            if (valid_poi_count + added_from_geo) >= 15:
                break
                
        print(f"  GeoSearch added {added_from_geo} extra POIs for {city_name}")

def crawl_wikivoyage(source_cfg: dict = None) -> list:
    """
    Dual-mode entrypoint:
    1. If source_cfg is provided (and has seed_titles & api_base), runs the raw page crawl
       (from travel-pipeline-v2 branch) and returns raw_pages.
    2. If source_cfg is None (standalone CLI run), runs the full Crawler v2 flow
       (from origin/main branch) and returns compatibility all_chunks.
    """
    if source_cfg is not None and "seed_titles" in source_cfg and "api_base" in source_cfg:
        # --- Raw Page Crawl Mode (travel-pipeline-v2 logic) ---
        api_base  = source_cfg["api_base"]
        max_pages = source_cfg.get("max_pages", 25)
        queue     = list(source_cfg["seed_titles"])
        visited   = set()
        results   = []

        while queue and len(results) < max_pages:
            title = queue.pop(0)
            if title in visited:
                continue
            visited.add(title)

            print(f"  [{len(results)+1}/{max_pages}] fetching wikivoyage: {title}")
            page = _fetch_page(api_base, title)
            time.sleep(REQUEST_DELAY_SECONDS + random.uniform(0, REQUEST_DELAY_JITTER))

            if not page:
                continue

            results.append({"title": page["title"], "url": page["url"], "html": page["html"]})

            for link_title in page["links"][:10]:
                if link_title not in visited:
                    queue.append(link_title)

        print(f"  Done: {len(results)} pages collected from Wikivoyage")
        return results

    else:
        # --- Standalone Crawler v2 Flow (origin/main logic) ---
        repo_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        out_dir = os.path.join(repo_dir, "travel_pipeline", OUTPUT_DIR)
        os.makedirs(out_dir, exist_ok=True)

        listings_out = []
        chunks_out = []
        dead_letter_out = []

        print("==========================================")
        print("Starting Crawler v2 (Official MediaWiki APIs)")
        print("==========================================")

        for city in WIKIVOYAGE_CITIES:
            try:
                process_city(city, listings_out, chunks_out, dead_letter_out)
            except Exception as e:
                print(f"  [ERROR] Processing {city} failed: {e}")

        # Output listings.jsonl
        listings_path = os.path.join(out_dir, "listings.jsonl")
        with open(listings_path, 'w', encoding='utf-8') as f:
            for item in listings_out:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Output chunks.jsonl
        chunks_path = os.path.join(out_dir, "chunks.jsonl")
        with open(chunks_path, 'w', encoding='utf-8') as f:
            for item in chunks_out:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Output dead_letter.jsonl
        dead_letter_path = os.path.join(out_dir, "dead_letter.jsonl")
        with open(dead_letter_path, 'w', encoding='utf-8') as f:
            for item in dead_letter_out:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Output compatibility all_chunks.json for downstream imports
        all_chunks_compat = []
        for chunk in chunks_out:
            all_chunks_compat.append({
                "page_title": chunk["city"],
                "content_text": chunk["content_text"],
                "section_path": chunk["name"]
            })
        all_chunks_path = os.path.join(out_dir, "all_chunks.json")
        with open(all_chunks_path, 'w', encoding='utf-8') as f:
            json.dump(all_chunks_compat, f, ensure_ascii=False, indent=2)

        # Print summary statistics
        print("\n==========================================")
        print("Crawler v2 Pipeline Complete")
        print("==========================================")
        print(f"  Total Valid POIs Discovered: {len(listings_out)}")
        print(f"  Total Narrative Chunks Generated: {len(chunks_out)}")
        print(f"  Total Rejected POIs (Dead-Letter): {len(dead_letter_out)}")
        print(f"  Saved listings to: {listings_path}")
        print(f"  Saved chunks to: {chunks_path}")
        print(f"  Saved dead-letter entries to: {dead_letter_path}")
        print(f"  Saved compatibility all_chunks.json to: {all_chunks_path}")
        print("==========================================\n")

        return all_chunks_compat

if __name__ == "__main__":
    crawl_wikivoyage()
