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
        "mal-59833",
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
        None,  # was wrongly mal-60572 (All-devouring Whale); resolve via title match
    ),
    "Frieren__Beyond_Journey_s_End_sub": (
        "Frieren Beyond Journeys End",
        "mal-52991",
    ),
    "Frieren__Beyond_Journey_s_End_Season_2_sub": (
        "Frieren Beyond Journeys End Season 2",
        "mal-59978",  # was wrongly mal-58567 (Solo Leveling S2)
    ),
    "Mob_Psycho_100_sub": ("Mob Psycho 100", "mal-32182"),
    "Mob_Psycho_100_II_sub": ("Mob Psycho 100 II", "mal-37514"),
    "Mob_Psycho_100_III_sub": ("Mob Psycho 100 III", "mal-50172"),
    "Vinland_Saga_sub": ("Vinland Saga", "mal-37521"),
    "Vinland_Saga__2nd_Season_sub": ("Vinland Saga Season 2", "mal-49387"),
    # --- 2026-07-28 inbox batch (Ghibli + BC movie) ---
    "Black_Clover__Sword_of_the_Wizard_King_sub": (
        "Black Clover Sword of the Wizard King",
        None,  # was wrongly mal-48561 (Jujutsu Kaisen 0); resolve via title match
    ),
    "Spirited_Away_sub": ("Spirited Away", "mal-199"),
    "Princess_Mononoke_sub": ("Princess Mononoke", "mal-164"),
    "Grave_of_the_Fireflies_sub": ("Grave of the Fireflies", "mal-578"),
    "The_Secret_World_of_Arrietty_sub": (
        "The Secret World of Arrietty",
        "mal-7711",
    ),
    "My_Neighbor_Totoro_sub": ("My Neighbor Totoro", "mal-523"),
    "Nausica__of_the_Valley_of_the_Wind_sub": (
        "Nausicaa of the Valley of the Wind",
        "mal-572",
    ),
    "Ponyo_sub": ("Ponyo", "mal-2890"),
    "Kiki_s_Delivery_Service_sub": ("Kikis Delivery Service", "mal-512"),
    "Howl_s_Moving_Castle_sub": ("Howls Moving Castle", "mal-431"),
    "Castle_in_the_Sky_sub": ("Castle in the Sky", "mal-513"),
    # --- 2026-07-28 missing inbox mappings ---
    "Ao_no_Exorcist__Ura_Ex_sub": ("Blue Exorcist Ura Ex", None),
    "Blood_Lad_sub": ("Blood Lad", None),
    "Blue_Exorcist_sub": ("Blue Exorcist", None),
    "Blue_Exorcist_The_Movie_sub": ("Blue Exorcist The Movie", None),
    "Blue_Exorcist__Beyond_the_Snow_Saga_sub": (
        "Blue Exorcist Beyond the Snow Saga",
        None,
    ),
    "Blue_Exorcist__Kyoto_Saga_sub": ("Blue Exorcist Kyoto Saga", None),
    "Blue_Exorcist__Shimane_Illuminati_Saga_sub": (
        "Blue Exorcist Shimane Illuminati Saga",
        None,
    ),
    "Blue_Exorcist__The_Blue_Night_Saga_sub": (
        "Blue Exorcist The Blue Night Saga",
        None,
    ),
    "Chainsaw_Man_the_Movie__Reze_Arc_sub": (
        "Chainsaw Man The Movie Reze Arc",
        None,
    ),
    "Demon_Slayer_Movie__Mugen_Train_sub": (
        "Demon Slayer Mugen Train Movie",
        "mal-40456",
    ),
    "Demon_Slayer__Entertainment_District_Arc_sub": (
        "Demon Slayer Entertainment District Arc",
        "mal-47778",
    ),
    "Demon_Slayer__Kimetsu_no_Yaiba_Hashira_Training_Arc_sub": (
        "Demon Slayer Hashira Training Arc",
        "mal-55701",
    ),
    "Demon_Slayer__Kimetsu_no_Yaiba_Infinity_Castle_sub": (
        "Demon Slayer Infinity Castle",
        "mal-59192",
    ),
    "Demon_Slayer__Kimetsu_no_Yaiba_Swordsmith_Village_Arc_sub": (
        "Demon Slayer Swordsmith Village Arc",
        "mal-51019",
    ),
    "Demon_Slayer__Kimetsu_no_Yaiba___To_the_Swordsmith_Village_sub": (
        "Demon Slayer To the Swordsmith Village",
        None,
    ),
    "Demon_Slayer__Kimetsu_no_Yaiba_sub": (
        "Demon Slayer Kimetsu no Yaiba",
        "mal-38000",
    ),
    "Dragon_Ball_Super__Broly_sub": ("Dragon Ball Super Broly", None),
    "Dragon_Ball_Super__Super_Hero_sub": ("Dragon Ball Super Super Hero", None),
    "Fate_Apocrypha_sub": ("Fate Apocrypha", None),
    "Fate_Extra__Last_Encore___Illustrias_Tendousetsu_sub": (
        "Fate Extra Last Encore Illustrias Tendousetsu",
        None,
    ),
    "Fate_Extra__Last_Encore_sub": ("Fate Extra Last Encore", None),
    "Fate_kaleid_liner_Prisma_Illya__Vow_in_the_Snow_sub": (
        "Fate kaleid liner Prisma Illya Vow in the Snow",
        "mal-34100",
    ),
    "Fate_strange_Fake_sub": ("Fate strange Fake", "mal-55830"),
    "Fate_Grand_Carnival_sub": ("Fate Grand Carnival", "mal-44248"),
    "JoJo_s_Bizarre_Adventure_sub": ("JoJos Bizarre Adventure", "mal-14719"),
    "JoJo_s_Bizarre_Adventure_Part_2__Stardust_Crusaders_sub": (
        "JoJos Bizarre Adventure Stardust Crusaders",
        "mal-20899",
    ),
    "JoJo_s_Bizarre_Adventure_Part_3__Stardust_Crusaders_2nd_Season__Uncensored__sub": (
        "JoJos Bizarre Adventure Stardust Crusaders 2nd Season",
        "mal-26055",
    ),
    "JoJo_s_Bizarre_Adventure_Part_4__Diamond_is_Unbreakable__Uncensored__sub": (
        "JoJos Bizarre Adventure Diamond is Unbreakable",
        "mal-31933",
    ),
    "JoJo_s_Bizarre_Adventure_Part_5__Golden_Wind__Uncensored__sub": (
        "JoJos Bizarre Adventure Golden Wind",
        "mal-37991",
    ),
    "JoJo_s_Bizarre_Adventure_Part_6__Stone_Ocean_sub": (
        "JoJos Bizarre Adventure Stone Ocean",
        "mal-48661",
    ),
    "JoJo_s_Bizarre_Adventure_Part_6__Stone_Ocean_Part_2_sub": (
        "JoJos Bizarre Adventure Stone Ocean Part 2",
        "mal-51367",
    ),
    "JoJo_s_Bizarre_Adventure__Stone_Ocean_Part_3_sub": (
        "JoJos Bizarre Adventure Stone Ocean Part 3",
        "mal-53273",
    ),
    "Jujutsu_Kaisen_0_Movie_sub": ("Jujutsu Kaisen 0 Movie", None),
    "Jujutsu_Kaisen_2nd_Season_sub": ("Jujutsu Kaisen 2nd Season", None),
    "Jujutsu_Kaisen_3rd_Season__The_Culling_Game_Part_1_sub": (
        "Jujutsu Kaisen 3rd Season The Culling Game Part 1",
        None,
    ),
    "Jujutsu_Kaisen__TV__sub": ("Jujutsu Kaisen", None),
    "Kabaneri_of_the_Iron_Fortress_sub": (
        "Kabaneri of the Iron Fortress",
        "mal-28623",
    ),
    "Kabaneri_of_the_Iron_Fortress__The_Battle_of_Unato_sub": (
        "Kabaneri of the Iron Fortress The Battle of Unato",
        "mal-34544",
    ),
    "Koutetsujou_no_Kabaneri_Movie_1__Tsudou_Hikari_sub": (
        "Kabaneri Movie 1 Tsudou Hikari",
        "mal-33519",
    ),
    "Magi__Adventure_of_Sinbad_sub": ("Magi Adventure of Sinbad", "mal-31741"),
    "Magi__Sinbad_no_Bouken_sub": ("Magi Sinbad no Bouken", "mal-22097"),  # OVA
    "Magi__The_Kingdom_of_Magic_sub": ("Magi The Kingdom of Magic", "mal-18115"),
    "Mashle__Magic_and_Muscles_sub": ("Mashle Magic and Muscles", None),
    "My_Hero_Academia_sub": ("My Hero Academia", None),
    "My_Hero_Academia_2_sub": ("My Hero Academia Season 2", None),
    "My_Hero_Academia_3_sub": ("My Hero Academia Season 3", None),
    "My_Hero_Academia_5th_Season_sub": ("My Hero Academia Season 5", None),
    "My_Hero_Academia_Season_6_sub": ("My Hero Academia Season 6", None),
    "My_Hero_Academia_Season_7_sub": ("My Hero Academia Season 7", None),
    "One_Piece_Film__Red_sub": ("One Piece Film Red", None),
    "One_Piece__The_Movie_13___Film__Gold_sub": ("One Piece Film Gold", None),
    "One_Piece__The_Movie_14___Stampede_sub": ("One Piece Stampede", None),
    "Overlord_sub": ("Overlord", "mal-29803"),
    "Overlord_II_sub": ("Overlord II", "mal-35073"),
    "Overlord_III_sub": ("Overlord III", "mal-37675"),
    "Overlord_Movie_1__The_Undead_King_sub": (
        "Overlord Movie 1 The Undead King",
        "mal-34161",
    ),
    "Overlord_Movie_2__The_Dark_Hero_sub": (
        "Overlord Movie 2 The Dark Hero",
        "mal-34428",
    ),
    "Pokemon_The_Movie_07__Destiny_Deoxys_sub": ("Pokemon Destiny Deoxys", None),
    "Pokemon_The_Movie_10__The_Rise_Of_Darkrai_sub": (
        "Pokemon The Rise of Darkrai",
        None,
    ),
    "Pokemon_The_Movie_12__Arceus_and_the_Jewel_of_Life_sub": (
        "Pokemon Arceus and the Jewel of Life",
        None,
    ),
    "Pokemon_The_Movie_13__Zoroark__Master_of_Illusions_sub": (
        "Pokemon Zoroark Master of Illusions",
        None,
    ),
    "Pokemon_the_Movie_14__Black___Victini_and_Reshiram_sub": (
        "Pokemon Black Victini and Reshiram",
        None,
    ),
    "Pokemon_the_Movie_14__White___Victini_and_Zekrom_sub": (
        "Pokemon White Victini and Zekrom",
        None,
    ),
    "Pokemon_the_Movie_15__Kyurem_VS__The_Sword_of_Justice_sub": (
        "Pokemon Kyurem vs The Sword of Justice",
        None,
    ),
    "Pokemon_the_Movie_18__Hoopa_and_the_Clash_of_Ages_sub": (
        "Pokemon Hoopa and the Clash of Ages",
        None,
    ),
    "Shangri_La_Frontier_sub": ("Shangri-La Frontier", None),
    "Shangri_La_Frontier_Season_2_sub": ("Shangri-La Frontier Season 2", None),
    "Shangri_La_Frontier_Special_sub": ("Shangri-La Frontier Special", None),
    "Steel_Ball_Run__JoJo_s_Bizarre_Adventure_sub": (
        "Steel Ball Run JoJos Bizarre Adventure",
        "mal-61469",
    ),
    "The_Demon_Slayer__Kimetsu_no_Yaiba_Mugen_Train_Arc_TV_sub": (
        "Demon Slayer Mugen Train Arc TV",
        "mal-49926",
    ),
    "Tokyo_Ghoul_sub": ("Tokyo Ghoul", None),
    "Your_Name_sub": ("Your Name", None),
}

EP_PATTERN = re.compile(r"^(\d+)Ep\.(\w+)$", re.IGNORECASE)
# Inbox sidecars: ``1Ep.en.vtt``, ``12Ep.vtt``, ``3Ep.de.forced.vtt``
VTT_PATTERN = re.compile(
    r"^(\d+)Ep(?:\.([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*))?\.vtt$",
    re.IGNORECASE,
)
VIDEO_EXTS = {".mp4", ".mkv", ".webm"}
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


def parse_vtt_sidecar(filename: str) -> tuple[int, str] | None:
    """Return ``(episode_number, dest_suffix)`` e.g. ``(1, '.en.vtt')``."""
    m = VTT_PATTERN.match(filename)
    if not m:
        return None
    ep = int(m.group(1))
    rest = (m.group(2) or "").strip(".")
    if rest:
        return ep, f".{rest.lower()}.vtt"
    return ep, ".vtt"


def target_name(ep: int, ext: str) -> str:
    return f"S01E{ep:02d}{ext}"


def _video_exists_for_episode(dest_dir: Path, ep: int) -> bool:
    stem = f"S01E{ep:02d}"
    return any((dest_dir / f"{stem}{ext}").is_file() for ext in VIDEO_EXTS)


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


def _copy_verified(
    src_file: Path,
    dest_file: Path,
    *,
    folder_name: str,
    imported: list[str],
    skipped: list[str],
    deleted: list[str],
    conflicts: list[str],
    delete_after_copy: bool,
) -> None:
    src_size = src_file.stat().st_size
    if dest_file.exists():
        if dest_file.stat().st_size == src_size:
            skipped.append(f"{dest_file.name} ({folder_name})")
            if delete_after_copy:
                _delete_source(src_file, deleted, conflicts)
            return
        conflicts.append(
            f"{dest_file.name} in {folder_name}: size mismatch "
            f"(local {dest_file.stat().st_size} vs {src_size})"
        )
        return
    copied = False
    last_err: OSError | None = None
    for attempt in range(5):
        try:
            shutil.copy2(src_file, dest_file)
            copied = True
            break
        except OSError as err:
            last_err = err
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
    if not copied:
        conflicts.append(
            f"{src_file.name} -> {folder_name}/{dest_file.name}: "
            f"copy failed ({last_err})"
        )
        return
    try:
        dest_size = dest_file.stat().st_size
    except OSError as err:
        conflicts.append(f"{folder_name}/{dest_file.name}: verify failed ({err})")
        return
    if dest_size != src_size:
        conflicts.append(
            f"{folder_name}/{dest_file.name}: size verify failed "
            f"(dest {dest_size} vs src {src_size})"
        )
        return
    imported.append(f"{folder_name}/{dest_file.name}")
    print(f" + {folder_name}/{dest_file.name}", flush=True)
    if delete_after_copy:
        _delete_source(src_file, deleted, conflicts)


def import_subtitles(*, delete_after_copy: bool = False) -> dict:
    """Copy inbox WebVTT sidecars next to matching library episodes.

    Inbox: ``…/<Show>_sub/subs/12Ep.en.vtt`` →
    ``anime/<Show>/S01E12.en.vtt`` (only when the episode video exists).
    """
    imported: list[str] = []
    skipped: list[str] = []
    deleted: list[str] = []
    conflicts: list[str] = []
    unmapped: list[str] = []
    no_video: list[str] = []

    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    for src_dir in sorted(DOWNLOADS.iterdir()):
        if not src_dir.is_dir():
            continue
        name = src_dir.name
        if name not in FOLDER_MAP:
            if any(src_dir.rglob("*.vtt")):
                unmapped.append(name)
            continue
        folder_name, _catalog_id, ep_offset = _map_entry(FOLDER_MAP[name])
        dest_dir = MEDIA_ROOT / folder_name
        if not dest_dir.is_dir():
            conflicts.append(f"{name}: library folder missing ({folder_name})")
            continue

        for src_file in sorted(src_dir.rglob("*.vtt")):
            if not src_file.is_file() or src_file.stat().st_size == 0:
                continue
            parsed = parse_vtt_sidecar(src_file.name)
            if not parsed:
                conflicts.append(f"{src_file}: unknown VTT name")
                continue
            ep_num, suffix = parsed
            ep = ep_num + ep_offset
            if not _video_exists_for_episode(dest_dir, ep):
                no_video.append(f"{folder_name}/S01E{ep:02d}{suffix}")
                continue
            dest_file = dest_dir / target_name(ep, suffix)
            _copy_verified(
                src_file,
                dest_file,
                folder_name=folder_name,
                imported=imported,
                skipped=skipped,
                deleted=deleted,
                conflicts=conflicts,
                delete_after_copy=delete_after_copy,
            )

    return {
        "imported": imported,
        "skipped": skipped,
        "deleted": deleted,
        "conflicts": conflicts,
        "unmapped": unmapped,
        "no_video": no_video,
    }


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
            if src_file.suffix.lower() == ".vtt":
                continue  # handled by import_subtitles (also under subs/)
            parsed = parse_episode(src_file.name)
            if not parsed:
                conflicts.append(f"{src_file}: unknown episode name")
                continue
            ep, ext = parsed
            if ext.lower() not in VIDEO_EXTS:
                conflicts.append(f"{src_file}: skipped non-video {ext}")
                continue
            dest_file = dest_dir / target_name(ep + ep_offset, ext)
            _copy_verified(
                src_file,
                dest_file,
                folder_name=folder_name,
                imported=imported,
                skipped=skipped,
                deleted=deleted,
                conflicts=conflicts,
                delete_after_copy=delete_after_copy,
            )

    subs = import_subtitles(delete_after_copy=delete_after_copy)
    imported.extend(subs["imported"])
    skipped.extend(subs["skipped"])
    deleted.extend(subs["deleted"])
    conflicts.extend(subs["conflicts"])

    return {
        "imported": imported,
        "skipped": skipped,
        "deleted": deleted,
        "conflicts": conflicts,
        "unmapped": unmapped,
        "catalog_updates": catalog_updates,
        "subs_no_video": subs.get("no_video", []),
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
    if args & {"--subs-only", "subs"}:
        result = import_subtitles(delete_after_copy=delete_after)
        print("SUBS IMPORTED:", len(result["imported"]))
        print("SUBS SKIPPED:", len(result["skipped"]))
        print("SUBS DELETED:", len(result["deleted"]))
        print("SUBS CONFLICTS:", len(result["conflicts"]))
        print("SUBS NO VIDEO:", len(result["no_video"]))
        print("UNMAPPED:", result["unmapped"])
        for line in result["imported"][:30]:
            print(" +", line)
        if len(result["imported"]) > 30:
            print(f" ... and {len(result['imported']) - 30} more")
        for c in result["conflicts"][:15]:
            print(" !", c)
        for line in result["no_video"][:10]:
            print(" ? no video for", line)
        raise SystemExit(0)

    result = import_all(delete_after_copy=delete_after)
    print("IMPORTED:", len(result["imported"]))
    print("SKIPPED:", len(result["skipped"]))
    print("DELETED:", len(result["deleted"]))
    print("CONFLICTS:", len(result["conflicts"]))
    print("UNMAPPED:", result["unmapped"])
    print("CATALOG:", len(result["catalog_updates"]))
    print("SUBS NO VIDEO:", len(result.get("subs_no_video", [])))
    for line in result["imported"][:20]:
        print(" +", line)
    if len(result["imported"]) > 20:
        print(f" ... and {len(result['imported']) - 20} more")
    for c in result["conflicts"][:10]:
        print(" !", c)
    if len(result["conflicts"]) > 10:
        print(f" ... and {len(result['conflicts']) - 10} more conflicts")
