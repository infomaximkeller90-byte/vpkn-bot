"""Telegram bot handlers."""
from __future__ import annotations

import asyncio
import io
import logging
import textwrap
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .ai import AI, ChatTurn
from .pdf_gen import render_document_pdf, render_flyer_pdf, safe_filename
from .storage import Storage

logger = logging.getLogger(__name__)


WELCOME_TEXT = textwrap.dedent(
    """\
    Привет! Я *VPKN* — твой AI-ассистент.

    Что я умею:
    • *Чат* — просто напиши любой вопрос, отвечу как Claude/ChatGPT
    • */pdf <тема>* — соберу красивый PDF документ
    • */flyer <описание>* — сделаю флаер/постер в PDF (для печати, для клиентов)
    • */image <описание>* — сгенерирую картинку
    • */reset* — очистить историю разговора
    • */help* — снова показать эту справку

    *Примеры:*
    `/pdf коммерческое предложение на ремонт квартиры под ключ, 80 кв м, цена 1.5 млн`
    `/flyer открытие пиццерии Mama Mia в субботу 12:00, скидка 30% на всё меню, телефон +7 999 123 4567`
    `/image логотип кофейни в минималистичном стиле`

    Можешь писать как обычному человеку — отвечу.
    """
)


HELP_TEXT = WELCOME_TEXT


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )


async def _upload_doc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT
    )


def _ai(context: ContextTypes.DEFAULT_TYPE) -> AI:
    return context.application.bot_data["ai"]


def _storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.application.bot_data["storage"]


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        HELP_TEXT, parse_mode=ParseMode.MARKDOWN
    )


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    _storage(context).reset(update.effective_chat.id)
    await update.effective_message.reply_text(
        "История разговора очищена. Начинаем с чистого листа."
    )


async def chat_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_chat is None:
        return
    text = (update.effective_message.text or "").strip()
    if not text:
        return

    await _typing(update, context)
    storage = _storage(context)
    history = storage.get(update.effective_chat.id)
    turns = [ChatTurn(role=m["role"], text=m["text"]) for m in history.messages]

    try:
        reply = await _ai(context).chat_reply(turns, text)
    except Exception as exc:  # noqa: BLE001 — surface model errors to the chat
        logger.exception("chat_reply failed")
        await update.effective_message.reply_text(
            f"Упс, что-то пошло не так с AI: {exc}"
        )
        return

    history.add("user", text)
    history.add("model", reply)
    storage.commit()

    # Telegram has a 4096 char limit per message — chunk if needed.
    for chunk in _chunk(reply, 4000):
        try:
            await update.effective_message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # Fall back to plain text if Markdown parsing fails.
            await update.effective_message.reply_text(chunk)


async def pdf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await update.effective_message.reply_text(
            "Напиши, про что сделать PDF.\n\n"
            "Пример: `/pdf договор на оказание услуг по ремонту электроники`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _typing(update, context)
    try:
        spec = await _ai(context).generate_document(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_document failed")
        await update.effective_message.reply_text(
            f"Не получилось придумать содержимое: {exc}"
        )
        return

    await _upload_doc(update, context)
    try:
        pdf_bytes = await asyncio.to_thread(render_document_pdf, spec)
    except Exception as exc:  # noqa: BLE001
        logger.exception("render_document_pdf failed")
        await update.effective_message.reply_text(
            f"Не получилось собрать PDF: {exc}"
        )
        return

    filename = safe_filename(str(spec.get("title") or prompt))
    await update.effective_message.reply_document(
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption=f"*{spec.get('title', 'Документ')}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def flyer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await update.effective_message.reply_text(
            "Опиши флаер: что рекламируем, когда, контакты, желаемая атмосфера.\n\n"
            "Пример: `/flyer открытие кофейни Bean Street в субботу 10:00, "
            "бесплатный капучино каждому, адрес Невский 22`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _typing(update, context)
    try:
        html = await _ai(context).generate_flyer_html(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_flyer_html failed")
        await update.effective_message.reply_text(
            f"Не получилось придумать дизайн флаера: {exc}"
        )
        return

    await _upload_doc(update, context)
    try:
        pdf_bytes = await asyncio.to_thread(render_flyer_pdf, html)
    except Exception as exc:  # noqa: BLE001
        logger.exception("render_flyer_pdf failed")
        await update.effective_message.reply_text(
            f"Не получилось отрендерить PDF из HTML: {exc}"
        )
        return

    filename = safe_filename(prompt, fallback="flyer")
    await update.effective_message.reply_document(
        document=io.BytesIO(pdf_bytes),
        filename=filename,
        caption="Готовый флаер",
    )


async def image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    prompt = " ".join(context.args or []).strip()
    if not prompt:
        await update.effective_message.reply_text(
            "Опиши картинку.\n\nПример: `/image логотип кофейни в минималистичном стиле`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if update.effective_chat is not None:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
        )

    try:
        image_bytes = await _ai(context).generate_image(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_image failed")
        await update.effective_message.reply_text(
            f"Не получилось сгенерировать картинку: {exc}"
        )
        return

    if not image_bytes:
        await update.effective_message.reply_text(
            "Модель не вернула картинку. Попробуй переформулировать запрос."
        )
        return

    await update.effective_message.reply_photo(
        photo=io.BytesIO(image_bytes),
        caption=prompt[:1024],
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            chunks.append(remaining)
            break
        # Try to break at the last newline before the limit.
        split = remaining.rfind("\n", 0, size)
        if split <= 0:
            split = size
        chunks.append(remaining[:split])
        remaining = remaining[split:].lstrip("\n")
    return chunks


def register(application: Application, ai: AI, storage: Storage) -> None:
    application.bot_data["ai"] = ai
    application.bot_data["storage"] = storage

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("reset", reset_cmd))
    application.add_handler(CommandHandler("pdf", pdf_cmd))
    application.add_handler(CommandHandler("flyer", flyer_cmd))
    application.add_handler(CommandHandler("image", image_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_msg))

    application.add_error_handler(error_handler)
