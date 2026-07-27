"""Import unsorted inbox -> D:\\Media\\Ko-Stream\\anime (S01Exx naming)."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

INBOX_ROOT = Path(os.environ.get("KOSTREAM_INBOX_ROOT", r"D:\UnsortedFiles\KoStream"))
DOWNLOADS = Path(os.environ.get("KOSTREAM_INBOX_ANIME", str(INBOX_ROOT / "Anime")))
MEDIA_ROOT = Path(r"D:\Media\Ko-Stream\anime")
CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog" / "selected.json"

# download folder name -> (library folder name, catalog id or None, episode offset)
FOLDER_MAP: dict[str, tuple[str, str | None, int]] = {
    "Bleach__Thousand_Year_Blood_War___The_Calamity_sub": (
        "Bleach TYBW Kashin-tan",
        "mal-60636",
    ),
    "Bleach_sub": ("Bleach", "mal-269"),
    # First cour (Sennen Kessen-hen / Arc)
    "Bleach__Thousand_Year_Blood_War_Arc_sub": (
        "Bleach TYBW",
        "mal-41467",
    ),
    "Bleach__Thousand_Year_Blood_War___The_Conflict_sub": (
        "Bleach TYBW Soukoku-tan",
        "mal-56784",
    ),
    "Bleach__Thousand_Year_Blood_War___The_Separation_sub": (
        "Bleach TYBW Ketsubetsu-tan",
        "mal-53998",
    ),
    "Ragna_Crimson_sub": ("Ragna Crimson", "mal-51297"),
    "Black_Clover_sub": ("Black Clover", "mal-34572"),
    "Fate_Grand_Order__Absolute_Demonic_Front___Babylonia_sub": (
        "Fate Grand Order Babylonia",
        "mal-38084",
    ),
    "Fate_Grand_Order__Divine_Realm_of_the_Round_Table___Camelot_Paladin__Agateram_sub": (
        "Fate Grand Order Camelot 2 Paladin Agateram",
        "mal-38086",
    ),
    "Fate_Grand_Order__Divine_Realm_of_the_Round_Table___Camelot_Wandering__Agateram_sub": (
        "Fate Grand Order Camelot 1 Wandering Agateram",
        "mal-38085",
    ),
    "Fate_Grand_Order__Final_Singularity___Grand_Temple_of_Time__Solomon_sub": (
        "Fate Grand Order Solomon",
        "mal-41497",
    ),
    "Fate_stay_night__Unlimited_Blade_Works_2nd_Season_sub": (
        "Fate stay night UBW 2nd Season",
        "mal-28701",
    ),
    "Fate_stay_night__Unlimited_Blade_Works_Prologue_sub": (
        "Fate stay night UBW Prologue",
        "mal-27821",
    ),
    "Fate_stay_night__Unlimited_Blade_Works_sub": (
        "Fate stay night UBW",
        "mal-22297",
    ),
    "Fate_stay_night_Movie__Heaven_s_Feel___I__Presage_Flower_sub": (
        "Fate Heaven's Feel I Presage Flower",
        "mal-25537",
    ),
    "Fate_stay_night_Movie__Heaven_s_Feel___II__Lost_Butterfly_sub": (
        "Fate Heaven's Feel II Lost Butterfly",
        "mal-33049",
    ),
    "Fate_stay_night_Movie__Heaven_s_Feel___III__Spring_Song_sub": (
        "Fate Heaven's Feel III Spring Song",
        "mal-33050",
    ),
    "Fate_Zero_Season_2_sub": ("Fate Zero 2nd Season", "mal-11741"),
    "Fate_Zero_sub": ("Fate Zero", "mal-10087"),
    "Gachiakuta_sub": ("Gachiakuta", "mal-59062"),
    "Gurren_Lagann_sub": ("Tengen Toppa Gurren Lagann", "mal-2001"),
    "Gurren_Lagann_The_Movie__Childhood_s_End_sub": (
        "Gurren Lagann Movie Childhoods End",
        "mal-4106",
    ),
    "Gurren_Lagann_The_Movie__The_Lights_in_the_Sky_are_Stars_sub": (
        "Gurren Lagann Movie Lights in the Sky",
        "mal-7311",
    ),
    "Hunter_x_Hunter__2011__sub": ("Hunter x Hunter 2011", "mal-11061"),
    "Maid_Sama___It_s_an_Extra__sub": ("Kaichou wa Maid-sama Omake", "mal-9366"),
    "Maid_Sama__Play_with_Your_Husband___sub": (
        "Kaichou wa Maid-sama Goshujinsama",
        "mal-10298",
    ),
    "Maid_Sama__sub": ("Kaichou wa Maid-sama", "mal-7054"),
    "Mushoku_Tensei__Jobless_Reincarnation_Season_3_sub": (
        "Mushoku Tensei III Isekai Ittara Honki Dasu",
        "mal-59193",
    ),
    "Nanbaka__Idiots_with_Student_Numbers__sub": (
        "Nanbaka Idiots with Student Numbers",
        None,
    ),
    "Nanbaka_2_sub": ("Nanbaka 2", "mal-34414"),
    "Nanbaka_sub": ("Nanbaka", "mal-30016"),
    "Re_ZERO__Starting_Life_in_Another_World__Memory_Snow_sub": (
        "Re Zero Memory Snow",
        "mal-36286",
    ),
    "Re_ZERO__Starting_Life_in_Another_World__Season_2_Part_2_sub": (
        "Re Zero Season 2 Part 2",
        "mal-42203",
    ),
    "Re_ZERO__Starting_Life_in_Another_World__Season_2_sub": (
        "Re Zero Season 2",
        "mal-39587",
    ),
    "Re_ZERO__Starting_Life_in_Another_World__Season_3_sub": (
        "Re Zero Season 3",
        "mal-54857",
    ),
    "Re_ZERO__Starting_Life_in_Another_World__sub": (
        "Re Zero Season 1",
        "mal-31240",
    ),
    "Re_ZERO__Starting_Life_in_Another_World__The_Frozen_Bond_sub": (
        "Re Zero Hyouketsu no Kizuna",
        "mal-38414",
    ),
    # Season 4 may already live under anime root (no inbox folder required for link repair)
    "Re_ZERO__Starting_Life_in_Another_World__Season_4_sub": (
        "Re Zero Season 4",
        "mal-61316",
    ),
    "Sakamoto_Days_Part_2_sub": ("Sakamoto Days", "mal-58939", 11),
    "Sakamoto_Days_sub": ("Sakamoto Days", "mal-58939", 0),
    "Steins_Gate__The_Movie___Load_Region_of_D_j__Vu_sub": (
        "Steins Gate Movie Deja Vu",
        "mal-11577",
    ),
    "Steins_Gate_0_sub": ("Steins Gate 0", "mal-30484"),
    "Steins_Gate_sub": ("Steins Gate", "mal-9253"),
    "Takopi_s_Original_Sin_sub": ("Takopi no Genzai", "mal-60489"),
    "That_Time_I_Got_Reincarnated_as_a_Slime_OAD_sub": (
        "Tensei Slime OVA",
        "mal-38793",
    ),
    "That_Time_I_Got_Reincarnated_as_a_Slime_Season_2_Part_2_sub": (
        "Tensei Slime 2nd Season Part 2",
        "mal-41487",
    ),
    "That_Time_I_Got_Reincarnated_as_a_Slime_Season_2_sub": (
        "Tensei Slime 2nd Season",
        "mal-39551",
    ),
    "That_Time_I_Got_Reincarnated_as_a_Slime_sub": (
        "Tensei Slime Season 1",
        "mal-37430",
    ),
    # --- 2026-07-27 inbox batch ---
    "Akame_ga_Kill_sub": ("Akame ga Kill!", "mal-22199"),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World__sub": (
        "KonoSuba Season 1",
        "mal-30831",
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World____God_s_Blessing_on_This_Wonderful_Choker__sub": (
        "KonoSuba Choker OVA",
        "mal-32380",  # was wrongly mal-31964 (Boku no Hero Academia)
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World__2_sub": (
        "KonoSuba Season 2",
        "mal-32937",
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World__2___God_s_Blessing_on_This_Wonderful_Art__sub": (
        "KonoSuba Art OVA",
        "mal-34626",
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World____Legend_of_Crimson_sub": (
        "KonoSuba Legend of Crimson",
        "mal-38040",
    ),
    "KonoSuba__An_Explosion_on_This_Wonderful_World__sub": (
        "KonoSuba An Explosion on This Wonderful World",
        "mal-51958",
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World__3_sub": (
        "KonoSuba Season 3",
        "mal-49458",
    ),
    "KonoSuba__God_s_Blessing_on_This_Wonderful_World__3_OVA_sub": (
        "KonoSuba Season 3 OVA",
        "mal-55701",
    ),
    "Chainsaw_Man_sub": ("Chainsaw Man", "mal-44511"),
    "Code_Geass__Lelouch_of_the_Rebellion_sub": (
        "Code Geass Lelouch of the Rebellion",
        "mal-1575",
    ),
    "Code_Geass__Lelouch_of_the_Rebellion_R2_sub": (
        "Code Geass Lelouch of the Rebellion R2",
        "mal-2904",
    ),
    "Code_Geass__Roz__of_the_Recapture_sub": (
        "Code Geass Roze of the Recapture",
        "mal-56835",
    ),
    "Gintama_sub": ("Gintama", "mal-918"),
    "Gintama_Season_2_sub": ("Gintama Season 2", "mal-9969"),
    "Gintama_Season_4_sub": ("Gintama Season 4", "mal-28977"),
    "Gintama_Season_5_sub": ("Gintama Season 5", "mal-34096"),
    "Gintama__Enchousen_sub": ("Gintama Enchousen", "mal-15417"),
    "Gintama__The_Final_sub": ("Gintama The Final", "mal-39486"),
    "Gintama__The_Semi_Final_sub": ("Gintama The Semi-Final", "mal-44087"),
    "Gintama___Silver_Soul_Arc_sub": (
        "Gintama Silver Soul Arc",
        "mal-36838",
    ),
    "Gintama___Silver_Soul_Arc___Second_Half_War_sub": (
        "Gintama Silver Soul Arc Second Half",
        "mal-37491",
    ),
    "Gintama__3_Z_Ginpachi_Sensei_sub": (
        "Gintama 3-Z Ginpachi-sensei",
        "mal-60572",
    ),
    "Frieren__Beyond_Journey_s_End_sub": (
        "Frieren Beyond Journeys End",
        "mal-52991",
    ),
    "Frieren__Beyond_Journey_s_End_Season_2_sub": (
        "Frieren Beyond Journeys End Season 2",
        "mal-58567",
    ),
    "Mob_Psycho_100_sub": ("Mob Psycho 100", "mal-32182"),
    "Mob_Psycho_100_II_sub": ("Mob Psycho 100 II", "mal-37514"),
    "Mob_Psycho_100_III_sub": ("Mob Psycho 100 III", "mal-50172"),
    "Vinland_Saga_sub": ("Vinland Saga", "mal-37521"),
    "Vinland_Saga__2nd_Season_sub": ("Vinland Saga Season 2", "mal-49387"),
}

EP_PATTERN = re.compile(r"^(\d+)Ep\.(\w+)$", re.IGNORECASE)
SKIP_EXT = {".part", ".crdownload"}


def _map_entry(value: tuple) -> tuple[str, str | None, int]:
    if len(value) == 2:
        return value[0], value[1], 0
    return value[0], value[1], value[2]


def parse_episode(filename: str) -> tuple[int, str] | None:
    m = EP_PATTERN.match(filename)
    if not m:
        return None
    return int(m.group(1)), f".{m.group(2).lower()}"


def target_name(ep: int, ext: str) -> str:
    return f"S01E{ep:02d}{ext}"


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def save_catalog(data: dict) -> None:
    CATALOG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def ensure_catalog_folder(catalog_id: str | None, folder_name: str) -> bool:
    if not catalog_id:
        return False
    data = load_catalog()
    shows = data.get("shows", [])
    updated = False
    for show in shows:
        if show.get("id") == catalog_id:
            if show.get("folder") != folder_name:
                show["folder"] = folder_name
                updated = True
            break
    else:
        # add minimal entry if missing (mal id from catalog_id)
        mal_id = int(catalog_id.replace("mal-", ""))
        shows.append(
            {
                "id": catalog_id,
                "enabled": True,
                "source": "mal",
                "folder": folder_name,
                "mal_id": mal_id,
                "title": folder_name,
            }
        )
        data["shows"] = shows
        updated = True
    if updated:
        save_catalog(data)
    return updated


def clear_catalog_folder_if(catalog_id: str, folder_name: str) -> bool:
    """Clear a wrongly attached folder (e.g. after a bad FOLDER_MAP id)."""
    data = load_catalog()
    updated = False
    for show in data.get("shows", []):
        if show.get("id") == catalog_id and show.get("folder") == folder_name:
            show.pop("folder", None)
            updated = True
            break
    if updated:
        save_catalog(data)
    return updated


def repair_catalog_folders(*, media_root: Path | None = None) -> dict:
    """Link catalog entries to existing anime folders via FOLDER_MAP (no file copies)."""
    root = media_root or MEDIA_ROOT
    linked: list[str] = []
    created: list[str] = []
    unchanged: list[str] = []
    skipped_missing_dir: list[str] = []

    # Undo known bad link from previous Choker OVA -> mal-31964 typo
    if clear_catalog_folder_if("mal-31964", "KonoSuba Choker OVA"):
        linked.append("cleared mal-31964 <- KonoSuba Choker OVA")

    for _src, val in FOLDER_MAP.items():
        folder_name, catalog_id, _off = _map_entry(val)
        if not catalog_id:
            continue
        if not (root / folder_name).is_dir():
            skipped_missing_dir.append(f"{catalog_id} -> {folder_name}")
            continue

        data = load_catalog()
        existing = next(
            (s for s in data.get("shows", []) if s.get("id") == catalog_id),
            None,
        )
        existed = existing is not None
        already = bool(existing and existing.get("folder") == folder_name)
        if already:
            unchanged.append(f"{catalog_id} -> {folder_name}")
            continue
        if ensure_catalog_folder(catalog_id, folder_name):
            if existed:
                linked.append(f"{catalog_id} -> {folder_name}")
            else:
                created.append(f"{catalog_id} -> {folder_name}")

    return {
        "linked": linked,
        "created": created,
        "unchanged": unchanged,
        "skipped_missing_dir": skipped_missing_dir,
    }


def _delete_source(src_file: Path, deleted: list[str], conflicts: list[str]) -> None:
    try:
        src_file.unlink()
        deleted.append(str(src_file))
        print(f" - deleted source {src_file.name}", flush=True)
    except OSError as err:
        conflicts.append(f"delete failed {src_file}: {err}")


def import_all(*, delete_after_copy: bool = False) -> dict:
    imported: list[str] = []
    skipped: list[str] = []
    deleted: list[str] = []
    conflicts: list[str] = []
    unmapped: list[str] = []
    catalog_updates: list[str] = []

    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name not in FOLDER_MAP:
            unmapped.append(name)
            continue
        folder_name, catalog_id, ep_offset = _map_entry(FOLDER_MAP[name])
        dest_dir = MEDIA_ROOT / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        if ensure_catalog_folder(catalog_id, folder_name):
            catalog_updates.append(f"{catalog_id} -> {folder_name}")

        for src_file in sorted(src_dir.iterdir()):
            if not src_file.is_file():
                continue
            if src_file.suffix.lower() in SKIP_EXT or src_file.stat().st_size == 0:
                continue
            parsed = parse_episode(src_file.name)
            if not parsed:
                conflicts.append(f"{src_file}: unknown episode name")
                continue
            ep, ext = parsed
            dest_file = dest_dir / target_name(ep + ep_offset, ext)
            src_size = src_file.stat().st_size
            if dest_file.exists():
                if dest_file.stat().st_size == src_size:
                    skipped.append(str(dest_file.name) + f" ({folder_name})")
                    # Duplicate in inbox — remove source when requested
                    if delete_after_copy:
                        _delete_source(src_file, deleted, conflicts)
                    continue
                conflicts.append(
                    f"{dest_file.name} in {folder_name}: size mismatch "
                    f"(local {dest_file.stat().st_size} vs {src_size})"
                )
                continue
            copied = False
            last_err: OSError | None = None
            for attempt in range(5):
                try:
                    shutil.copy2(src_file, dest_file)
                    copied = True
                    break
                except OSError as err:
                    last_err = err
                    # WinError 32 / sharing violation — brief retry
                    if attempt < 4:
                        time.sleep(1.5 * (attempt + 1))
            if not copied:
                conflicts.append(
                    f"{src_file.name} -> {folder_name}/{dest_file.name}: "
                    f"copy failed ({last_err})"
                )
                continue
            # Verify size before treating as success / deleting source
            try:
                dest_size = dest_file.stat().st_size
            except OSError as err:
                conflicts.append(
                    f"{folder_name}/{dest_file.name}: verify failed ({err})"
                )
                continue
            if dest_size != src_size:
                conflicts.append(
                    f"{folder_name}/{dest_file.name}: size verify failed "
                    f"(dest {dest_size} vs src {src_size})"
                )
                continue
            imported.append(f"{folder_name}/{dest_file.name}")
            print(f" + {folder_name}/{dest_file.name}", flush=True)
            if delete_after_copy:
                _delete_source(src_file, deleted, conflicts)

    return {
        "imported": imported,
        "skipped": skipped,
        "deleted": deleted,
        "conflicts": conflicts,
        "unmapped": unmapped,
        "catalog_updates": catalog_updates,
    }


if __name__ == "__main__":
    import sys

    args = set(sys.argv[1:])
    if args & {"--repair-catalog", "repair"}:
        result = repair_catalog_folders()
        print("LINKED:", len(result["linked"]))
        print("CREATED:", len(result["created"]))
        print("UNCHANGED:", len(result["unchanged"]))
        print("SKIPPED (no dir):", len(result["skipped_missing_dir"]))
        for line in result["linked"]:
            print(" ~", line)
        for line in result["created"]:
            print(" +", line)
        for line in result["skipped_missing_dir"]:
            print(" !", line)
        raise SystemExit(0)

    delete_after = "--delete-after-copy" in args
    result = import_all(delete_after_copy=delete_after)
    print("IMPORTED:", len(result["imported"]))
    print("SKIPPED:", len(result["skipped"]))
    print("DELETED:", len(result["deleted"]))
    print("CONFLICTS:", len(result["conflicts"]))
    print("UNMAPPED:", result["unmapped"])
    print("CATALOG:", len(result["catalog_updates"]))
    for line in result["imported"][:20]:
        print(" +", line)
    if len(result["imported"]) > 20:
        print(f" ... and {len(result['imported']) - 20} more")
    for c in result["conflicts"][:10]:
        print(" !", c)
    if len(result["conflicts"]) > 10:
        print(f" ... and {len(result['conflicts']) - 10} more conflicts")
