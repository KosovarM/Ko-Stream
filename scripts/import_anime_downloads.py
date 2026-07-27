"""Import unsorted inbox -> D:\\Media\\Ko-Stream\\anime (S01Exx naming)."""

from __future__ import annotations

import json
import os
import re
import shutil
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
    "Bleach__Thousand_Year_Blood_War___The_Conflict_sub": (
        "Bleach TYBW Soukoku-tan",
        "mal-56784",
    ),
    "Bleach__Thousand_Year_Blood_War___The_Separation_sub": (
        "Bleach TYBW Ketsubetsu-tan",
        "mal-53998",
    ),
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


def import_all() -> dict:
    imported: list[str] = []
    skipped: list[str] = []
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
                    continue
                conflicts.append(
                    f"{dest_file.name} in {folder_name}: size mismatch "
                    f"(local {dest_file.stat().st_size} vs {src_size})"
                )
                continue
            shutil.copy2(src_file, dest_file)
            imported.append(f"{folder_name}/{dest_file.name}")

    return {
        "imported": imported,
        "skipped": skipped,
        "conflicts": conflicts,
        "unmapped": unmapped,
        "catalog_updates": catalog_updates,
    }


if __name__ == "__main__":
    result = import_all()
    print("IMPORTED:", len(result["imported"]))
    print("SKIPPED:", len(result["skipped"]))
    print("CONFLICTS:", len(result["conflicts"]))
    print("UNMAPPED:", result["unmapped"])
    print("CATALOG:", len(result["catalog_updates"]))
    for line in result["imported"][:20]:
        print(" +", line)
    if len(result["imported"]) > 20:
        print(f" ... and {len(result['imported']) - 20} more")
    for c in result["conflicts"][:10]:
        print(" !", c)
