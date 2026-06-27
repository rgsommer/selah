"""Quiz mode for Selah Display System.

Interactive trivia game using displayed media.
Questions loaded from quiz_questions.json or auto-generated from media metadata.
"""

import json
import time
import random
import os
import pygame
from modules.logger import log_error


def start_quiz_mode(screens, config, all_files):
    """Launch an interactive quiz session. Blocks until user presses ESC."""
    screen = screens.get("landscape") or screens.get("portrait")
    if not screen or not all_files:
        return

    questions = _load_questions(all_files)
    if not questions:
        _show_message(screen, "No quiz questions available!", duration=3)
        return

    random.shuffle(questions)
    score = 0
    total = min(len(questions), 10)

    for i, q in enumerate(questions[:total]):
        result = _show_question(screen, q, i + 1, total, config)
        if result is None:
            break
        if result:
            score += 1

    _show_results(screen, score, total)


def _load_questions(all_files):
    """Load quiz questions from file, or generate basic ones."""
    questions = []
    try:
        with open("quiz_questions.json", "r") as f:
            questions = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        log_error(f"Failed to load quiz questions: {e}")

    if not questions and all_files:
        sampled = random.sample(all_files, min(20, len(all_files)))
        for fp in sampled:
            questions.append({
                "image": fp,
                "question": "What's the story behind this photo?",
                "type": "open",
            })
    return questions


def _show_question(screen, question, num, total, config):
    """Display a single quiz question. Returns True/False/None(ESC)."""
    try:
        screen_w, screen_h = screen.get_size()
        screen.fill((20, 20, 40))

        font_size = max(28, screen_w // 30)
        font = pygame.font.Font(None, font_size)
        small_font = pygame.font.Font(None, max(22, font_size - 8))

        image_path = question.get("image")
        if image_path:
            try:
                img = pygame.image.load(image_path)
                img_w, img_h = img.get_size()
                max_h = screen_h // 2 - 40
                max_w = screen_w - 80
                scale = min(max_w / img_w, max_h / img_h)
                img = pygame.transform.smoothscale(img, (int(img_w * scale), int(img_h * scale)))
                img_rect = img.get_rect(centerx=screen_w // 2, top=20)
                screen.blit(img, img_rect)
            except Exception:
                pass

        q_text = question.get("question", "No question")
        header = f"Question {num}/{total}"
        header_surf = small_font.render(header, True, (180, 180, 180))
        screen.blit(header_surf, (20, screen_h // 2 + 10))

        words = q_text.split()
        lines = []
        line = ""
        for w in words:
            test = f"{line} {w}".strip()
            if font.size(test)[0] < screen_w - 80:
                line = test
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)

        y = screen_h // 2 + 50
        for ln in lines:
            surf = font.render(ln, True, (255, 255, 255))
            screen.blit(surf, (40, y))
            y += font.get_linesize()

        options = question.get("options", [])
        correct = question.get("answer", 0)

        if options:
            y += 20
            for idx, opt in enumerate(options):
                label = f"  {chr(65 + idx)}. {opt}"
                opt_surf = small_font.render(label, True, (200, 200, 255))
                screen.blit(opt_surf, (60, y))
                y += small_font.get_linesize() + 8

        hint = "Press A/B/C/D to answer, ESC to quit" if options else "Press SPACE to continue, ESC to quit"
        hint_surf = small_font.render(hint, True, (120, 120, 120))
        screen.blit(hint_surf, (20, screen_h - 40))

        pygame.display.flip()

        while True:
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    if not options:
                        if event.key == pygame.K_SPACE:
                            return True
                    else:
                        key_map = {pygame.K_a: 0, pygame.K_b: 1, pygame.K_c: 2, pygame.K_d: 3}
                        if event.key in key_map:
                            chosen = key_map[event.key]
                            is_correct = (chosen == correct)
                            _flash_answer(screen, is_correct, screen_w, screen_h)
                            return is_correct
                if event.type == pygame.QUIT:
                    return None
            time.sleep(0.05)
    except Exception as e:
        log_error(f"Quiz question display failed: {e}")
        return None


def _flash_answer(screen, correct, screen_w, screen_h):
    try:
        color = (0, 180, 0, 80) if correct else (180, 0, 0, 80)
        overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        overlay.fill(color)
        screen.blit(overlay, (0, 0))
        font = pygame.font.Font(None, max(48, screen_w // 15))
        text = "Correct!" if correct else "Wrong!"
        text_color = (0, 255, 0) if correct else (255, 80, 80)
        surf = font.render(text, True, text_color)
        rect = surf.get_rect(center=(screen_w // 2, screen_h // 2))
        screen.blit(surf, rect)
        pygame.display.flip()
        time.sleep(1.5)
    except Exception:
        pass


def _show_results(screen, score, total):
    try:
        screen_w, screen_h = screen.get_size()
        screen.fill((20, 20, 40))
        big_font = pygame.font.Font(None, max(60, screen_w // 12))
        font = pygame.font.Font(None, max(36, screen_w // 20))

        title = big_font.render("Quiz Complete!", True, (255, 215, 0))
        screen.blit(title, title.get_rect(centerx=screen_w // 2, top=screen_h // 4))

        score_surf = big_font.render(f"{score} / {total}", True, (255, 255, 255))
        screen.blit(score_surf, score_surf.get_rect(centerx=screen_w // 2, top=screen_h // 2 - 30))

        pct = (score / total * 100) if total else 0
        if pct >= 80: comment = "Amazing!"
        elif pct >= 60: comment = "Great job!"
        elif pct >= 40: comment = "Not bad!"
        else: comment = "Better luck next time!"

        comment_surf = font.render(comment, True, (180, 220, 255))
        screen.blit(comment_surf, comment_surf.get_rect(centerx=screen_w // 2, top=screen_h // 2 + 60))

        hint_surf = font.render("Press any key to continue...", True, (120, 120, 120))
        screen.blit(hint_surf, (screen_w // 2 - hint_surf.get_width() // 2, screen_h - 60))
        pygame.display.flip()

        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN or event.type == pygame.QUIT:
                    waiting = False
            time.sleep(0.05)
    except Exception as e:
        log_error(f"Quiz results display failed: {e}")


def _show_message(screen, message, duration=3):
    try:
        screen_w, screen_h = screen.get_size()
        screen.fill((20, 20, 40))
        font = pygame.font.Font(None, max(36, screen_w // 20))
        surf = font.render(message, True, (255, 255, 255))
        screen.blit(surf, surf.get_rect(center=(screen_w // 2, screen_h // 2)))
        pygame.display.flip()
        time.sleep(duration)
    except Exception:
        pass
