from ..zutil import *
from ..zstatic import *
from .. import zdynamic as dmc
from PIL import Image

EmojiStyleTemplates = [
    "风格A：清爽日系二次元线稿上色，色块干净，轻阴影，表情夸张但可爱",
    "风格B：美式卡通贴纸风，粗描边，高对比，简洁背景，文字像贴纸标题",
    "风格C：国风Q版，柔和水墨晕染，线条简化，色彩克制，情绪明显",
    "风格D：像素风贴纸（高质量像素画），背景透明，文字像游戏UI弹窗",
    "风格E：极简扁平插画，几何形状，纯色块，留白多，重点突出表情与文案",
]

EmojiKmojiFixedStyleTemplate = ""

def _emoji_pick_style_template():
    templates = EmojiStyleTemplates
    if not isinstance(templates, list) or not templates:
        return ""
    picked = random.choice([str(t) for t in templates if str(t).strip()])
    return picked.strip()

def _rgba_dist(a, b):
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])), abs(int(a[2]) - int(b[2])))

def transparentize_checkerboard_background(image_path: str, tolerance: int = 18):
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    if w <= 4 or h <= 4:
        return image_path

    px = img.load()
    edge = []
    for x in range(w):
        edge.append(px[x, 0])
        edge.append(px[x, h - 1])
    for y in range(h):
        edge.append(px[0, y])
        edge.append(px[w - 1, y])

    freq = {}
    for c in edge:
        rgb = (int(c[0]), int(c[1]), int(c[2]))
        freq[rgb] = freq.get(rgb, 0) + 1
    colors = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
    bg_colors = [c for c, _ in colors[:2]]
    if not bg_colors:
        return image_path

    visited = [[False] * w for _ in range(h)]
    q = []
    def push(x, y):
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        if visited[y][x]:
            return
        visited[y][x] = True
        q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    to_clear = []
    while q:
        x, y = q.pop()
        c = px[x, y]
        rgb = (int(c[0]), int(c[1]), int(c[2]))
        ok = False
        for bg in bg_colors:
            if _rgba_dist(rgb, bg) <= tolerance:
                ok = True
                break
        if not ok:
            continue
        to_clear.append((x, y))
        push(x + 1, y)
        push(x - 1, y)
        push(x, y + 1)
        push(x, y - 1)

    if not to_clear:
        return image_path

    for x, y in to_clear:
        r, g, b, _a = px[x, y]
        px[x, y] = (int(r), int(g), int(b), 0)
    img.save(image_path)
    return image_path

def _emoji_message_filter_prompt():
    return (
        "你是一个表情包生图助手。请判断每条用户原始发言是否适合用作表情包图上的“情绪/动作/文案”依据。\n"
        "输出必须为严格 JSON，字段如下：\n"
        '{ "action": "use"|"refine"|"drop", "text": "<当action=use/refine时输出可用文本，否则为空>" }\n'
        "规则：\n"
        "- drop：纯无意义、过长、包含隐私/敏感信息、仅网址/仅数字、或与情绪表达无关。\n"
        "- use：短句、能表达情绪/动作/槽点、适合做表情包文案或情绪触发。\n"
        "- refine：内容可用但需要压缩为<=20字、去除敏感信息、或改成更适合作为表情包的口吻。\n"
        "不要输出除 JSON 外的任何内容。"
    )

def _emoji_batch_message_filter_prompt():
    return (
        "你是一个表情包生图助手。请对多条用户原始发言逐条判断是否适合用作表情包图上的“情绪/动作/文案”依据。\n"
        "输入会给出多条消息，每条都有 index。\n"
        "输出必须为严格 JSON 数组，数组元素字段如下：\n"
        '{ "index": <int>, "action": "use"|"refine"|"drop", "text": "<当action=use/refine时输出可用文本，否则为空>" }\n'
        "规则：\n"
        "- drop：纯无意义、过长、包含隐私/敏感信息、仅网址/仅数字、或与情绪表达无关。\n"
        "- use：短句、能表达情绪/动作/槽点、适合做表情包文案或情绪触发。\n"
        "- refine：内容可用但需要压缩为<=20字、去除敏感信息、或改成更适合作为表情包的口吻。\n"
        "必须对每条输入都输出一条结果，且 index 一一对应。\n"
        "不要输出除 JSON 外的任何内容。"
    )

def _emoji_batch_classify_messages(messages):
    from ..zapi import ai_api
    import json as _json
    if not messages:
        return []
    packed = []
    for i, m in enumerate(messages):
        packed.append({"index": i, "text": m})
    check_prompt = _emoji_batch_message_filter_prompt() + "\n\n消息列表:\n" + _json.dumps(packed, ensure_ascii=False)
    res = ai_api(check_prompt, temperature=0.2)
    try:
        arr = _json.loads(res)
    except Exception as e:
        raise Exception(f"emoji_message_check_error: parse_json_failed res={res} err={repr(e)}")
    if not isinstance(arr, list):
        raise Exception(f"emoji_message_check_error: invalid_json_type res={res}")
    out = [None] * len(messages)
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        idx = obj.get("index")
        if not isinstance(idx, int):
            continue
        if idx < 0 or idx >= len(messages):
            continue
        action = (obj.get("action") or "").strip()
        text = (obj.get("text") or "").strip()
        out[idx] = {"action": action, "text": text}
    for i, v in enumerate(out):
        if v is None:
            raise Exception("emoji_message_check_error: missing_index_result")
    return out

def _emoji_pick_one_refined_message(user_qid: str):
    from ..zmemory import instance as zm
    import hashlib as _hashlib

    recent_items = zm.load_user_recent_passive_items(user_qid, 8)
    candidates = []
    for item in recent_items[::-1]:
        msg = (item.get("text", "") or "").strip()
        if not msg:
            continue
        msg_hash = _hashlib.sha1(msg.encode("utf-8")).hexdigest()
        candidates.append({"raw": msg, "hash": msg_hash})

    if not candidates:
        return {"action": "none", "text": "", "raw": "", "hash": "", "checked": []}

    checked = []
    uncached_texts = []
    uncached_infos = []

    for info in candidates:
        cached = zm.emoji.get_msg_action(user_qid, info["hash"])
        if cached is None:
            uncached_texts.append(info["raw"])
            uncached_infos.append(info)
            if len(uncached_texts) >= 8:
                break

    if uncached_texts:
        results = _emoji_batch_classify_messages(uncached_texts)
        for info, res in zip(uncached_infos, results):
            action = (res.get("action") or "").strip()
            text = (res.get("text") or "").strip()
            zm.emoji.set_msg_action(user_qid, info["hash"], action=action, text=text, raw_text=info["raw"])

    pool = []
    for info in candidates:
        cached = zm.emoji.get_msg_action(user_qid, info["hash"])
        if cached is None:
            continue
        action = (cached.get("action") or "").strip()
        text = (cached.get("text") or "").strip()
        checked.append({"action": action, "text": text, "raw": info["raw"], "hash": info["hash"]})
        if action == "drop":
            continue
        if action in {"use", "refine"} and text and not zm.emoji.msg_used(user_qid, info["hash"]):
            pool.append({"action": action, "text": text, "raw": info["raw"], "hash": info["hash"]})

    if pool:
        picked = random.choice(pool)
        zm.emoji.mark_msg_used(user_qid, picked["hash"])
        picked["checked"] = checked
        return picked

    return {"action": "none", "text": "", "raw": "", "hash": "", "checked": checked}

def _emoji_template_local_dir():
    return getattr(dmc, "EmojiTemplateLocalDir", None) or os.path.join("wzry_images", "emoji_template")

def _emoji_template_extra_dirs():
    return [os.path.join("wzry_images", "custom_wzry_E1")]

def _emoji_generated_local_dir():
    return getattr(dmc, "EmojiGeneratedLocalDir", None) or os.path.join("wzry_images", "generated")

def _emoji_task_timeout_seconds():
    return getattr(dmc, "EmojiImageTaskTimeoutSeconds", None) or 600

def _emoji_meta_jsonl_path():
    return getattr(dmc, "EmojiGenMetaPath", None) or os.path.join(_emoji_generated_local_dir(), "meta.jsonl")

def _emoji_template_public_dir():
    return getattr(dmc, "EmojiTemplatePublicDir", None) or "emoji_template"

def _emoji_pick_template_path():
    from ..zfile import get_file_list
    candidates = []
    template_dirs = [_emoji_template_local_dir()] + _emoji_template_extra_dirs()
    for template_dir in template_dirs:
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            candidates.extend(get_file_list(template_dir, ext))
    if not candidates:
        raise Exception("emoji_template_error: no templates found in template dirs")
    return random.choice(candidates)

def _emoji_pick_template_by_num(template_num):
    from ..zfile import get_file_list
    candidates = []
    template_dirs = [_emoji_template_local_dir()] + _emoji_template_extra_dirs()
    for template_dir in template_dirs:
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            candidates.extend(get_file_list(template_dir, ext))
    if not candidates:
        raise Exception("emoji_template_error: no templates found in template dirs")
    for p in candidates:
        base = os.path.basename(p)
        head = base.split("_", 1)[0].split(".", 1)[0]
        if head.isdigit():
            try:
                if int(head) == int(template_num):
                    return p
            except Exception:
                pass
    raise Exception(f"emoji_template_error: template num not found num={template_num}")

def _emoji_template_reference_url(template_path: str):
    from ..zfile import copyfile_to_dir
    if not nginx_path:
        raise Exception("emoji_template_error: nginx_path is empty (NGINX_HTML env missing)")
    public_dir = os.path.join(nginx_path, _emoji_template_public_dir())
    copied = copyfile_to_dir(template_path, public_dir)
    filename = os.path.basename(copied)
    domain = confs["WebService"]["server_domain"]
    return f"https://{domain}/{_emoji_template_public_dir()}/{filename}", filename

def _emoji_build_prompt(*, last_user_text: str, summary_2d: str, style_template: str = ""):
    last_user_text = (last_user_text or "").strip()
    summary_2d = (summary_2d or "").strip()
    prompt = "请以参考图作为“画风与角色设定”参考生成一张静态图片。参考图仅用于风格与角色识别特征，不要把姿态、表情、镜头角度、构图一比一复刻。请根据用户上下文表达情绪与动作，多样化展示人物的姿态与表情（例如：开心/震惊/无语/生气/得意/委屈/疑惑等，对应不同动作与脸部表情）。"
    if style_template:
        prompt += "\n\n本次风格模板(随机选一)：\n" + style_template
    prompt += "\n\n画面要求："
    prompt += "\n- 只出现一个人物（保持角色辨识度，允许适度改动作、表情、角度、手势、道具）"
    prompt += "\n- 文字只出现一句短句（<=12字），必须与用户上下文相关"
    prompt += "\n- 文字呈现形式二选一：对话气泡 或 简洁字幕条/贴纸标题（不强制气泡）"
    prompt += "\n- 背景尽量透明（PNG alpha），仅保留人物与文字元素；若无法透明则使用纯色简洁背景且不抢戏"
    prompt += "\n- 画面干净、清晰、适合作为表情包；不要水印；不要多张图；不要输出任何解释性文字"
    prompt += "\n\n用户最近发言:\n" + (last_user_text if last_user_text else "（空）")
    prompt += "\n\n用户近2天发言总结:\n" + (summary_2d if summary_2d else "（空）")
    return prompt

def _emoji_build_prompt_with_message(*, recent_msg: str, summary_2d: str, style_template: str = ""):
    summary_2d = (summary_2d or "").strip()
    prompt = "请以参考图作为“画风与角色设定”参考生成一张静态图片。参考图仅用于风格与角色识别特征，不要把姿态、表情、镜头角度、构图一比一复刻。请根据用户上下文表达情绪与动作，多样化展示人物的姿态与表情（例如：开心/震惊/无语/生气/得意/委屈/疑惑等，对应不同动作与脸部表情）。"
    if style_template:
        prompt += "\n\n本次风格模板(随机选一)：\n" + style_template
    prompt += "\n\n画面要求："
    prompt += "\n- 只出现一个人物（保持角色辨识度，允许适度改动作、表情、角度、手势、道具）"
    prompt += "\n- 文字只出现一句短句（<=12字），必须与用户上下文相关"
    prompt += "\n- 文字呈现形式二选一：对话气泡 或 简洁字幕条/贴纸标题（不强制气泡）"
    prompt += "\n- 背景尽量透明（PNG alpha），仅保留人物与文字元素；若无法透明则使用纯色简洁背景且不抢戏"
    prompt += "\n- 画面干净、清晰、适合作为表情包；不要水印；不要多张图；不要输出任何解释性文字"
    prompt += "\n\n可用的最近发言(已筛选/润色，且本条不会重复使用):\n"
    prompt += (recent_msg.strip() if recent_msg else "（空）") + "\n"
    prompt += "\n用户近2天发言总结:\n" + (summary_2d if summary_2d else "（空）")
    return prompt

def _emoji_build_kmoji_prompt(*, last_user_text: str, summary_2d: str, prompt_tail: str, style_template: str = ""):
    tail = (prompt_tail or "").strip()
    if tail:
        prompt = "请以参考图作为“画风与角色设定”参考生成一张静态图片。参考图仅用于风格与角色识别特征，不要把姿态、表情、镜头角度、构图一比一复刻。请根据用户上下文表达情绪与动作，多样化展示人物的姿态与表情（例如：开心/震惊/无语/生气/得意/委屈/疑惑等，对应不同动作与脸部表情）。"
        if style_template:
            prompt += "\n\n本次风格模板(固定)：\n" + style_template
        prompt += "\n\n画面要求："
        prompt += "\n- 只出现一个人物（保持角色辨识度，允许适度改动作、表情、角度、手势、道具）"
        prompt += "\n- 文字只出现一句短句（<=12字），必须与用户上下文相关"
        prompt += "\n- 文字呈现形式二选一：对话气泡 或 简洁字幕条/贴纸标题（不强制气泡）"
        prompt += "\n- 背景尽量透明（PNG alpha），仅保留人物与文字元素；若无法透明则使用纯色简洁背景且不抢戏"
        prompt += "\n- 画面干净、清晰、适合作为表情包；不要水印；不要多张图；不要输出任何解释性文字"
        prompt += "\n\n用户手动提示词:\n" + tail
        return prompt

    return _emoji_build_prompt(last_user_text=last_user_text, summary_2d=summary_2d, style_template=style_template)

def generate_user_emoji_image(*, user_qid: str, size=None):
    from ..zapi import apimart_images_generate
    from ..zfile import download_url_to_file, append_jsonl, ensure_dir
    from ..zmemory import instance as zm
    from ..ztime import time_r

    summary_2d = zm.load_user_summary_last_days(user_qid, 2)

    template_path = _emoji_pick_template_path()
    reference_url, template_filename = _emoji_template_reference_url(template_path)
    picked = _emoji_pick_one_refined_message(user_qid)
    style_template = _emoji_pick_style_template()
    prompt = _emoji_build_prompt_with_message(recent_msg=picked.get("text", ""), summary_2d=summary_2d, style_template=style_template)

    if not size:
        size = getattr(dmc, "EmojiImageSize", None) or "2048x2048"
    resolution = getattr(dmc, "EmojiImageResolution", None) or "1k"
    if isinstance(size, str) and "x" in size and ":" not in size:
        try:
            w, h = size.lower().split("x", 1)
            w = int(w.strip())
            h = int(h.strip())
            if w == h:
                size = "1:1"
            else:
                import math as _math
                g = _math.gcd(w, h)
                size = f"{w//g}:{h//g}"
        except Exception:
            size = "1:1"

    gen_res = apimart_images_generate(prompt=prompt, reference_image_url=reference_url, size=size, resolution=resolution, task_timeout_seconds=_emoji_task_timeout_seconds())
    image_url = gen_res["url"]
    request_payload = gen_res["request"]

    now = time_r()
    ts = now.strftime("%Y%m%d_%H%M%S")
    local_dir = _emoji_generated_local_dir()
    ensure_dir(local_dir)
    basename = f"emoji_{ts}_{user_qid}_{os.path.splitext(template_filename)[0]}.png"
    local_path = os.path.join(local_dir, basename)
    download_url_to_file(image_url, local_path)
    transparentize_checkerboard_background(local_path)

    meta = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user_qid": str(user_qid),
        "image_name": basename,
        "image_path": os.path.abspath(local_path),
        "size": size,
        "template_file": os.path.abspath(template_path),
        "template_public_url": reference_url,
        "prompt": prompt,
        "style_template": style_template,
        "picked_msg": picked,
        "request": request_payload,
        "image_url": image_url,
    }
    append_jsonl(_emoji_meta_jsonl_path(), meta)
    return meta

def generate_user_kmoji_image(*, user_qid: str, custom_image_url: str = None, template_num: int = None, prompt_tail: str = "", size=None):
    from ..zapi import apimart_images_generate
    from ..zfile import download_url_to_file, append_jsonl, ensure_dir, copyfile_to_dir
    from ..zmemory import instance as zm
    from ..ztime import time_r

    use_default_template = False
    if not custom_image_url and template_num is None:
        use_default_template = True

    style_template = EmojiKmojiFixedStyleTemplate
    picked = None
    tail = (prompt_tail or "").strip()
    if tail:
        prompt = _emoji_build_kmoji_prompt(last_user_text="", summary_2d="", prompt_tail=tail, style_template=style_template)
        summary_2d = ""
    else:
        summary_2d = zm.load_user_summary_last_days(user_qid, 2)
        picked = _emoji_pick_one_refined_message(user_qid)
        prompt = _emoji_build_prompt_with_message(recent_msg=picked.get("text", ""), summary_2d=summary_2d, style_template=style_template)

    now = time_r()
    ts = now.strftime("%Y%m%d_%H%M%S")

    if use_default_template:
        template_path = _emoji_pick_template_path()
        reference_url, _ = _emoji_template_reference_url(template_path)
    elif template_num is not None:
        template_path = _emoji_pick_template_by_num(template_num)
        reference_url, _ = _emoji_template_reference_url(template_path)
    else:
        template_dir = _emoji_template_local_dir()
        ensure_dir(template_dir)
        template_name = f"kmoji_{ts}_{user_qid}.png"
        template_path = os.path.join(template_dir, template_name)
        download_url_to_file(custom_image_url, template_path)
        if not nginx_path:
            raise Exception("kmoji_error: nginx_path is empty (NGINX_HTML env missing)")
        public_dir = os.path.join(nginx_path, _emoji_template_public_dir())
        copied = copyfile_to_dir(template_path, public_dir)
        filename = os.path.basename(copied)
        domain = confs["WebService"]["server_domain"]
        reference_url = f"https://{domain}/{_emoji_template_public_dir()}/{filename}"

    if not size:
        size = getattr(dmc, "EmojiImageSize", None) or "2048x2048"
    resolution = getattr(dmc, "EmojiImageResolution", None) or "1k"
    if isinstance(size, str) and "x" in size and ":" not in size:
        try:
            w, h = size.lower().split("x", 1)
            w = int(w.strip())
            h = int(h.strip())
            if w == h:
                size = "1:1"
            else:
                import math as _math
                g = _math.gcd(w, h)
                size = f"{w//g}:{h//g}"
        except Exception:
            size = "1:1"

    gen_res = apimart_images_generate(prompt=prompt, reference_image_url=reference_url, size=size, resolution=resolution, task_timeout_seconds=_emoji_task_timeout_seconds())
    image_url = gen_res["url"]
    request_payload = gen_res["request"]

    local_dir = _emoji_generated_local_dir()
    ensure_dir(local_dir)
    basename = f"kmoji_{ts}_{user_qid}.png"
    local_path = os.path.join(local_dir, basename)
    download_url_to_file(image_url, local_path)
    transparentize_checkerboard_background(local_path)

    meta = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user_qid": str(user_qid),
        "image_name": basename,
        "image_path": os.path.abspath(local_path),
        "size": size,
        "template_file": os.path.abspath(template_path),
        "template_public_url": reference_url,
        "prompt": prompt,
        "style_template": style_template,
        "picked_msg": picked,
        "prompt_tail": (prompt_tail or "").strip(),
        "custom_image_url": custom_image_url,
        "template_num": template_num,
        "use_default_template": use_default_template,
        "request": request_payload,
        "image_url": image_url,
    }
    append_jsonl(_emoji_meta_jsonl_path(), meta)
    return meta
