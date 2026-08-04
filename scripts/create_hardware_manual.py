from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "AeroOS_Hardware_Setup_and_Commissioning_Manual.pdf"
PHOTO_DIR = ROOT / "assets" / "manual"
PI4_PHOTO = PHOTO_DIR / "pi4-official.jpg"
DISPLAY_PHOTO = PHOTO_DIR / "touch-display-official.png"
DISPLAY_PLUGS_PHOTO = PHOTO_DIR / "touch-display-plugs.png"
PI_PLUGS_PHOTO = PHOTO_DIR / "pi-display-plugs.png"
DISPLAY_POWER_PHOTO = PHOTO_DIR / "touch-display-power.jpg"
ARDUCAM_PHOTO = PHOTO_DIR / "arducam-manual-cover.png"
DHT22_PHOTO = PHOTO_DIR / "dht22-adafruit.jpg"
DS18B20_PHOTO = PHOTO_DIR / "ds18b20-adafruit.jpg"
TEMT6000_PHOTO = PHOTO_DIR / "temt6000-sparkfun.jpg"
PCF8591_PHOTO = PHOTO_DIR / "pcf8591-waveshare.jpg"
IMAGER_DEVICE = PHOTO_DIR / "imager-device-tab.png"
IMAGER_OS = PHOTO_DIR / "imager-os-tab.png"
IMAGER_STORAGE = PHOTO_DIR / "imager-storage-tab.png"
IMAGER_CONFIRM = PHOTO_DIR / "imager-are-you-sure.png"
IMAGER_WRITE = PHOTO_DIR / "imager-write.png"

W, H = A4
M = 16 * mm
CONTENT_W = W - 2 * M
BLUE = colors.HexColor("#3676D8")
BLUE_DARK = colors.HexColor("#245CA9")
BLUE_SOFT = colors.HexColor("#E5EEFC")
CYAN = colors.HexColor("#3AA7C8")
CYAN_SOFT = colors.HexColor("#E7F6FA")
INK = colors.HexColor("#171719")
MUTED = colors.HexColor("#6D6E72")
PAPER = colors.HexColor("#F4F4F3")
SURFACE = colors.HexColor("#FBFBFA")
LINE = colors.HexColor("#D9DDE3")
AMBER = colors.HexColor("#DA8736")
AMBER_SOFT = colors.HexColor("#FFF0DE")
RED = colors.HexColor("#D54C4C")
RED_SOFT = colors.HexColor("#FCE7E7")
NAVY = colors.HexColor("#17233A")
WHITE = colors.white

PAGES = 22
REVISION = "4.0"


def rounded(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill=SURFACE, stroke=LINE, r=4 * mm):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, r, fill=1, stroke=1)


def text(c: canvas.Canvas, value: str, x: float, y: float, size=8, color=INK, font="Helvetica"):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, y, value)


def centered(c: canvas.Canvas, value: str, x: float, y: float, size=8, color=INK, font="Helvetica"):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(x, y, value)


def wrap_lines(value: str, width: float, size: float, font="Helvetica") -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def paragraph(c: canvas.Canvas, value: str, x: float, y: float, width: float, size=8, leading=11, color=MUTED, font="Helvetica") -> float:
    for line in wrap_lines(value, width, size, font):
        text(c, line, x, y, size, color, font)
        y -= leading
    return y


def photo(
    c: canvas.Canvas,
    path: Path,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    crop: tuple[float, float, float, float] | None = None,
    radius: float = 3 * mm,
    border=LINE,
):
    """Draw a sharp, cropped photo inside a rounded card.

    crop uses fractional coordinates (left, top, right, bottom) before the
    image is fitted to the requested box.
    """
    with Image.open(path) as source:
        image = source.convert("RGB")
        if crop:
            left, top, right, bottom = crop
            image = image.crop(
                (
                    round(image.width * left),
                    round(image.height * top),
                    round(image.width * right),
                    round(image.height * bottom),
                )
            )
        target_w = max(320, round(w * 2.5))
        target_h = max(240, round(h * 2.5))
        image = ImageOps.fit(image, (target_w, target_h), method=Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=94, optimize=True)
        buffer.seek(0)
        c.saveState()
        clip = c.beginPath()
        clip.roundRect(x, y, w, h, radius)
        c.clipPath(clip, stroke=0, fill=0)
        c.drawImage(ImageReader(buffer), x, y, width=w, height=h, mask="auto")
        c.restoreState()
    c.setStrokeColor(border)
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, radius, fill=0, stroke=1)


def source_line(c: canvas.Canvas, value: str, x: float, y: float, width: float):
    paragraph(c, value, x, y, width, 5.3, 6.5, MUTED)


def page_base(c: canvas.Canvas, page: int, section_name: str):
    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(M, H - 12 * mm, W - M, H - 12 * mm)
    text(c, "AEROOS", M, H - 9 * mm, 8, BLUE, "Helvetica-Bold")
    text(c, section_name.upper(), M + 23 * mm, H - 9 * mm, 6.4, MUTED, "Helvetica-Bold")
    c.line(M, 12 * mm, W - M, 12 * mm)
    text(c, f"Hardware bring-up and commissioning manual - Revision {REVISION}", M, 8 * mm, 6.2, MUTED)
    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(BLUE)
    c.drawRightString(W - M, 8 * mm, f"{page:02d} / {PAGES:02d}")


def heading(c: canvas.Canvas, number: str, title_value: str, subtitle: str):
    text(c, number, M, H - 27 * mm, 8, BLUE, "Helvetica-Bold")
    text(c, title_value, M, H - 38 * mm, 21, INK, "Helvetica-Bold")
    paragraph(c, subtitle, M, H - 46 * mm, CONTENT_W, 8.2, 11, MUTED)


def label(c: canvas.Canvas, value: str, x: float, y: float, color=BLUE):
    text(c, value.upper(), x, y, 6.2, color, "Helvetica-Bold")


def callout(c: canvas.Canvas, x: float, y: float, w: float, h: float, title_value: str, body: str, tone="blue"):
    fill, accent = {
        "blue": (BLUE_SOFT, BLUE),
        "cyan": (CYAN_SOFT, CYAN),
        "amber": (AMBER_SOFT, AMBER),
        "red": (RED_SOFT, RED),
    }[tone]
    rounded(c, x, y, w, h, fill, accent, 3 * mm)
    c.setFillColor(accent)
    c.roundRect(x, y, 3 * mm, h, 2 * mm, fill=1, stroke=0)
    text(c, title_value, x + 7 * mm, y + h - 8 * mm, 8.2, INK, "Helvetica-Bold")
    paragraph(c, body, x + 7 * mm, y + h - 14 * mm, w - 12 * mm, 7, 9, MUTED)


def wire(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float, color=BLUE, dashed=False):
    c.setStrokeColor(color)
    c.setLineWidth(1.4)
    if dashed:
        c.setDash(3, 2)
    c.line(x1, y1, x2, y2)
    c.setDash()
    angle = 1 if x2 >= x1 else -1
    c.setFillColor(color)
    c.setStrokeColor(color)
    c.line(x2, y2, x2 - angle * 3 * mm, y2 + 1.6 * mm)
    c.line(x2, y2, x2 - angle * 3 * mm, y2 - 1.6 * mm)


def component(c: canvas.Canvas, x: float, y: float, w: float, h: float, title_value: str, detail: str, accent=BLUE):
    rounded(c, x, y, w, h, SURFACE, LINE, 3 * mm)
    c.setFillColor(colors.Color(accent.red, accent.green, accent.blue, alpha=0.12))
    c.circle(x + 9 * mm, y + h / 2, 5 * mm, fill=1, stroke=0)
    centered(c, title_value[:1], x + 9 * mm, y + h / 2 - 2.4, 8, accent, "Helvetica-Bold")
    text(c, title_value, x + 17 * mm, y + h - 8 * mm, 7.6, INK, "Helvetica-Bold")
    paragraph(c, detail, x + 17 * mm, y + h - 13 * mm, w - 21 * mm, 6.3, 8, MUTED)


def step_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, number: int, title_value: str, body: str, check_value: str):
    rounded(c, x, y, w, h, SURFACE, LINE, 4 * mm)
    c.setFillColor(BLUE)
    c.circle(x + 10 * mm, y + h - 11 * mm, 6 * mm, fill=1, stroke=0)
    centered(c, str(number), x + 10 * mm, y + h - 13.4 * mm, 8, WHITE, "Helvetica-Bold")
    text(c, title_value, x + 20 * mm, y + h - 12.5 * mm, 9.3, INK, "Helvetica-Bold")
    paragraph(c, body, x + 8 * mm, y + h - 23 * mm, w - 16 * mm, 7, 9, MUTED)
    c.setStrokeColor(BLUE)
    c.setLineWidth(1)
    c.rect(x + 8 * mm, y + 7 * mm, 4 * mm, 4 * mm, fill=0, stroke=1)
    text(c, check_value, x + 15 * mm, y + 8 * mm, 6.4, BLUE_DARK, "Helvetica-Bold")


def cover(c: canvas.Canvas):
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#213B68"))
    c.circle(W - 20 * mm, H - 26 * mm, 63 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#10203B"))
    c.circle(10 * mm, 12 * mm, 52 * mm, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.roundRect(M, H - 38 * mm, 18 * mm, 18 * mm, 5 * mm, fill=1, stroke=0)
    c.setStrokeColor(WHITE)
    c.setLineWidth(2)
    c.circle(M + 9 * mm, H - 29 * mm, 4.5 * mm, fill=0, stroke=1)
    c.line(M + 9 * mm, H - 33 * mm, M + 9 * mm, H - 25 * mm)
    text(c, "AEROOS", M + 24 * mm, H - 30 * mm, 14, WHITE, "Helvetica-Bold")
    text(c, "RASPBERRY PI 4 / HARDWARE BRING-UP", M, H - 70 * mm, 8, colors.HexColor("#8DB9FF"), "Helvetica-Bold")
    text(c, "Hardware Setup and", M, H - 89 * mm, 28, WHITE, "Helvetica-Bold")
    text(c, "Commissioning Manual", M, H - 103 * mm, 28, WHITE, "Helvetica-Bold")
    paragraph(
        c,
        "Sensor, camera, display and dry-run control integration for the Nexora aeroponic research prototype.",
        M,
        H - 118 * mm,
        145 * mm,
        10,
        14,
        colors.HexColor("#BAC8DE"),
    )
    callout(
        c,
        M,
        48 * mm,
        CONTENT_W,
        38 * mm,
        "REVISION 4.0 - CLOSED-LOOP CONTROL + FLASHING",
        "Raspberry Pi 4 8 GB | SC1227 800 x 480 touch display | DHT22 | DS18B20 | TEMT6000 + PCF8591 | Arducam B0483. Includes automatic recirculation behavior, component photographs, safety gates and a visual image-flashing workflow.",
        "blue",
    )
    text(c, "Prepared 23 July 2026", M, 27 * mm, 7.2, colors.HexColor("#AAB8CD"))
    c.setFont("Helvetica-Bold", 7.2)
    c.drawRightString(W - M, 27 * mm, "A4 / VECTOR ILLUSTRATED")


def page_2(c):
    page_base(c, 2, "Safety boundary")
    heading(c, "01", "What this phase does", "AeroOS brings up sensing, imaging and the touchscreen while keeping every physical actuator unavailable.")
    y = H - 73 * mm
    cards = [
        ("SENSE", "DHT22 climate, DS18B20 solution temperature and coarse TEMT6000 light.", BLUE),
        ("SEE", "Arducam B0483 live 1920 x 1080 at 15 fps and requested 64 MP stills.", CYAN),
        ("CONTROL", "Fan policy runs as a request only. Mist and fan relay power remains held.", AMBER),
    ]
    for i, item in enumerate(cards):
        component(c, M + i * 59 * mm, y, 54 * mm, 33 * mm, item[0], item[1], item[2])
    callout(c, M, y - 45 * mm, CONTENT_W, 32 * mm, "NON-NEGOTIABLE POWER HOLD", "Do not connect pumps, fans, relay load terminals, the 5 V mist maker or the future 12 V supply during this phase. Pi GPIO is 3.3 V logic only. Header 5 V pins are fixed power rails, not controllable GPIO.", "red")
    label(c, "Capability truth table", M, y - 58 * mm)
    rows = [
        ("Available now", "Temperature, humidity, solution temperature, light percentage, camera"),
        ("Visible but unavailable", "pH, EC, reservoir level, delivery flow, dosing, mixer"),
        ("Output condition", "Actuator master enable = false; no relay GPIO object is created"),
        ("Automatic recirculation", "PIN-protected UI scheduler is ready; physical output stays blocked until relay commissioning"),
        ("System state", "Development / Interlocks unavailable"),
    ]
    yy = y - 69 * mm
    for left, right in rows:
        rounded(c, M, yy, CONTENT_W, 14 * mm, SURFACE, LINE, 2 * mm)
        text(c, left, M + 5 * mm, yy + 5.5 * mm, 7, INK, "Helvetica-Bold")
        paragraph(c, right, M + 48 * mm, yy + 8 * mm, 120 * mm, 6.4, 7.2, MUTED)
        yy -= 16.5 * mm


def page_3(c):
    page_base(c, 3, "Photographic inventory")
    heading(c, "02", "Identify the exact hardware first", "Match each photograph to the marking on your own part. Similar-looking modules can use different pin orders and relay polarity.")
    cards = [
        (PI4_PHOTO, "Raspberry Pi 4 Model B", "8 GB host; 40-pin header at the top edge.", "Raspberry Pi documentation"),
        (DISPLAY_PHOTO, "SC1227 7 inch display", "Original 800 x 480 DSI touch display.", "Raspberry Pi documentation"),
        (ARDUCAM_PHOTO, "Arducam 64 MP", "B0483 / IMX519 family; confirm the label on the ribbon or PCB.", "Arducam 64 MP manual"),
        (DHT22_PHOTO, "DHT22 climate sensor", "Use the bare-sensor or module wiring variant that matches your part.", "Adafruit product 385"),
        (DS18B20_PHOTO, "DS18B20 probe", "Waterproof probe; wire colours are not universal.", "Adafruit product 381"),
        (TEMT6000_PHOTO, "TEMT6000 light", "Three terminals: SIG, GND and VCC on the reference breakout.", "SparkFun BOB-08688"),
        (PCF8591_PHOTO, "PCF8591 ADC", "Reference board only; verify A0, SDA, SCL, VCC and GND labels.", "Waveshare PCF8591 board"),
        (ARDUCAM_PHOTO, "Relay and pumps", "Not pictured because your models and ratings are unverified. Record every marking before use.", "User hardware - photo required"),
    ]
    card_w, card_h = 41.5 * mm, 58 * mm
    start_y = 139 * mm
    for index, (path, title_value, detail, source) in enumerate(cards):
        col = index % 4
        row = index // 4
        x = M + col * 45.5 * mm
        y = start_y - row * 65 * mm
        rounded(c, x, y, card_w, card_h, SURFACE, LINE, 3 * mm)
        if title_value == "Relay and pumps":
            c.setFillColor(AMBER_SOFT)
            c.roundRect(x + 3 * mm, y + 28 * mm, card_w - 6 * mm, 26 * mm, 2 * mm, fill=1, stroke=0)
            centered(c, "PHOTO + RATING", x + card_w / 2, y + 42 * mm, 7.2, AMBER, "Helvetica-Bold")
            centered(c, "REQUIRED", x + card_w / 2, y + 34 * mm, 7.2, AMBER, "Helvetica-Bold")
        else:
            crop = (0.04, 0.02, 0.96, 0.68) if path == ARDUCAM_PHOTO else None
            photo(c, path, x + 3 * mm, y + 28 * mm, card_w - 6 * mm, 26 * mm, crop=crop, radius=2 * mm)
        text(c, title_value, x + 4 * mm, y + 22 * mm, 6.6, INK, "Helvetica-Bold")
        paragraph(c, detail, x + 4 * mm, y + 16 * mm, card_w - 8 * mm, 5.5, 6.5, MUTED)
        source_line(c, source, x + 4 * mm, y + 5 * mm, card_w - 8 * mm)
    callout(c, M, 22 * mm, CONTENT_W, 28 * mm, "BEFORE WIRING", "Photograph both sides of every relay, pump and fan. Record coil / input voltage, load voltage, rated current, terminal labels and whether the relay board claims 3.3 V logic compatibility. Stop if any marking is unreadable.", "amber")


def page_4(c):
    page_base(c, 4, "Wet and dry zones")
    heading(c, "03", "Separate water from logic", "Treat the prototype as two physical zones joined only by protected cables and tubing.")
    y = 67 * mm
    rounded(c, M, y, 82 * mm, 135 * mm, CYAN_SOFT, CYAN, 5 * mm)
    rounded(c, M + 92 * mm, y, 86 * mm, 135 * mm, BLUE_SOFT, BLUE, 5 * mm)
    label(c, "Wet zone", M + 7 * mm, y + 123 * mm, CYAN)
    label(c, "Dry zone", M + 99 * mm, y + 123 * mm, BLUE)
    wet = [("Chamber", "roots + mist"), ("Reservoir", "future 12 V pump"), ("DS18B20", "probe only"), ("Tubing", "drip loop before exit")]
    dry = [("Pi 4", "touch UI + control"), ("SC1227", "DSI + approved 5 V"), ("DHT22", "splash shield"), ("PCF8591", "TEMT6000 A0"), ("Arducam", "CSI ribbon"), ("Relays", "logic only - loads open")]
    yy = y + 102 * mm
    for a, b in wet:
        component(c, M + 7 * mm, yy, 68 * mm, 20 * mm, a, b, CYAN)
        yy -= 25 * mm
    yy = y + 102 * mm
    for a, b in dry:
        component(c, M + 99 * mm, yy, 72 * mm, 16 * mm, a, b, BLUE)
        yy -= 19 * mm
    wire(c, M + 82 * mm, y + 78 * mm, M + 92 * mm, y + 78 * mm, AMBER, True)
    centered(c, "SEALED PASS-THROUGH", W / 2, y + 84 * mm, 5.8, AMBER, "Helvetica-Bold")
    callout(c, M, 31 * mm, CONTENT_W, 25 * mm, "PLACEMENT RULE", "Mount the Pi, PCF8591 and relay logic higher than the reservoir rim, with connector openings facing down or sideways. Provide a drip loop on every cable approaching the dry enclosure.", "blue")


PIN_NAMES = {
    1: "3V3", 2: "5V", 3: "GPIO2 SDA", 4: "5V", 5: "GPIO3 SCL", 6: "GND",
    7: "GPIO4 1-Wire", 8: "GPIO14", 9: "GND", 10: "GPIO15", 11: "GPIO17 MIST",
    12: "GPIO18 DHT22", 13: "GPIO27", 14: "GND", 15: "GPIO22", 16: "GPIO23",
    17: "3V3", 18: "GPIO24", 19: "GPIO10", 20: "GND", 21: "GPIO9",
    22: "GPIO25 FAN", 23: "GPIO11", 24: "GPIO8", 25: "GND", 26: "GPIO7",
    27: "ID_SD", 28: "ID_SC", 29: "GPIO5", 30: "GND", 31: "GPIO6",
    32: "GPIO12", 33: "GPIO13", 34: "GND", 35: "GPIO19", 36: "GPIO16",
    37: "GPIO26", 38: "GPIO20", 39: "GND", 40: "GPIO21",
}


def page_5(c):
    page_base(c, 5, "Raspberry Pi header")
    heading(c, "04", "40-pin map: physical and BCM", "Orient the Pi with USB ports to the right. Pin 1 is the 3.3 V corner pin. Verify with the board silkscreen before wiring.")
    y0 = 50 * mm
    row_h = 8.3 * mm
    selected = {1, 2, 3, 4, 5, 6, 7, 9, 11, 12, 17, 22}
    for row in range(20):
        odd = row * 2 + 1
        even = odd + 1
        y = y0 + (19 - row) * row_h
        for pin, x in [(odd, M), (even, M + 91 * mm)]:
            fill = BLUE_SOFT if pin in selected else SURFACE
            stroke = BLUE if pin in selected else LINE
            rounded(c, x, y, 84 * mm, 6.5 * mm, fill, stroke, 1.5 * mm)
            c.setFillColor(BLUE if pin in selected else colors.HexColor("#BFC5CC"))
            circle_x = x + (5 * mm if pin % 2 else 79 * mm)
            c.circle(circle_x, y + 3.25 * mm, 2 * mm, fill=1, stroke=0)
            if pin % 2:
                text(c, f"{pin:02d}", x + 10 * mm, y + 2.1 * mm, 5.5, MUTED, "Helvetica-Bold")
                text(c, PIN_NAMES[pin], x + 20 * mm, y + 2.1 * mm, 5.5, INK)
            else:
                c.setFont("Helvetica-Bold", 5.5)
                c.setFillColor(MUTED)
                c.drawRightString(x + 74 * mm, y + 2.1 * mm, f"{pin:02d}")
                c.setFillColor(INK)
                c.drawRightString(x + 64 * mm, y + 2.1 * mm, PIN_NAMES[pin])
    callout(c, M, 25 * mm, CONTENT_W, 19 * mm, "USED IN THIS PHASE", "DHT22: physical 12 / BCM18. DS18B20: physical 7 / BCM4. I2C: physical 3 SDA and 5 SCL. Future relay logic: physical 11 / BCM17 and physical 22 / BCM25. Sensors use 3.3 V.", "blue")


def page_6(c):
    page_base(c, 6, "SC1227 touch display")
    heading(c, "05", "Connect the 7 inch DSI display", "Use the original 15-way DSI ribbon. The display is an approved 5 V load; the pumps and relay coils are not part of this connection.")
    photos = [
        (DISPLAY_PLUGS_PHOTO, "1  Display connector", "Open the retaining clip evenly; insert the FFC with contacts facing up, away from the display."),
        (PI_PLUGS_PHOTO, "2  Raspberry Pi DSI", "On Raspberry Pi 4, insert the other end in the DISPLAY connector with contacts toward USB / Ethernet."),
        (DISPLAY_POWER_PHOTO, "3  Display power", "Red to 5 V, black to GND. Use one documented pin pair and verify twice before power-on."),
    ]
    for i, (path, title_value, body) in enumerate(photos):
        x = M + i * 60.5 * mm
        rounded(c, x, 101 * mm, 56 * mm, 91 * mm, SURFACE, LINE, 4 * mm)
        photo(c, path, x + 4 * mm, 134 * mm, 48 * mm, 52 * mm, radius=2 * mm)
        text(c, title_value, x + 5 * mm, 124 * mm, 7.1, INK, "Helvetica-Bold")
        paragraph(c, body, x + 5 * mm, 117 * mm, 46 * mm, 5.8, 7, MUTED)
    source_line(c, "Photos: Raspberry Pi documentation, Touch Display connection sequence.", M, 95 * mm, CONTENT_W)
    label(c, "Assembly sequence", M, 86 * mm)
    seq = [
        "Shut down; unplug USB-C power. Wait until the red power LED is off.",
        "Fit the display-side FFC, close its latch and confirm the cable is square.",
        "Fit the Raspberry Pi-side FFC in the connector marked DISPLAY; do not use CAMERA.",
        "Connect display red to physical pin 2 or 4 (5 V), and black to physical pin 6 (GND).",
        "Inspect for exposed contacts, trapped ribbon, metal contact or reversed power.",
        "Power on and verify 800 x 480 landscape, all four touch corners and no undervoltage icon.",
    ]
    yy = 77 * mm
    for i, line in enumerate(seq, 1):
        c.setFillColor(BLUE)
        c.circle(M + 3 * mm, yy + 1 * mm, 2.5 * mm, fill=1, stroke=0)
        centered(c, str(i), M + 3 * mm, yy - 1 * mm, 5.5, WHITE, "Helvetica-Bold")
        text(c, line, M + 9 * mm, yy - 1 * mm, 6.3, INK)
        yy -= 7.8 * mm
    callout(c, M, 15 * mm, CONTENT_W, 18 * mm, "STOP CONDITION", "If the ribbon is hot, the display flashes, touch axes are reversed or Raspberry Pi reports undervoltage: shut down, disconnect power and recheck the DSI orientation and 5 V / GND pins.", "red")


def page_7(c):
    page_base(c, 7, "Arducam B0483")
    heading(c, "06", "Mount and verify the 64 MP camera", "Use the CSI ribbon without tight folds. Keep optics outside the direct mist plume and provide a repeatable viewing angle.")
    rounded(c, M, 78 * mm, 60 * mm, 112 * mm, SURFACE, LINE, 5 * mm)
    photo(c, ARDUCAM_PHOTO, M + 5 * mm, 119 * mm, 50 * mm, 65 * mm, crop=(0.03, 0.02, 0.96, 0.52), radius=3 * mm)
    text(c, "64 MP autofocus module", M + 8 * mm, 108 * mm, 7.3, INK, "Helvetica-Bold")
    paragraph(c, "Use the label on your PCB or cable to confirm B0483 / IMX519 compatibility. A similar lens housing is not sufficient identification.", M + 8 * mm, 100 * mm, 44 * mm, 6.1, 7.4, MUTED)
    source_line(c, "Photo: Arducam 64 MP camera manual.", M + 8 * mm, 83 * mm, 44 * mm)
    wire(c, M + 60 * mm, 140 * mm, M + 95 * mm, 140 * mm, BLUE)
    rounded(c, M + 95 * mm, 112 * mm, 83 * mm, 62 * mm, BLUE_SOFT, BLUE, 5 * mm)
    centered(c, "Raspberry Pi CSI", M + 136.5 * mm, 157 * mm, 9, INK, "Helvetica-Bold")
    text(c, "Live: 1920 x 1080 @ 15 fps", M + 104 * mm, 143 * mm, 7, BLUE_DARK)
    text(c, "Focus: continuous / capture cycle", M + 104 * mm, 133 * mm, 7, BLUE_DARK)
    text(c, "Still: 9152 x 6944 on request", M + 104 * mm, 123 * mm, 7, BLUE_DARK)
    label(c, "Mounting and optical reference", M, 65 * mm)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.rect(M, 28 * mm, CONTENT_W, 30 * mm, fill=0, stroke=1)
    for xx in range(0, 9):
        c.line(M + xx * CONTENT_W / 8, 28 * mm, M + xx * CONTENT_W / 8, 58 * mm)
    for yy in range(0, 4):
        c.line(M, 28 * mm + yy * 10 * mm, W - M, 28 * mm + yy * 10 * mm)
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.3)
    c.rect(M + 3 * mm, 31 * mm, CONTENT_W - 6 * mm, 24 * mm, fill=0, stroke=1)
    centered(c, "Keep the same camera height, angle, lighting and scale marker for every experiment.", W / 2, 41 * mm, 7.1, BLUE_DARK, "Helvetica-Bold")
    callout(c, M, 14 * mm, CONTENT_W, 11 * mm, "IMAGE BUILD GATE", "Commissioning requires enumeration, a stable 1920 x 1080 / 15 fps stream, autofocus and a 9152 x 6944 still.", "amber")


def page_8(c):
    page_base(c, 8, "DHT22")
    heading(c, "07", "Wire the chamber climate sensor", "First determine whether you have a bare four-pin DHT22 or a three-pin module. Do not copy a pin order that does not match the markings on your part.")
    photo(c, DHT22_PHOTO, M, 120 * mm, 68 * mm, 65 * mm, radius=4 * mm)
    source_line(c, "Reference photo: Adafruit DHT22 product 385.", M, 113 * mm, 68 * mm)
    rounded(c, M + 77 * mm, 121 * mm, 101 * mm, 64 * mm, BLUE_SOFT, BLUE, 4 * mm)
    label(c, "Bare 4-pin sensor - front grille facing you", M + 84 * mm, 175 * mm)
    rows = [
        ("1 VCC", "3.3 V - physical pin 1 or 17"),
        ("2 DATA", "GPIO18 - physical pin 12"),
        ("3 NC", "leave open"),
        ("4 GND", "ground - physical pin 9"),
        ("Pull-up", "4.7-10 kOhm from DATA to 3.3 V"),
    ]
    yy = 165 * mm
    for left, right in rows:
        text(c, left, M + 84 * mm, yy, 6.4, INK, "Helvetica-Bold")
        text(c, right, M + 111 * mm, yy, 6.2, BLUE_DARK)
        yy -= 8.6 * mm
    callout(c, M, 78 * mm, 86 * mm, 29 * mm, "THREE-PIN MODULE", "Read the PCB labels. Connect VCC to 3.3 V, OUT / DATA to GPIO18 and GND to ground. Most modules include a pull-up, but verify rather than assume.", "amber")
    callout(c, M + 92 * mm, 78 * mm, 86 * mm, 29 * mm, "PLACEMENT", "Use a vented splash shield. Keep the sensing face at least 100 mm from nozzles and 50 mm from Raspberry Pi, buck converter or relay coils.", "blue")
    label(c, "Commissioning test", M, 66 * mm)
    steps = [
        "With power off, continuity-check VCC, DATA and GND to the intended header pins.",
        "Boot; wait two minutes. Confirm readings update approximately every two seconds.",
        "Compare against a trusted room reference for ten minutes; note the offset, do not silently correct it.",
        "Unplug DATA: within ten seconds AeroOS must show climate unavailable and request fan OFF.",
        "Reconnect: valid temperature and RH must recover without inventing the missing samples.",
    ]
    yy = 60 * mm
    for i, body in enumerate(steps, 1):
        text(c, f"{i}.", M, yy, 6.3, BLUE, "Helvetica-Bold")
        paragraph(c, body, M + 7 * mm, yy, CONTENT_W - 7 * mm, 5.7, 6.3, INK)
        yy -= 6.1 * mm
    callout(c, M, 13 * mm, CONTENT_W, 18 * mm, "STOP", "Any hot sensor, unstable Raspberry Pi, impossible humidity or swapped pin marking: power off and re-identify the module.", "red")


def page_9(c):
    page_base(c, 9, "DS18B20")
    heading(c, "08", "Wire the waterproof solution probe", "The 1-Wire data line requires a 4.7 kOhm pull-up to 3.3 V. Probe wire colours vary; verify the seller’s label before applying power.")
    x1, y1 = M, 125 * mm
    component(c, x1, y1, 48 * mm, 27 * mm, "3.3 V", "Physical pin 1 or 17", RED)
    component(c, x1, y1 - 34 * mm, 48 * mm, 27 * mm, "GPIO4", "Physical pin 7 / 1-Wire", BLUE)
    component(c, x1, y1 - 68 * mm, 48 * mm, 27 * mm, "GND", "Physical pin 9", INK)
    probe_x = M + 129 * mm
    rounded(c, probe_x, y1 - 52 * mm, 49 * mm, 70 * mm, SURFACE, LINE, 5 * mm)
    photo(c, DS18B20_PHOTO, probe_x + 4 * mm, y1 - 18 * mm, 41 * mm, 31 * mm, radius=3 * mm)
    centered(c, "DS18B20 reference probe", probe_x + 24.5 * mm, y1 - 28 * mm, 6.2, INK, "Helvetica-Bold")
    source_line(c, "Photo: Adafruit product 381.", probe_x + 6 * mm, y1 - 36 * mm, 37 * mm)
    wire(c, x1 + 48 * mm, y1 + 13.5 * mm, probe_x, y1 + 6 * mm, RED)
    wire(c, x1 + 48 * mm, y1 - 20.5 * mm, probe_x, y1 - 18 * mm, BLUE)
    wire(c, x1 + 48 * mm, y1 - 54.5 * mm, probe_x, y1 - 44 * mm, INK)
    c.setStrokeColor(AMBER)
    c.setLineWidth(2)
    c.line(M + 73 * mm, y1 + 13.5 * mm, M + 73 * mm, y1 - 20.5 * mm)
    for i in range(7):
        yy = y1 + 8 * mm - i * 5 * mm
        c.line(M + 69 * mm, yy, M + 77 * mm, yy - 2.5 * mm)
    text(c, "4.7 kOhm", M + 79 * mm, y1 - 8 * mm, 7, AMBER, "Helvetica-Bold")
    callout(c, M, 19 * mm, 85 * mm, 32 * mm, "WIRE IDENTIFICATION", "Common probes use red = VCC, black / blue = GND and yellow / white = DATA, but this is not guaranteed. Use the exact supplier diagram; never rely on colour alone.", "amber")
    callout(c, M + 93 * mm, 19 * mm, 85 * mm, 32 * mm, "PLACEMENT + TEST", "Keep joints dry and add a drip loop. Confirm a `/sys/bus/w1/devices/28-*` device, compare at two temperatures, then unplug and verify only solution temperature becomes unavailable.", "blue")


def page_10(c):
    page_base(c, 10, "TEMT6000 and PCF8591")
    heading(c, "09", "Connect coarse ambient light telemetry", "The TEMT6000 analog output is read on PCF8591 A0. This 8-bit ADC is not accepted for production pH or EC chemistry.")
    photo(c, TEMT6000_PHOTO, M, 128 * mm, 52 * mm, 50 * mm, radius=4 * mm)
    text(c, "TEMT6000 reference breakout", M, 120 * mm, 6.8, INK, "Helvetica-Bold")
    source_line(c, "Photo: SparkFun BOB-08688.", M, 114 * mm, 52 * mm)
    photo(c, PCF8591_PHOTO, M + 66 * mm, 128 * mm, 52 * mm, 50 * mm, radius=4 * mm)
    text(c, "PCF8591 reference board", M + 66 * mm, 120 * mm, 6.8, INK, "Helvetica-Bold")
    source_line(c, "Photo: Waveshare PCF8591 AD/DA board.", M + 66 * mm, 114 * mm, 52 * mm)
    rounded(c, M + 132 * mm, 128 * mm, 46 * mm, 50 * mm, BLUE_SOFT, BLUE, 4 * mm)
    centered(c, "Raspberry Pi 4", M + 155 * mm, 165 * mm, 8.2, INK, "Helvetica-Bold")
    centered(c, "pin 3  SDA", M + 155 * mm, 151 * mm, 6.5, BLUE_DARK)
    centered(c, "pin 5  SCL", M + 155 * mm, 142 * mm, 6.5, BLUE_DARK)
    centered(c, "3.3 V + GND", M + 155 * mm, 133 * mm, 6.5, BLUE_DARK)
    wire(c, M + 52 * mm, 151 * mm, M + 66 * mm, 151 * mm, CYAN)
    wire(c, M + 118 * mm, 151 * mm, M + 132 * mm, 151 * mm, BLUE)
    label(c, "Wiring table", M, 100 * mm)
    rows = [
        ("TEMT VCC", "PCF VCC", "Pi 3.3 V"),
        ("TEMT OUT", "PCF A0", "Analog channel 0"),
        ("TEMT GND", "PCF GND", "Common Pi ground"),
        ("PCF SDA", "-", "Physical pin 3 / BCM2"),
        ("PCF SCL", "-", "Physical pin 5 / BCM3"),
    ]
    yy = 88 * mm
    for a, b, d in rows:
        rounded(c, M, yy, CONTENT_W, 10 * mm, SURFACE, LINE, 1.5 * mm)
        text(c, a, M + 4 * mm, yy + 3.3 * mm, 6.2, INK, "Helvetica-Bold")
        text(c, b, M + 56 * mm, yy + 3.3 * mm, 6.2, BLUE_DARK)
        text(c, d, M + 104 * mm, yy + 3.3 * mm, 6.2, MUTED)
        yy -= 12 * mm
    callout(c, M, 18 * mm, CONTENT_W, 20 * mm, "DISPLAYED VALUE", "Leave A1, A2 and A3 unused. AeroOS reports a coarse 0-100% A0 percentage. Verify the labels on your own boards; a reference photo is not a pinout. The result is not calibrated lux, PAR or PPFD.", "amber")


def page_11(c):
    page_base(c, 11, "Relay and pump state")
    heading(c, "10", "Automatic closed-loop recirculation", "Water starts in one reservoir, is pumped to the root nozzles, and returns by gravity to the same reservoir. The UI switch controls the scheduler; it never directly energizes a GPIO.")
    label(c, "Physical water path", M, 193 * mm, BLUE)
    nodes = [
        ("01", "Reservoir", "shared water volume", CYAN),
        ("02", "Pump + relay", "12 V load path", AMBER),
        ("03", "Root nozzles", "short mist pulse", BLUE),
        ("04", "Gravity return", "drain to reservoir", CYAN),
    ]
    x_positions = [M, M + 45 * mm, M + 90 * mm, M + 135 * mm]
    for index, (number, title_value, detail, tone) in enumerate(nodes):
        x = x_positions[index]
        rounded(c, x, 153 * mm, 39 * mm, 31 * mm, SURFACE, tone, 3 * mm)
        centered(c, number, x + 6 * mm, 173 * mm, 6.2, tone, "Helvetica-Bold")
        text(c, title_value, x + 5 * mm, 165 * mm, 7, INK, "Helvetica-Bold")
        paragraph(c, detail, x + 5 * mm, 159 * mm, 29 * mm, 5.6, 6.2, MUTED)
        if index < 3:
            wire(c, x + 39 * mm, 168.5 * mm, x_positions[index + 1], 168.5 * mm, tone)
    c.setStrokeColor(CYAN)
    c.setLineWidth(1.4)
    c.setDash(3, 2)
    c.line(M + 154 * mm, 150 * mm, M + 154 * mm, 143 * mm)
    c.line(M + 154 * mm, 143 * mm, M + 19 * mm, 143 * mm)
    c.line(M + 19 * mm, 143 * mm, M + 19 * mm, 150 * mm)
    c.setDash()
    centered(c, "same reservoir - no drain-to-waste outlet", W / 2, 136 * mm, 6.1, CYAN, "Helvetica-Bold")

    label(c, "What the interface now does", M, 119 * mm, BLUE)
    behaviors = [
        ("Enable switch", "operator PIN required"),
        ("Missing level / flow", "30 min supervised session"),
        ("Development pulse", "maximum 2 seconds"),
        ("Default interval", "one request every 5 minutes"),
        ("Disable switch", "pump OFF immediately"),
        ("Expiry / restart / fault", "automation OFF + pump OFF"),
    ]
    yy = 105 * mm
    for left, right in behaviors:
        rounded(c, M, yy, 84 * mm, 10 * mm, BLUE_SOFT, BLUE, 2 * mm)
        text(c, left, M + 4 * mm, yy + 3.4 * mm, 6, INK, "Helvetica-Bold")
        c.setFont("Helvetica-Bold", 5.8)
        c.setFillColor(BLUE_DARK)
        c.drawRightString(M + 80 * mm, yy + 3.4 * mm, right)
        yy -= 12 * mm

    label(c, "Physical activation boundary", M + 94 * mm, 119 * mm, AMBER)
    activation = [
        ("Shipped image", "master enable false"),
        ("Relay polarity", "must be measured"),
        ("Relay input", "must accept 3.3 V"),
        ("Pump supply", "separate rated 12 V"),
        ("Dry-run risk", "operator supervision"),
        ("Unverified state", "switch remains disabled"),
    ]
    yy = 105 * mm
    for left, right in activation:
        rounded(c, M + 94 * mm, yy, 84 * mm, 10 * mm, AMBER_SOFT, AMBER, 2 * mm)
        text(c, left, M + 98 * mm, yy + 3.4 * mm, 6, INK, "Helvetica-Bold")
        c.setFont("Helvetica-Bold", 5.8)
        c.setFillColor(AMBER)
        c.drawRightString(M + 174 * mm, yy + 3.4 * mm, right)
        yy -= 12 * mm

    callout(c, M, 17 * mm, CONTENT_W, 22 * mm, "IMPORTANT", "The automatic function is implemented end-to-end, but the supplied Raspberry Pi profile deliberately keeps actuator_master_enable=false and both relay drivers disabled. After relay and 12 V power commissioning, the same PIN-protected switch activates the bounded scheduler. Never power a pump from a Pi header pin.", "red")


def page_12(c):
    page_base(c, 12, "Cable routing")
    heading(c, "11", "Route cables for service and safety", "Use distinct paths for low-voltage sensors, camera / display ribbons and future actuator power.")
    y = 70 * mm
    rounded(c, M, y, CONTENT_W, 125 * mm, SURFACE, LINE, 5 * mm)
    lanes = [
        ("LANE A - SENSOR", BLUE, "DHT22, DS18B20, I2C"),
        ("LANE B - HIGH SPEED", CYAN, "DSI display, CSI camera"),
        ("LANE C - FUTURE POWER", AMBER, "12 V pump / fan - empty now"),
    ]
    for i, (name, color, detail) in enumerate(lanes):
        yy = y + (95 - i * 34) * mm
        c.setFillColor(colors.Color(color.red, color.green, color.blue, alpha=0.10))
        c.roundRect(M + 12 * mm, yy, CONTENT_W - 24 * mm, 22 * mm, 3 * mm, fill=1, stroke=0)
        c.setStrokeColor(color)
        c.setLineWidth(3)
        c.line(M + 18 * mm, yy + 11 * mm, W - M - 18 * mm, yy + 11 * mm)
        text(c, name, M + 21 * mm, yy + 14 * mm, 7, color, "Helvetica-Bold")
        text(c, detail, M + 21 * mm, yy + 5 * mm, 6.4, MUTED)
    c.setFillColor(BLUE_SOFT)
    c.roundRect(M + 12 * mm, y + 8 * mm, 55 * mm, 19 * mm, 3 * mm, fill=1, stroke=0)
    centered(c, "DRIP LOOP BEFORE ENTRY", M + 39.5 * mm, y + 15 * mm, 6.2, BLUE_DARK, "Helvetica-Bold")
    c.setStrokeColor(BLUE)
    c.arc(M + 72 * mm, y + 5 * mm, M + 95 * mm, y + 28 * mm, startAng=180, extent=180)
    text(c, "Strain relief", M + 104 * mm, y + 15 * mm, 7, INK, "Helvetica-Bold")
    text(c, "Label both ends", M + 140 * mm, y + 15 * mm, 7, INK, "Helvetica-Bold")
    callout(c, M, 29 * mm, CONTENT_W, 28 * mm, "ROUTING RULES", "No ribbon cable under sharp metal edges. No sensor splice in the wet zone. Keep future motor wiring separate from I2C and 1-Wire. Leave service loops without allowing cable coils to sit below possible leaks.", "blue")


def page_13(c):
    page_base(c, 13, "Assembly sequence")
    heading(c, "12", "Assembly steps 1-4", "Complete each check box before moving on. Keep every power supply disconnected during continuity work.")
    step_card(c, M, 135 * mm, 85 * mm, 60 * mm, 1, "Prepare and label", "Photograph the Pi header. Label DHT22, DS18B20, PCF8591, TEMT6000, camera, display and both relay channels.", "Every lead identified at both ends")
    step_card(c, M + 93 * mm, 135 * mm, 85 * mm, 60 * mm, 2, "Mount dry enclosure", "Place the Pi above the reservoir rim. Provide airflow, cable entry glands, a drip edge and access to SD / USB.", "Enclosure stable and splash-separated")
    step_card(c, M, 66 * mm, 85 * mm, 60 * mm, 3, "Install display", "Connect DSI ribbon, approved display 5 V and ground. Keep the remaining 5 V rail clear of actuator loads.", "Ribbon latched and polarity verified")
    step_card(c, M + 93 * mm, 66 * mm, 85 * mm, 60 * mm, 4, "Install camera", "Connect CSI ribbon, mount outside direct mist and place a scale marker in the root field of view.", "Lens clean; mount cannot shift")
    callout(c, M, 25 * mm, CONTENT_W, 27 * mm, "CONTINUITY GATE", "With power still off, confirm no short between 3.3 V and GND, no short between 5 V and GND, and no accidental continuity from any relay load terminal to the Pi.", "amber")


def page_14(c):
    page_base(c, 14, "Assembly sequence")
    heading(c, "13", "Assembly steps 5-8", "Bring up one sensor bus at a time so a wiring fault has a narrow search area.")
    step_card(c, M, 135 * mm, 85 * mm, 60 * mm, 5, "Wire DHT22", "Use 3.3 V, GPIO18 and ground. Install the vented splash shield in representative chamber air.", "Data line verified at physical pin 12")
    step_card(c, M + 93 * mm, 135 * mm, 85 * mm, 60 * mm, 6, "Wire DS18B20", "Use GPIO4 with a 4.7 kOhm pull-up to 3.3 V. Keep the cable joint dry and add a drip loop.", "Probe enumerates on 1-Wire")
    step_card(c, M, 66 * mm, 85 * mm, 60 * mm, 7, "Wire light path", "Connect TEMT6000 output to PCF8591 A0, then SDA / SCL to pins 3 / 5 at 3.3 V.", "0x48 appears on I2C bus 1")
    step_card(c, M + 93 * mm, 66 * mm, 85 * mm, 60 * mm, 8, "Prepare relay hold", "Connect no load terminals. Confirm labels only. Leave the actuator master enable false.", "COM / NO / NC visibly marked HOLD")
    callout(c, M, 25 * mm, CONTENT_W, 27 * mm, "FIRST POWER-ON", "Power the Pi and display only. Watch for heat, smell, reboot loops or undervoltage. If any appear, shut down immediately and disconnect power before inspection.", "red")


def flow_box(c, x, y, w, title_value, detail, tone=BLUE):
    component(c, x, y, w, 24 * mm, title_value, detail, tone)


def page_15(c):
    page_base(c, 15, "AeroOS boot flow")
    heading(c, "14", "Boot and commissioning flow", "The operating system proves safe state before presenting the chamber UI.")
    xs = [M, M + 62 * mm, M + 124 * mm]
    ys = [156 * mm, 108 * mm, 60 * mm]
    nodes = [
        ("01 Power", "Pi + display only", BLUE),
        ("02 Kernel", "I2C, 1-Wire, DSI, CSI", BLUE),
        ("03 Camera gate", "enumerate + stream + AF + still", CYAN),
        ("04 AeroOS", "outputs forced off", BLUE),
        ("05 Sensors", "nullable capability scan", BLUE),
        ("06 State", "Development / Interlocks unavailable", AMBER),
        ("07 Touch UI", "800 x 480 local kiosk", BLUE),
        ("08 Monitor", "2 second telemetry loop", BLUE),
        ("09 Power hold", "relay loads remain open", RED),
    ]
    for idx, (title_value, detail, tone) in enumerate(nodes):
        col = idx % 3
        row = idx // 3
        x, y = xs[col], ys[row]
        flow_box(c, x, y, 54 * mm, title_value, detail, tone)
        if col < 2:
            wire(c, x + 54 * mm, y + 12 * mm, xs[col + 1], y + 12 * mm, tone)
        elif row < 2:
            wire(c, x + 27 * mm, y, x + 27 * mm, ys[row + 1] + 24 * mm, tone)
    callout(c, M, 23 * mm, CONTENT_W, 22 * mm, "FAIL-SAFE RESULT", "A camera gate failure blocks commissioning. A sensor failure is visible and nullable. Browser failure, service restart and shutdown all request outputs off.", "blue")


def page_16(c):
    page_base(c, 16, "Automation gates")
    heading(c, "15", "How the automatic toggle flows", "The dashboard switch controls a bounded scheduler. Physical pumping begins only after the hardware master and relay channel have been commissioned.")
    gates = [
        ("01", "Operator enables", "PIN-protected Automatic recirculation switch is turned on."),
        ("02", "Hardware gate", "Actuator master true; relay polarity and safe boot verified."),
        ("03", "Session gate", "With missing level / flow, a 30 minute supervised session is required."),
        ("04", "Cycle due", "The next-cycle timestamp has elapsed; no output is already active."),
        ("05", "Safety validation", "Fresh sensors, no critical lockout and duration within hard limit."),
        ("06", "Relay pulse", "GPIO commands the verified driver; 12 V pump power stays outside Raspberry Pi."),
        ("07", "Water returns", "Mist drains from the roots back into the same reservoir."),
        ("08", "Stop safely", "Disable, expiry, restart or fault requests automation OFF and pump OFF."),
    ]
    for i, (number, title_value, detail) in enumerate(gates):
        col = i % 2
        row = i // 2
        x = M + col * 91 * mm
        y = 169 * mm - row * 34 * mm
        rounded(c, x, y, 85 * mm, 27 * mm, BLUE_SOFT if i < 6 else CYAN_SOFT, BLUE if i < 6 else CYAN, 3 * mm)
        centered(c, number, x + 9 * mm, y + 11 * mm, 8, BLUE, "Helvetica-Bold")
        text(c, title_value, x + 18 * mm, y + 17 * mm, 6.8, INK, "Helvetica-Bold")
        paragraph(c, detail, x + 18 * mm, y + 11 * mm, 61 * mm, 5.5, 6.4, MUTED)
        if i < len(gates) - 2:
            wire(c, x + 42 * mm, y, x + 42 * mm, y - 7 * mm, BLUE)
    callout(c, M, 24 * mm, CONTENT_W, 27 * mm, "SHIPPED IMAGE STATE", "The complete UI and scheduler can be tested in the simulator. On the Raspberry Pi image, Gate 02 is false by default, so the switch is visibly disabled and no relay GPIO object exists. Commissioning the relay and hardware master unlocks the same flow; it does not require a second UI.", "amber")


def page_17(c):
    page_base(c, 17, "Commissioning tests")
    heading(c, "16", "Test cards", "Record date, operator, result and evidence for every card. A pass requires stable behavior, not one successful sample.")
    tests = [
        ("DISPLAY + TOUCH", "Boot 10 times. Confirm 800 x 480 landscape, accurate touch corners and no horizontal scrolling.", "Screenshot + boot log"),
        ("DHT22", "Observe 10 minutes. Unplug: value becomes unavailable. Reconnect: valid telemetry recovers.", "Temperature / RH history"),
        ("DS18B20", "Compare at room and reservoir temperature. Unplug: only solution temperature becomes unavailable.", "Two-point record"),
        ("TEMT6000", "Cover and illuminate sensor. Confirm monotonic 0-100% movement; never label as calibrated lux.", "ADC percentage plot"),
        ("CAMERA", "Stream 1080p15, autofocus, take 9152 x 6944 still, stop / restart stream and inspect sharpness.", "JPEG + gate logs"),
        ("OUTPUT SAFETY", "Try manual and automatic mist, fan and dosing paths. Master false must prevent every GPIO energize attempt.", "API audit + GPIO test"),
    ]
    x_positions = [M, M + 91 * mm]
    yy = 161 * mm
    for i, (title_value, body, evidence) in enumerate(tests):
        x = x_positions[i % 2]
        if i and i % 2 == 0:
            yy -= 56 * mm
        rounded(c, x, yy, 85 * mm, 47 * mm, SURFACE, LINE, 4 * mm)
        label(c, title_value, x + 7 * mm, yy + 36 * mm)
        paragraph(c, body, x + 7 * mm, yy + 28 * mm, 71 * mm, 6.5, 8, MUTED)
        text(c, f"Evidence: {evidence}", x + 7 * mm, yy + 7 * mm, 5.8, BLUE_DARK, "Helvetica-Bold")
    callout(c, M, 20 * mm, CONTENT_W, 20 * mm, "ACCEPTANCE", "Sensors and camera operate; missing values remain unavailable; every physical actuator remains unpowered.", "blue")


def decision(c, x, y, question, yes_text, no_text):
    rounded(c, x, y, 52 * mm, 21 * mm, BLUE_SOFT, BLUE, 3 * mm)
    centered(c, question, x + 26 * mm, y + 8 * mm, 6.5, INK, "Helvetica-Bold")
    wire(c, x + 26 * mm, y, x + 26 * mm, y - 12 * mm, BLUE)
    text(c, f"YES: {yes_text}", x - 5 * mm, y - 19 * mm, 5.6, BLUE_DARK, "Helvetica-Bold")
    text(c, f"NO: {no_text}", x + 28 * mm, y - 19 * mm, 5.6, RED, "Helvetica-Bold")


def page_18(c):
    page_base(c, 18, "Troubleshooting")
    heading(c, "17", "Troubleshooting decision trees", "Power off before reseating any ribbon or moving any conductor.")
    label(c, "Sensor unavailable", M, 185 * mm)
    decision(c, M + 8 * mm, 154 * mm, "Correct 3.3 V and GND?", "check bus", "rewire")
    decision(c, M + 66 * mm, 154 * mm, "Bus enumerates?", "check data", "inspect pull-up")
    decision(c, M + 124 * mm, 154 * mm, "Only one driver fails?", "replace sensor", "inspect shared wiring")
    label(c, "Camera gate failed", M, 113 * mm)
    decision(c, M + 8 * mm, 82 * mm, "Camera listed?", "test stream", "reseat CSI")
    decision(c, M + 66 * mm, 82 * mm, "1080p stream stable?", "test AF", "inspect ribbon / power")
    decision(c, M + 124 * mm, 82 * mm, "64 MP still saved?", "pass gate", "check driver pin")
    callout(c, M, 30 * mm, 85 * mm, 33 * mm, "PI REBOOTS OR UNDERVOLTAGE", "Disconnect every nonessential load. Keep pumps, fans, mister and relay load contacts open. Verify the Pi supply and display wiring.", "red")
    callout(c, M + 93 * mm, 30 * mm, 85 * mm, 33 * mm, "TOUCH WRONG OR CLIPPED", "Confirm 800 x 480 landscape, DSI autodetection and the input calibration rule. Restart only after a clean shutdown.", "amber")


def page_19(c):
    page_base(c, 19, "Future 12 V power phase")
    heading(c, "18", "Power architecture - future phase only", "This appendix shows separation boundaries without inventing pump ratings, fuses, wire sizes or converter limits.")
    y = 104 * mm
    rounded(c, M, y, 52 * mm, 66 * mm, BLUE_SOFT, BLUE, 5 * mm)
    centered(c, "5 V LOGIC DOMAIN", M + 26 * mm, y + 53 * mm, 8, BLUE_DARK, "Helvetica-Bold")
    centered(c, "Pi 4", M + 26 * mm, y + 39 * mm, 7, INK)
    centered(c, "SC1227 display", M + 26 * mm, y + 28 * mm, 7, INK)
    centered(c, "relay logic only", M + 26 * mm, y + 17 * mm, 7, INK)
    rounded(c, M + 66 * mm, y, 46 * mm, 66 * mm, AMBER_SOFT, AMBER, 5 * mm)
    centered(c, "INTERFACE", M + 89 * mm, y + 53 * mm, 8, AMBER, "Helvetica-Bold")
    centered(c, "fuse", M + 89 * mm, y + 39 * mm, 7, INK)
    centered(c, "driver / relay", M + 89 * mm, y + 28 * mm, 7, INK)
    centered(c, "flyback protection", M + 89 * mm, y + 17 * mm, 7, INK)
    rounded(c, M + 126 * mm, y, 52 * mm, 66 * mm, RED_SOFT, RED, 5 * mm)
    centered(c, "12 V ACTUATOR DOMAIN", M + 152 * mm, y + 53 * mm, 8, RED, "Helvetica-Bold")
    centered(c, "mist pump", M + 152 * mm, y + 39 * mm, 7, INK)
    centered(c, "ventilation fan", M + 152 * mm, y + 28 * mm, 7, INK)
    centered(c, "future measured loads", M + 152 * mm, y + 17 * mm, 7, INK)
    wire(c, M + 52 * mm, y + 33 * mm, M + 66 * mm, y + 33 * mm, BLUE, True)
    wire(c, M + 112 * mm, y + 33 * mm, M + 126 * mm, y + 33 * mm, AMBER, True)
    callout(c, M, 68 * mm, CONTENT_W, 25 * mm, "MEASURE BEFORE DESIGN", "Record each pump and fan nameplate, steady current, startup current, voltage tolerance and duty cycle. Then select fuse, conductor, connector, driver, buck converter and enclosure thermal design.", "amber")
    callout(c, M, 36 * mm, CONTENT_W, 25 * mm, "COMMON REFERENCE", "If a non-isolated logic interface requires a common ground, implement it at one documented point after verifying the module topology. Never route actuator current through Pi ground pins.", "red")
    centered(c, "HOLD - DO NOT ASSEMBLE THIS DOMAIN IN REVISION 4.0", W / 2, 22 * mm, 8, RED, "Helvetica-Bold")


def page_20(c):
    page_base(c, 20, "Release checklist")
    heading(c, "19", "Ready for sensor and camera trials", "Sign only after the evidence exists. This is not approval for powered pumps, fans, mist makers or dosing.")
    checks = [
        "Pi 4 and SC1227 boot reliably at 800 x 480 landscape",
        "Touch targets respond accurately across all screen edges",
        "DHT22 reports temperature and humidity; failure becomes unavailable",
        "DS18B20 reports solution temperature through 1-Wire",
        "PCF8591 appears at 0x48 and TEMT6000 changes monotonically",
        "Arducam passes 1080p15, autofocus and 9152 x 6944 still capture",
        "pH, EC, level and flow remain explicitly unavailable",
        "Automatic recirculation is PIN-protected and master false prevents GPIO energizing",
        "Relay COM / NO / NC terminals are labelled HOLD - POWER PHASE",
        "Wet / dry separation, drip loops and strain relief are complete",
    ]
    yy = 181 * mm
    for item in checks:
        c.setStrokeColor(BLUE)
        c.setLineWidth(1)
        c.rect(M, yy - 1 * mm, 4 * mm, 4 * mm, fill=0, stroke=1)
        paragraph(c, item, M + 8 * mm, yy + 1.2 * mm, CONTENT_W - 8 * mm, 7, 9, INK)
        yy -= 11.5 * mm
    callout(c, M, 35 * mm, CONTENT_W, 31 * mm, "PHOTO + TECHNICAL SOURCES", "raspberrypi.com/documentation/accessories/display.html and /computers/getting-started.html; official Raspberry Pi documentation repository; adafruit.com/product/385 and /381; sparkfun.com TEMT6000 BOB-08688; waveshare.com/wiki/PCF8591_AD_DA_Board; arducam.com/downloads/arducam_64mp_pi_camera_manual.pdf; NXP PCF8591 specification.", "blue")
    rounded(c, M, 20 * mm, CONTENT_W, 10 * mm, SURFACE, LINE, 2 * mm)
    text(c, "Operator:", M + 5 * mm, 23.5 * mm, 6.2, MUTED)
    c.line(M + 25 * mm, 22.5 * mm, M + 75 * mm, 22.5 * mm)
    text(c, "Date:", M + 86 * mm, 23.5 * mm, 6.2, MUTED)
    c.line(M + 100 * mm, 22.5 * mm, M + 130 * mm, 22.5 * mm)
    text(c, "Result: PASS / HOLD", M + 140 * mm, 23.5 * mm, 6.2, BLUE_DARK, "Helvetica-Bold")


def page_21(c):
    page_base(c, 21, "Flash AeroOS")
    heading(c, "20", "Flash the AeroOS image: select", "Use Raspberry Pi Imager on macOS, Windows or Linux. The screenshots are from the official Raspberry Pi documentation; labels may move slightly between releases.")
    label(c, "01 Verify and prepare the image", M, 194 * mm, BLUE)
    callout(c, M, 155 * mm, CONTENT_W, 31 * mm, "VERIFY BEFORE WRITING", "In output/image, run shasum -a 256 -c SHA256SUMS-r4. If Imager does not accept the .img.zst file, create a normal .img with: unzstd -k AeroOS-RPi4-8GB-SC1227-2026-07-23-r4.img.zst. Keep at least 8 GB free for the decompressed file.", "blue")
    photo(c, IMAGER_DEVICE, M, 83 * mm, 85 * mm, 61 * mm, crop=(0.00, 0.02, 1.00, 0.98), radius=3 * mm)
    photo(c, IMAGER_OS, M + 93 * mm, 83 * mm, 85 * mm, 61 * mm, crop=(0.00, 0.02, 1.00, 0.98), radius=3 * mm)
    label(c, "02 Choose device", M, 75 * mm, BLUE)
    paragraph(c, "Select Raspberry Pi 4. Do not select Pi 5 even when it appears first.", M, 68 * mm, 82 * mm, 6.5, 8, MUTED)
    label(c, "03 Choose OS > Use custom", M + 93 * mm, 75 * mm, BLUE)
    paragraph(c, "Scroll to Use custom, then select the verified AeroOS .img. Do not choose Raspberry Pi OS.", M + 93 * mm, 68 * mm, 82 * mm, 6.5, 8, MUTED)
    callout(c, M, 22 * mm, CONTENT_W, 26 * mm, "KEEP THE HARDWARE SAFE", "Before flashing or first boot, disconnect pump power, fan power, relay COM / NO / NC terminals and the 5 V mist maker. The Pi, display, camera and approved 3.3 V sensors are the only connected devices for initial bring-up.", "red")
    source_line(c, "Screenshots: Raspberry Pi Ltd documentation, Getting started > Install using Imager.", M, 17 * mm, CONTENT_W)


def page_22(c):
    page_base(c, 22, "Flash AeroOS")
    heading(c, "21", "Flash the AeroOS image: write and boot", "Select the microSD card by capacity, write the verified image, allow verification to finish, then perform a dry first boot.")
    photo(c, IMAGER_STORAGE, M, 142 * mm, 54 * mm, 43 * mm, crop=(0.00, 0.02, 1.00, 0.98), radius=3 * mm)
    photo(c, IMAGER_CONFIRM, M + 62 * mm, 142 * mm, 54 * mm, 43 * mm, crop=(0.00, 0.02, 1.00, 0.98), radius=3 * mm)
    photo(c, IMAGER_WRITE, M + 124 * mm, 142 * mm, 54 * mm, 43 * mm, crop=(0.00, 0.02, 1.00, 0.98), radius=3 * mm)
    captions = [
        ("04 Select storage", "Identify the microSD by capacity. Disconnect other removable drives if uncertain."),
        ("05 Confirm erase", "This destroys all data on the selected card. Recheck the device name and size."),
        ("06 Write + verify", "Do not cancel verification. Wait for the successful completion message."),
    ]
    for index, (title_value, body) in enumerate(captions):
        x = M + index * 62 * mm
        label(c, title_value, x, 134 * mm, BLUE)
        paragraph(c, body, x, 127 * mm, 54 * mm, 6.2, 7.5, MUTED)
    label(c, "Dry first-boot sequence", M, 96 * mm, BLUE)
    boot_steps = [
        ("1", "Eject", "Safely eject the card and insert it into the unpowered Pi."),
        ("2", "Inspect", "Confirm relay loads and 12 V pump power are still disconnected."),
        ("3", "Power", "Power the Pi + official display; use Ethernet for initial bring-up."),
        ("4", "Gate", "Wait for camera enumeration, 1080p15, autofocus and 64 MP still tests."),
        ("5", "Dashboard", "Confirm 800 x 480 touch, real sensors and unavailable missing capabilities."),
        ("6", "Automation", "The automatic switch remains disabled until relay/master commissioning."),
    ]
    for index, (number, title_value, body) in enumerate(boot_steps):
        col = index % 3
        row = index // 3
        x = M + col * 60 * mm
        y = 62 * mm - row * 32 * mm
        component(c, x, y, 54 * mm, 25 * mm, f"{number}  {title_value}", body, BLUE if index < 5 else AMBER)
    source_line(c, "Screenshots: Raspberry Pi Ltd documentation. Image-specific checksum and filenames: output/image/FLASHING.md and SHA256SUMS-r4.", M, 17 * mm, CONTENT_W)


PAGE_FUNCTIONS = [
    cover, page_2, page_3, page_4, page_5, page_6, page_7, page_8, page_9,
    page_10, page_11, page_12, page_13, page_14, page_15, page_16, page_17,
    page_18, page_19, page_20, page_21, page_22,
]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle(f"AeroOS Hardware Setup and Commissioning Manual - Revision {REVISION}")
    pdf.setAuthor("AeroOS / Nexora prototype project")
    pdf.setSubject("Photo-led Raspberry Pi 4 sensor, imaging and safe hardware bring-up guide")
    pdf.setKeywords("AeroOS, Raspberry Pi 4, aeroponics, DHT22, DS18B20, Arducam, PCF8591, relay, pump automation")
    for index, draw_page in enumerate(PAGE_FUNCTIONS):
        draw_page(pdf)
        if index < len(PAGE_FUNCTIONS) - 1:
            pdf.showPage()
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()
