"""
LightClaw ChatManager — 会话元数据持久化层。

职责：
  - 管理 ``chats.json``：存储每个用户（agentId, userId）维度的会话列表（ChatMeta）
  - 维护 ``sessionIdHistory``：跨 Reset 的历史 sessionId 路由表，使超时/主动 reset
    后历史消息仍可完整回溯
  - CRUD：list / create / update / delete 会话
  - append_session_history：幂等追加旧 sessionId（reset 检测时调用）

文件布局（遵循 _sessions_dir 约定）：
  <sessions_dir>/chats/<agentId>/<userId>/chats.json

线程安全：
  - 路径级 threading.Lock + 原子 rename（先写 .tmp 再 os.replace）
  - asyncio 环境下 ChatManager.delete_chat 等耗时 IO 应通过 run_in_executor 调用；
    但在测试和普通同步路径中直接调用也是安全的。

对标 OpenClaw：
  src/socket/service/chat-{list,create,update,delete}.ts
  src/utils/common.ts → readChatsFile / writeChatsFile
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_SESSION_ID_HISTORY = 100

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class ChatMeta:
    """单条会话的元数据，与 OpenClaw TypeScript ChatMeta 字段完全对齐。"""
    chatId: str
    title: str
    titleLocked: bool
    createdAt: int   # 毫秒时间戳
    updatedAt: int   # 毫秒时间戳
    pinned: bool
    # 历史所有 sessionId 的路由表——跨 Reset 历史合并的核心字段
    sessionIdHistory: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ChatMeta":
        return ChatMeta(
            chatId=d.get("chatId", ""),
            title=d.get("title", "新会话"),
            titleLocked=bool(d.get("titleLocked", False)),
            createdAt=int(d.get("createdAt", 0)),
            updatedAt=int(d.get("updatedAt", 0)),
            pinned=bool(d.get("pinned", False)),
            sessionIdHistory=list(d.get("sessionIdHistory") or []),
        )


# ---------------------------------------------------------------------------
# ChatsStore — chats.json 读写层
# ---------------------------------------------------------------------------

# 全局：路径 → Lock，保证同一文件路径同一时刻只有一个写操作
_file_locks: Dict[str, threading.Lock] = {}
_class_lock = threading.Lock()


def _get_file_lock(path: str) -> threading.Lock:
    with _class_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def _now_ms() -> int:
    return int(time.time() * 1000)


class ChatsStore:
    """chats.json 的低级读写封装。

    每个 (agentId, userId) 对应一个独立的 chats.json 文件，存储于：
        <sessions_dir>/chats/<agentId>/<userId>/chats.json
    """

    SCHEMA_VERSION = 1

    def __init__(self, sessions_dir: str, agent_id: str, user_id: str):
        self._path = os.path.join(
            sessions_dir, "chats", agent_id, user_id, "chats.json"
        )
        self._lock = _get_file_lock(self._path)

    @property
    def path(self) -> str:
        return self._path

    def _read_unlocked(self) -> List[ChatMeta]:
        """从磁盘读取（不加锁，调用方负责持锁）。"""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            chats_raw = data.get("chats") if isinstance(data, dict) else data
            if isinstance(chats_raw, list):
                return [ChatMeta.from_dict(c) for c in chats_raw if isinstance(c, dict)]
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[chats_store] Failed to read %s: %s", self._path, exc)
        return []

    def read(self) -> List[ChatMeta]:
        """读取 chats.json，文件不存在时返回空列表（不自动初始化）。"""
        with self._lock:
            return self._read_unlocked()

    def _write_unlocked(self, chats: List[ChatMeta]) -> None:
        """原子写入（不加锁，调用方负责持锁）。"""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "version": self.SCHEMA_VERSION,
            "chats": [c.to_dict() for c in chats],
        }
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.error("[chats_store] Write failed for %s: %s", self._path, exc)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def write(self, chats: List[ChatMeta]) -> None:
        """原子写入 chats.json（tmpfile + os.replace）。"""
        with self._lock:
            self._write_unlocked(chats)

    def read_modify_write(self, modifier) -> None:
        """在持锁状态下完成 read → modify → write，保证原子性。

        modifier(chats: List[ChatMeta]) -> bool | None
          - 返回 False 表示无需写入（只读查询或幂等跳过）
          - 返回 True 或 None 均触发写入
        用于 append_session_history 等 read-then-write 场景。
        """
        with self._lock:
            chats = self._read_unlocked()
            need_write = modifier(chats)
            if need_write is not False:
                self._write_unlocked(chats)

    def read_or_init_default(self, agent_id: str, user_id: str) -> List[ChatMeta]:
        """读取或初始化：文件不存在时写入一条 legacy 兜底会话（chatId=''）。

        chatId='' 是专为旧用户平滑升级设计的特殊值：
          - history_request 对 chatId='' 的请求退回旧 sessionKey 格式（无 chatId 后缀）
          - 前端已有 const defaultChat = incoming.find(c => c.chatId === '') 的识别逻辑
          - 保证旧用户首次连接新版本时，历史消息不丢失
        """
        result: List[ChatMeta] = []

        def _init_if_empty(chats: List[ChatMeta]):
            if chats:
                result.extend(chats)
                return False  # 已有数据，跳过写入
            now = _now_ms()
            legacy = ChatMeta(
                chatId="",
                title="历史会话",
                titleLocked=False,
                createdAt=now,
                updatedAt=now,
                pinned=False,
                sessionIdHistory=[],
            )
            chats.append(legacy)
            result.append(legacy)
            return True  # 写入 legacy

        try:
            self.read_modify_write(_init_if_empty)
        except OSError as exc:
            logger.warning("[chats_store] Could not init default chat: %s", exc)
            # 返回当前已读到的内容（可能为空）
        return result


# ---------------------------------------------------------------------------
# ChatManager — Chat CRUD 业务逻辑
# ---------------------------------------------------------------------------

class ChatManager:
    """Chat CRUD 层，对标 OpenClaw src/socket/service/chat-*.ts。"""

    def __init__(self, sessions_dir: str):
        self._sessions_dir = sessions_dir

    def _store(self, agent_id: str, user_id: str) -> ChatsStore:
        return ChatsStore(self._sessions_dir, agent_id, user_id)

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def list_chats(self, agent_id: str, user_id: str) -> List[ChatMeta]:
        """返回用户的全量会话列表（按 updatedAt 倒序）。不存在时自动初始化。"""
        store = self._store(agent_id, user_id)
        chats = store.read_or_init_default(agent_id, user_id)
        return sorted(chats, key=lambda c: c.updatedAt, reverse=True)

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create_chat(self, agent_id: str, user_id: str) -> ChatMeta:
        """创建新会话，prepend 到列表头部，返回新建的 ChatMeta。"""
        store = self._store(agent_id, user_id)
        now = _now_ms()
        new_chat = ChatMeta(
            chatId=str(uuid.uuid4()),
            title="新会话",
            titleLocked=False,
            createdAt=now,
            updatedAt=now,
            pinned=False,
            sessionIdHistory=[],
        )

        def _prepend(chats: List[ChatMeta]) -> None:
            chats.insert(0, new_chat)

        store.read_modify_write(_prepend)
        return new_chat

    # ------------------------------------------------------------------
    # 更新标题
    # ------------------------------------------------------------------

    def update_chat(
        self, agent_id: str, user_id: str, chat_id: str, title: str
    ) -> Optional[ChatMeta]:
        """更新会话标题，同时将 titleLocked 置为 True。返回被修改的 ChatMeta，不存在时返回 None。"""
        store = self._store(agent_id, user_id)
        target: Optional[ChatMeta] = None

        def _modifier(chats: List[ChatMeta]) -> None:
            nonlocal target
            for c in chats:
                if c.chatId == chat_id:
                    c.title = title
                    c.titleLocked = True
                    c.updatedAt = _now_ms()
                    target = c
                    break

        store.read_modify_write(_modifier)
        return target

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    def delete_chat(
        self, agent_id: str, user_id: str, chat_id: str
    ) -> Optional[ChatMeta]:
        """删除会话：移除 chats.json 条目 + 清理 sessions.json 中该 chatId 的 sessionKey。
        SQLite 数据保留（历史可查）。返回被删除的 ChatMeta，不存在时返回 None。
        """
        store = self._store(agent_id, user_id)
        target: Optional[ChatMeta] = None

        def _modifier(chats: List[ChatMeta]) -> None:
            nonlocal target
            for i, c in enumerate(chats):
                if c.chatId == chat_id:
                    target = c
                    del chats[i]
                    break

        store.read_modify_write(_modifier)
        if target is None:
            return None
        # 清理 sessions.json 中含该 chatId 的 sessionKey（key 末段为 :<chatId>）
        if chat_id:
            self._cleanup_sessions_json(chat_id)
        return target

    def _cleanup_sessions_json(self, chat_id: str) -> None:
        """从 sessions.json 移除所有 key 末段为 :<chat_id> 的条目。"""
        sessions_path = os.path.join(self._sessions_dir, "sessions.json")
        suffix = f":{chat_id}"
        try:
            with open(sessions_path, "r", encoding="utf-8") as f:
                store = json.load(f)
            if not isinstance(store, dict):
                return
            keys_to_remove = [k for k in store if k.endswith(suffix)]
            if not keys_to_remove:
                return
            for k in keys_to_remove:
                del store[k]
            tmp = sessions_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, sessions_path)
            logger.info(
                "[chat_manager] Cleaned %d sessionKey(s) for chatId=%s",
                len(keys_to_remove), chat_id,
            )
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[chat_manager] _cleanup_sessions_json failed for chatId=%s: %s",
                chat_id, exc,
            )

    # ------------------------------------------------------------------
    # sessionIdHistory 追加（跨 Reset 历史完整性的核心方法）
    # ------------------------------------------------------------------

    def append_session_history(
        self,
        agent_id: str,
        user_id: str,
        chat_id: str,
        old_session_id: str,
    ) -> bool:
        """幂等追加旧 sessionId 到 chats.json 中对应会话的 sessionIdHistory。

        调用场景：
          1. 超时自动 reset（idle/daily）：inbound 检测到 session_id 变化后调用
          2. 用户主动 clearContext（P2）：reset_session() 后调用
          3. ensureSessionInHistory 兜底：拉历史时把当前 sessionId 写入（如不存在）

        已存在则跳过（幂等）。返回 True 表示实际写入了，False 表示已存在或未找到目标 chat。
        使用 read_modify_write 保证 read→modify→write 的原子性，避免并发竞态。
        """
        if not old_session_id:
            return False
        store = self._store(agent_id, user_id)
        written = False

        def _modifier(chats: List[ChatMeta]):
            nonlocal written
            target = next((c for c in chats if c.chatId == chat_id), None)
            if target is None and chat_id == "":
                now = _now_ms()
                target = ChatMeta(
                    chatId="",
                    title="历史会话",
                    titleLocked=False,
                    createdAt=now,
                    updatedAt=now,
                    pinned=False,
                    sessionIdHistory=[],
                )
                chats.append(target)
            if target is None:
                logger.debug(
                    "[chat_manager] append_session_history: chatId=%s not found "
                    "for user=%s agent=%s",
                    chat_id, user_id, agent_id,
                )
                return False  # 无需写入
            if old_session_id in target.sessionIdHistory:
                return False  # 已存在，幂等跳过，无需写入
            target.sessionIdHistory.append(old_session_id)
            if len(target.sessionIdHistory) > MAX_SESSION_ID_HISTORY:
                target.sessionIdHistory = target.sessionIdHistory[-MAX_SESSION_ID_HISTORY:]
            target.updatedAt = _now_ms()
            written = True
            logger.info(
                "[chat_manager] Appended sessionId=%s to chatId=%s (user=%s agent=%s) "
                "history_len=%d",
                old_session_id, chat_id, user_id, agent_id, len(target.sessionIdHistory),
            )
            return True  # 需要写入

        store.read_modify_write(_modifier)
        return written

    def get_session_id_history(
        self,
        agent_id: str,
        user_id: str,
        chat_id: str,
    ) -> List[str]:
        """返回指定会话的 sessionIdHistory 列表，不存在时返回空列表。"""
        store = self._store(agent_id, user_id)
        chats = store.read_or_init_default(agent_id, user_id)
        for c in chats:
            if c.chatId == chat_id:
                return list(c.sessionIdHistory)
        return []

    def touch_chat(
        self,
        agent_id: str,
        user_id: str,
        chat_id: str,
    ) -> Optional[ChatMeta]:
        """仅刷新会话 updatedAt，不改标题等其他字段。"""
        store = self._store(agent_id, user_id)
        target: Optional[ChatMeta] = None

        def _modifier(chats: List[ChatMeta]):
            nonlocal target
            for c in chats:
                if c.chatId == chat_id:
                    c.updatedAt = _now_ms()
                    target = c
                    return True
            if chat_id == "":
                now = _now_ms()
                legacy = ChatMeta(
                    chatId="",
                    title="历史会话",
                    titleLocked=False,
                    createdAt=now,
                    updatedAt=now,
                    pinned=False,
                    sessionIdHistory=[],
                )
                chats.append(legacy)
                target = legacy
                return True
            return False

        store.read_modify_write(_modifier)
        return target
