"""Phone-upload QR code overlay.

Periodically shows a small QR in the corner that opens the web-control upload
page, so family can send photos from a phone without typing a URL. The target
is qr_upload_url if set, otherwise auto-detected as http://<this-pi-ip>:<port>.
"""

import time
import socket

import pygame

from modules.logger import log_error

try:
    import qrcode
    HAS_QR = True
except Exception:
    HAS_QR = False

_qr_surface = None
_qr_url = None


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "raspberrypi.local"


def _upload_url(config):
    url = (config.get("qr_upload_url") or "").strip()
    if url:
        return url
    port = config.get("web_control_port", 5000)
    return f"http://{_local_ip()}:{port}/upload"


def _build_qr(url, target_px=220):
    qr = qrcode.QRCode(border=2, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    scale = max(3, target_px // max(1, n))
    size = n * scale
    surf = pygame.Surface((size, size))
    surf.fill((255, 255, 255))
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                pygame.draw.rect(surf, (0, 0, 0), (c * scale, r * scale, scale, scale))
    return surf


def show_upload_qr_if_scheduled(screens, config):
    """Show the QR for a few seconds at the start of each interval window."""
    global _qr_surface, _qr_url
    if not config.get("upload_qr_enabled", False) or not HAS_QR:
        return

    interval = max(60, int(config.get("upload_qr_interval_minutes", 30)) * 60)
    show_secs = int(config.get("upload_qr_seconds", 20))
    if (time.time() % interval) >= show_secs:
        return

    url = _upload_url(config)
    if _qr_surface is None or url != _qr_url:
        try:
            _qr_surface = _build_qr(url)
            _qr_url = url
        except Exception as e:
            log_error(f"QR build failed: {e}")
            return

    for screen in screens.values():
        _render_qr(screen, _qr_surface)


def show_upload_qr_now(screens, config, seconds=60):
    """On-demand (F11): a big centred QR + URL shown until any key/tap or until
    `seconds` elapse. Ensures the web server is up so the link actually works."""
    if not HAS_QR:
        try:
            from modules.toast import queue_toast
            queue_toast("QR needs the 'qrcode' package")
        except Exception:
            pass
        return
    # Make sure the server backing the link is running (idempotent).
    try:
        from modules.web_control import start_web_server
        start_web_server(config, screens)
    except Exception:
        pass

    url = _upload_url(config)
    print(f"[Selah] Upload QR URL: {url}")   # visible in the console for debugging
    try:
        big = _build_qr(url, target_px=440)   # large, easy to scan from a distance
    except Exception as e:
        log_error(f"QR build failed: {e}")
        return

    end = time.time() + max(3, int(seconds))
    clock = pygame.time.Clock()
    pygame.event.clear()
    while time.time() < end:
        for event in pygame.event.get():
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                              pygame.FINGERDOWN, pygame.QUIT):
                return
        for screen in screens.values():
            _render_qr_center(screen, big, url)
        try:
            pygame.display.flip()
        except Exception:
            pass
        clock.tick(20)


def _render_qr_center(screen, qr_surf, url):
    try:
        w, h = screen.get_size()
        qs = qr_surf.get_width()
        title_font = pygame.font.Font(None, max(30, w // 22))
        url_font = pygame.font.Font(None, max(20, w // 46))
        title = title_font.render("Scan to add a photo", True, (255, 255, 255))
        sub = url_font.render(url, True, (200, 200, 210))
        hint = url_font.render("press any key to close", True, (150, 150, 165))

        pad = 28
        inner_w = max(qs, title.get_width(), sub.get_width())
        box_w = inner_w + pad * 2
        box_h = title.get_height() + qs + sub.get_height() + hint.get_height() + pad * 2 + 40
        bx, by = (w - box_w) // 2, (h - box_h) // 2

        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 185))
        screen.blit(dim, (0, 0))
        card = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        card.fill((22, 22, 30, 245))
        screen.blit(card, (bx, by))

        y = by + pad
        screen.blit(title, (bx + (box_w - title.get_width()) // 2, y))
        y += title.get_height() + 16
        screen.blit(qr_surf, (bx + (box_w - qs) // 2, y))
        y += qs + 14
        screen.blit(sub, (bx + (box_w - sub.get_width()) // 2, y))
        y += sub.get_height() + 8
        screen.blit(hint, (bx + (box_w - hint.get_width()) // 2, y))
    except Exception as e:
        log_error(f"QR centre render failed: {e}")


def _render_qr(screen, qr_surf):
    try:
        w, h = screen.get_size()
        qs = qr_surf.get_width()
        pad = 16
        font = pygame.font.Font(None, max(20, w // 52))
        label = font.render("Scan to send photos", True, (255, 255, 255))

        box_w = max(qs, label.get_width()) + pad * 2
        box_h = qs + label.get_height() + pad * 2 + 6
        bx, by = w - box_w - 20, h - box_h - 20

        bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 175))
        screen.blit(bg, (bx, by))
        screen.blit(qr_surf, (bx + (box_w - qs) // 2, by + pad))
        screen.blit(label, (bx + (box_w - label.get_width()) // 2, by + pad + qs + 6))
        try:
            pygame.display.flip()
        except Exception:
            pass
    except Exception as e:
        log_error(f"QR render failed: {e}")
