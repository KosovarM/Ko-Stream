"""Manga chapter completion helpers."""

from pathlib import Path

from kostream.manga import MangaChapter, MangaTitle
from kostream.manga_progress import (
    chapter_completed,
    chapter_position,
    chapters_read_count,
    filter_currently_publishing,
    is_currently_publishing,
    load_manga_completed,
    manga_reading_status,
    mark_chapter_read,
    mark_manga_completed,
    save_manga_completed,
)


def _manga() -> MangaTitle:
    return MangaTitle(
        id="mal-manga-1",
        title="Demo",
        folder="Demo",
        chapters=[
            MangaChapter(id="c1", title="Chapter 01", page_count=10, kind="cbz", relative="01.cbz"),
            MangaChapter(id="c2", title="Chapter 02", page_count=12, kind="cbz", relative="02.cbz"),
        ],
        mal_id=1,
        num_chapters_read=0,
    )


def test_mark_chapter_read(tmp_path: Path):
    path = tmp_path / "manga_completed.json"
    manga = _manga()
    assert chapter_position(manga, "c2") == 2
    count = mark_chapter_read(manga, "c1", path)
    assert count == 1
    assert chapter_completed(manga, "c1", load_manga_completed(path), 0)
    assert not chapter_completed(manga, "c2", load_manga_completed(path), 0)
    count = mark_chapter_read(manga, "c2", path)
    assert count == 2
    assert chapter_completed(manga, "c2", load_manga_completed(path), 0)


def test_unmark_chapter_read(tmp_path: Path):
    from kostream.manga_progress import next_unread_chapter, unmark_chapter_read

    path = tmp_path / "manga_completed.json"
    manga = _manga()
    mark_chapter_read(manga, "c2", path)
    count = unmark_chapter_read(manga, "c2", path)
    assert count == 1
    assert chapter_completed(manga, "c1", load_manga_completed(path), 0)
    assert not chapter_completed(manga, "c2", load_manga_completed(path), 0)
    nxt = next_unread_chapter(manga, load_manga_completed(path), 0)
    assert nxt is not None
    assert nxt.id == "c2"


def test_next_unread_chapter_and_hide_when_completed(tmp_path: Path):
    from kostream.manga_progress import next_unread_chapter

    path = tmp_path / "manga_completed.json"
    manga = _manga()
    assert next_unread_chapter(manga, {}, 0) is not None
    mark_manga_completed(manga, path)
    assert manga_reading_status(manga, load_manga_completed(path)) == "completed"
    assert next_unread_chapter(manga, load_manga_completed(path), 0) is None


def test_mark_chapters_read_through_range(tmp_path: Path):
    from kostream.manga_progress import mark_chapters_read_through

    path = tmp_path / "manga_completed.json"
    manga = _manga()
    manga.chapters.append(
        MangaChapter(id="c3", title="Chapter 03", page_count=8, kind="cbz", relative="03.cbz")
    )
    count = mark_chapters_read_through(manga, 2, path)
    assert count == 2
    completed = load_manga_completed(path)
    assert chapter_completed(manga, "c1", completed, 0)
    assert chapter_completed(manga, "c2", completed, 0)
    assert not chapter_completed(manga, "c3", completed, 0)
    # Idempotent / already-read chapters in range
    assert mark_chapters_read_through(manga, 1, path) == 2
    assert mark_chapters_read_through(manga, 3, path) == 3


def test_mark_chapters_read_through_meta_only(tmp_path: Path):
    from kostream.manga_progress import mark_chapters_read_through

    path = tmp_path / "manga_completed.json"
    manga = MangaTitle(
        id="mal-manga-meta",
        title="Meta Only",
        folder="",
        chapters=[],
        mal_id=99,
        num_chapters_mal=12,
        num_chapters_read=0,
    )
    count = mark_chapters_read_through(manga, 5, path)
    assert count == 5
    assert load_manga_completed(path)[manga.id] == 5
    assert manga.num_chapters_read == 5


def test_mal_chapters_read_counts():
    manga = _manga()
    manga.num_chapters_read = 2
    assert chapter_completed(manga, "c2", {}, 2)


def test_progress_reached_completion():
    from kostream.watch_progress import progress_reached_completion

    assert progress_reached_completion({"seconds": 900, "duration": 1000})
    assert not progress_reached_completion({"seconds": 800, "duration": 1000})
    assert not progress_reached_completion(900)



def test_manga_reading_status_new_reading_completed(tmp_path: Path):
    manga = _manga()
    assert manga_reading_status(manga) == "new"
    assert chapters_read_count(manga) == 0

    path = tmp_path / "manga_completed.json"
    mark_chapter_read(manga, "c1", path)
    completed = load_manga_completed(path)
    assert chapters_read_count(manga, completed) == 1
    assert manga_reading_status(manga, completed) == "reading"

    mark_manga_completed(manga, path)
    completed = load_manga_completed(path)
    assert manga_reading_status(manga, completed) == "completed"


def test_manga_reading_status_mal_completed():
    manga = _manga()
    manga.list_status = "completed"
    assert manga_reading_status(manga) == "completed"


def test_manga_reading_status_mal_progress_only():
    manga = _manga()
    manga.num_chapters_read = 1
    assert manga_reading_status(manga) == "reading"
    manga.num_chapters_read = 2
    assert manga_reading_status(manga) == "completed"


def test_currently_publishing():
    manga = _manga()
    manga.manga_status = "currently_publishing"
    assert is_currently_publishing(manga)
    assert filter_currently_publishing([manga]) == [manga]
    manga.manga_status = "finished"
    assert not is_currently_publishing(manga)


def test_chapter_page_progress_save_load(tmp_path: Path):
    from kostream.manga_progress import (
        clear_chapter_page_index,
        get_chapter_page_index,
        resume_point,
        set_chapter_page_index,
    )

    path = tmp_path / "manga_page_progress.json"
    assert get_chapter_page_index("mal-manga-1", "c1", path) is None
    assert set_chapter_page_index("mal-manga-1", "c1", 19, path) == 19
    assert get_chapter_page_index("mal-manga-1", "c1", path) == 19
    assert resume_point("mal-manga-1", path) == {
        "chapter_id": "c1",
        "page_index": 19,
    }
    set_chapter_page_index("mal-manga-1", "c2", 3, path)
    assert resume_point("mal-manga-1", path)["chapter_id"] == "c2"
    clear_chapter_page_index("mal-manga-1", "c2", path)
    assert get_chapter_page_index("mal-manga-1", "c2", path) is None
    assert resume_point("mal-manga-1", path) is None
    assert get_chapter_page_index("mal-manga-1", "c1", path) == 19


def test_mark_read_clears_page_progress(tmp_path: Path):
    from kostream.manga_progress import (
        get_chapter_page_index,
        mark_chapters_read_through,
        set_chapter_page_index,
    )

    completed = tmp_path / "manga_completed.json"
    pages = tmp_path / "manga_page_progress.json"
    manga = _manga()
    set_chapter_page_index(manga.id, "c1", 7, pages)
    set_chapter_page_index(manga.id, "c2", 4, pages)
    mark_chapters_read_through(manga, 1, completed, pages)
    assert get_chapter_page_index(manga.id, "c1", pages) is None
    assert get_chapter_page_index(manga.id, "c2", pages) == 4
    mark_chapter_read(manga, "c2", completed, pages)
    assert get_chapter_page_index(manga.id, "c2", pages) is None


def test_chapters_payload_includes_page_index():
    manga = _manga()
    page_progress = {
        manga.id: {"last_chapter_id": "c1", "pages": {"c1": 5, "c2": 2}}
    }
    payload = manga.chapters_payload_with_progress({}, page_progress)
    assert payload[0]["page_index"] == 5
    assert payload[1]["page_index"] == 2
    assert payload[0]["number"] == "1"
    assert payload[0]["name"] == ""
    # Done chapters omit page_index
    completed = {manga.id: 1}
    payload2 = manga.chapters_payload_with_progress(completed, page_progress)
    assert payload2[0]["done"] is True
    assert "page_index" not in payload2[0]
    assert payload2[1].get("page_index") == 2


def test_chapters_payload_splits_named_title():
    manga = MangaTitle(
        id="m1",
        title="Demo",
        folder="Demo",
        chapters=[
            MangaChapter(
                id="c1",
                title="Chapter 1: Dog & Chainsaw",
                page_count=10,
                kind="dir",
                relative="Chapter 01",
            )
        ],
    )
    row = manga.chapters_payload()[0]
    assert row["number"] == "1"
    assert row["name"] == "Dog & Chainsaw"
    assert row["title"] == "Chapter 1: Dog & Chainsaw"
