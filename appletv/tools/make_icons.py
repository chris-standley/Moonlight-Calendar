"""Draws the Apple TV app icon (two parallax layers) and Top Shelf images into Assets.xcassets.

Run from the repo root: python3 appletv/tools/make_icons.py   (needs Pillow)
The artwork is the wall screens' crescent logo: a lilac gradient with a white crescent and two stars.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(__file__), "..", "Moonlight", "Assets.xcassets")
BRAND = os.path.join(ROOT, "App Icon & Top Shelf Image.brandassets")
INFO = {"author": "xcode", "version": 1}
TOP, BOTTOM = (124, 140, 248), (179, 140, 240)  # #7C8CF8 -> #B38CF0
SS = 3  # supersampling


def gradient(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    return img


def gradient_fast(w, h):
    # Diagonal gradient built from a small one, scaled up (smooth enough, and quick at 4640px).
    return gradient(64, max(2, round(64 * h / w))).resize((w, h), Image.BICUBIC)


def crescent(w, h, cx, cy, r):
    """White crescent + stars on transparent, centred at (cx, cy) with outer radius r (web logo geometry)."""
    big = Image.new("L", (w * SS, h * SS), 0)
    d = ImageDraw.Draw(big)
    s = SS
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=255)
    # cut-out disc: offset right, slightly smaller (7.2/9 of the radius in the 32px logo)
    cr = r * 0.85
    ox = cx + r * 0.64
    d.ellipse([(ox - cr) * s, (cy - r) * s, (ox + cr) * s, (cy + r) * s], fill=0)
    for (dx, dy, rr, a) in [(0.39, -0.67, 0.145, 235), (0.72, -0.07, 0.1, 190)]:
        x, y, q = cx + dx * r * 1.0 + r * 0.35, cy + dy * r, rr * r
        d.ellipse([(x - q) * s, (y - q) * s, (x + q) * s, (y + q) * s], fill=a)
    mask = big.resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    layer.putalpha(mask)
    return layer


def save_imageset(folder, images, idiom="tv"):
    os.makedirs(folder, exist_ok=True)
    entries = []
    for scale, img, name in images:
        img.save(os.path.join(folder, name))
        entries.append({"filename": name, "idiom": idiom, "scale": scale})
    write(os.path.join(folder, "Contents.json"), {"images": entries, "info": INFO})


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def icon_stack(name, w, h, scales):
    stack = os.path.join(BRAND, name + ".imagestack")
    write(os.path.join(stack, "Contents.json"),
          {"info": INFO, "layers": [{"filename": "Front.imagestacklayer"}, {"filename": "Back.imagestacklayer"}]})
    for layer in ("Front", "Back"):
        folder = os.path.join(stack, layer + ".imagestacklayer")
        write(os.path.join(folder, "Contents.json"), {"info": INFO})
        imgs = []
        for scale in scales:
            k = int(scale[0])
            W, H = w * k, h * k
            if layer == "Back":
                img = gradient_fast(W, H)
            else:
                img = crescent(W, H, W * 0.47, H * 0.5, H * 0.3)
                # soft glow so the crescent lifts off the background in the parallax
                glow = img.filter(ImageFilter.GaussianBlur(H * 0.03))
                img = Image.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, 0)), glow)
                img = Image.alpha_composite(img, crescent(W, H, W * 0.47, H * 0.5, H * 0.3))
            fn = f"{layer.lower()}{'' if k == 1 else '@%dx' % k}.png"
            imgs.append((scale, img.convert("RGB") if layer == "Back" else img, fn))
        save_imageset(os.path.join(folder, "Content.imageset"), imgs)


def top_shelf(name, w, h):
    imgs = []
    for k in (1, 2):
        W, H = w * k, h * k
        img = gradient_fast(W, H).convert("RGBA")
        img = Image.alpha_composite(img, crescent(W, H, W * 0.5 - H * 0.55, H * 0.5, H * 0.17))
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT, int(H * 0.16))
        d.text((W * 0.5 - H * 0.28, H * 0.5), "Moonlight", font=font, fill=(255, 255, 255, 255), anchor="lm")
        imgs.append((f"{k}x", img.convert("RGB"), f"{name.lower().replace(' ', '-')}{'' if k == 1 else '@2x'}.png"))
    save_imageset(os.path.join(BRAND, name + ".imageset"), imgs)


FONT = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/SFNSRounded.ttf",
    "/Library/Fonts/Arial Rounded Bold.ttf",
] if os.path.exists(p)), None)

if __name__ == "__main__":
    if FONT is None:
        sys.exit("No bold font found for the Top Shelf wordmark")
    write(os.path.join(ROOT, "Contents.json"), {"info": INFO})
    write(os.path.join(ROOT, "AccentColor.colorset", "Contents.json"), {
        "colors": [{"color": {"color-space": "srgb", "components": {
            "red": "0x6C", "green": "0x7B", "blue": "0xF0", "alpha": "1.000"}}, "idiom": "universal"}],
        "info": INFO})
    write(os.path.join(BRAND, "Contents.json"), {"assets": [
        {"filename": "App Icon - App Store.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "1280x768"},
        {"filename": "App Icon.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "400x240"},
        {"filename": "Top Shelf Image Wide.imageset", "idiom": "tv", "role": "top-shelf-image-wide", "size": "2320x720"},
        {"filename": "Top Shelf Image.imageset", "idiom": "tv", "role": "top-shelf-image", "size": "1920x720"},
    ], "info": INFO})
    icon_stack("App Icon", 400, 240, ["1x", "2x"])
    icon_stack("App Icon - App Store", 1280, 768, ["1x"])
    top_shelf("Top Shelf Image", 1920, 720)
    top_shelf("Top Shelf Image Wide", 2320, 720)
    print("wrote", ROOT)
