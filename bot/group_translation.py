"""Background English ↔ Traditional Chinese translation of human group text."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import wraps
import logging
import os
import re
import threading
import hashlib
import html


from database.read_cache import ReadCache

TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
_cache = ReadCache(max_entries=256)
_http = threading.local()
_pool = None
_pool_lock = threading.Lock()
_pending = threading.BoundedSemaphore(16)


@dataclass(frozen=True)
class TranslationJob:
    text: str
    reply_token: str
    quote_token: str | None = None
    mentions: tuple[tuple[int, int], ...] = ()


def _session():
    import requests
    if not hasattr(_http, "session"):
        _http.session = requests.Session()
    return _http.session


def translation_job(event):
    source = event.source
    user_id = getattr(source, "user_id", None)
    group_id = getattr(source, "group_id", None)
    if (getattr(source, "type", None) != "group" or not isinstance(group_id, str)
            or not group_id.startswith("C") or not isinstance(user_id, str) or not user_id.startswith("U")
            or user_id == os.getenv("LINE_BOT_USER_ID")):
        return None
    text = getattr(event.message, "text", "")
    reply_token = getattr(event, "reply_token", None)
    if not isinstance(text, str) or not text.strip() or not isinstance(reply_token, str) or not reply_token:
        return None
    from bot.report_keywords import REPORT_KEYWORDS
    if text.strip() in REPORT_KEYWORDS:
        return None
    if text.lstrip().startswith("/") or re.match(r"\s*edit(?:\s|$)", text, re.IGNORECASE):
        return None
    mention = getattr(event.message, "mention", None)
    items = getattr(mention, "mentionees", None)
    spans = []
    if isinstance(items, (list, tuple)):
        for item in items:
            index, length = getattr(item, "index", None), getattr(item, "length", None)
            if type(index) is int and type(length) is int and index >= 0 and length > 0:
                spans.append((index, length))
    quote = getattr(event.message, "quote_token", None)
    return TranslationJob(text, reply_token, quote if isinstance(quote, str) and quote else None, tuple(spans))


def _parts(text, mentions):
    """Exclude protected content from the API rather than asking it to preserve it."""
    ranges = []
    encoded = text.encode("utf-16-le")
    for index, length in mentions:
        try:
            start = len(encoded[:index * 2].decode("utf-16-le"))
            end = len(encoded[:(index + length) * 2].decode("utf-16-le"))
        except UnicodeDecodeError:
            continue
        if 0 <= start < end <= len(text):
            ranges.append((start, end))
    for match in re.finditer(r"https?://[^\s]+|\b[Ss]\d{4,}\b|\b[UC][0-9a-fA-F]{32}\b|@[\w./|\-]+", text):
        ranges.append(match.span())
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    parts, position = [], 0
    for start, end in merged:
        if start > position:
            parts.append((text[position:start], False))
        parts.append((text[start:end], True))
        position = end
    if position < len(text):
        parts.append((text[position:], False))
    return parts


def _google_translate(texts, target, key):
    # Exceptions are logged by type only: request URLs can contain the API key.
    response = _session().post(TRANSLATE_URL, params={"key": key},
                               json={"q": list(texts), "target": target, "format": "text"},
                               timeout=(3, 8))
    response.raise_for_status()
    values = response.json().get("data", {}).get("translations", [])
    if not isinstance(values, list) or len(values) != len(texts):
        raise ValueError("Invalid translation response count")
    for value in values:
        if (not isinstance(value, dict) or not isinstance(value.get("translatedText"), str)
                or not value["translatedText"].strip() or not isinstance(value.get("detectedSourceLanguage"), str)):
            raise ValueError("Invalid translation response")
    return values


def translate_group_text(text, mentions=()):
    key = os.getenv("GOOGLE_CLOUD_TRANSLATE", "").strip()
    if not key:
        return None
    parts = _parts(text, mentions)
    indexes = [index for index, (part, protected) in enumerate(parts)
               if not protected and re.search(r"[A-Za-z\u3400-\u9fff]", part)]
    if not indexes or len(indexes) > 128:
        return None
    texts = tuple(parts[index][0] for index in indexes)
    content = "".join(texts)
    han = len(re.findall(r"[\u3400-\u9fff]", content))
    latin = len(re.findall(r"[A-Za-z]", content))
    target = "en" if han * 2 >= latin else "zh-TW"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    translations = _cache.get((texts, target, fingerprint),
                              lambda: _google_translate(texts, target, key), ttl=300)
    # Check Google's language detection, not just Unicode: do not translate
    # Japanese, Filipino, or other languages simply because scripts overlap.
    dominant = max(range(len(texts)), key=lambda index: len(texts[index]))
    source = translations[dominant]["detectedSourceLanguage"].lower()
    if source != "en" and not source.startswith("zh"):
        return None
    if (source == "en" and target == "en") or (source.startswith("zh") and target != "en"):
        target = "zh-TW" if source == "en" else "en"
        translations = _cache.get((texts, target, fingerprint),
                                  lambda: _google_translate(texts, target, key), ttl=300)
    for index, value in zip(indexes, translations):
        original = parts[index][0]
        leading = re.match(r"\s*", original)[0]
        trailing = re.search(r"\s*$", original)[0]
        parts[index] = (leading + html.unescape(value["translatedText"]).strip() + trailing, False)
    result = "".join(part for part, _ in parts)
    return result if result.strip() != text.strip() else None


def text_chunks(text, limit=4900):
    chunks, current, units = [], [], 0
    for character in text:
        size = 2 if ord(character) > 0xFFFF else 1
        if units + size > limit:
            chunks.append("".join(current))
            current, units = [], 0
        current.append(character)
        units += size
    if current:
        chunks.append("".join(current))
    if len(chunks) > 5:
        raise ValueError("Translation exceeds LINE reply size")
    return chunks


def _run(job):
    try:
        result = translate_group_text(job.text, job.mentions)
        if result:
            from app import send_group_translation
            send_group_translation(job.reply_token, text_chunks(result), job.quote_token)
    except Exception as error:
        logging.warning("GROUP TRANSLATION ERROR: %s", type(error).__name__)
    finally:
        _pending.release()


def queue_group_translation(event):
    global _pool
    if not os.getenv("GOOGLE_CLOUD_TRANSLATE", "").strip():
        return
    job = translation_job(event)
    if job is None or not _pending.acquire(blocking=False):
        return
    try:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="group-translation")
            _pool.submit(_run, job)
    except Exception as error:
        _pending.release()
        logging.warning("GROUP TRANSLATION QUEUE ERROR: %s", type(error).__name__)


def group_translations(function):
    @wraps(function)
    def wrapped(event):
        queue_group_translation(event)
        return function(event)
    return wrapped


def close_translation_pool():
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool:
        pool.shutdown(wait=True)
