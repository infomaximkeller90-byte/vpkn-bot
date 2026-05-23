"""Thin wrapper around the Google Gemini API.

Exposes the high-level helpers used by the rest of the bot:

- ``chat_reply`` — chat completion with conversation history; optional
  attachment (image / PDF) for vision and document analysis.
- ``generate_document`` — produce a structured JSON document spec from a
  natural language prompt (used by the PDF generator).
- ``generate_flyer_html`` — produce a self-contained HTML+CSS flyer from a
  natural language prompt (used by the flyer generator).
- ``clone_flyer_html_from_pdf`` — take an uploaded PDF + caption, produce a
  new self-contained HTML+CSS flyer that mimics the original style.
- ``generate_image`` — image generation via Gemini image models.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


CHAT_SYSTEM_PROMPT = (
    "Ты — VPKN, дружелюбный AI-ассистент в Telegram. Отвечай на языке "
    "пользователя (по умолчанию русский). Будь полезным, кратким и точным. "
    "Используй Markdown для форматирования (жирный, курсив, списки, ссылки), "
    "Telegram отрендерит его. Не используй слишком много эмодзи. "
    "Пользователь может присылать картинки и PDF-файлы — разбирай их и "
    "отвечай по содержанию. "
    "Если пользователь хочет сгенерировать PDF документ — подскажи команду "
    "/pdf <описание>. Для флаеров/постеров — /flyer <описание>. Для очистки "
    "истории разговора — /reset. Для генерации картинки — /image <описание>."
)


FLYER_CLONE_SYSTEM_PROMPT = (
    "Ты — дизайнер-клонировщик. Тебе дают PDF-образец и задачу от "
    "пользователя. Изучи стиль оригинала (композиция, цвета, типографика, "
    "иерархия, декоративные элементы) и сгенерируй ОДИН самодостаточный HTML-"
    "файл (включая <style>) под задачу пользователя в том же визуальном "
    "языке. Только HTML, без пояснений и без markdown-блоков ```. Требования:\n"
    "- @page { size: A4; margin: 0; } и body без margin, чтобы заполнить лист\n"
    "- Сохрани стиль, цвета и композицию оригинала, но весь текст/"
    "  данные подмени под задачу пользователя\n"
    "- Только системные/веб-безопасные шрифты (sans-serif, serif). НЕ подключай "
    "  Google Fonts\n"
    "- НЕ используй внешние картинки или ссылки. Все декоративные элементы делай "
    "  через CSS/SVG inline\n"
    "- Если в оригинале были фото/логотипы — замени их на похожие по духу "
    "  SVG-иллюстрации (не пытайся вставить реальное фото)\n"
    "- Подходит для печати на A4 или отправки клиенту"
)

# JSON schema describing the structured PDF "document spec" that
# the PDF renderer expects from the model.
DOCUMENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "author": {"type": "string"},
        "date": {"type": "string"},
        "language": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "paragraphs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "numbered": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "callout": {"type": "string"},
                },
                "required": ["heading"],
            },
        },
    },
    "required": ["title", "sections"],
}


DOCUMENT_SYSTEM_PROMPT = (
    "Ты — генератор содержимого для PDF документов. Твоя задача — превратить "
    "запрос пользователя в полноценный, профессионально оформленный документ. "
    "Пиши на языке пользователя. Структура: title (короткий, ёмкий заголовок), "
    "опционально subtitle, и массив sections с heading и paragraphs (и/или "
    "bullets/numbered где уместно). Делай 3-7 секций, каждая секция — 1-3 "
    "качественных абзаца. Пиши конкретно, без воды. Если запрос — флаер/постер, "
    "ответь что лучше использовать /flyer и сделай очень короткий документ."
)


FLYER_SYSTEM_PROMPT = (
    "Ты — дизайнер флаеров. Сгенерируй ОДИН самодостаточный HTML файл "
    "(включая <style>) для печати на A4 (210мм x 297мм). Только HTML, без "
    "пояснений, без markdown-блоков ```. Требования:\n"
    "- @page { size: A4; margin: 0; } и body без margin, чтобы заполнить лист\n"
    "- Современный, привлекательный дизайн под суть запроса (цвета, типографика)\n"
    "- Используй только системные/веб-безопасные шрифты (sans-serif, serif). НЕ "
    "  подключай Google Fonts (нет интернета во время рендеринга)\n"
    "- НЕ используй внешние картинки или ссылки. Все элементы (фоны, формы, "
    "  градиенты, иконки) делай через CSS/SVG inline\n"
    "- Большой смелый заголовок, чёткая иерархия, легко читается с расстояния\n"
    "- Включи все важные детали из запроса (даты, телефоны, адреса, цены)\n"
    "- Подходит для отправки клиентам или печати"
)


@dataclass
class ChatTurn:
    role: str  # "user" or "model"
    text: str


def _history_to_contents(history: Iterable[ChatTurn]) -> List[types.Content]:
    contents: List[types.Content] = []
    for turn in history:
        contents.append(
            types.Content(
                role=turn.role,
                parts=[types.Part.from_text(text=turn.text)],
            )
        )
    return contents


class AI:
    def __init__(
        self,
        api_key: str,
        chat_model: str = "gemini-flash-latest",
        image_model: str = "gemini-2.5-flash-image",
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self.chat_model = chat_model
        self.image_model = image_model

    async def chat_reply(
        self,
        history: List[ChatTurn],
        user_text: str,
        attachment_data: Optional[bytes] = None,
        attachment_mime: Optional[str] = None,
    ) -> str:
        """Generate a chat reply, given prior history + the new user turn.

        ``attachment_data`` / ``attachment_mime`` let the user attach a single
        binary (image or PDF) to the current turn. The attachment is sent as
        an additional Part on the user turn so Gemini can reason about it.
        """
        contents = _history_to_contents(history)
        user_parts: List[types.Part] = []
        if attachment_data and attachment_mime:
            user_parts.append(
                types.Part.from_bytes(
                    data=attachment_data, mime_type=attachment_mime
                )
            )
        user_parts.append(types.Part.from_text(text=user_text))
        contents.append(types.Content(role="user", parts=user_parts))

        def _run() -> str:
            response = self._client.models.generate_content(
                model=self.chat_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=CHAT_SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=2048,
                ),
            )
            return (response.text or "").strip() or "(пустой ответ)"

        return await asyncio.to_thread(_run)

    async def clone_flyer_html_from_pdf(
        self, pdf_bytes: bytes, user_caption: str
    ) -> str:
        """Given a PDF sample and a free-form caption, return new flyer HTML.

        The model is shown the PDF in-line and asked to mimic its visual
        language while substituting the content for what the user described
        in their caption.
        """
        caption = (user_caption or "").strip() or (
            "Сделай в том же стиле, без конкретных правок — выбери схожую тему."
        )
        parts = [
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            types.Part.from_text(
                text=(
                    "Приложен образец в PDF. Сделай похожий флаер/постер "
                    "по задаче:\n\n" + caption
                )
            ),
        ]

        def _run() -> str:
            response = self._client.models.generate_content(
                model=self.chat_model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=FLYER_CLONE_SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=8192,
                ),
            )
            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```\s*$", "", raw)
            return raw.strip()

        return await asyncio.to_thread(_run)

    async def generate_document(self, user_prompt: str) -> dict:
        """Generate a structured document spec ready for the PDF renderer."""

        def _run() -> dict:
            response = self._client.models.generate_content(
                model=self.chat_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=DOCUMENT_SYSTEM_PROMPT,
                    temperature=0.6,
                    response_mime_type="application/json",
                    response_schema=DOCUMENT_SCHEMA,
                    max_output_tokens=4096,
                ),
            )
            raw = (response.text or "").strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Document JSON decode failed: %s; raw=%s", exc, raw[:500])
                # Last-ditch attempt: extract JSON object from text.
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
                raise

        return await asyncio.to_thread(_run)

    async def generate_flyer_html(self, user_prompt: str) -> str:
        """Generate a self-contained HTML+CSS flyer for the PDF renderer."""

        def _run() -> str:
            response = self._client.models.generate_content(
                model=self.chat_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=FLYER_SYSTEM_PROMPT,
                    temperature=0.8,
                    max_output_tokens=8192,
                ),
            )
            raw = (response.text or "").strip()
            # Strip ``` fences if the model added them despite instructions.
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
                raw = re.sub(r"\n?```\s*$", "", raw)
            return raw.strip()

        return await asyncio.to_thread(_run)

    async def generate_image(self, user_prompt: str) -> Optional[bytes]:
        """Generate a single image (PNG bytes) from a text prompt.

        Returns ``None`` if the model didn't include an image in the response.
        """

        def _run() -> Optional[bytes]:
            response = self._client.models.generate_content(
                model=self.image_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            for candidate in response.candidates or []:
                content = candidate.content
                if content is None:
                    continue
                for part in content.parts or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and inline.data:
                        data = inline.data
                        if isinstance(data, str):
                            return base64.b64decode(data)
                        return bytes(data)
            return None

        return await asyncio.to_thread(_run)
