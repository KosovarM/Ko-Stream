"""English/Japanese title aliases for matching media folders to MAL catalog entries."""

from __future__ import annotations

import re
from typing import Iterable

from kostream.manga_catalog import _manga_match_key, _manga_tokens

# Explicit folder name -> MAL id overrides (merged with FOLDER_MAP at runtime).
# Keys must match library folder names under D:/Media/Ko-Stream/anime exactly.
FOLDER_MAL_IDS: dict[str, int] = {
    # JoJo — English inbox/library folder names
    "JoJos Bizarre Adventure": 14719,
    "JoJos Bizarre Adventure Stardust Crusaders": 20899,
    "JoJos Bizarre Adventure Stardust Crusaders 2nd Season": 26055,
    "JoJos Bizarre Adventure Diamond is Unbreakable": 31933,
    "JoJos Bizarre Adventure Golden Wind": 37991,
    "JoJos Bizarre Adventure Stone Ocean": 48661,
    "JoJos Bizarre Adventure Stone Ocean Part 2": 51367,
    "JoJos Bizarre Adventure Stone Ocean Part 3": 53273,
    "Steel Ball Run JoJos Bizarre Adventure": 61469,
}

# English arc/series phrases -> extra match tokens (incl. romanized MAL fragments).
TITLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "golden wind": ("ougon no kaze", "part 5", "part5"),
    "diamond is unbreakable": ("diamond wa kudakenai", "part 4", "part4"),
    "stardust crusaders 2nd season": ("egypt hen", "battle in egypt", "part 3 2", "26055"),
    "stardust crusaders": ("stardust crusaders", "part 3", "part3"),
    "stone ocean part 3": ("stone ocean part 3", "part 6 3", "53273"),
    "stone ocean part 2": ("stone ocean part 2", "part 6 2", "51367"),
    "stone ocean": ("stone ocean", "part 6", "part6"),
    "steel ball run": ("steel ball run", "61469"),
    "bizarre adventure": ("kimyou na bouken", "jojo no kimyou"),
    "entertainment district": ("yuukaku hen", "47778"),
    "swordsmith village": ("katanakaji no sato", "51019"),
    "hashira training": ("hashira geiko", "55701"),
    "mugen train arc tv": ("mugen ressha hen", "49926"),
    "mugen train movie": ("mugen train", "40456"),
    "infinity castle": ("infinity castle", "59192"),
    "kabaneri of the iron fortress the battle of unato": ("unato kessen", "34544"),
    "kabaneri of the iron fortress": ("koutetsujou no kabaneri", "28623"),
    "kabaneri movie 1 tsudou hikari": ("tsudou hikari", "33519"),
    "overlord movie 1 the undead king": ("undead king", "34161"),
    "overlord movie 2 the dark hero": ("dark hero", "34428"),
    "overlord iii": ("overlord iii", "37675"),
    "overlord ii": ("overlord ii", "35073"),
}

_APOSTROPHE_RE = re.compile(r"[''`´]")
_JOJO_RE = re.compile(r"\bjojos\b", re.IGNORECASE)


def normalize_title_for_match(value: str) -> str:
    """Lowercase, unify apostrophes, JoJos -> JoJo, collapse whitespace."""
    text = str(value or "").strip()
    text = _APOSTROPHE_RE.sub("", text)
    text = _JOJO_RE.sub("jojo", text)
    text = re.sub(r"\s+", " ", text)
    return text.casefold().strip()


def normalize_search_query(folder: str) -> str:
    """Build an AniList-friendly query from a library folder name."""
    text = normalize_title_for_match(folder.replace("_", " "))
    # Restore readable JoJo's for search APIs that expect it
    text = re.sub(r"\bjojo\b", "JoJo's", text, count=1)
    text = re.sub(r"\bjojo\b", "JoJo", text)
    return text.strip()


def folder_mal_id(folder: str, folder_map: dict[str, int] | None = None) -> int | None:
    """Resolve MAL id from FOLDER_MAP, explicit aliases, or None."""
    if folder in FOLDER_MAL_IDS:
        return int(FOLDER_MAL_IDS[folder])
    if folder_map and folder in folder_map:
        return int(folder_map[folder])
    return None


def folder_match_keys(folder: str) -> set[str]:
    """All normalized keys/tokens used to match a library folder to catalog titles."""
    keys: set[str] = set()
    raw = str(folder or "").strip()
    if not raw:
        return keys

    norm = normalize_title_for_match(raw)
    keys.add(_manga_match_key(norm))

    tokens = set(_manga_tokens(norm))
    keys.update(tokens)

    folded = norm.replace(" ", "")
    for phrase, synonyms in TITLE_SYNONYMS.items():
        if phrase in norm or phrase.replace(" ", "") in folded:
            keys.update(_manga_tokens(" ".join(synonyms)))
            keys.add(_manga_match_key(phrase))

    mal_id = folder_mal_id(raw)
    if mal_id is not None:
        keys.add(str(mal_id))

    return {k for k in keys if k}


def entry_match_keys(title: str | None, *, mal_id: int | None = None) -> set[str]:
    """Normalized keys for a catalog/MAL title."""
    keys: set[str] = set()
    if title:
        norm = normalize_title_for_match(title)
        keys.add(_manga_match_key(norm))
        keys.update(_manga_tokens(norm))
        norm_key = _manga_match_key(norm)
        for phrase, synonyms in TITLE_SYNONYMS.items():
            phrase_key = _manga_match_key(phrase)
            if phrase in norm or (phrase_key and phrase_key in norm_key):
                for syn in synonyms:
                    keys.add(_manga_match_key(syn))
                    keys.update(_manga_tokens(syn))
    if mal_id is not None:
        keys.add(str(int(mal_id)))
    return {k for k in keys if k}


def match_score(folder_keys: set[str], entry_keys: set[str]) -> float:
    """Token overlap score in [0, 1]; mal-id token match is instant win."""
    if not folder_keys or not entry_keys:
        return 0.0
    if folder_keys & entry_keys:
        # Direct mal-id or exact key hit
        if any(k.isdigit() and len(k) >= 4 for k in folder_keys & entry_keys):
            return 1.0
        overlap = folder_keys & entry_keys
        if _manga_match_key(next(iter(overlap))) == next(iter(overlap)):
            return 1.0
    overlap = folder_keys & entry_keys
    if not overlap:
        return 0.0
    return len(overlap) / min(len(folder_keys), len(entry_keys))


def folder_plausibly_matches_title(folder: str, title: str | None, *, min_score: float = 0.5) -> bool:
    """True when a library folder name reasonably belongs to this anime title.

    Used to reject cross-wired catalog ``folder`` fields (e.g. Ginpachi folder on
    an unrelated MAL id) and to validate FOLDER_MAP entries before linking.
    """
    if not folder or not title:
        return False
    folder_norm = normalize_title_for_match(folder)
    title_norm = normalize_title_for_match(title)
    if not folder_norm or not title_norm:
        return False
    if folder_norm == title_norm:
        return True
    if folder_norm in title_norm or title_norm in folder_norm:
        return True
    score = match_score(folder_match_keys(folder), entry_match_keys(title))
    # Generic tokens like "movie"/"season" inflate overlap — require a higher bar
    # when the only shared keys are weak.
    stop = {
        "movie",
        "movies",
        "season",
        "part",
        "the",
        "and",
        "of",
        "ova",
        "ona",
        "special",
        "film",
        "arc",
        "hen",
        "2nd",
        "3rd",
        "4th",
    }
    folder_tokens = {t for t in _manga_tokens(folder_norm) if t not in stop}
    title_tokens = {t for t in _manga_tokens(title_norm) if t not in stop}
    strong_overlap = folder_tokens & title_tokens
    # Never accept a high match_score that is only stopword noise (e.g. "movie").
    if not strong_overlap:
        return False
    if score >= min_score:
        return True
    # Shared significant tokens (length ≥ 4), ignoring stopwords.
    significant = {t for t in strong_overlap if len(t) >= 4}
    if len(significant) >= 2:
        return True
    if len(significant) == 1 and len(next(iter(significant))) >= 8:
        return True
    return False


def best_catalog_match(
    folder: str,
    candidates: Iterable[tuple[str | None, int | None]],
    *,
    min_score: float = 0.45,
) -> tuple[int | None, float]:
    """Return (mal_id, score) for best title match among (title, mal_id) pairs."""
    folder_keys = folder_match_keys(folder)
    if not folder_keys:
        return None, 0.0

    best_mal: int | None = None
    best = 0.0
    for title, mal_id in candidates:
        score = match_score(folder_keys, entry_match_keys(title, mal_id=mal_id))
        if score > best:
            best = score
            best_mal = int(mal_id) if mal_id is not None else None

    if best < min_score:
        return None, best
    return best_mal, best
