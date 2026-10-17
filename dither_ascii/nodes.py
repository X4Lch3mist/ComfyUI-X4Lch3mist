"""
Dither & ASCII nodes for ComfyUI  -  by X4Lch3mist

Two post-processing nodes that turn any image into
  * a 1-bit ordered / error-diffusion dither (stripes, Bayer, halftone, ...)
  * ASCII art rendered with a monospace font

No model, no GPU, only NumPy + Pillow. IMAGE in, IMAGE (+ MASK) out.
"""

import os
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _hex_to_rgb(value, fallback=(255, 255, 255)):
    """'#33FF66', '33ff66', '#3f6' -> (r, g, b) as floats 0..1"""
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        rgb = tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        rgb = fallback
    return np.array(rgb, dtype=np.float32) / 255.0


def _luma(rgb):
    """(H, W, 3) float -> (H, W) float, Rec.601 weights"""
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _levels(v, black_point, white_point, gamma, invert):
    """Classic levels: everything below black_point becomes pure black,
    everything above white_point pure white, gamma bends the midtones."""
    wp = max(white_point, black_point + 1e-3)
    v = np.clip((v - black_point) / (wp - black_point), 0.0, 1.0)
    if gamma != 1.0:
        v = v ** (1.0 / gamma)
    if invert:
        v = 1.0 - v
    return v


def _resize_gray(v, w, h, resample):
    img = Image.fromarray((np.clip(v, 0, 1) * 255).astype(np.uint8), "L")
    return np.asarray(img.resize((max(1, w), max(1, h)), resample), dtype=np.float32) / 255.0


def _resize_rgb(rgb, w, h, resample):
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
    return np.asarray(img.resize((max(1, w), max(1, h)), resample), dtype=np.float32) / 255.0


# ----------------------------------------------------------------------------
# threshold maps for ordered dithering
# ----------------------------------------------------------------------------

def _bayer(n):
    """Bayer matrix with side = next power of two >= n, values 0..1"""
    m = np.array([[0, 2], [3, 1]], dtype=np.float32)
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m / m.size


def _tri(t, n):
    """triangle wave 0..1..0 with period n -> lines grow symmetrically"""
    p = (t % n) / n
    return np.abs(p * 2.0 - 1.0)


def _rank_normalize(m):
    """Turn any map into evenly distributed thresholds, so 50 % grey
    gives exactly 50 % white pixels regardless of the pattern shape."""
    flat = m.ravel()
    ranks = flat.argsort(kind="stable").argsort(kind="stable")
    return ((ranks + 0.5) / flat.size).reshape(m.shape).astype(np.float32)


def _threshold_map(pattern, n, smoothing):
    """Returns an (S, S) tile of thresholds 0..1"""
    n = int(max(2, n))
    if pattern == "bayer":
        return _bayer(n)

    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    if pattern == "diagonal stripes":
        base = _tri(xx + yy, n)
    elif pattern == "diagonal stripes (reverse)":
        base = _tri(xx - yy, n)
    elif pattern == "horizontal lines":
        base = _tri(yy, n)
    elif pattern == "vertical lines":
        base = _tri(xx, n)
    elif pattern == "crosshatch":
        base = np.minimum(_tri(xx + yy, n), _tri(xx - yy, n))
    elif pattern == "halftone dots":
        base = 0.5 - (np.cos(2 * np.pi * (xx + 0.5) / n) + np.cos(2 * np.pi * (yy + 0.5) / n)) / 4.0
    else:
        base = _tri(xx + yy, n)

    # a pinch of Bayer breaks ties inside a stripe -> smoother tone steps.
    # smoothing=0 keeps hard graphic lines, 1 is almost plain Bayer.
    tile = np.tile(_bayer(4), (n // 4 + 1, n // 4 + 1))[:n, :n]
    mixed = (1.0 - smoothing) * base + smoothing * tile + 1e-4 * tile
    return _rank_normalize(mixed)


# ----------------------------------------------------------------------------
# error diffusion (slower, organic grain)
# ----------------------------------------------------------------------------

_KERNELS = {
    # (dy, dx, weight)
    "floyd-steinberg": [(0, 1, 7 / 16), (1, -1, 3 / 16), (1, 0, 5 / 16), (1, 1, 1 / 16)],
    "atkinson": [(0, 1, 1 / 8), (0, 2, 1 / 8), (1, -1, 1 / 8), (1, 0, 1 / 8), (1, 1, 1 / 8), (2, 0, 1 / 8)],
}


def _error_diffusion(v, kernel):
    a = v.astype(np.float32).copy()
    h, w = a.shape
    out = np.zeros_like(a)
    k = _KERNELS[kernel]
    for y in range(h):
        # serpentine scan avoids diagonal "worm" artefacts
        rng = range(w) if y % 2 == 0 else range(w - 1, -1, -1)
        sgn = 1 if y % 2 == 0 else -1
        row = a[y]
        for x in rng:
            old = row[x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = new
            err = old - new
            if err == 0.0:
                continue
            for dy, dx, wt in k:
                yy, xx = y + dy, x + dx * sgn
                if 0 <= xx < w and yy < h:
                    a[yy, xx] += err * wt
    return out


# ----------------------------------------------------------------------------
# font handling for ASCII
# ----------------------------------------------------------------------------

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/lucon.ttf",
    "C:/Windows/Fonts/cour.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    # macOS
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
]


def _load_font(size, font_path=""):
    paths = []
    if font_path and font_path.strip():
        p = font_path.strip().strip('"')
        paths.append(p)
        # allow just a file name that sits next to this script / in ./fonts
        here = os.path.dirname(os.path.abspath(__file__))
        paths += [os.path.join(here, p), os.path.join(here, "fonts", p)]
    paths += _FONT_CANDIDATES
    for p in paths:
        try:
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _glyph_atlas(charset, font, line_spacing):
    """Pre-render every character once -> (K, ch, cw) coverage masks."""
    asc, desc = font.getmetrics()
    ch = max(1, int(round((asc + desc) * line_spacing)))
    try:
        cw = int(round(font.getlength("M")))
    except AttributeError:
        cw = font.getbbox("M")[2]
    cw = max(1, cw)
    masks = []
    for c in charset:
        img = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(img).text((0, (ch - (asc + desc)) // 2), c, fill=255, font=font)
        masks.append(np.asarray(img, dtype=np.float32) / 255.0)
    return np.stack(masks), cw, ch


def _sort_by_density(charset, masks):
    order = np.argsort(masks.reshape(len(charset), -1).mean(axis=1), kind="stable")
    return "".join(charset[i] for i in order), masks[order]


# ----------------------------------------------------------------------------
# nodes
# ----------------------------------------------------------------------------

DITHER_PATTERNS = [
    "diagonal stripes",
    "diagonal stripes (reverse)",
    "horizontal lines",
    "vertical lines",
    "crosshatch",
    "bayer",
    "halftone dots",
    "floyd-steinberg",
    "atkinson",
]


class X4L_Dither:
    DESCRIPTION = ("1-bit dither: turns an image into two colours using stripes, "
                   "Bayer dots, halftone or error diffusion. Also outputs the "
                   "pattern as a MASK for compositing.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "pattern": (DITHER_PATTERNS, {"default": "diagonal stripes"}),
                "pixel_size": ("INT", {"default": 2, "min": 1, "max": 32, "step": 1,
                    "tooltip": "Size of one dither pixel in output pixels. Bigger = coarser, more retro."}),
                "pattern_size": ("INT", {"default": 8, "min": 2, "max": 64, "step": 1,
                    "tooltip": "Period of the stripes / dots, measured in dither pixels. Ignored by floyd-steinberg and atkinson."}),
                "smoothing": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blends a little Bayer into stripes/dots. 0 = hard graphic lines, higher = finer tone steps."}),
                "black_point": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Everything darker than this becomes solid background. Raise it if dark areas get striped."}),
                "white_point": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Everything brighter than this becomes solid foreground."}),
                "gamma": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 5.0, "step": 0.05,
                    "tooltip": ">1 brightens midtones (more ink), <1 darkens them."}),
                "invert": ("BOOLEAN", {"default": False}),
                "fg_color": ("STRING", {"default": "#FFFFFF", "tooltip": "Colour of the 'on' pixels, hex."}),
                "bg_color": ("STRING", {"default": "#000000", "tooltip": "Colour of the 'off' pixels, hex."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "run"
    CATEGORY = "X4Lch3mist/image"

    def run(self, image, pattern, pixel_size, pattern_size, smoothing,
            black_point, white_point, gamma, invert, fg_color, bg_color):
        fg = _hex_to_rgb(fg_color, (255, 255, 255))
        bg = _hex_to_rgb(bg_color, (0, 0, 0))
        imgs, masks = [], []

        for frame in image.cpu().numpy():
            H, W = frame.shape[:2]
            v = _luma(frame[..., :3])
            v = _levels(v, black_point, white_point, gamma, invert)

            w, h = max(1, W // pixel_size), max(1, H // pixel_size)
            small = _resize_gray(v, w, h, Image.BOX) if pixel_size > 1 else v

            if pattern in _KERNELS:
                bits = _error_diffusion(small, pattern)
            else:
                tile = _threshold_map(pattern, pattern_size, smoothing)
                s = tile.shape[0]
                T = np.tile(tile, (h // s + 1, w // s + 1))[:h, :w]
                bits = (small > T).astype(np.float32)

            if pixel_size > 1:
                bits = np.asarray(
                    Image.fromarray((bits * 255).astype(np.uint8), "L").resize((W, H), Image.NEAREST),
                    dtype=np.float32) / 255.0

            rgb = bg[None, None, :] + (fg - bg)[None, None, :] * bits[..., None]
            imgs.append(rgb.astype(np.float32))
            masks.append(bits.astype(np.float32))

        return (torch.from_numpy(np.stack(imgs)), torch.from_numpy(np.stack(masks)))


class X4L_ASCII:
    DESCRIPTION = ("ASCII art: maps brightness to characters and renders them "
                   "with a monospace font. Colour can be fixed, fade with "
                   "brightness or be taken from the source image.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "charset": ("STRING", {"default": " .:-=+*#%@",
                    "tooltip": "Characters from dark to bright. The first one (usually a space) is used for the darkest areas."}),
                "sort_by_density": ("BOOLEAN", {"default": False,
                    "tooltip": "Re-order the charset by how much ink each glyph really has. Handy for custom charsets."}),
                "font_size": ("INT", {"default": 12, "min": 4, "max": 128, "step": 1,
                    "tooltip": "Character height in pixels. Smaller = more detail, bigger = more readable."}),
                "line_spacing": ("FLOAT", {"default": 1.0, "min": 0.6, "max": 2.0, "step": 0.05}),
                "black_point": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Everything darker than this becomes empty background."}),
                "white_point": ("FLOAT", {"default": 0.95, "min": 0.0, "max": 1.0, "step": 0.01}),
                "gamma": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 5.0, "step": 0.05}),
                "invert": ("BOOLEAN", {"default": False,
                    "tooltip": "Use for dark text on a light background."}),
                "color_mode": (["fade", "fixed", "source image"], {"default": "fade",
                    "tooltip": "fade: fg colour, dimmer in dark areas | fixed: one colour | source image: each character takes the colour of the picture."}),
                "fg_color": ("STRING", {"default": "#33FF66"}),
                "bg_color": ("STRING", {"default": "#000000"}),
            },
            "optional": {
                "font_path": ("STRING", {"default": "",
                    "tooltip": "Optional path to a .ttf/.otf monospace font. Empty = Consolas / DejaVu Sans Mono / built-in."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "text")
    FUNCTION = "run"
    CATEGORY = "X4Lch3mist/image"

    def run(self, image, charset, sort_by_density, font_size, line_spacing,
            black_point, white_point, gamma, invert, color_mode,
            fg_color, bg_color, font_path=""):
        if not charset:
            charset = " .:-=+*#%@"
        fg = _hex_to_rgb(fg_color, (51, 255, 102))
        bg = _hex_to_rgb(bg_color, (0, 0, 0))

        font = _load_font(font_size, font_path)
        glyphs, cw, ch = _glyph_atlas(charset, font, line_spacing)
        if sort_by_density:
            charset, glyphs = _sort_by_density(charset, glyphs)
        K = len(charset)

        imgs, masks, texts = [], [], []
        for frame in image.cpu().numpy():
            H, W = frame.shape[:2]
            rgb_src = frame[..., :3]
            cols, rows = max(1, W // cw), max(1, H // ch)

            v = _levels(_luma(rgb_src), black_point, white_point, gamma, invert)
            g = _resize_gray(v, cols, rows, Image.BOX)
            idx = np.minimum((g * K).astype(np.int32), K - 1)

            # cell colours
            if color_mode == "source image":
                col = _resize_rgb(rgb_src, cols, rows, Image.BOX)
                # lift dark source colours a bit so the glyphs stay visible
                col = np.clip(col / np.maximum(col.max(axis=-1, keepdims=True), 1e-3) *
                              (0.35 + 0.65 * g[..., None]), 0, 1)
            elif color_mode == "fixed":
                col = np.broadcast_to(fg, (rows, cols, 3))
            else:  # fade
                col = bg + (fg - bg) * (0.3 + 0.7 * g[..., None])

            # stitch glyph tiles: (rows, cols, ch, cw) -> (rows*ch, cols*cw)
            cover = glyphs[idx].transpose(0, 2, 1, 3).reshape(rows * ch, cols * cw)
            colour = np.repeat(np.repeat(col, ch, axis=0), cw, axis=1)
            art = bg + (colour - bg) * cover[..., None]

            # centre on a canvas of the original size so the workflow keeps its resolution
            canvas = np.empty((H, W, 3), dtype=np.float32)
            canvas[:] = bg
            mcanvas = np.zeros((H, W), dtype=np.float32)
            oy, ox = (H - rows * ch) // 2, (W - cols * cw) // 2
            canvas[oy:oy + rows * ch, ox:ox + cols * cw] = art
            mcanvas[oy:oy + rows * ch, ox:ox + cols * cw] = cover

            imgs.append(canvas)
            masks.append(mcanvas)
            texts.append("\n".join("".join(charset[i] for i in r).rstrip() for r in idx))

        return (torch.from_numpy(np.stack(imgs)),
                torch.from_numpy(np.stack(masks)),
                "\n\n".join(texts))


NODE_CLASS_MAPPINGS = {
    "X4L_Dither": X4L_Dither,
    "X4L_ASCII": X4L_ASCII,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "X4L_Dither": "Dither 1-bit",
    "X4L_ASCII": "ASCII Art",
}
