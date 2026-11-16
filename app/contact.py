import io

from PIL import Image, ImageChops, ImageFilter, ImageMath, ImageOps

Image.MAX_IMAGE_PIXELS = 200_000_000

VERSION = "2"

FILM_GAMMA = {"colour": 0.6, "bw": 0.65}
TARGET = 0.21
WHITE = 6.0
BLACK = 0.015


def _lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _enc(v):
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


LIN = [max(_lin(float(i)), 1e-4) for i in range(256)]


def _pct(hist, q):
    total = sum(hist)
    if not total:
        return None
    target, run = q * total, 0
    for i, n in enumerate(hist):
        run += n
        if run >= target:
            return i
    return 255


def _masks(small):
    lum = small.convert("L")
    top = _pct(lum.histogram(), 0.97)
    bright = lum.point(lambda v: 255 if v >= top else 0)
    table = [_pct(ch.histogram(bright), 0.5) or 255 for ch in small.split()]
    r, g, b = (ch.point(lambda v, t=t: min(255, round(255 * v / max(t, 1)))) for ch, t in zip(small.split(), table))
    lo = ImageChops.darker(r, ImageChops.darker(g, b))
    hi = ImageChops.lighter(r, ImageChops.lighter(g, b))
    is_table = ImageMath.lambda_eval(
        lambda a: (a["lo"] * 100 >= a["hi"] * 86) & (a["hi"] >= 165), lo=lo, hi=hi
    ).convert("L").point(lambda v: 255 if v else 0)
    film = ImageChops.invert(is_table).filter(ImageFilter.MinFilter(5))
    film = ImageChops.multiply(film, hi.point(lambda v: 255 if v > 4 else 0))
    if film.histogram()[255] < 0.03 * small.width * small.height:
        return None, None
    return film, lum


def _channel_lut(base_v, hist_img, gamma):
    base = LIN[max(base_v, 1)]
    mid = _pct(hist_img, 0.5)
    mid_x = (base / LIN[mid]) ** (1 / gamma) - 1 if mid is not None and LIN[mid] < base else 0.0
    scale = TARGET / mid_x if mid_x > 1e-4 else 1.0
    lut = []
    for i in range(256):
        x = max(((base / LIN[i]) ** (1 / gamma) - 1) * scale - BLACK, 0.0) if LIN[i] < base else 0.0
        lut.append(round(255 * _enc(x * (1 + x / WHITE**2) / (1 + x))))
    return lut


def _base(small, film, lum):
    base_l = _pct(lum.histogram(film), 0.98)
    clearest = ImageChops.multiply(film, lum.point(lambda v: 255 if v >= base_l else 0))
    if not clearest.histogram()[255]:
        clearest = film
    return [_pct(ch.histogram(clearest), 0.5) for ch in small.split()], base_l


def _image_mask(film, lum, base_l):
    clear = lum.point(lambda v: 0 if v >= base_l * 0.9 else 255)
    return ImageChops.multiply(film, clear)


def positive(img, process=None):
    img = ImageOps.exif_transpose(img).convert("RGB")
    if process == "slide":
        return img
    small = img.copy()
    small.thumbnail((700, 700))
    film, lum = _masks(small)
    if film is None:
        film = Image.new("L", small.size, 255)
        lum = small.convert("L")
    base, base_l = _base(small, film, lum)
    pic = _image_mask(film, lum, base_l)
    if pic.histogram()[255] < 0.01 * small.width * small.height:
        pic = film
    if process == "bw":
        g = small.convert("L")
        lut = _channel_lut(base_l, g.histogram(pic), FILM_GAMMA["bw"])
        return img.convert("L").point(lut)
    luts = [_channel_lut(b, ch.histogram(pic), FILM_GAMMA["colour"]) for b, ch in zip(base, small.split())]
    return Image.merge("RGB", [ch.point(lut) for ch, lut in zip(img.split(), luts)])


def to_jpeg(img, quality=88):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()
