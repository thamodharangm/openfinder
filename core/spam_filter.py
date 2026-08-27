import re
from typing import Tuple
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import SPAM_TRIGGERS


def is_spam_or_bait(text: str) -> Tuple[bool, str]:
    """
    Checks if a LinkedIn post is spam, engagement bait (e.g. 'comment email below'),
    or an irrelevant promotional post.
    
    Returns:
        (is_spam: bool, reason: str)
    """
    if not text or len(text.strip()) < 30:
        return True, "Post text too short"

    text_lower = text.lower()

    for trigger in SPAM_TRIGGERS:
        if trigger in text_lower:
            return True, f"Matched engagement-bait pattern: '{trigger}'"

    # Check for excessive emojis or spam patterns
    if text_lower.count("👇") > 4 and "comment" in text_lower:
        return True, "Comment-bait pattern detected"

    return False, "Genuine post"
