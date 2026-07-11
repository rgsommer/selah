"""F2 sender approval manager - approve/reject email contributors.

Lists approved senders AND senders awaiting approval (from pending_approvals.json)
in one scrollable view. Pending senders show in amber with a ⏳; Space
approves/unapproves the highlighted sender individually (a per-sender
alternative to F5's approve-all).
"""

import json
import pygame
from modules.logger import log_error

APPROVED_SENDERS_FILE = "approved_senders.json"


def _build_rows():
    """Combined list: pending senders first (need attention), then approved.

    Each row is a dict: {"type": "pending"|"approved", "email", "name", "files"}.
    """
    approved = _load_senders()
    try:
        from modules.email_handler import _load_pending
        pending = _load_pending()
    except Exception:
        pending = []

    # Collapse pending entries to one row per email (summing their file counts).
    pmap = {}
    for e in pending:
        em = (e.get("sender_email") or "").strip()
        if not em or em in approved:
            continue
        d = pmap.setdefault(em, {"email": em, "name": e.get("sender_name") or em, "files": 0})
        d["files"] += len(e.get("files") or [])

    rows = [{"type": "pending", "email": d["email"], "name": d["name"], "files": d["files"]}
            for d in pmap.values()]
    rows += [{"type": "approved", "email": s, "name": s, "files": 0} for s in approved]
    return rows, approved


def show_sender_manager(screen, config):
    """Display sender management interface. Press ESC or F2 to close."""
    if not screen:
        return

    try:
        rows, approved = _build_rows()
        screen_w, screen_h = screen.get_size()
        font_size = max(22, screen_w // 40)
        font = pygame.font.Font(None, font_size)
        title_font = pygame.font.Font(None, font_size + 10)

        selected = 0
        scroll = 0
        adding = False
        add_buffer = ""
        flash = ""            # transient status line after an action
        running = True
        clock = pygame.time.Clock()
        max_rows = 1

        while running:
            screen.fill((20, 30, 20))
            n_pending = sum(1 for r in rows if r["type"] == "pending")

            title_txt = "Sender Manager (F2)"
            if n_pending:
                title_txt += f"   ·   {n_pending} awaiting approval"
            title = title_font.render(title_txt, True, (100, 255, 100))
            screen.blit(title, (20, 10))

            instructions = font.render(
                "Up/Down  PgUp/PgDn   Space=Approve/Unapprove   A=Add  D=Delete  ESC=Close",
                True, (150, 150, 150)
            )
            screen.blit(instructions, (20, 15 + title_font.get_linesize()))

            list_top = 60 + title_font.get_linesize()
            row_h = font_size + 10
            bottom_reserve = (row_h * 3 + 20) if adding else (row_h + 12 if flash else 10)
            avail = max(row_h, screen_h - list_top - bottom_reserve)
            max_rows = max(1, avail // row_h)

            if not rows:
                msg = font.render("No approved or pending senders (all senders allowed)",
                                  True, (200, 200, 100))
                screen.blit(msg, (20, list_top))
            else:
                if selected < scroll:
                    scroll = selected
                elif selected >= scroll + max_rows:
                    scroll = selected - max_rows + 1
                scroll = max(0, min(scroll, max(0, len(rows) - max_rows)))

                y = list_top
                for i in range(scroll, min(scroll + max_rows, len(rows))):
                    row = rows[i]
                    sel = (i == selected)
                    if sel:
                        hl = pygame.Surface((screen_w - 20, font_size + 8), pygame.SRCALPHA)
                        hl.fill((40, 80, 40, 150))
                        screen.blit(hl, (10, y - 3))
                    if row["type"] == "pending":
                        color = (255, 210, 90) if not sel else (255, 230, 140)
                        fc = row["files"]
                        line = f"  ⏳ {row['name']}  <{row['email']}>  · {fc} pending photo{'s' if fc != 1 else ''}"
                    else:
                        color = (210, 210, 210) if not sel else (255, 255, 255)
                        line = f"  ✓ {row['email']}"
                    screen.blit(font.render(line, True, color), (20, y))
                    y += row_h

                counter = font.render(f"{selected + 1}/{len(rows)}", True, (150, 150, 150))
                screen.blit(counter, (screen_w - counter.get_width() - 20,
                                      15 + title_font.get_linesize()))
                if scroll > 0:
                    up = font.render("▲ more", True, (120, 200, 120))
                    screen.blit(up, (screen_w - up.get_width() - 20, list_top - row_h + 2))
                if scroll + max_rows < len(rows):
                    dn = font.render("▼ more", True, (120, 200, 120))
                    screen.blit(dn, (screen_w - dn.get_width() - 20, list_top + max_rows * row_h - 2))

            if adding:
                ay = screen_h - bottom_reserve + 10
                screen.blit(font.render("Enter email address:", True, (255, 255, 100)), (20, ay))
                ay += font_size + 5
                screen.blit(font.render(f"  {add_buffer}_", True, (255, 255, 255)), (20, ay))
            elif flash:
                screen.blit(font.render(flash, True, (140, 230, 140)),
                            (20, screen_h - row_h - 4))

            try:
                pygame.display.flip()
            except Exception:
                pass

            def _refresh():
                nonlocal rows, approved, selected
                rows, approved = _build_rows()
                selected = max(0, min(selected, len(rows) - 1))

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if adding:
                        if event.key == pygame.K_RETURN and add_buffer.strip():
                            a = _load_senders()
                            if add_buffer.strip() not in a:
                                a.append(add_buffer.strip())
                                _save_senders(a)
                            add_buffer = ""
                            adding = False
                            _refresh()
                        elif event.key == pygame.K_ESCAPE:
                            adding = False
                            add_buffer = ""
                        elif event.key == pygame.K_BACKSPACE:
                            add_buffer = add_buffer[:-1]
                        elif event.unicode and event.unicode.isprintable():
                            add_buffer += event.unicode
                    else:
                        if event.key in (pygame.K_ESCAPE, pygame.K_F2):
                            running = False
                        elif event.key == pygame.K_DOWN and rows:
                            selected = min(selected + 1, len(rows) - 1)
                        elif event.key == pygame.K_UP and rows:
                            selected = max(selected - 1, 0)
                        elif event.key == pygame.K_PAGEDOWN and rows:
                            selected = min(selected + max_rows, len(rows) - 1)
                        elif event.key == pygame.K_PAGEUP and rows:
                            selected = max(selected - max_rows, 0)
                        elif event.key == pygame.K_HOME and rows:
                            selected = 0
                        elif event.key == pygame.K_END and rows:
                            selected = len(rows) - 1
                        elif event.key == pygame.K_a:
                            adding = True
                            add_buffer = ""
                            flash = ""
                        elif event.key == pygame.K_SPACE and rows:
                            row = rows[selected]
                            if row["type"] == "pending":
                                try:
                                    from modules.email_handler import approve_pending_sender
                                    moved = approve_pending_sender(row["email"], config)
                                    flash = (f"Approved {row['name']} — {moved} photo(s) added"
                                             if moved >= 0 else f"Approved {row['name']}")
                                except Exception as e:
                                    log_error(f"Approve failed: {e}")
                                    flash = "Approve failed (see log)"
                            else:                       # un-approve
                                a = _load_senders()
                                if row["email"] in a:
                                    a.remove(row["email"])
                                    _save_senders(a)
                                flash = f"Unapproved {row['email']}"
                            _refresh()
                        elif event.key == pygame.K_d and rows:
                            row = rows[selected]
                            if row["type"] == "pending":
                                try:
                                    from modules.email_handler import reject_pending_sender
                                    reject_pending_sender(row["email"])
                                    flash = f"Rejected {row['name']}"
                                except Exception as e:
                                    log_error(f"Reject failed: {e}")
                            else:
                                a = _load_senders()
                                if row["email"] in a:
                                    a.remove(row["email"])
                                    _save_senders(a)
                                flash = f"Removed {row['email']}"
                            _refresh()

            clock.tick(30)

    except Exception as e:
        log_error(f"Sender manager error: {e}")


def _load_senders():
    """Load approved senders from JSON file."""
    try:
        with open(APPROVED_SENDERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_senders(senders):
    """Save approved senders to JSON file."""
    try:
        with open(APPROVED_SENDERS_FILE, "w") as f:
            json.dump(senders, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save senders: {e}")
