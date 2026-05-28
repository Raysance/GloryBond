from ..zutil import *
from ..zstatic import *
from .. import zdynamic as dmc

def _emoji_template_local_dir():
    return getattr(dmc, "EmojiTemplateLocalDir", None) or os.path.join("wzry_images", "emoji_template")

def _emoji_generated_local_dir():
    return getattr(dmc, "EmojiGeneratedLocalDir", None) or os.path.join("wzry_images", "generated")

def _emoji_meta_jsonl_path():
    return getattr(dmc, "EmojiGenMetaPath", None) or os.path.join(_emoji_generated_local_dir(), "meta.jsonl")

def _emoji_template_public_dir():
    return getattr(dmc, "EmojiTemplatePublicDir", None) or "emoji_template"

def _emoji_pick_template_path():
    from ..zfile import get_file_list
    template_dir = _emoji_template_local_dir()
    candidates = []
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidates.extend(get_file_list(template_dir, ext))
    if not candidates:
        raise Exception(f"emoji_template_error: no templates in {template_dir}")
    return random.choice(candidates)

def _emoji_template_reference_url(template_path: str):
    from ..zfile import copyfile_to_dir
    if not nginx_path:
        raise Exception("emoji_template_error: nginx_path is empty (NGINX_HTML env missing)")
    public_dir = os.path.join(nginx_path, _emoji_template_public_dir())
    copied = copyfile_to_dir(template_path, public_dir)
    filename = os.path.basename(copied)
    domain = confs["WebService"]["server_domain"]
    return f"https://{domain}/{_emoji_template_public_dir()}/{filename}", filename

def _emoji_build_prompt(*, last_user_text: str, summary_2d: str):
    last_user_text = (last_user_text or "").strip()
    summary_2d = (summary_2d or "").strip()
    prompt = "请以参考图作为“画风与角色设定”参考生成一张静态图片。参考图仅用于风格与角色识别特征，不要把姿态、表情、镜头角度、构图一比一复刻。请根据用户上下文表达情绪与动作，多样化展示人物的姿态与表情（例如：开心/震惊/无语/生气/得意/委屈/疑惑等，对应不同动作与脸部表情）。"
    prompt += "\n\n画面要求："
    prompt += "\n- 只出现一个人物（保持角色辨识度，允许适度改动作、表情、角度、手势、道具）"
    prompt += "\n- 文字只出现一句短句（<=12字），必须与用户上下文相关"
    prompt += "\n- 文字呈现形式二选一：对话气泡 或 简洁字幕条/贴纸标题（不强制气泡）"
    prompt += "\n- 画面干净、清晰、适合作为表情包；不要水印；不要多张图；不要输出任何解释性文字"
    prompt += "\n\n用户最近发言:\n" + (last_user_text if last_user_text else "（空）")
    prompt += "\n\n用户近2天发言总结:\n" + (summary_2d if summary_2d else "（空）")
    return prompt

def generate_user_emoji_image(*, user_qid: str, size=None):
    from ..zapi import ark_images_generate
    from ..zfile import download_url_to_file, append_jsonl, ensure_dir
    from ..zmemory import instance as zm
    from ..ztime import time_r

    last_text = zm.load_user_recent_passive_text(user_qid)
    summary_2d = zm.load_user_summary_last_days(user_qid, 2)

    template_path = _emoji_pick_template_path()
    reference_url, template_filename = _emoji_template_reference_url(template_path)
    prompt = _emoji_build_prompt(last_user_text=last_text, summary_2d=summary_2d)

    if not size:
        size = getattr(dmc, "EmojiImageSize", None) or "2048x2048"

    gen_res = ark_images_generate(prompt=prompt, reference_image_url=reference_url, size=size)
    image_url = gen_res["url"]
    request_payload = gen_res["request"]

    now = time_r()
    ts = now.strftime("%Y%m%d_%H%M%S")
    local_dir = _emoji_generated_local_dir()
    ensure_dir(local_dir)
    basename = f"emoji_{ts}_{user_qid}_{os.path.splitext(template_filename)[0]}.png"
    local_path = os.path.join(local_dir, basename)
    download_url_to_file(image_url, local_path)

    meta = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "user_qid": str(user_qid),
        "image_name": basename,
        "image_path": os.path.abspath(local_path),
        "size": size,
        "template_file": os.path.abspath(template_path),
        "template_public_url": reference_url,
        "prompt": prompt,
        "request": request_payload,
        "image_url": image_url,
    }
    append_jsonl(_emoji_meta_jsonl_path(), meta)
    return meta
