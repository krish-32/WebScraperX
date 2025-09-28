import os
from dotenv import load_dotenv
import requests
import json
import logging
import argparse
import re
import html as html_lib
from typing import List, Dict, Any, Optional
import time
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from bs4 import BeautifulSoup
from postal.parser import parse_address

load_dotenv(dotenv_path='../.env')

API_KEY = os.getenv("MY_KEY")
GEO_MAP_API = os.getenv("GEO_MAP_API")



TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid"}

SOCIAL_DOMAINS = {
    "facebook": ("facebook.com",),
    "instagram": ("instagram.com",),
    "twitter": ("twitter.com", "x.com"),
    "tiktok": ("tiktok.com",),
    "linkedin": ("linkedin.com",),
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?60|0)\s?(?:\d[\s-]?){7,10}")  # Malaysia-leaning heuristic
ZIP_RE = re.compile(r"\b\d{5}\b")
WHATSAPP_RE = re.compile(r"https?://(wa\.me|api\.whatsapp\.com|chat\.whatsapp\.com)/[\w/?=&%-]+", re.I)


# -------------------------------
# Helper functions (keep existing)
# -------------------------------


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL to improve deduplication.

    - Lowercase hostname
    - Remove fragments
    - Remove common tracking query params (utm_*, gclid, fbclid, ...)
    - Sort remaining query params
    - Normalize trailing slash (keep root '/', strip trailing slash from paths)
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        #print(parsed,url)
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Filter query params
        q = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if k in TRACKING_QUERY_KEYS:
                continue
            if any(k.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
                continue
            q.append((k, v))
        q.sort(key=lambda kv: kv[0])
        query = urlencode(q, doseq=True)

        normalized = urlunparse((parsed.scheme, netloc, path, "", query, ""))
        #print(normalized)
        return normalized
    except Exception:
        return url

def get_google_search_results(query: str, num_results: int = 11, country: str = "") -> List[Dict[str, Any]]:
    """Fetch Google search results via ScrapingDog with basic retry logic."""
    url = "https://api.scrapingdog.com/google"
    params = {
        "api_key": API_KEY,
        "query": query,
        "results": num_results,
        "country": country,
        "domain": "google.com",
        "advance_search": "true"
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=100)
            response.raise_for_status()
            data = response.json()
            return data.get("organic_results", [])
        except Exception as e:
            logging.warning("Request attempt %d failed: %s", attempt + 1, e)
    
    return []



def get_lat_lng(location_name: str, api_key: str) -> str:
    url = "http://api.openweathermap.org/geo/1.0/direct"
    params = {
        "q": location_name,
        "limit": 1,
        "appid": api_key,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    if data:
        lat = data[0]["lat"]
        lon = data[0]["lon"]
        return f"@{lat},{lon},15z"
    return ""


def get_google_maps_results(query: str, ll: str = "", page: int = 0) -> List[Dict[str, Any]]:
    """Fetch Google Maps search results via ScrapingDog.

    The endpoint returns JSON. Structure may vary; we try common containers.
    """
    if not API_KEY:
        return []
    
    base_url = "https://api.scrapingdog.com/google_maps"
    params = {
        "api_key": API_KEY,
        "query": query,
        "page": page,
        "ll": ll,
    }
    
    #print(page)
    for attempt in range(3):
        try:
            resp = requests.get(base_url, params=params, timeout=100)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if "search_results" in data and isinstance(data["search_results"], list):
                    return data["search_results"]
                if "name" in data or "formatted_address" in data:
                    return [data]
            return []
        except Exception as e:
            logging.warning("Maps request attempt %d failed: %s", attempt + 1, e)
    return []

def get_all_google_maps_results(query: str, ll: str = "", max_pages: int = 10) -> List[Dict[str, Any]]:
    """Fetch multiple pages of Google Maps results by paginating until no more results or max_pages reached."""
    all_results = []
    #print(max_pages)
    for page in range(max_pages):
        results = get_google_maps_results(query, ll, page)
        #print("results",results)
        if results is not None and len(results) > 0:
            #print(f"Fetched {len(results)} results from page {page}")
            latitude = results[0]['gps_coordinates']['latitude']
            longitude = results[0]['gps_coordinates']['longitude']
            
            ll  = f"@{latitude},{longitude},15z"
        # if not results:
        #     break 
        all_results.extend(results)
    return all_results



def clean_business_name(title: Optional[str], url: Optional[str]) -> str:
    """Clean and normalize a business/page title.

    - HTML-unescape entities
    - Remove common site section suffixes after separators (|, -, –)
    - Collapse whitespace
    - Fallback to domain-derived name if too short or generic
    """
    if not title:
        return domain_to_name(url)

    # HTML entities and normalize unicode dashes to hyphen
    t = html_lib.unescape(title)
    t = t.replace("–", "-")

    # Remove common trailing sections after separators (keep left-most as main)
    # e.g., "Acme Care - Home | Best in KL" -> "Acme Care"
    t = re.split(r"\s*[\-|\|]\s*", t)[0]

    # Remove generic words if the whole title is generic
    generic = {"about", "services", "home", "faq", "contact"}
    t_stripped = t.strip()
    if len(t_stripped) < 3 or t_stripped.lower() in generic:
        return domain_to_name(url)

    # Collapse whitespace
    t_norm = re.sub(r"\s+", " ", t_stripped)
    return t_norm

def domain_to_name(url: Optional[str]) -> str:
    try:
        domain = urlparse(url or "").netloc
        domain = domain.replace("www.", "").split(".")[0]
        return domain.replace("-", " ").title()
    except:
        return "Unknown"

def fetch_html_via_scrapingdog(session: requests.Session, target_url: str, dynamic: bool = False, timeout: int = 30) -> Optional[str]:
    """Fetch HTML using ScrapingDog's scrape API."""
    if not API_KEY:
        logging.error("Missing MY_KEY for ScrapingDog API")
        return None
    try:
        params = {
            "api_key": API_KEY,
            "url": target_url,
            'premium': 'true',
            'dynamic': 'true',
        }
        resp = session.get("https://api.scrapingdog.com/scrape", params=params, timeout=timeout)
        if 200 <= resp.status_code < 400 and resp.text:
            return resp.text
        logging.warning("ScrapingDog scrape non-2xx for %s: %s", target_url, resp.status_code)
    except Exception as e:
        logging.debug("ScrapingDog scrape failed for %s: %s", target_url, e)
    return None

def fetch_html_direct(session: requests.Session, url: str, timeout: int = 30) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
    try:
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if 200 <= resp.status_code < 400 and resp.text:
            return resp.text
    except Exception as e:
        logging.debug("Direct fetch failed for %s: %s", url, e)
    return None

SOCIAL_DOMAINS = {
    "facebook": ("facebook.com",),
    "instagram": ("instagram.com",),
    "twitter": ("twitter.com", "x.com"),
    "tiktok": ("tiktok.com",),
    "linkedin": ("linkedin.com",),
}


def extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    data = []
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        try:
            text = tag.string or tag.text
            if not text:
                continue
            obj = json.loads(text)
            if isinstance(obj, list):
                data.extend(obj)
            else:
                data.append(obj)
        except Exception:
            continue
    return data

def first(*vals: Optional[str]) -> Optional[str]:
    for v in vals:
        if v and isinstance(v, str):
            s = v.strip()
            if s:
                return s
    return None

def pick_social_from_sameas(same_as: Any) -> Dict[str, Optional[str]]:
    out = {"facebookurl": None, "instagramurl": None, "twitterurl": None, "tiktokurl": None, "linkedinurl": None}
    if not same_as:
        return out
    links = same_as if isinstance(same_as, list) else [same_as]
    for link in links:
        if not isinstance(link, str):
            continue
        l = link.lower()
        if any(d in l for d in SOCIAL_DOMAINS["facebook"]):
            out["facebookurl"] = link
        elif any(d in l for d in SOCIAL_DOMAINS["instagram"]):
            out["instagramurl"] = link
        elif any(d in l for d in SOCIAL_DOMAINS["twitter"]):
            out["twitterurl"] = link
        elif any(d in l for d in SOCIAL_DOMAINS["tiktok"]):
            out["tiktokurl"] = link
        elif any(d in l for d in SOCIAL_DOMAINS["linkedin"]):
            out["linkedinurl"] = link
    return out

def extract_from_html(url: str, html_text: str) -> Dict[str, Any]:
    
    soup = BeautifulSoup(html_text, "html.parser")
    #print("html",html_text)
    #print("soup",soup)

    # Defaults
    out: Dict[str, Any] = {
        "center_name": None,
        "address": None,
        "city": None,
        "state": None,
        "country": None,
        "zipcode": None,
        "email": None,
        "website": normalize_url(url),
        "websiteurl": None,
        "phone": None,
        "whatsapp": None,
        "facebookurl": None,
        "instagramurl": None,
        "twitterurl": None,
        "tiktokurl": None,
        "linkedinurl": None,
        "services": None,
    }

    # Title as fallback name
    title_text = soup.title.string.strip() if soup.title and soup.title.string else None
    out["center_name"] = clean_business_name(title_text, url)

    # JSON-LD parsing for Organization/LocalBusiness
    ld_list = extract_json_ld(soup)
    #print(ld_list)
   
    for obj in ld_list:
        
        try:
            name = obj.get("name")
            if name and not out["center_name"]:
                out["center_name"] = str(name).strip()

            address = obj.get("address")
            #print("address",address)
            if isinstance(address, dict):
                out["address"] = first(address.get("streetAddress"), address.get("address")) or out["address"]
                out["city"] = first(address.get("addressLocality"), address.get("locality")) or out["city"]
                out["state"] = first(address.get("addressRegion"), address.get("region")) or out["state"]
                out["country"] = first(address.get("addressCountry"),) or out["country"]
                out["zipcode"] = first(address.get("postalCode")) or out["zipcode"]

            # phones/emails
            out["phone"] = first(obj.get("telephone"), obj.get("phone")) or out["phone"]
            
            # website alternates
            out["websiteurl"] = first(obj.get("url")) or out["websiteurl"]

            # social sameAs
            link = obj.get("sameAs")
            email = obj.get("email")
            

            if link is None:
                graphs = obj.get("@graph")
                #print("skkkkk",graphs)
                if graphs is not None:
                    for graph in graphs:
                        type=graph.get("@type")
                        #print("type",type)
                        if type=='Organization':
                            link=graph.get("sameAs")
                            break
                            #print("link2",link)
                        link=graph.get("sameAs")
            if email is None:
                contact_point= obj.get("contactPoint")
                if contact_point is not None:
                    email=contact_point.get("email")
                
                if email is None:
                    graphs = obj.get("@graph")
                    
                    if graphs is not None:
                        for graph in graphs:
                            email=graph.get("email")
                            if email is not None:
                                break

            
            out["email"] = first(email) or out["email"]


            #print(same_as)
            social = pick_social_from_sameas(link)
            for k, v in social.items():
                out[k] = out[k] or v
        except Exception as e:
            print("errr",e)
            continue

    # Heuristic extraction from visible content
    

    # Email
    # print(EMAIL_RE)
    # emails = EMAIL_RE.findall(text)
    # print(emails)
    # if emails:
    #     out["email"] = out["email"] or emails[0]

    # Phone
    # phones = PHONE_RE.findall(text)
    # if phones:
    #     out["phone"] = out["phone"] or phones[0]

    # WhatsApp links
    #print(soup.find_all("a", href=True))
    for a in soup.find_all("a", href=True):
        
        href = a["href"].strip()
        
        if WHATSAPP_RE.search(href):
            
            out["whatsapp"] = out["whatsapp"] or href
        # Social links by domain
        hlow = href.lower()
        if any(d in hlow for d in SOCIAL_DOMAINS["facebook"]):
            out["facebookurl"] = out["facebookurl"] or href
        elif any(d in hlow for d in SOCIAL_DOMAINS["instagram"]):
            out["instagramurl"] = out["instagramurl"] or href
        elif any(d in hlow for d in SOCIAL_DOMAINS["twitter"]):
            out["twitterurl"] = out["twitterurl"] or href
        elif any(d in hlow for d in SOCIAL_DOMAINS["tiktok"]):
            out["tiktokurl"] = out["tiktokurl"] or href
        elif any(d in hlow for d in SOCIAL_DOMAINS["linkedin"]):
            out["linkedinurl"] = out["linkedinurl"] or href

    # Address heuristics: look for elements with address-like classes or itemprop
    addr_candidates: List[str] = []
    # Prefer explicit <address> tags
    for addr_tag in soup.find_all("address"):
        text_val = addr_tag.get_text(" ", strip=True)
        if text_val and len(text_val) > 10:
            addr_candidates.append(text_val)
    # Generic heuristic by class/id/itemprop
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", [])).lower()
        idv = (tag.get("id") or "").lower()
        itemprop = (tag.get("itemprop") or "").lower()
        if any(key in cls for key in ["address", "addr"]) or any(key in idv for key in ["address", "addr"]) or itemprop == "address":
            text_val = tag.get_text(" ", strip=True)
            if text_val and len(text_val) > 10:
                addr_candidates.append(text_val)
    if addr_candidates and not out["address"]:
        out["address"] = addr_candidates[0]

    # Zipcode from address text
    if out["address"] and not out["zipcode"]:
        m = ZIP_RE.search(out["address"])
        if m:
            out["zipcode"] = m.group(0)

    # Services: look for sections headed with 'Services'
    services: List[str] = []
    for header in soup.find_all(["h1", "h2", "h3", "h4" ]):
        htxt = (header.get_text(" ", strip=True) or "").lower()
        if "service" in htxt:
            # Find following list items or paragraphs near this header
            ul = header.find_next(["ul", "ol"])
            if ul:
                for li in ul.find_all("li"):
                    lit = li.get_text(" ", strip=True)
                    if lit and len(lit) > 2:
                        services.append(lit)
            else:
                # Fallback: nearby paragraphs
                for p in header.find_all_next("p", limit=5):
                    pt = p.get_text(" ", strip=True)
                    if pt and len(pt) > 5:
                        services.append(pt)
            if services:
                break
    if services:
        out["services"] = services

    return out

def clean_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate results based on normalized URL."""
    seen = set()
    cleaned: List[Dict[str, Any]] = []
    for r in results:
        url = r.get("link")
        norm = normalize_url(url)
        if norm and norm not in seen:
            seen.add(norm)
            cleaned.append(r)
    return cleaned

def filter_relevant(results: List[Dict[str, Any]], keywords: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Filter results by presence of any keyword in title or snippet (case-insensitive)."""
    if keywords is None:
        keywords = ["care", "postpartum", "baby", "mother", "confinement"]
    lowered = [kw.lower() for kw in keywords]
    filtered: List[Dict[str, Any]] = []
    for r in results:
        title = (r.get("title") or "").lower()
        snippet = (r.get("snippet") or "").lower()
        if any(kw in title or kw in snippet for kw in lowered):
            filtered.append(r)
    return filtered


def extract_components(address_pairs):
    city = None
    state = None
    country = None
    zipcode = None
    for text, label in address_pairs:
        if label == 'city':
            city = text
        elif label == 'state':
            state = text
        elif label == 'country':
            country = text
        elif label == 'postcode':
            zipcode = text
    return {'city': city, 'state': state, 'country': country, 'zipcode': zipcode}


# Keep all your existing functions: get_google_search_results, get_lat_lng, get_google_maps_results, get_all_google_maps_results, clean_business_name, fetch_html_via_scrapingdog, fetch_html_direct, extract_json_ld, pick_social_from_sameas, extract_from_html, clean_results, filter_relevant, save_json
# (Copy all of them exactly as in your original file)

# ---------------------------------------
# Main function to call from FastAPI
# ---------------------------------------

def scrape_businesses(
    query: str = "",
    country: str = "",
    keywords: Optional[List[str]] = None,
    fetch: str = "api",
    dynamic: bool = False,
    source: str = "all",
    ll: str = "@4.2105,101.9758,15z",
    page: int = 0,
) -> List[Dict[str, Any]]:

    if not API_KEY:
        return []
    if not query:
        return []



    logging.info("Fetching results for query: %s (source=%s)", query, source)

    combined_tagged: List[tuple] = []
    source_order: List[str] = ["search", "maps"] if source == "all" else [source]

    for src in source_order:
        if src == "maps":
            try:
                location = extract_components(parse_address(query)) if query else {}
                place = location.get("country") or location.get("state") or "malaysia"
                ll_param = get_lat_lng(place, GEO_MAP_API)
            except Exception as e:
                ll_param = ""

            try:
                maps_raw = get_all_google_maps_results(query, ll=ll_param or ll, max_pages=page or 0)
            except Exception as e:
                maps_raw = []
            
            for item in maps_raw:
                combined_tagged.append(("maps", item))

    # Dedupe across sources by normalized URL
    def url_for_dedupe(src: str, r: Dict[str, Any]) -> Optional[str]:
        u = r.get("website") or r.get("website_url") or r.get("link")
        return normalize_url(u) if u else None

    seen_urls = set()
    filtered_tagged: List[tuple] = []
    for src, r in combined_tagged:
        key = url_for_dedupe(src, r)
        if key and key not in seen_urls:
            seen_urls.add(key)
            filtered_tagged.append((src, r))
        elif key is None:
            filtered_tagged.append((src, r))

    all_data: List[Dict[str, Any]] = []
    session = requests.Session()

    for idx, item in enumerate(filtered_tagged, start=1):
        src, res = item
        if src == "maps":
            name = res.get("name") or res.get("title")
            address = res.get("formatted_address") or res.get("address")
            phone = res.get("phone") or res.get("phone_number")
            website_field = res.get("website") or res.get("website_url") or res.get("link") or None
            snippet = None
            services = res.get("types") or res.get("type") or None
            business_name = clean_business_name(name, website_field)

            comps = {"city": None, "state": None, "country": None, "zipcode": None}
            if address:
                parsed = parse_address(address)
                if parsed and len(parsed) > 0:
                    comps = extract_components(parsed)

            search_results = get_google_search_results(
                business_name,
                num_results=11,
                country=comps.get("country") or comps.get("state") or comps.get("city") or country or None,
            )
            search_clean = clean_results(search_results)
            if search_clean and len(search_clean) > 0:
                search_filtered = filter_relevant(search_clean, keywords=keywords)

            if search_filtered and len(search_filtered) > 0 and website_field is None:
                link = search_filtered[0].get("link")
                if snippet is None:
                    snippet = search_filtered[0].get("snippet")

            record: Dict[str, Any] = {
                "id": idx,
                "business_name": business_name,
                "url": website_field or link if 'link' in locals() else None,
                "snippet": snippet,
                "center_name": business_name,
                "address": address,
                "city": comps.get("city"),
                "state": comps.get("state") or comps.get("city"),
                "country": comps.get("country") or comps.get("state") or comps.get("city"),
                "zipcode": comps.get("zipcode"),
                "email": None,
                "website": normalize_url(website_field) if website_field else None,
                "websiteurl": None,
                "phone": phone,
                "whatsapp": None,
                "facebookurl": None,
                "instagramurl": None,
                "twitterurl": None,
                "tiktokurl": None,
                "linkedinurl": None,
                "services": services,
            }

            # Enrich from website
            html_text: Optional[str] = None
            if website_field:
                if fetch == "api":
                    html_text = fetch_html_via_scrapingdog(session, website_field, dynamic=dynamic)
                elif fetch == "direct":
                    html_text = fetch_html_direct(session, website_field)
                else:
                    html_text = fetch_html_via_scrapingdog(session, website_field, dynamic=dynamic) or fetch_html_direct(session, website_field)

            if html_text:
                enrich = extract_from_html(website_field, html_text)
                for k in [
                    "center_name","address","city","state","country","zipcode","email",
                    "website","websiteurl","phone","whatsapp","facebookurl","instagramurl",
                    "twitterurl","tiktokurl","linkedinurl","services"
                ]:
                    if k in enrich and enrich[k]:
                        record[k] = record.get(k) or enrich[k]

        all_data.append(record)


    return all_data


# -------------------------------
# Keep command-line usage intact
# -------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape and clean results via ScrapingDog (Google or Google Maps)")
    parser.add_argument("--query", default="Confinementcares in malaysia", help="Search query")
    parser.add_argument("--country", default="", help="Country code for search (default: my)")
    parser.add_argument("--num-results", type=int, default=50, help="Number of results to fetch (default: 50)")
    parser.add_argument("--keywords", nargs="*", default=["care","postpartum","baby","mother","confinement"], help="Keywords for relevance filtering")
    parser.add_argument("--fetch", choices=["api","direct","auto"], default="api", help="How to fetch site HTML for enrichment (default: api)")
    parser.add_argument("--dynamic", action="store_true", help="Use dynamic rendering when fetching via ScrapingDog")
    parser.add_argument("--source", choices=["search","maps","all"], default="all", help="Data source: 'search', 'maps', or 'all' (both)")
    parser.add_argument("--ll", default="@4.2105,101.9758,15z", help="Google Maps ll parameter (lat,lng; optional)")
    parser.add_argument("--page", type=int, default=1, help="Google Maps results page (0-based)")
    args = parser.parse_args()

    scrape_businesses(
        query=args.query,
        country=args.country,
        num_results=args.num_results,
        keywords=args.keywords,
       
        fetch=args.fetch,
        dynamic=args.dynamic,
        source=args.source,
        ll=args.ll,
        page=args.page,
    )
