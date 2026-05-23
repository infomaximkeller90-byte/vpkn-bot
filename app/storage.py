"""Lightweight per-chat conversation memory.

Persisted as JSON on disk so we don't lose history across restarts.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ChatHistory:
    messages: List[Dict[str, str]] = field(default_factory=list)

    def add(self, role: str, text: str) -> None:
        self.messages.append({"role": role, "text": text})
        # Keep last ~30 turns to bound prompt size.
        if len(self.messages) > 60:
            self.messages = self.messages[-60:]

    def reset(self) -> None:
        self.messages.clear()


class Storage:
    def __init__(self, data_dir: str) -> None:
        self.path = os.path.join(data_dir, "chats.json")
        self._lock = threading.Lock()
        self._chats: Dict[str, ChatHistory] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for chat_id, msgs in raw.items():
                self._chats[chat_id] = ChatHistory(messages=list(msgs))
        except (json.JSONDecodeError, OSError):
            self._chats = {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {cid: c.messages for cid, c in self._chats.items()},
                f,
                ensure_ascii=False,
            )
        os.replace(tmp, self.path)

    def get(self, chat_id: int) -> ChatHistory:
        with self._lock:
            key = str(chat_id)
            if key not in self._chats:
                self._chats[key] = ChatHistory()
            return self._chats[key]

    def commit(self) -> None:
        with self._lock:
            self._save()

    def reset(self, chat_id: int) -> None:
        with self._lock:
            self._chats[str(chat_id)] = ChatHistory()
            self._save()
