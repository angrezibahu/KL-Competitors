"""Dominant-colour extraction from a screenshot (for the 'colour trends' tab)."""

from PIL import Image

# A small palette of friendly names so the dashboard can label swatches.
_NAMED = {
    "black": (20, 20, 20), "white": (245, 245, 245), "grey": (128, 128, 128),
    "cream": (245, 235, 215), "beige": (222, 205, 175),
    "pink": (240, 170, 190), "blush": (245, 205, 210), "hot pink": (230, 90, 150),
    "red": (200, 50, 50), "coral": (240, 130, 110), "orange": (230, 150, 70),
    "gold": (212, 175, 55), "yellow": (235, 215, 90),
    "green": (90, 160, 110), "sage": (170, 185, 160), "teal": (70, 160, 160),
    "blue": (80, 130, 200), "navy": (40, 55, 95), "sky": (150, 195, 230),
    "purple": (140, 100, 180), "lilac": (190, 170, 215),
    "brown": (120, 85, 60), "tan": (200, 170, 130),
}


def _nearest_name(rgb):
    r, g, b = rgb
    best, best_d = None, 1e9
    for name, (nr, ng, nb) in _NAMED.items():
        d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


def looks_blank(image_path, white_thresh=236, min_share=0.985, max_std=6.0):
    """True if the screenshot is almost entirely near-white with virtually no
    visual variation -- i.e. the page hadn't painted when we shot it. This is a
    conservative BACKSTOP to the DOM render gate: it only fires on a genuinely
    empty frame (both an overwhelming white share AND a near-flat luminance
    spread), so a legitimately minimalist, image-led page with a logo/nav/hero
    won't trip it. Reuses Pillow; samples a small downscaled crop, so it's cheap.
    Returns False whenever it can't tell -- never block on uncertainty."""
    try:
        img = Image.open(image_path).convert("RGB").resize((100, 100))
    except Exception:
        return False
    raw = img.tobytes()                      # flat R,G,B,R,G,B,...
    px = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    n = len(px) or 1
    white = sum(1 for r, g, b in px
                if r >= white_thresh and g >= white_thresh and b >= white_thresh)
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px]
    mean = sum(lum) / n
    std = (sum((x - mean) ** 2 for x in lum) / n) ** 0.5
    return (white / n) >= min_share and std <= max_std


def dominant_colours(image_path, n=6):
    """Return a list of {hex, name, share} sorted by prevalence."""
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:  # pragma: no cover - defensive
        return [{"error": str(exc)}]

    img = img.resize((120, 120))
    pal = img.convert("P", palette=Image.ADAPTIVE, colors=n)
    palette = pal.getpalette()
    colour_counts = pal.getcolors() or []
    total = sum(c for c, _ in colour_counts) or 1

    out = []
    for count, idx in sorted(colour_counts, reverse=True):
        r, g, b = palette[idx * 3: idx * 3 + 3]
        out.append({
            "hex": f"#{r:02x}{g:02x}{b:02x}",
            "name": _nearest_name((r, g, b)),
            "share": round(count / total, 4),
        })
    return out[:n]
