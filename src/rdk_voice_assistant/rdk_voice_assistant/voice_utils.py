import re
import time
from typing import Optional


def normalize_text(text: str) -> str:
    """Remove whitespace and common punctuation marks from speech text."""
    return re.sub(r'[\s,，。！？!?、；;：“”"\'（）()【】\[\]<>《》]+', '', text).strip()


def remove_emojis(text: str) -> str:
    """Strip emojis and specific voice-annoying symbols from vocalized text."""
    try:
        emoji_pattern = re.compile(
            r'[\U0001F300-\U0001F5FF]'
            r'|[\U0001F600-\U0001F64F]'
            r'|[\U0001F680-\U0001F6FF]'
            r'|[\U0001F900-\U0001F9FF]'
            r'|[\u2700-\u27BF]'
            r'|[\u2600-\u26FF]',
            re.UNICODE
        )
        text = emoji_pattern.sub('', text)
    except Exception:
        pass
    return text.replace('~', '').strip()


def match_wake_word(text: str, wake_words_str: str) -> Optional[str]:
    """Check if the text contains any of the configured wake words."""
    normalized_text = normalize_text(text)
    words = [normalize_text(item) for item in wake_words_str.split(',') if item.strip()]
    # Match longest wake word first to prevent partial matching (e.g. '小智小智' matching '小智')
    for word in sorted(set(words), key=len, reverse=True):
        if word and word in normalized_text:
            return word
    return None


def should_drop_command(
    text: str,
    last_command_text: str,
    last_command_time: float,
    cooldown_sec: float,
    duplicate_window_sec: float,
    logger=None
) -> bool:
    """Check if the command is a duplicate or falls inside the cooldown window."""
    now = time.time()
    if not last_command_text:
        return False

    elapsed = now - last_command_time

    if elapsed < cooldown_sec:
        if logger:
            logger.info(
                f'Discarded STT text during command cooldown ({elapsed:.2f}s < {cooldown_sec:.2f}s): {text}'
            )
        return True

    if elapsed < duplicate_window_sec:
        if text == last_command_text or text in last_command_text or last_command_text in text:
            if logger:
                logger.info(f'Discarded duplicate/overlapping STT text: {text}')
            return True

    return False
