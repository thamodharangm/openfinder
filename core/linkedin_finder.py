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

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False


class LinkedInFinder:
    """
    Finds real-time LinkedIn hiring posts using search dorking queries (Zero ban risk).
    Supports DuckDuckGo search API & fallback web scrapers.
    """

    def __init__(self, skills_taxonomy: Optional[List[str]] = None):
        self.skills_taxonomy = skills_taxonomy or COMMON_SKILLS

    def build_query_variations(self, keywords: str, location: str = DEFAULT_LOCATION, remote_only: bool = False) -> List[str]:
        """
        Builds progressive query variations from strict to broad to maximize search yields.
        """
        kw_clean = keywords.replace('"', '').strip()
        loc_clean = location.replace('"', '').strip() if location else ""
        remote_str = "remote" if remote_only else ""

        # Strategy 1: Direct LinkedIn Posts & Updates
        q1 = f'site:linkedin.com/posts/ OR site:linkedin.com/feed/ ("hiring" OR "we are hiring" OR "job opening") "{kw_clean}"'
        if loc_clean:
            q1 += f' "{loc_clean}"'
        if remote_str:
            q1 += f' {remote_str}'

        # Strategy 2: Broad LinkedIn domain query
        q2 = f'site:linkedin.com ("hiring" OR "job opening") "{kw_clean}"'
        if loc_clean:
            q2 += f' "{loc_clean}"'
        if remote_str:
            q2 += f' {remote_str}'

        # Strategy 3: General search query targeting LinkedIn hiring discussions
        q3 = f'linkedin hiring {kw_clean} {loc_clean} {remote_str}'.strip()

        return [q1, q2, q3]

    def search_duckduckgo(self, query: str, max_results: int = DEFAULT_MAX_RESULTS, timeframe: Optional[str] = DEFAULT_TIMEFRAME) -> List[Dict[str, Any]]:
        """
        Executes DuckDuckGo search using ddgs library.
        timeframe: 'd' (day), 'w' (week), 'm' (month), or None
        """
        results = []
        if not HAS_DDGS:
            return results

        try:
            with DDGS() as ddgs:
                ddg_results = ddgs.text(
                    query,
                    region="in-en" if "India" in query or "Bangalore" in query else "wt-wt",
                    timelimit=timeframe if timeframe in ['d', 'w', 'm'] else None,
                    max_results=max_results * 2
                )
                for item in ddg_results:
                    link = item.get("href", "")
                    if "linkedin.com" in link:
                        results.append({
                            "title": item.get("title", ""),
                            "link": link,
                            "snippet": item.get("body", "")
                        })
        except Exception as e:
            print(f"[LinkedInFinder] DDGS error: {e}", file=sys.stderr)

        return results

    def search_html_fallback(self, query: str, max_results: int = DEFAULT_MAX_RESULTS) -> List[Dict[str, Any]]:
        """
        Direct HTTP fallback if DDGS library is unavailable.
        """
        results = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        try:
            with httpx.Client(headers=headers, timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("div", class_="result__body")
                    for block in links[:max_results * 2]:
                        title_el = block.find("a", class_="result__url")
                        snippet_el = block.find("a", class_="result__snippet")
                        link_el = block.find("a", class_="result__url")
                        
                        href = link_el["href"] if link_el and "href" in link_el.attrs else ""
                        title = title_el.get_text(strip=True) if title_el else ""
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                        if "linkedin.com" in href:
                            results.append({
                                "title": title,
                                "link": href,
                                "snippet": snippet
                            })
        except Exception as e:
            print(f"[LinkedInFinder] Fallback search error: {e}", file=sys.stderr)

        return results

    def search_hiring_posts(
        self, 
        keywords: str, 
        location: str = DEFAULT_LOCATION, 
        timeframe: Optional[str] = DEFAULT_TIMEFRAME,
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Primary search function with multi-tier query fallback.
        """
        queries = self.build_query_variations(keywords, location, remote_only)
        all_raw = []

        for q in queries:
            # 1. Try DuckDuckGo search
            raw = self.search_duckduckgo(q, max_results=max_results, timeframe=timeframe)
            if not raw and timeframe:
                raw = self.search_duckduckgo(q, max_results=max_results, timeframe=None)
            
            # 2. Try HTML scraper fallback
            if not raw:
                raw = self.search_html_fallback(q, max_results=max_results)

            if raw:
                all_raw.extend(raw)
                if len(all_raw) >= max_results:
                    break

        # Deduplicate results by URL
        seen_urls = set()
        parsed_posts = []

        for raw in all_raw:
            url = raw.get("link", "")
            if url in seen_urls:
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

        return parsed_posts
