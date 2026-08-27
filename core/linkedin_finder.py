import re
import urllib.parse
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import COMMON_SKILLS, DEFAULT_LOCATION, DEFAULT_TIMEFRAME, DEFAULT_MAX_RESULTS
from core.spam_filter import is_spam_or_bait
from core.post_parser import PostParser
from core.cache import SearchCache


class LinkedInFinder:
    """
    Finds real-time LinkedIn hiring posts using multi-provider pure Python search.
    Completely avoids native DLL conflicts and rate limit walls.
    Integrates local cache for instant sub-second responses.
    """

    def __init__(self, skills_taxonomy: Optional[List[str]] = None):
        self.skills_taxonomy = skills_taxonomy or COMMON_SKILLS
        self.cache = SearchCache()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

    def clean_linkedin_url(self, raw_url: str) -> str:
        """Decodes Yahoo/search redirect wrappers into direct LinkedIn URLs."""
        if "RU=" in raw_url:
            match = re.search(r'RU=([^/&]+)', raw_url)
            if match:
                decoded = urllib.parse.unquote(match.group(1))
                return decoded
        return raw_url

    def search_yahoo(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[Dict[str, Any]]:
        """
        Primary search provider: Yahoo HTML search engine.
        Returns high-quality, real-time indexed LinkedIn hiring posts.
        """
        results = []
        try:
            url = "https://search.yahoo.com/search"
            params = {"p": query, "n": max_results * 2}
            
            with httpx.Client(headers=self.headers, timeout=12.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.find_all("div", class_="algo")
                    
                    for item in items:
                        title_el = item.find("h3")
                        link_el = item.find("a")
                        snippet_el = item.find("div", class_="compText") or item.find("p")

                        if not title_el or not link_el:
                            continue

                        title = title_el.get_text(strip=True)
                        raw_link = link_el.get("href", "")
                        clean_link = self.clean_linkedin_url(raw_link)
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                        if "linkedin.com" in clean_link:
                            results.append({
                                "title": title,
                                "link": clean_link,
                                "snippet": snippet
                            })
        except Exception as e:
            print(f"[LinkedInFinder] Yahoo search error: {e}", file=sys.stderr)

        return results

    def search_bing(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[Dict[str, Any]]:
        """
        Secondary search provider: Bing HTML search engine.
        """
        results = []
        try:
            url = "https://www.bing.com/search"
            params = {"q": query, "count": max_results * 2}
            
            with httpx.Client(headers=self.headers, timeout=12.0, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.find_all("li", class_="b_algo")
                    
                    for item in items:
                        title_el = item.find("h2")
                        link_el = item.find("a")
                        snippet_el = item.find("div", class_="b_caption") or item.find("p")

                        if not title_el or not link_el:
                            continue

                        title = title_el.get_text(strip=True)
                        clean_link = link_el.get("href", "")
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                        if "linkedin.com" in clean_link:
                            results.append({
                                "title": title,
                                "link": clean_link,
                                "snippet": snippet
                            })
        except Exception as e:
            print(f"[LinkedInFinder] Bing search error: {e}", file=sys.stderr)

        return results

    @staticmethod
    def is_valid_post_url(url: str) -> bool:
        """
        Ensures the URL is strictly a personal recruiter/founder LinkedIn POST or Activity update,
        and completely filters out generic job boards (/jobs/, /directory/, /company/).
        """
        if not url:
            return False
        url_lower = url.lower()

        # Explicitly ban generic job aggregator / company directories
        if any(forbidden in url_lower for forbidden in ['/jobs/', '/job/', '/directory/', '/salary/', '/school/']):
            return False

        # Strictly require genuine post or activity paths
        return bool('/posts/' in url_lower or '/feed/update/' in url_lower or 'activity-' in url_lower)

    def build_queries(self, keywords: str, location: str = DEFAULT_LOCATION, remote_only: bool = False) -> List[str]:
        """
        Builds precision queries that specifically target LinkedIn Posts, explicitly excluding /jobs/ pages.
        """
        # Clean slashes, quotes, and punctuation
        kw = re.sub(r'[/\\()|]', ' ', keywords)
        kw = re.sub(r'\s+', ' ', kw).replace('"', '').strip()
        loc = location.replace('"', '').strip() if location else ""
        remote = "remote" if remote_only else ""

        # Query 1: Direct LinkedIn Post URLs only (excluding job boards)
        q1 = f'site:linkedin.com/posts/ ("hiring" OR "we are hiring" OR "looking for") "{kw}" {loc} {remote} -inurl:jobs'.strip()
        # Query 2: Feed update / Activity URLs
        q2 = f'site:linkedin.com/feed/update/ ("hiring" OR "job opening") "{kw}" {loc} {remote} -inurl:jobs'.strip()
        # Query 3: Broad post keyword match
        q3 = f'site:linkedin.com/posts/ "{kw}" {loc} hiring -inurl:jobs'.strip()

        return [q1, q2, q3]

    def search_hiring_posts(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: Optional[str] = DEFAULT_TIMEFRAME,
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Primary search function: checks cache first, queries multi-tier providers, 
        strips spam, and extracts contact emails, apply links, and required skills.
        """
        cache_key = f"{keywords}::{location}::{remote_only}::{max_results}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        queries = self.build_queries(keywords, location, remote_only)
        all_raw = []

        for q in queries:
            # 1. Try Yahoo
            raw = self.search_yahoo(q, max_results=max_results)
            if raw:
                all_raw.extend(raw)

            # 2. Try Bing if needed
            if len(all_raw) < max_results:
                raw_bing = self.search_bing(q, max_results=max_results)
                if raw_bing:
                    all_raw.extend(raw_bing)

            if len(all_raw) >= max_results:
                break

        # Deduplicate results by URL and strictly enforce post URLs only
        seen_urls = set()
        parsed_posts = []

        for raw in all_raw:
            url = raw.get("link", "")
            if not url or url in seen_urls:
                continue

            # Strict check: Must be a LinkedIn POST / Activity update (No /jobs/ links allowed)
            if not self.is_valid_post_url(url):
                continue

            seen_urls.add(url)

            full_text = f"{raw.get('title', '')} {raw.get('snippet', '')}"
            
            # Spam check
            is_spam, reason = is_spam_or_bait(full_text)
            if is_spam:
                continue

            parsed = PostParser.parse(raw, self.skills_taxonomy)
            parsed_posts.append(parsed)

            if len(parsed_posts) >= max_results:
                break

        # Cache results for faster subsequent retrieval
        if parsed_posts:
            self.cache.set(cache_key, parsed_posts)

        return parsed_posts
