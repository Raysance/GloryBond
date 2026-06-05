"""Read prompt.txt in this folder and call qbot.zapi.apimart_images_generate."""

import argparse
import types
import os
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def install_qbot_namespace():
    """Install qbot namespace packages without executing qbot plugin entry."""
    packages = {
        "src": REPO_ROOT / "src",
        "src.plugins": REPO_ROOT / "src" / "plugins",
        "src.plugins.qbot": REPO_ROOT / "src" / "plugins" / "qbot",
    }
    for name, path in packages.items():
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            module.__package__ = name
            sys.modules[name] = module


def load_qbot_modules():
    """Load qbot modules needed by this debug script."""
    install_qbot_namespace()
    from src.plugins.qbot.zapi import apimart_images_generate
    from src.plugins.qbot.zfile import append_jsonl, download_url_to_file, ensure_dir, readera
    from src.plugins.qbot.ztime import time_r
    return apimart_images_generate, append_jsonl, download_url_to_file, ensure_dir, readera, time_r


def read_prompt(prompt_file: str):
    """Read full prompt from a txt file in the same directory."""
    _, _, _, _, readera, _ = load_qbot_modules()
    prompt_path = THIS_DIR / prompt_file
    prompt = readera(str(prompt_path)).strip()
    if not prompt:
        raise Exception(f"debug_image_gen_error: empty prompt file path={prompt_path}")
    return prompt, prompt_path


def run_image_generate(*, prompt_file: str, size: str, resolution: str, reference_image_url: str, timeout_seconds: int):
    """Generate one image and save image plus metadata into out directory."""
    apimart_images_generate, append_jsonl, download_url_to_file, ensure_dir, _, time_r = load_qbot_modules()
    prompt, prompt_path = read_prompt(prompt_file)
    out_dir = THIS_DIR / "out"
    ensure_dir(str(out_dir))
    res = apimart_images_generate(
        prompt=prompt,
        reference_image_url=reference_image_url,
        size=size,
        resolution=resolution,
        task_timeout_seconds=timeout_seconds,
    )
    image_url = res["url"]
    now = time_r()
    basename = f"apimart_debug_{now.strftime('%Y%m%d_%H%M%S')}.png"
    image_path = out_dir / basename
    download_url_to_file(image_url, str(image_path))
    meta = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "prompt_file": str(prompt_path),
        "image_path": str(image_path),
        "image_url": image_url,
        "size": size,
        "resolution": resolution,
        "reference_image_url": reference_image_url,
        "timeout_seconds": timeout_seconds,
        "request": res.get("request", {}),
    }
    append_jsonl(str(out_dir / "meta.jsonl"), meta)
    print(str(image_path))
    return meta


def main():
    """Parse CLI args and run image generation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", default="prompt.txt")
    parser.add_argument("--size", default="1:1")
    parser.add_argument("--resolution", default="1k")
    parser.add_argument("--reference-image-url", default="")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    run_image_generate(
        prompt_file=args.prompt_file,
        size=args.size,
        resolution=args.resolution,
        reference_image_url=args.reference_image_url,
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    main()
