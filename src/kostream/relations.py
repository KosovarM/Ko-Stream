"""Prequel / sequel navigation from MAL related_anime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kostream.models import Show

MAL_ANIME_URL = "https://myanimelist.net/anime/{mal_id}"
NAV_RELATION_TYPES = ("prequel", "sequel")
RELATION_LABELS = {"prequel": "Prequel", "sequel": "Sequel"}
RELATION_ORDER = {"prequel": 0, "sequel": 1}


@dataclass(frozen=True)
class RelationLink:
    kind: str
    label: str
    title: str
    href: str
    external: bool
    mal_id: int


def mal_anime_url(mal_id: int) -> str:
    return MAL_ANIME_URL.format(mal_id=mal_id)


def build_relation_links(
    show: Show,
    mal_id_to_show_id: dict[int, str],
    show_url: Callable[[str], str],
) -> list[RelationLink]:
    links: list[RelationLink] = []
    for rel in show.related_anime:
        if rel.relation_type not in NAV_RELATION_TYPES:
            continue
        catalog_id = mal_id_to_show_id.get(rel.mal_id)
        if catalog_id:
            links.append(
                RelationLink(
                    kind=rel.relation_type,
                    label=RELATION_LABELS[rel.relation_type],
                    title=rel.title,
                    href=show_url(catalog_id),
                    external=False,
                    mal_id=rel.mal_id,
                )
            )
        else:
            links.append(
                RelationLink(
                    kind=rel.relation_type,
                    label=RELATION_LABELS[rel.relation_type],
                    title=rel.title,
                    href=mal_anime_url(rel.mal_id),
                    external=True,
                    mal_id=rel.mal_id,
                )
            )
    links.sort(key=lambda link: (RELATION_ORDER.get(link.kind, 9), link.title.casefold()))
    return links
