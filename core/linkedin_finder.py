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

    def build_query(self, keywords: str, location: str = DEFAULT_LOCATION, remote_only: bool = False) -> str:
        """
        Builds a precision Google/DDG dorking query for LinkedIn posts.
        """
        # Flexible LinkedIn post search query
        base = 'site:linkedin.com/posts/ ("hiring" OR "job opening" OR "immediate joiner" OR "we are hiring")'
        
        kw_clean = keywords.replace('"', '')
        loc_part = f'{location}' if location else ""
        remote_part = 'remote' if remote_only else ""

        parts = [base, kw_clean]
        if loc_part:
            parts.append(loc_part)
        if remote_part:
            parts.append(remote_part)

        return " ".join(parts)

    def search_duckduckgo(self, query: str, max_results: int = DEFAULT_MAX_RESULTS, timeframe: str = DEFAULT_TIMEFRAME) -> List[Dict[str, Any]]:
        """
        Executes DuckDuckGo search using ddgs library.
        timeframe: 'd' (day), 'w' (week), 'm' (month)
        """
        results = []
        if not HAS_DDGS:
            return results

        try:
            with DDGS() as ddgs:
                # time options: 'd', 'w', 'm', 'y'
                ddg_results = ddgs.text(
                    query,
                    region="in-en" if "India" in query else "wt-wt",
                    timelimit=timeframe if timeframe in ['d', 'w', 'm'] else 'w',
                    max_results=max_results * 2 # Fetch extra to account for spam filtering
                )
                for item in ddg_results:
                    link = item.get("href", "")
                    # Ensure it is a LinkedIn post or activity URL
                    if "linkedin.com" in link:
                        results.append({
                            "title": item.get("title", ""),
                            "link": link,
                            "snippet": item.get("body", "")
                        })
        except Exception as e:
            # Fallback or log
            print(f"[LinkedInFinder] DDGS search error: {e}", file=sys.stderr)

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
        timeframe: str = DEFAULT_TIMEFRAME,
        remote_only: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS
    ) -> List[Dict[str, Any]]:
        """
        Primary search function:
        1. Formulates query
        2. Retrieves web results
        3. Filters spam/bait
        4. Parses contact emails, apply links, and skills
        """
        query = self.build_query(keywords, location, remote_only)
        
        # 1. Fetch raw search results
        raw_results = self.search_duckduckgo(query, max_results=max_results, timeframe=timeframe)
        
        # If strict timeframe returned 0, try without strict timeframe filter
        if not raw_results and timeframe:
            raw_results = self.search_duckduckgo(query, max_results=max_results, timeframe=None)

        if not raw_results:
            raw_results = self.search_html_fallback(query, max_results=max_results)

        # 2. Filter & Parse
        parsed_posts = []
        for raw in raw_results:
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
