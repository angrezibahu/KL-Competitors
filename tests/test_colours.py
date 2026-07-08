"""Tests for the screenshot blank-frame backstop (scraper/colours.looks_blank).

The DOM render gate in capture.py is the primary defence against shooting a
still-loading page; looks_blank is the conservative pixel-level net that must
flag a genuinely empty frame WITHOUT tripping on a legitimately minimalist,
image-led luxury homepage.
"""

import os
import tempfile

from PIL import Image, ImageDraw

from scraper.colours import looks_blank


def _save(img):
    path = os.path.join(tempfile.mkdtemp(), "shot.jpg")
    img.save(path, "JPEG", quality=70)
    return path


def test_pure_white_frame_is_blank():
    assert looks_blank(_save(Image.new("RGB", (1200, 900), (255, 255, 255))))


def test_faint_offwhite_frame_is_blank():
    assert looks_blank(_save(Image.new("RGB", (1200, 900), (252, 252, 252))))


def test_minimalist_hero_is_not_blank():
    """Lots of white space but a real hero band + logo -> a good shot."""
    img = Image.new("RGB", (1200, 1600), (250, 249, 247))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 120, 1200, 780], fill=(180, 150, 120))   # hero photo
    dr.rectangle([500, 40, 700, 90], fill=(20, 20, 20))       # logo
    assert not looks_blank(_save(img))


def test_text_on_white_is_not_flagged_by_pixels():
    """The 'hero missing, nav text present' case carries enough contrast that
    the pixel test leaves it alone -- it's the DOM render gate's job, not this
    backstop's, so this must NOT false-positive here."""
    img = Image.new("RGB", (1200, 1600), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    for y in range(400, 700, 40):
        dr.rectangle([200, y, 900, y + 18], fill=(30, 30, 30))
    assert not looks_blank(_save(img))


def test_unreadable_path_does_not_block():
    assert looks_blank("/no/such/file.jpg") is False
