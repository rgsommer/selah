"""F1 on-screen configuration editor using pygame UI."""

import pygame
from modules.logger import log_error


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

        # Editable config keys with display labels
        editable_fields = [
            ("rotate_interval", "Rotate Interval (sec)", "int"),
            ("on_time", "Display On Time", "str"),
            ("off_time", "Display Off Time", "str"),
            ("manual_navigation_pause", "Nav Pause (sec)", "int"),
            ("motion_timeout", "Motion Timeout (sec)", "int"),
            ("enable_face_recognition", "Face Recognition", "bool"),
            ("verse_display_enabled", "Verse Display", "bool"),
            ("calendar_display_enabled", "Calendar Display", "bool"),
            ("weather_enabled", "Weather Display", "bool"),
            ("motion_detection_enabled", "Motion Detection", "bool"),
            ("motion_triggered_slideshow", "Motion Slideshow", "bool"),
            ("voice_control_enabled", "Voice Control", "bool"),
            ("web_control_enabled", "Web Control", "bool"),
            ("weather_time", "Weather Time (HH:MM)", "str"),
            ("special_days_enabled", "Special Days", "bool"),
            ("night_light_enabled", "Night Light (motion)", "bool"),
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
        max_visible = (screen_h - 120) // (font_size + 12)

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
            y = 60 + title_font.get_linesize()
            for i in range(scroll_offset, min(len(editable_fields), scroll_offset + max_visible)):
                key, label, ftype = editable_fields[i]
                value = config.get(key, "")

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
                else:
                    if ftype == "bool":
                        val_str = "ON" if value else "OFF"
                        color = (100, 255, 100) if value else (255, 100, 100)
                    else:
                        val_str = str(value)
                        color = (255, 255, 255)

                val_surf = font.render(val_str, True, color)
                screen.blit(val_surf, (screen_w // 2, y))
                y += font_size + 12

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
                            if ftype != "bool":
                                editing = True
                                edit_buffer = str(config.get(key, ""))
                        elif event.key == pygame.K_SPACE:
                            key, _, ftype = editable_fields[selected]
                            if ftype == "bool":
                                config[key] = not config.get(key, False)

            clock.tick(30)

    except Exception as e:
        log_error(f"Config GUI error: {e}")
