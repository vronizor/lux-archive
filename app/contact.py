import io

from PIL import Image, ImageChops, ImageOps

Image.MAX_IMAGE_PIXELS = 200_000_000

FILM_GAMMA = {"colour": 0.6, "bw": 0.65}
LOW, HIGH = 0.002, 0.995


def _lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _enc(v):
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


LIN = [max(_lin(float(i)), 1e-4) for i in range(256)]


def _film_mask(img):
    r, g, b = img.split()
    lo = ImageChops.darker(r, ImageChops.darker(g, b))
    hi = ImageChops.lighter(r, ImageChops.lighter(g, b))
    not_table = lo.point(lambda v: 255 if v < 238 else 0)
    not_dark = hi.point(lambda v: 255 if v > 12 else 0)
    mask = ImageChops.multiply(not_table, not_dark)
    return mask if mask.histogram()[255] > 0.05 * img.width * img.height else None


def _pct(hist, q):
    total = sum(hist)
    target, run = q * total, 0
    for i, n in enumerate(hist):
        run += n
        if run >= target:
            return i
    return 255


def _curve(hist, gamma):
    base = LIN[max(_pct(hist, HIGH), 1)]
    dense = LIN[min(_pct(hist, LOW), 254)]
    top = (base / dense) ** (1 / gamma) - 1 or 1.0
    lut = []
    for i in range(256):
        ratio = (base / LIN[i]) ** (1 / gamma) - 1 if LIN[i] < base else 0.0
        lut.append(round(255 * _enc(ratio / top)))
    return lut


def positive(img, process=None):
    img = ImageOps.exif_transpose(img).convert("RGB")
    if process == "slide":
        return img
    small = img.copy()
    small.thumbnail((800, 800))
    mask = _film_mask(small)
    if process == "bw":
        g = small.convert("L")
        lut = _curve(g.histogram(mask), FILM_GAMMA["bw"])
        return img.convert("L").point(lut)
    luts = [_curve(ch.histogram(mask), FILM_GAMMA["colour"]) for ch in small.split()]
    return Image.merge("RGB", [ch.point(lut) for ch, lut in zip(img.split(), luts)])


def to_jpeg(img, quality=88):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()
