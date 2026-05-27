"""
content_parser.py
-----------------
Parses the structured response from the OpenAI API into per-platform sections.

The model is instructed to emit sections delimited by `===SECTION_NAME===`.
We split on those delimiters and return a dict.
"""

# Order matters only for human readability; parsing handles any order.
SECTION_KEYS = [
    "TOPIC",
    "GOOGLE_BUSINESS_PROFILE",
    "FACEBOOK",
    "INSTAGRAM",
    "LINKEDIN",
    "CTA_SUGGESTIONS",
    "IMAGE_IDEAS",
]


def parse_sections(raw: str) -> dict[str, str]:
    """
    Split the raw model output into a {section_key: content} dict.

    Missing sections are returned as empty strings so downstream code
    can write placeholder files without crashing.
    """
    sections: dict[str, str] = {key: "" for key in SECTION_KEYS}

    # Walk through each known key and grab everything between its delimiter
    # and the next known delimiter (or end of string).
    for i, key in enumerate(SECTION_KEYS):
        start_marker = f"==={key}==="
        if start_marker not in raw:
            continue

        after = raw.split(start_marker, 1)[1]

        # Find the earliest next delimiter that appears after this one.
        next_index = len(after)
        for other in SECTION_KEYS:
            if other == key:
                continue
            marker = f"==={other}==="
            idx = after.find(marker)
            if idx != -1 and idx < next_index:
                next_index = idx

        sections[key] = after[:next_index].strip()

    return sections
