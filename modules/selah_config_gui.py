"""F1 on-screen configuration editor using pygame UI."""

import re
import time
import pygame
from modules.logger import log_error


def _load_contacts():
    """Load the family/friends contacts (with optional birthdays)."""
    try:
        from modules.contacts import load_contacts
        return load_contacts()
    except Exception:
        return []

# Default weights restored when a layout checkbox is switched back ON.
LAYOUT_DEFAULT_WEIGHTS = {"single": 50, "split": 20, "cascade": 20, "tile3": 30, "tile6": 20}


def _layout_is_on(config, mode):
    """A layout is 'on' when its weight is non-zero."""
    return (config.get("layout_weights") or {}).get(mode, 0) > 0


def _layout_toggle(config, mode):
    """Flip a layout on/off by toggling its weight between 0 and a default."""
    weights = dict(config.get("layout_weights") or {})
    if weights.get(mode, 0) > 0:
        weights[mode] = 0
    else:
        weights[mode] = LAYOUT_DEFAULT_WEIGHTS.get(mode, 25)
    config["layout_weights"] = weights


def _extract_folder_id(text):
    """Pull a Drive folder ID from a pasted share link, or accept a raw ID.

    Handles:
      https://drive.google.com/drive/folders/<ID>?usp=sharing
      https://drive.google.com/open?id=<ID>
      <ID>
    """
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    # Otherwise assume a raw ID (strip any stray query/path bits).
    return text.split("?")[0].rstrip("/").split("/")[-1]


def _manage_drive_folders(screen, config):
    """Sub-screen to add/remove Google Drive source folders.

    A=Add (paste a share link or ID), D=Delete selected, ESC=Back.
    Edits config["google_drive_folder_ids"] in place.
    """
    screen_w, screen_h = screen.get_size()
    font_size = max(22, screen_w // 40)
    font = pygame.font.Font(None, font_size)
    title_font = pygame.font.Font(None, font_size + 10)
    small = pygame.font.Font(None, max(18, font_size - 6))

    folders = [str(f) for f in (config.get("google_drive_folder_ids") or [])]
    selected = 0
    adding = False
    buf = ""
    clock = pygame.time.Clock()

    running = True
    while running:
        screen.fill((20, 20, 40))
        title = title_font.render("Google Drive Folders", True, (100, 200, 255))
        screen.blit(title, (20, 10))
        instr = small.render(
            "A=Add   D=Delete   ESC=Back     (paste a share link or folder ID)",
            True, (150, 150, 150))
        screen.blit(instr, (20, 15 + title_font.get_linesize()))

        y = 60 + title_font.get_linesize()
        if not folders and not adding:
            empty = font.render("(none yet — press A to add a folder)", True, (200, 200, 120))
            screen.blit(empty, (30, y))
        for i, fid in enumerate(folders):
            if i == selected and not adding:
                hl = pygame.Surface((screen_w - 20, font_size + 8), pygame.SRCALPHA)
                hl.fill((60, 60, 120, 150))
                screen.blit(hl, (10, y - 2))
            txt = font.render(f"{i + 1}.  {fid}", True, (255, 255, 255))
            screen.blit(txt, (30, y))
            y += font_size + 10

        if adding:
            prompt = font.render("Add (link or ID): " + buf + "_", True, (255, 255, 100))
            screen.blit(prompt, (30, y + 14))

        try:
            pygame.display.flip()
        except Exception:
            pass

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if adding:
                    if event.key == pygame.K_RETURN:
                        fid = _extract_folder_id(buf)
                        if fid and fid not in folders:
                            folders.append(fid)
                            selected = len(folders) - 1
                        adding, buf = False, ""
                    elif event.key == pygame.K_ESCAPE:
                        adding, buf = False, ""
                    elif event.key == pygame.K_BACKSPACE:
                        buf = buf[:-1]
                    elif event.unicode and event.unicode.isprintable():
                        buf += event.unicode
                else:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_a:
                        adding, buf = True, ""
                    elif event.key == pygame.K_d and folders:
                        folders.pop(selected)
                        selected = max(0, min(selected, len(folders) - 1))
                    elif event.key == pygame.K_DOWN:
                        selected = min(selected + 1, max(0, len(folders) - 1))
                    elif event.key == pygame.K_UP:
                        selected = max(selected - 1, 0)

        clock.tick(30)

    config["google_drive_folder_ids"] = folders


def _manage_contacts(screen, config):
    """Sub-screen to manage family/friends, their birthdays, and invitations.

    A=Add email (name + photo keyword auto-derived), B=Set birthday for the
    selected person, D=Delete, N=Nudge (email everyone an invitation), ESC=Back.
    On a person's birthday, Selah celebrates them and favours their photos.
    """
    from modules.contacts import (
        load_contacts, save_contacts, parse_birthday, derive_name, derive_keyword,
    )

    screen_w, screen_h = screen.get_size()
    font_size = max(22, screen_w // 40)
    font = pygame.font.Font(None, font_size)
    title_font = pygame.font.Font(None, font_size + 10)
    small = pygame.font.Font(None, max(18, font_size - 6))

    contacts = load_contacts()
    selected = 0
    input_mode = None  # None | "email" | "birthday"
    buf = ""
    message = ""
    msg_until = 0
    clock = pygame.time.Clock()

    running = True
    while running:
        screen.fill((20, 20, 40))
        title = title_font.render("Family & Friends", True, (100, 200, 255))
        screen.blit(title, (20, 10))
        instr = small.render(
            "A=Add   B=Set Birthday   D=Delete   N=Nudge   ESC=Back",
            True, (150, 150, 150))
        screen.blit(instr, (20, 15 + title_font.get_linesize()))

        y = 60 + title_font.get_linesize()
        if not contacts and input_mode != "email":
            screen.blit(font.render("(none yet — press A to add an email)", True, (200, 200, 120)), (30, y))
        for i, c in enumerate(contacts):
            if i == selected and input_mode is None:
                hl = pygame.Surface((screen_w - 20, font_size + 8), pygame.SRCALPHA)
                hl.fill((60, 60, 120, 150))
                screen.blit(hl, (10, y - 2))
            bday = c.get("birthday") or "—"
            line = f"{i + 1}.  {c.get('email', '')}     birthday: {bday}"
            screen.blit(font.render(line, True, (255, 255, 255)), (30, y))
            y += font_size + 10

        if input_mode == "email":
            screen.blit(font.render("Add email: " + buf + "_", True, (255, 255, 100)), (30, y + 14))
        elif input_mode == "birthday":
            who = contacts[selected].get("email", "") if contacts else ""
            screen.blit(font.render(f"Birthday for {who}  (e.g. Sept 4): " + buf + "_",
                                    True, (255, 255, 100)), (30, y + 14))

        if message and time.time() < msg_until:
            screen.blit(font.render(message, True, (120, 255, 160)), (30, screen_h - font_size - 16))

        try:
            pygame.display.flip()
        except Exception:
            pass

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type != pygame.KEYDOWN:
                continue

            if input_mode == "email":
                if event.key == pygame.K_RETURN:
                    em = buf.strip()
                    if em and "@" in em and not any(c.get("email") == em for c in contacts):
                        contacts.append({
                            "email": em, "name": derive_name(em),
                            "birthday": "", "photo_keyword": derive_keyword(em),
                        })
                        selected = len(contacts) - 1
                        save_contacts(contacts)
                    input_mode, buf = None, ""
                elif event.key == pygame.K_ESCAPE:
                    input_mode, buf = None, ""
                elif event.key == pygame.K_BACKSPACE:
                    buf = buf[:-1]
                elif event.unicode and event.unicode.isprintable():
                    buf += event.unicode

            elif input_mode == "birthday":
                if event.key == pygame.K_RETURN:
                    if contacts:
                        bd = parse_birthday(buf)
                        contacts[selected]["birthday"] = bd
                        save_contacts(contacts)
                        message = f"Birthday set to {bd}" if bd else "Couldn't read that date"
                        msg_until = time.time() + 3
                    input_mode, buf = None, ""
                elif event.key == pygame.K_ESCAPE:
                    input_mode, buf = None, ""
                elif event.key == pygame.K_BACKSPACE:
                    buf = buf[:-1]
                elif event.unicode and event.unicode.isprintable():
                    buf += event.unicode

            else:  # list navigation
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_a:
                    input_mode, buf = "email", ""
                elif event.key == pygame.K_b and contacts:
                    input_mode = "birthday"
                    buf = str(contacts[selected].get("birthday", ""))
                elif event.key == pygame.K_d and contacts:
                    contacts.pop(selected)
                    selected = max(0, min(selected, len(contacts) - 1))
                    save_contacts(contacts)
                elif event.key == pygame.K_n and contacts:
                    screen.blit(font.render("Sending invitations...", True, (255, 255, 100)),
                                (30, screen_h - font_size - 16))
                    try:
                        pygame.display.flip()
                    except Exception:
                        pass
                    try:
                        from modules.email_handler import send_invitations
                        n = send_invitations(config, recipients=[c.get("email") for c in contacts])
                        message = f"Invitation sent to {n} contact(s)."
                    except Exception as e:
                        log_error(f"Nudge failed: {e}")
                        message = "Nudge failed — check email settings."
                    msg_until = time.time() + 4
                elif event.key == pygame.K_DOWN:
                    selected = min(selected + 1, max(0, len(contacts) - 1))
                elif event.key == pygame.K_UP:
                    selected = max(selected - 1, 0)

        clock.tick(30)


def show_config_gui(screen, config):
    """Display an interactive configuration editor overlay.

    Allows editing key settings using keyboard input.
    Press ESC or F1 again to close.
    """
    if not screen:
        return

    try:
        screen_w, screen_h = screen.get_size()
        font_size = max(22, screen_w // 40)
        font = pygame.font.Font(None, font_size)
        title_font = pygame.font.Font(None, font_size + 10)

        # Editable config keys: (key, label, type).
        # type "layoutbool" toggles config["layout_weights"][key] on/off.
        editable_fields = [
            # --- Layout variety ---
            ("videos_enabled", "Play Videos", "bool"),
            ("video_muted", "  Mute Videos", "bool"),
            ("video_max_seconds", "  Max Video Length (sec, 0=full)", "int"),
            ("layout_variety_enabled", "Layout Variety", "bool"),
            ("single", "  Layout: Full Single", "layoutbool"),
            ("split", "  Layout: Split (2, slide)", "layoutbool"),
            ("cascade", "  Layout: Cascade (3, stacked)", "layoutbool"),
            ("tile3", "  Layout: Tile 3", "layoutbool"),
            ("tile6", "  Layout: Tile 6", "layoutbool"),
            ("layout_fade_enabled", "  Fade Transitions", "bool"),
            ("transition_style", "  Transition (crossfade/fade_black/random)", "str"),
            ("photo_effects_enabled", "Photo Effects (random)", "bool"),
            ("photo_effect_chance", "  Effect Chance (%)", "int"),
            ("photo_effect_sepia", "  Use Sepia", "bool"),
            ("photo_effect_bw", "  Use B&W", "bool"),
            ("balanced_rotation", "Balanced Folder Rotation", "bool"),
            ("screen_rotation_sync", "Screens Change Together", "bool"),
            ("recent_memory_enabled", "Avoid Repeats (recent memory)", "bool"),
            ("on_this_day_enabled", "On-This-Day Flashbacks", "bool"),
            ("on_this_day_sprinkle", "  Sprinkle Through Day (off = first thing)", "bool"),
            ("on_this_day_interval_minutes", "  Sprinkle Every (min)", "int"),
            ("upload_qr_enabled", "Phone Upload QR", "bool"),
            ("coming_up_enabled", "Coming-Up Birthday Heads-Up", "bool"),
            ("favorites_boost_enabled", "Boost Favorites", "bool"),
            ("privacy_mode_enabled", "Guest/Privacy Mode", "bool"),
            ("hide_blurry_enabled", "Hide Blurry Photos", "bool"),
            ("weekly_digest_enabled", "Weekly Digest Email", "bool"),
            ("nudge_enabled", "Nudge Quiet Senders", "bool"),
            ("nudge_inactive_weeks", "  Nudge After (weeks quiet)", "int"),
            ("health_watchdog_enabled", "Health Watchdog (disk)", "bool"),
            ("rotate_interval", "Rotate Interval (sec)", "int"),

            # --- Daily schedule ---
            ("timezone", "Time Zone", "str"),
            ("on_time", "Photos Start (morning HH:MM)", "str"),
            ("off_time", "Photos Stop (night HH:MM)", "str"),
            ("moon_phase_enabled", "Night Moon Phase", "bool"),
            ("night_screen_off", "Night: Blank HDMI (true dark)", "bool"),
            ("calendar_display_enabled", "Daily Agenda (calendar)", "bool"),
            ("google_calendar_id", "  Calendar ID", "str"),
            ("calendar_start_time", "  Agenda Start (HH:MM)", "str"),
            ("calendar_times", "  Agenda Times (csv HH:MM)", "csv"),
            ("calendar_duration_minutes", "  Agenda Duration (min, 0=all day)", "int"),
            ("weather_enabled", "Weather Display", "bool"),
            ("weather_time", "  Weather Time (HH:MM)", "str"),
            ("weather_times", "  Weather Times (csv HH:MM)", "csv"),
            ("status_line_enabled", "Status Line (time+temp+forecast)", "bool"),
            ("status_line_position", "  Status Line Position (top/bottom)", "str"),
            ("special_days_enabled", "Special Days", "bool"),
            ("special_days_time", "  Special Days Time (HH:MM)", "str"),

            # --- People ---
            ("__contacts__", "Family & Friends (birthdays + invite)", "contacts"),

            # --- Photo sources ---
            ("cloud_backup_enabled", "Google Drive Sync", "bool"),
            ("google_drive_folder_ids", "Drive Folders", "drivelist"),
            ("drive_push_enabled", "  Upload Local -> Drive (backup)", "bool"),
            ("family_folder_enabled", "Family/Friends Folder", "bool"),
            ("family_folder_id", "  Family Folder ID/Link", "str"),
            ("family_folder_recurring", "  Greetings Repeat Yearly", "bool"),

            # --- Features ---
            ("verse_display_enabled", "Verse Display", "bool"),
            ("enable_face_recognition", "Face Recognition", "bool"),
            ("motion_detection_enabled", "Motion Detection", "bool"),
            ("motion_triggered_slideshow", "Motion Slideshow", "bool"),
            ("motion_timeout", "Motion Timeout (sec)", "int"),
            ("night_light_enabled", "Night Light (motion)", "bool"),
            ("voice_control_enabled", "Voice Control", "bool"),
            ("web_control_enabled", "Web Control", "bool"),
            ("manual_navigation_pause", "Nav Pause (sec)", "int"),

            # --- Captions / overlays ---
            ("show_file_name", "Show File Name", "bool"),
            ("show_file_date", "Show File Date", "bool"),
            ("show_caption", "Show Caption", "bool"),
            ("immediate_display", "Immediate Display", "bool"),
            ("notification_sound_enabled", "Notification Sound", "bool"),
            ("notification_duration", "Toast Duration (sec)", "int"),
            ("media_mode", "Media Mode", "str"),
        ]

        selected = 0
        editing = False
        edit_buffer = ""
        scroll_offset = 0

        # Leave room for the two-line header and a footer hint.
        header_h = 70 + title_font.get_linesize()
        footer_h = font_size + 16
        max_visible = max(4, (screen_h - header_h - footer_h) // (font_size + 12))

        running = True
        clock = pygame.time.Clock()

        while running:
            # Draw background
            screen.fill((20, 20, 40))

            # Title
            title = title_font.render("Selah Configuration (F1)", True, (100, 200, 255))
            screen.blit(title, (20, 10))

            instructions = font.render(
                "Up/Down=Navigate  Enter=Edit  Space=Toggle  ESC=Close",
                True, (150, 150, 150)
            )
            screen.blit(instructions, (20, 15 + title_font.get_linesize()))

            # Draw fields
            y = header_h
            for i in range(scroll_offset, min(len(editable_fields), scroll_offset + max_visible)):
                key, label, ftype = editable_fields[i]

                # Highlight selected row
                if i == selected:
                    highlight = pygame.Surface((screen_w - 20, font_size + 10), pygame.SRCALPHA)
                    highlight.fill((60, 60, 120, 150))
                    screen.blit(highlight, (10, y - 3))

                # Label
                label_surf = font.render(f"{label}:", True, (200, 200, 200))
                screen.blit(label_surf, (20, y))

                # Value
                if editing and i == selected:
                    val_str = edit_buffer + "_"
                    color = (255, 255, 100)
                elif ftype == "layoutbool":
                    on = _layout_is_on(config, key)
                    val_str = "ON" if on else "OFF"
                    color = (100, 255, 100) if on else (255, 100, 100)
                elif ftype == "bool":
                    on = config.get(key, False)
                    val_str = "ON" if on else "OFF"
                    color = (100, 255, 100) if on else (255, 100, 100)
                elif ftype == "drivelist":
                    n = len(config.get("google_drive_folder_ids") or [])
                    val_str = f"{n} folder(s)  [Enter]"
                    color = (255, 255, 255)
                elif ftype == "contacts":
                    val_str = f"{len(_load_contacts())} people  [Enter]"
                    color = (255, 255, 255)
                elif ftype == "csv":
                    val_str = ", ".join(str(x) for x in (config.get(key) or [])) or "(none)"
                    color = (255, 255, 255)
                else:
                    val_str = str(config.get(key, ""))
                    color = (255, 255, 255)

                val_surf = font.render(val_str, True, color)
                screen.blit(val_surf, (screen_w // 2, y))
                y += font_size + 12

            # Footer hint — the family whitelist lives in the F2 sender manager.
            footer = font.render(
                "Family whitelist: close this, then press F2 (Sender Manager)",
                True, (120, 160, 220)
            )
            screen.blit(footer, (20, screen_h - footer_h))

            try:
                pygame.display.flip()
            except Exception:
                pass

            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE or event.key == pygame.K_F1:
                        running = False
                    elif editing:
                        if event.key == pygame.K_RETURN:
                            # Apply edit
                            key, _, ftype = editable_fields[selected]
                            try:
                                if ftype == "int":
                                    config[key] = int(edit_buffer)
                                elif ftype == "csv":
                                    config[key] = [x.strip() for x in edit_buffer.split(",") if x.strip()]
                                else:
                                    config[key] = edit_buffer
                            except ValueError:
                                pass
                            editing = False
                        elif event.key == pygame.K_BACKSPACE:
                            edit_buffer = edit_buffer[:-1]
                        else:
                            if event.unicode and event.unicode.isprintable():
                                edit_buffer += event.unicode
                    else:
                        if event.key == pygame.K_DOWN:
                            selected = min(selected + 1, len(editable_fields) - 1)
                            if selected >= scroll_offset + max_visible:
                                scroll_offset = selected - max_visible + 1
                        elif event.key == pygame.K_UP:
                            selected = max(selected - 1, 0)
                            if selected < scroll_offset:
                                scroll_offset = selected
                        elif event.key == pygame.K_RETURN:
                            key, _, ftype = editable_fields[selected]
                            if ftype == "drivelist":
                                # Open the add/remove sub-screen.
                                _manage_drive_folders(screen, config)
                            elif ftype == "contacts":
                                _manage_contacts(screen, config)
                            elif ftype not in ("bool", "layoutbool"):
                                # Only text/number fields are editable; toggles use Space.
                                editing = True
                                if ftype == "csv":
                                    edit_buffer = ", ".join(str(x) for x in (config.get(key) or []))
                                else:
                                    edit_buffer = str(config.get(key, ""))
                        elif event.key == pygame.K_SPACE:
                            key, _, ftype = editable_fields[selected]
                            if ftype == "bool":
                                config[key] = not config.get(key, False)
                            elif ftype == "layoutbool":
                                _layout_toggle(config, key)

            clock.tick(30)

    except Exception as e:
        log_error(f"Config GUI error: {e}")
