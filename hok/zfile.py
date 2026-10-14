
from .zutil import *


def load_agent_artifact_image(identifier):
    """Read an already validated, locally stored agent PNG by opaque ID."""
    import re
    from pathlib import Path
    from PIL import Image
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Invalid agent artifact")
    path = Path(temp_path) / ("chat_plot_" + identifier + ".png")
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("Agent artifact exceeds image size limit")
    with Image.open(path) as image:
        if image.format != "PNG" or image.width * image.height > 16_000_000:
            raise ValueError("Unsupported agent output image")
        image.load()
        width, height = image.size
    return {"raw": path.read_bytes(), "width": width, "height": height}


def store_agent_artifact(identifier, raw):
    """Save validated agent output as a trace-compatible PNG in file_transfer."""
    import io
    import re
    from pathlib import Path
    from PIL import Image

    if not re.fullmatch(r"[a-f0-9]{32}", identifier) or len(raw) > 32 * 1024**2:
        raise ValueError("Invalid agent artifact")
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in {"PNG", "JPEG", "WEBP"} or source.width * source.height > 16_000_000:
            raise ValueError("Unsupported agent output image")
        source.load()
        image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        directory = Path(temp_path)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("chat_plot_" + identifier + ".png")
        image.save(path, "PNG")
        return {"artifact_id": identifier, "path": str(path), "width": image.width, "height": image.height}
from .zstatic import *
from . import zdynamic as dmc
import shutil
import os
import io
import hashlib
import requests

def readera(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = file.read()
        return str(data)
    except FileNotFoundError:
        return ""
def writera(filepath,data):
    try:
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(data)
        return None
    except Exception as e:
        return None

def readerl(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []


def read_history_date(target_date):
    """Read one daily history payload from PostgreSQL, with JSON archive fallback."""
    try:
        from .zdb import read_history_date as read_history_date_from_db

        database_payload = read_history_date_from_db(target_date)
        if database_payload:
            return database_payload
    except Exception as exc:
        log_message(f"POSTGRES_HISTORY_READ_FALLBACK: date={target_date} error={repr(exc)}", logging.WARNING)
    return readerl(os.path.join(data_root, "history", f"{target_date}.json"))


def list_history_archive_dates_descending():
    """List only daily JSON history archives, without consulting PostgreSQL."""
    history_dir = os.path.join(data_root, "history")
    if not os.path.isdir(history_dir):
        return []
    dates = []
    for filename in os.listdir(history_dir):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", filename)
        if match and os.path.isfile(os.path.join(history_dir, filename)):
            dates.append(match.group(1))
    return sorted(dates, reverse=True)


def read_history_archive_date(target_date):
    """Read one emergency daily JSON archive without a database lookup."""
    return readerl(os.path.join(data_root, "history", f"{target_date}.json"))


def daily_history_path(target_date):
    return os.path.join(data_root, "history", f"{target_date}.json")


def personal_history_path(target_date, userid):
    return os.path.join(
        data_root,
        "history",
        "personal",
        str(target_date),
        f"{userid}.json",
    )


def battle_detail_path(gameseq):
    return os.path.join(data_root, "history", "battles", f"{gameseq}.json")


def read_honor_districts():
    """Read the honor-rank district tree through the project's IO boundary."""
    return readerl(os.path.join(data_root, "honor", "districts.json"))


def read_emoji_reference():
    return readerl("emojiref.json")


def read_dynamic_variables():
    return dict(dynamic_variables)


def news_text_path(target_date):
    return os.path.join(data_root, "news", f"{target_date}.txt")


def hero_rank_archive_path(target_date):
    return os.path.join(data_root, "herorank", f"{target_date}.json")


def hero_tier_archive_path(target_date):
    return os.path.join(data_root, "herotier", f"{target_date}.json")


def list_history_dates_descending(start_date=None):
    """Return database history dates, with the JSON archive as fallback."""
    try:
        from .zdb import list_history_dates_descending as list_history_dates_from_db

        database_dates = list_history_dates_from_db(start_date=start_date)
        if database_dates:
            return database_dates
    except Exception as exc:
        log_message(f"POSTGRES_HISTORY_DATES_FALLBACK: start={start_date} error={repr(exc)}", logging.WARNING)
    history_dir = os.path.join(data_root, "history")
    if not os.path.isdir(history_dir):
        return []
    dates = []
    for filename in os.listdir(history_dir):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", filename)
        if not match:
            continue
        history_date = match.group(1)
        if start_date and history_date < str(start_date):
            continue
        if os.path.isfile(os.path.join(history_dir, filename)):
            dates.append(history_date)
    return sorted(dates, reverse=True)


def read_battle_detail(gameseq):
    """Read one battle detail from PostgreSQL, with JSON archive fallback."""
    try:
        from .zdb import read_battle_detail as read_battle_detail_from_db

        database_payload = read_battle_detail_from_db(gameseq)
        if database_payload:
            return database_payload
    except Exception as exc:
        log_message(f"POSTGRES_BATTLE_READ_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
    return readerl(os.path.join(data_root, "history", "battles", f"{gameseq}.json"))


def read_personal_history(target_date, userid):
    """Read a personal snapshot from PostgreSQL, with JSON archive fallback."""
    try:
        from .zdb import read_personal_snapshot

        database_payload = read_personal_snapshot(target_date, userid)
        if database_payload:
            return database_payload
    except Exception as exc:
        log_message(
            f"POSTGRES_PERSONAL_READ_FALLBACK: date={target_date} userid={userid} error={repr(exc)}",
            logging.WARNING,
        )
    return readerl(os.path.join(data_root, "history", "personal", str(target_date), f"{userid}.json"))


def read_hero_tier(target_date):
    """Read one hero-tier snapshot from PostgreSQL, with JSON archive fallback."""
    try:
        from .zdb import read_hero_tier_date

        database_payload = read_hero_tier_date(target_date)
        if database_payload:
            return database_payload
    except Exception as exc:
        log_message(f"POSTGRES_HERO_TIER_READ_FALLBACK: date={target_date} error={repr(exc)}", logging.WARNING)
    return readerl(os.path.join(data_root, "herotier", f"{target_date}.json"))


def read_hero_rank(target_date):
    """Read one hero-rank snapshot from PostgreSQL, with emergency JSON fallback."""
    try:
        from .zdb import read_hero_rank_date

        database_payload = read_hero_rank_date(target_date)
        if database_payload:
            return database_payload
    except Exception as exc:
        log_message(f"POSTGRES_HERO_RANK_READ_FALLBACK: date={target_date} error={repr(exc)}", logging.WARNING)
    return readerl(os.path.join(data_root, "herorank", f"{target_date}.json"))


def battle_detail_exists(gameseq):
    """Check PostgreSQL first and retain compatibility with the JSON archive."""
    try:
        from .zdb import battle_detail_exists as battle_detail_exists_in_db

        if battle_detail_exists_in_db(gameseq):
            return True
    except Exception as exc:
        log_message(f"POSTGRES_BATTLE_EXISTS_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
    return file_exist(os.path.join(data_root, "history", "battles", f"{gameseq}.json"))


def writerl(filepath,data):
    descriptor = classify_postgres_archive_path(filepath)
    if descriptor and not postgres_archive_json:
        sync_result = _sync_postgres_archive(filepath, data)
        if sync_result is not False:
            return None
    try:
        parent_dir = os.path.dirname(str(filepath))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        if descriptor:
            _sync_postgres_archive(filepath, data)
        return None
    except Exception:
        return None


def classify_postgres_archive_path(filepath):
    """Describe a managed JSON archive path without changing the source file."""
    absolute_path = os.path.abspath(str(filepath))
    try:
        data_relative_path = os.path.relpath(
            absolute_path,
            os.path.abspath(data_root),
        ).replace(os.sep, "/")
    except Exception:
        return None
    if data_relative_path == ".." or data_relative_path.startswith("../"):
        return None
    relative_path = f"data/{data_relative_path}"
    match = re.fullmatch(r"data/history/(\d{4}-\d{2}-\d{2})\.json", relative_path)
    if match:
        return {"kind": "history", "date": match.group(1), "source_path": relative_path}
    match = re.fullmatch(r"data/history/battles/(\d+)\.json", relative_path)
    if match:
        return {"kind": "battle", "game_seq": match.group(1), "source_path": relative_path}
    match = re.fullmatch(r"data/history/personal/(\d{4}-\d{2}-\d{2})/(\d+)\.json", relative_path)
    if match:
        return {
            "kind": "personal",
            "date": match.group(1),
            "user_id": match.group(2),
            "source_path": relative_path,
        }
    match = re.fullmatch(r"data/history/power/(\d+)\.json", relative_path)
    if match:
        return {"kind": "power", "game_seq": match.group(1), "source_path": relative_path}
    match = re.fullmatch(r"data/herotier/(\d{4}-\d{2}-\d{2})\.json", relative_path)
    if match:
        return {"kind": "hero_tier", "date": match.group(1), "source_path": relative_path}
    match = re.fullmatch(r"data/herorank/(\d{4}-\d{2}-\d{2})\.json", relative_path)
    if match:
        return {"kind": "hero_rank", "date": match.group(1), "source_path": relative_path}
    return None


def _sync_postgres_archive(filepath, data):
    descriptor = classify_postgres_archive_path(filepath)
    if not descriptor:
        return None
    try:
        from . import zdb

        kind = descriptor["kind"]
        if kind == "history":
            return zdb.replace_history_date(descriptor["date"], data, descriptor["source_path"])
        if kind == "battle":
            return zdb.upsert_battle_detail(descriptor["game_seq"], data, descriptor["source_path"])
        if kind == "personal":
            return zdb.upsert_personal_snapshot(
                descriptor["date"], descriptor["user_id"], data, descriptor["source_path"]
            )
        if kind == "power":
            return zdb.upsert_battle_power(descriptor["game_seq"], data, descriptor["source_path"])
        if kind == "hero_tier":
            return zdb.replace_hero_tier_date(descriptor["date"], data, descriptor["source_path"])
        if kind == "hero_rank":
            return zdb.replace_hero_rank_date(descriptor["date"], data, descriptor["source_path"])
    except Exception as exc:
        log_message(
            f"POSTGRES_ARCHIVE_SYNC_ERROR: path={descriptor['source_path']} error={repr(exc)}",
            logging.ERROR,
        )
        return False
    return False


def list_postgres_archive_files(kinds=None):
    """List importable JSON archives through the project's IO boundary."""
    requested = set(kinds or ("history", "battle", "personal", "power", "hero_tier", "hero_rank"))
    roots = {
        "history": os.path.join(data_root, "history"),
        "battle": os.path.join(data_root, "history", "battles"),
        "personal": os.path.join(data_root, "history", "personal"),
        "power": os.path.join(data_root, "history", "power"),
        "hero_tier": os.path.join(data_root, "herotier"),
        "hero_rank": os.path.join(data_root, "herorank"),
    }
    entries = []
    for kind in requested:
        root = roots.get(kind)
        if not root or not os.path.isdir(root):
            continue
        if kind in {"history", "hero_tier", "hero_rank"}:
            candidates = [os.path.join(root, name) for name in os.listdir(root)]
        else:
            candidates = []
            for current_root, _, filenames in os.walk(root):
                candidates.extend(os.path.join(current_root, name) for name in filenames)
        for path in candidates:
            if not path.endswith(".json") or not os.path.isfile(path):
                continue
            descriptor = classify_postgres_archive_path(path)
            if descriptor and descriptor["kind"] == kind:
                entries.append((path, descriptor))
    return sorted(entries, key=lambda item: item[1]["source_path"])


def postgres_archive_metadata(filepath):
    stat_result = os.stat(filepath)
    return {"size": stat_result.st_size, "mtime_ns": stat_result.st_mtime_ns}

    
def copyfile(src_file,dst_file):
    shutil.copy(src_file,dst_file)
def file_exist(file_path):
    return os.path.exists(file_path)


def existing_absolute_path(file_path):
    """Return an absolute path only when the target file exists."""
    if not file_path or not os.path.exists(file_path):
        return None
    return os.path.abspath(file_path)


def hero_tier_image_path():
    """Return the output path regenerated for every tier query."""
    return os.path.join(temp_path, "temp_files", "hero_tier.png")


def battle_exhibit_image_path(gameseq=None):
    """Return the single-battle exhibit image path.

    A game sequence is used when available so concurrent battle requests do
    not overwrite the image that an earlier request is about to send.
    """
    filename = "exhibit.png" if gameseq is None else f"exhibit_{gameseq}.png"
    return os.path.join(temp_path, "temp_files", filename)


def battle_power_image_path():
    """Return the regenerated battle-power analysis image path."""
    return os.path.join(temp_path, "temp_files", "coplayer_analyses.png")


def battle_power_history_dir():
    return os.path.join(data_root, "history", "power")


def battle_power_history_path(gameseq):
    return os.path.join(battle_power_history_dir(), f"{gameseq}.json")


def battle_power_failed_dir():
    return os.path.join(data_root, "history", "power_failed")


def battle_power_failed_path(gameseq):
    return os.path.join(battle_power_failed_dir(), f"{gameseq}.json")


def battle_power_rank_image_path(filename_hash):
    directory = ensure_dir(os.path.join("resources", "wzry_images", "tmp"))
    return os.path.join(directory, f"power_rank_{filename_hash}.png")


def gametime_rank_image_path(filename_hash):
    directory = ensure_dir(os.path.join("resources", "wzry_images", "tmp"))
    return os.path.join(directory, f"gametime_rank_{filename_hash}.png")


def grade_chart_output_paths():
    directory = os.path.join(temp_path, "wzry_grade_chart")
    return os.path.join(directory, "grade_chart.png"), directory


def watch_battle_shot_path(roleid):
    return os.path.join(temp_path, "wzry_btl_shot", f"{roleid}.png")


def list_hero_skin_names():
    skin_root = os.path.join("resources", "wzry_images", "skins")
    return sorted(
        name
        for name in os.listdir(skin_root)
        if os.path.isdir(os.path.join(skin_root, name))
    )


def list_hero_skin_files(hero_name):
    hero_root = os.path.join("resources", "wzry_images", "skins", str(hero_name))
    return sorted(
        name
        for name in os.listdir(hero_root)
        if os.path.isfile(os.path.join(hero_root, name))
    )


def hero_skin_asset_path(hero_name, skin_file):
    return os.path.join(
        project_root,
        "resources",
        "wzry_images",
        "skins",
        str(hero_name),
        str(skin_file),
    )


def read_hero_skill_descriptions(hero_id):
    payload = readerl(
        os.path.join(
            "resources",
            "wzry_images",
            "hero_skills",
            f"{hero_id}.json",
        )
    )
    return [skill["desc"] for skill in payload["skillList1"]]


def web_history_json_path(filename_hashed):
    """Return the public JSON path for one web history artifact."""
    return os.path.join(temp_path, "temp_files", f"{filename_hashed}.json")


def write_web_history_payload(filename_hashed, payload):
    """Persist one web history payload through the project's IO boundary."""
    json_path = web_history_json_path(filename_hashed)
    ensure_dir(os.path.dirname(json_path))
    writerl(json_path, payload)
    return json_path


def write_daily_history_export(date_text, payload):
    """Persist one daily history export through the archive-aware writer."""
    path = os.path.join(data_root, "history", f"{date_text}.json")
    writerl(path, payload)
    return path


def save_kpl_push_image(image_url, cid, date_text):
    """Download one generated KPL push image into its dated asset directory."""
    day_dir = os.path.join("resources", "wzry_images", "kpl", str(date_text))
    ensure_dir(day_dir)
    local_path = os.path.join(day_dir, f"{cid}.png")
    download_url_to_file(image_url, local_path)
    return local_path


def hero_tier_avatar_cache_path(hero_item):
    """Key one long-lived hero asset by hero id and source URL fingerprint."""
    hero_id = re.sub(r"[^0-9A-Za-z_-]", "", str(hero_item.get("heroId") or "unknown")) or "unknown"
    avatar_url = str(hero_item.get("avatarUrl") or "")
    url_fingerprint = hashlib.sha1(avatar_url.encode("utf-8")).hexdigest()[:12]
    return os.path.join(
        project_root,
        "resources",
        "wzry_images",
        "hero_avatars",
        f"{hero_id}_{url_fingerprint}.img",
    )


def load_hero_tier_avatar_cache(tier_items):
    """Return cached avatar bytes and the hero items still needing download."""
    avatars = {}
    missing_items = []
    for item in tier_items:
        hero_id = str(item.get("heroId"))
        cache_path = hero_tier_avatar_cache_path(item)
        try:
            with open(cache_path, "rb") as file:
                content = file.read()
        except FileNotFoundError:
            content = b""
        if content:
            avatars[hero_id] = content
        else:
            missing_items.append(item)
    return avatars, missing_items


def save_hero_tier_avatar_cache(tier_items, avatar_bytes):
    """Persist newly downloaded avatar bytes through the IO boundary."""
    items_by_id = {str(item.get("heroId")): item for item in tier_items}
    saved = 0
    for hero_id, content in avatar_bytes.items():
        item = items_by_id.get(str(hero_id))
        if not item or not content:
            continue
        cache_path = hero_tier_avatar_cache_path(item)
        ensure_dir(os.path.dirname(cache_path))
        with open(cache_path, "wb") as file:
            file.write(content)
        saved += 1
    return saved


def get_file_list(root_path,end_with):
    file_list=[]
    if os.path.exists(root_path) and os.path.isdir(root_path):
        for filename in os.listdir(root_path):
            if filename.endswith(end_with):
                file_path = os.path.join(root_path, filename)
                file_list.append(file_path)
    return file_list

def ensure_dir(dir_path):
    """Ensure directory exists, otherwise raise."""
    if not dir_path:
        raise Exception("ensure_dir_error: empty dir_path")
    os.makedirs(dir_path, exist_ok=True)
    return dir_path

def copyfile_to_dir(src_file, dst_dir):
    """Copy file to dst_dir, keep basename."""
    ensure_dir(dst_dir)
    dst_file = os.path.join(dst_dir, os.path.basename(src_file))
    shutil.copy(src_file, dst_file)
    return dst_file

def download_url_to_file(url: str, dst_file: str):
    """Download url to dst_file, raise on failure."""
    ensure_dir(os.path.dirname(dst_file))
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dst_file, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
    return dst_file

def append_jsonl(filepath: str, item):
    """Append one json line, raise on failure."""
    ensure_dir(os.path.dirname(filepath))
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False))
        f.write("\n")
    return filepath


def append_hok_exception_log(error_msg, context=None):
    """Append one HOK Exception record to the runtime error log."""
    from .ztime import time_r

    item = {
        "time": time_r().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "HOK Exception",
        "error": str(error_msg),
        "context": context or {},
    }
    return append_jsonl(os.path.join(log_root, "error.log"), item)


def first_existing_path(paths):
    """Return the first existing path from an ordered candidate list."""
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def save_pil_image(image, filepath, **save_options):
    """Persist a Pillow image through the project's IO boundary."""
    parent = os.path.dirname(str(filepath))
    if parent:
        ensure_dir(parent)
    image.save(filepath, **save_options)
    return str(filepath)


def pil_image_from_bytes(content):
    """Decode image bytes through the project's IO boundary."""
    from PIL import Image

    image = Image.open(io.BytesIO(content))
    image.load()
    return image


def combine_chat_plot_images(artifacts):
    """Compose harness charts into one proportional, bounded two-column image."""
    import uuid
    from PIL import Image

    if len(artifacts) < 2:
        return list(artifacts)
    if len(artifacts) > int(confs.get("QQAgent", {}).get("max_output_images", 4)):
        raise ValueError("chat_plot_collage: too many images")
    width = max(800, min(3200, int(agent_plot_config.get("collage_width", 2400))))
    gap = 24
    columns = min(len(artifacts), max(1, min(2, int(agent_plot_config.get("collage_columns", 2)))))
    cell_width = (width - gap * (columns + 1)) // columns
    images = []
    for item in artifacts:
        if not chat_plot_public_path(item["path"]):
            raise ValueError("chat_plot_collage: invalid harness image path")
        with Image.open(item["path"]) as source:
            if source.format != "PNG" or max(source.size) > 4096:
                raise ValueError("chat_plot_collage: invalid PNG dimensions")
            picture = source.convert("RGB")
        picture.thumbnail((cell_width, 1800), Image.Resampling.LANCZOS)
        images.append(picture)
    row_heights = [max(image.height for image in images[n:n + columns])
                   for n in range(0, len(images), columns)]
    canvas = Image.new("RGB", (width, sum(row_heights) + gap * (len(row_heights) + 1)), "#f6f8fc")
    top = gap
    for row, height in enumerate(row_heights):
        for col, picture in enumerate(images[row * columns:(row + 1) * columns]):
            left = gap + col * (cell_width + gap) + (cell_width - picture.width) // 2
            canvas.paste(picture, (left, top + (height - picture.height) // 2))
        top += height + gap
    output_path = os.path.join(temp_path, f"chat_plot_{uuid.uuid4().hex}.png")
    canvas.save(output_path, format="PNG", optimize=True)
    return [{"artifact_id": "plot_collage", "path": output_path, "width": canvas.width,
             "height": canvas.height, "source_count": len(artifacts)}]


def chat_plot_public_path(path):
    """Expose only harness PNGs inside the configured public artifact root."""
    import re

    resolved = os.path.realpath(path)
    if os.path.dirname(resolved) != os.path.realpath(temp_path):
        return ""
    name = os.path.basename(resolved)
    if not re.fullmatch(r"chat_plot_[0-9a-f]{32}\.png", name):
        return ""
    return f"/file_transfer/{name}"
