"""Provisional news categories, assigned by simple rules on the title.

This only decides what the interface shows first. It is a stand-in for the
planned news classifier (a language model reading the full text), which
will replace it; nothing here should be used as evidence by the agent.
"""

import re

# Checked in order; the first match wins.
_RULES: list[tuple[str, re.Pattern]] = [
    (
        "community",
        re.compile(
            r"fan ?art|competition|contest|giveaway|twitch drops?|qualifier|tournament|"
            r"\bvods?\b|showcase|community (spotlight|highlight)|highlights? #|"
            r"dev(eloper)? (stream|diary)|livestream|\bstream\b|podcast|soundtrack|merch|wallpaper|\bq&a\b",
            re.I,
        ),
    ),
    ("sale", re.compile(r"\bsale\b|% off|discount|free weekend|free to play (this|for)|\bbundle\b", re.I)),
    (
        "update",
        re.compile(r"\bpatch\b|patch ?notes|hot ?fix|\bupdate\b|changelog|release notes|\bv?\d+\.\d+(\.\d+)*[a-z]?\b.*(patch|notes|live)", re.I),
    ),
    (
        "release",
        re.compile(
            r"now available|out now|is live|is here|has (arrived|launched)|launch(es|ed)?\b|"
            r"available now|\bdlc\b|expansion|new (season|league|chapter|map|operator|hero|character)|"
            r"season \d+|early access|1\.0",
            re.I,
        ),
    ),
    (
        "announcement",
        re.compile(r"announc|reveal|roadmap|timeline|coming (soon|to|on)|teaser|trailer|preview|\bbegins\b|starts? (on|in)|weeks? until|save the date", re.I),
    ),
]

# Higher shows first. Launches move player counts the most; routine
# community posts the least.
PRIORITY = {"release": 3, "update": 2, "announcement": 2, "sale": 2, "community": 1, "other": 1}


def classify(title: str | None, official: bool, tags: list[str] | None = None) -> tuple[str, int]:
    """Return (category, priority); anything not from the developer gets priority 0."""
    category = "other"
    if tags and "patchnotes" in tags:
        category = "update"
    else:
        for name, pattern in _RULES:
            if pattern.search(title or ""):
                category = name
                break
    return category, (PRIORITY[category] if official else 0)
