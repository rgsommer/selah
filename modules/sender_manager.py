"""F2 sender approval manager - approve/reject/block email contributors.

Shows three groups in one scrollable list:
  * PENDING  (amber)  — awaiting approval (from pending_approvals.json)
  * approved (green)  — on the whitelist (approved_senders.json)
  * blocked  (red)    — previously approved then un-approved (unapproved_senders.json)

Space toggles the highlighted sender: approve a pending one, un-approve an
approved one (it becomes 'blocked', not forgotten, so you can re-approve), or
re-approve a blocked one. D forgets a row entirely. Because un-approving keeps
the address, a mistaken un-approve is one keystroke to undo.
"""

import json
import pygame
from modules.logger import log_error

APPROVED_SENDERS_FILE = "approved_senders.json"
UNAPPROVED_SENDERS_FILE = "unapproved_senders.json"


def _build_rows():
    """Combined rows: pending first, then approved, then blocked."""
    approved = _load_senders()
    unapproved = _load_unapproved()
    try:
        from modules.email_handler import _load_pending
        pending = _load_pending()
    except Exception:
        pending = []

    approved_set = set(approved)
    pmap = {}
    for e in pending:
        em = (e.get("sender_email") or "").strip()
        if not em or em in approved_set:
            continue
        d = pmap.setdefault(em, {"email": em, "name": e.get("sender_name") or em, "files": 0})
        d["files"] += len(e.get("files") or [])
    pending_set = set(pmap)

    rows = [{"type": "pending", "email": d["email"], "name": d["name"], "files": d["files"]}
            for d in pmap.values()]
    rows += [{"type": "approved", "email": s} for s in approved]
    rows += [{"type": "blocked", "email": em} for em in unapproved
             if em not in approved_set and em not in pending_set]
    return rows, approved, unapproved


def show_sender_manager(screen, config):
    """Display sender management interface. Press ESC or F2 to close."""
    if not screen:
        return

    try:
        rows, approved, unapproved = _build_rows()
        screen_w, screen_h = screen.get_size()
        font_size = max(22, screen_w // 40)
        font = pygame.font.Font(None, font_size)
        title_font = pygame.font.Font(None, font_size + 10)

        selected = 0
        scroll = 0
        adding = False
        add_buffer = ""
        flash = ""
        running = True
        clock = pygame.time.Clock()
        max_rows = 1

        while running:
            screen.fill((20, 30, 20))
            n_pending = sum(1 for r in rows if r["type"] == "pending")

            title_txt = "Sender Manager (F2)"
            if n_pending:
                title_txt += f"   -   {n_pending} awaiting approval"
            screen.blit(title_font.render(title_txt, True, (100, 255, 100)), (20, 10))

            screen.blit(font.render(
                "Up/Dn  PgUp/PgDn   SPACE = approve / unapprove / re-approve   A=Add  D=Forget  ESC=Close",
                True, (150, 150, 150)), (20, 15 + title_font.get_linesize()))

            list_top = 60 + title_font.get_linesize()
            row_h = font_size + 10
            bottom_reserve = (row_h * 3 + 20) if adding else (row_h + 12 if flash else 10)
            avail = max(row_h, screen_h - list_top - bottom_reserve)
            max_rows = max(1, avail // row_h)

            if not rows:
                screen.blit(font.render("No senders yet (all senders allowed until you add one)",
                                        True, (200, 200, 100)), (20, list_top))
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
                        color = (255, 220, 120)
                        fc = row["files"]
                        line = f"  PENDING   {row['name']}  <{row['email']}>   {fc} photo{'s' if fc != 1 else ''} waiting"
                    elif row["type"] == "blocked":
                        color = (230, 140, 140)
                        line = f"  blocked   {row['email']}   (SPACE to re-approve)"
                    else:
                        color = (150, 230, 150)
                        line = f"  approved  {row['email']}"
                    screen.blit(font.render(line, True, color), (20, y))
                    y += row_h

                counter = font.render(f"{selected + 1}/{len(rows)}", True, (150, 150, 150))
                screen.blit(counter, (screen_w - counter.get_width() - 20,
                                      15 + title_font.get_linesize()))
                if scroll > 0:
                    screen.blit(font.render("... more above", True, (120, 200, 120)),
                                (screen_w - 190, list_top - row_h + 2))
                if scroll + max_rows < len(rows):
                    screen.blit(font.render("... more below", True, (120, 200, 120)),
                                (screen_w - 190, list_top + max_rows * row_h - 2))

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
                nonlocal rows, approved, unapproved, selected
                rows, approved, unapproved = _build_rows()
                selected = max(0, min(selected, len(rows) - 1))

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if adding:
                        if event.key == pygame.K_RETURN and add_buffer.strip():
                            em = add_buffer.strip()
                            a = _load_senders()
                            if em not in a:
                                a.append(em)
                                _save_senders(a)
                            _set_unapproved(_load_unapproved(), em, remove=True)  # clear any block
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
                            flash = _toggle(rows[selected], config)
                            _refresh()
                        elif event.key == pygame.K_d and rows:
                            flash = _forget(rows[selected])
                            _refresh()

            clock.tick(30)

    except Exception as e:
        log_error(f"Sender manager error: {e}")


def _toggle(row, config):
    """Space: approve a pending sender, un-approve an approved one (-> blocked),
    or re-approve a blocked one. Returns a status line."""
    em = row["email"]
    if row["type"] == "pending":
        try:
            from modules.email_handler import approve_pending_sender
            moved = approve_pending_sender(em, config)
            _set_unapproved(_load_unapproved(), em, remove=True)
            return (f"Approved {row.get('name', em)} - {moved} photo(s) added"
                    if moved >= 0 else f"Approved {row.get('name', em)}")
        except Exception as e:
            log_error(f"Approve failed: {e}")
            return "Approve failed (see log)"
    if row["type"] == "blocked":
        a = _load_senders()
        if em not in a:
            a.append(em)
            _save_senders(a)
        _set_unapproved(_load_unapproved(), em, remove=True)
        return f"Re-approved {em}"
    # approved -> blocked (kept, so it can be re-approved)
    a = _load_senders()
    if em in a:
        a.remove(em)
        _save_senders(a)
    _set_unapproved(_load_unapproved(), em, remove=False)
    return f"Un-approved {em} (still listed as blocked - SPACE to undo)"


def _forget(row):
    """D: remove the row entirely (reject pending / forget approved / forget blocked)."""
    em = row["email"]
    if row["type"] == "pending":
        try:
            from modules.email_handler import reject_pending_sender
            reject_pending_sender(em)
        except Exception as e:
            log_error(f"Reject failed: {e}")
        return f"Rejected {row.get('name', em)}"
    a = _load_senders()
    if em in a:
        a.remove(em)
        _save_senders(a)
    _set_unapproved(_load_unapproved(), em, remove=True)
    return f"Forgot {em}"


def _load_senders():
    try:
        with open(APPROVED_SENDERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_senders(senders):
    try:
        with open(APPROVED_SENDERS_FILE, "w") as f:
            json.dump(senders, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save senders: {e}")


def _load_unapproved():
    try:
        with open(UNAPPROVED_SENDERS_FILE, "r") as f:
            return [str(s).strip() for s in json.load(f) if str(s).strip()]
    except Exception:
        return []


def _set_unapproved(current, email, remove):
    """Add or remove an email in the blocked list and persist."""
    email = (email or "").strip()
    s = [x for x in current if x != email]
    if not remove and email:
        s.append(email)
    try:
        with open(UNAPPROVED_SENDERS_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except Exception as e:
        log_error(f"Failed to save unapproved senders: {e}")
