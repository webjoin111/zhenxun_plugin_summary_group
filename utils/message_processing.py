import asyncio
import os
from pathlib import Path
import re
import time
from typing import Any

import aiofiles
from nonebot.adapters.onebot.v11 import Bot

from zhenxun.configs.path_config import TEMP_PATH
from zhenxun.services.log import logger
from zhenxun.utils.decorator.retry import Retry
from zhenxun.utils.platform import PlatformUtils
from zhenxun.utils.utils import get_user_avatar

from .. import base_config
from ..config import summary_config
from .core import ErrorCode, SummaryException

_message_cache: dict[str, tuple[tuple[list, dict], float]] = {}


try:
    from zhenxun.models.chat_history import ChatHistory
except ImportError:
    ChatHistory = None
    logger.warning("无法导入 ChatHistory 模型，数据库历史记录功能不可用。")


async def get_group_messages(
    bot: Bot,
    group_id: int,
    count: int,
    use_db: bool = False,
    target_user_ids: set[str] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """获取群聊消息，支持从数据库或API获取，可选用户过滤和消息处理"""

    cache_ttl = base_config.get("MESSAGE_CACHE_TTL_SECONDS", 300)

    if cache_ttl > 0 and not target_user_ids:
        group_id_str = str(group_id)
        cache_key = f"{group_id_str}:{count}"
        current_time = time.time()

        if cache_key in _message_cache:
            cached_data, timestamp = _message_cache[cache_key]
            if current_time - timestamp < cache_ttl:
                logger.debug(
                    f"命中消息缓存 (群: {group_id}, 数量: {count})，"
                    f"剩余有效期: {cache_ttl - (current_time - timestamp):.1f}s"
                )
                import copy

                return copy.deepcopy(cached_data)

    group_id_str = str(group_id)

    raw_messages = []

    if use_db and ChatHistory:
        logger.debug(
            f"尝试从数据库获取群 {group_id} 的最近 {count} 条聊天记录", command="DB历史"
        )
        try:
            db_messages = (
                await ChatHistory.filter(group_id=group_id_str)
                .order_by("-create_time")
                .limit(count)
                .all()
            )

            if not db_messages:
                logger.warning(
                    f"数据库中未找到群 {group_id} 的聊天记录",
                    command="DB历史",
                    group_id=group_id,
                )
                return [], {}

            formatted_messages = []
            for msg in reversed(db_messages):
                formatted_messages.append(
                    {
                        "message_id": msg.id,
                        "user_id": int(msg.user_id) if msg.user_id.isdigit() else 0,
                        "time": int(msg.create_time.timestamp()),
                        "message_type": "group",
                        "message": [
                            {
                                "type": "text",
                                "data": {"text": msg.plain_text or ""},
                            }
                        ],
                        "raw_message": msg.plain_text or "",
                        "sender": {
                            "user_id": int(msg.user_id) if msg.user_id.isdigit() else 0
                        },
                    }
                )
            logger.debug(
                f"从数据库成功获取并格式化 {len(formatted_messages)} 条消息 (使用 plain_text)",
                command="DB历史",
                group_id=group_id,
            )
            logger.warning(
                "使用数据库历史记录时，图片、@ 等非文本信息可能无法正确处理。",
                command="DB历史",
            )
            raw_messages = formatted_messages
        except Exception as e:
            logger.error(
                f"从数据库获取群 {group_id} 历史记录失败: {e}",
                command="DB历史",
                group_id=group_id,
                e=e,
            )
            ex = SummaryException(
                message=f"数据库历史记录获取失败: {e!s}",
                code=ErrorCode.DB_QUERY_ERROR,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e
    else:
        if use_db and not ChatHistory:
            logger.warning(
                "配置了使用数据库历史但 ChatHistory 模型导入失败，回退到 API 获取。"
            )

        logger.debug(
            f"通过 API 获取群 {group_id} 的最近 {count} 条聊天记录", command="API历史"
        )
        try:

            @Retry.simple(
                stop_max_attempt=summary_config.get_max_retries(),
                wait_fixed_seconds=summary_config.get_retry_delay(),
            )
            async def fetch_with_retry():
                response = await bot.get_group_msg_history(
                    group_id=group_id, count=count
                )
                raw_messages = response.get("messages", [])
                logger.debug(
                    f"从群 {group_id} API 获取了 {len(raw_messages)} 条原始消息",
                    command="API历史",
                    group_id=group_id,
                )
                return raw_messages

            raw_messages = await fetch_with_retry()
        except Exception as e:
            logger.error(
                f"通过 API 获取群 {group_id} 的原始消息历史失败 (所有重试后): {e}",
                command="API历史",
                group_id=group_id,
                e=e,
            )
            ex = SummaryException(
                message=f"API 消息历史获取失败: {e!s}",
                code=ErrorCode.MESSAGE_FETCH_FAILED,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e

    filtered_messages = raw_messages
    if target_user_ids:
        filtered_messages = [
            msg for msg in raw_messages if str(msg.get("user_id")) in target_user_ids
        ]
        logger.debug(
            f"过滤后剩余 {len(filtered_messages)} 条消息 (来自用户: {target_user_ids})",
            command="get_group_messages",
            group_id=group_id,
        )

    if not filtered_messages:
        logger.warning(
            f"群 {group_id} 未返回任何有效消息{'（指定用户）' if target_user_ids else ''}",
            command="get_group_messages",
            group_id=group_id,
        )
        return [], {}

    try:
        processed_data, user_info_cache = await process_message(
            filtered_messages, bot, group_id
        )

        if cache_ttl > 0 and not target_user_ids:
            _message_cache[cache_key] = (
                (processed_data, user_info_cache),
                time.time(),
            )
            logger.debug(f"消息已存入缓存 (群: {group_id}, 数量: {count})")

        return processed_data, user_info_cache
    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息失败: {e}",
            command="get_group_messages",
            group_id=group_id,
            e=e,
        )
        ex = SummaryException(
            message=f"消息处理失败: {e!s}",
            code=ErrorCode.MESSAGE_PROCESS_FAILED,
            details={"error": str(e), "group_id": group_id, "count": count},
            cause=e,
        )
        raise ex from e


@Retry.api(
    stop_max_attempt=summary_config.get_user_info_max_retries() + 1,
    wait_exp_multiplier=summary_config.get_user_info_retry_delay(),
    log_name="获取用户信息",
)
async def _fetch_user_info_with_retry(bot: Bot, user_id_str: str, group_id_str: str):
    """带重试机制的安全用户信息获取"""
    user_info_timeout = summary_config.get_user_info_timeout()
    result = await asyncio.wait_for(
        PlatformUtils.get_user(bot, user_id_str, group_id_str),
        timeout=user_info_timeout,
    )
    return result


async def process_message(
    messages: list, bot: Bot, group_id: int
) -> tuple[list[dict[str, str]], dict[str, str]]:
    logger.debug(
        f"开始处理群 {group_id} 的 {len(messages)} 条原始消息",
        command="消息处理",
        group_id=group_id,
    )
    try:
        if not messages:
            return [], {}

        exclude_bot = base_config.get("EXCLUDE_BOT_MESSAGES", False)
        bot_self_id = bot.self_id

        user_ids_to_fetch: set[str] = set()
        for msg in messages:
            sender_id = msg.get("user_id")
            if sender_id:
                user_ids_to_fetch.add(str(sender_id))
            raw_segments = msg.get("message", [])
            for segment in raw_segments:
                if isinstance(segment, dict):
                    seg_type = segment.get("type")
                    seg_data = segment.get("data", {})
                    if seg_type == "at" and "qq" in seg_data:
                        user_ids_to_fetch.add(str(seg_data["qq"]))

        user_info_cache: dict[str, str] = {}
        group_id_str = str(group_id)

        if user_ids_to_fetch:
            logger.debug(
                f"需要获取 {len(user_ids_to_fetch)} 个用户的信息: {sorted(user_ids_to_fetch)}",
                group_id=group_id,
            )

            concurrent_limit = summary_config.get_concurrent_user_fetch_limit()
            semaphore = asyncio.Semaphore(concurrent_limit)

            async def get_user_with_sem(user_id: str):
                async with semaphore:
                    try:
                        return user_id, await _fetch_user_info_with_retry(
                            bot, user_id, group_id_str
                        )
                    except Exception as e:
                        logger.warning(
                            f"获取用户 {user_id} 信息最终失败: {e}", group_id=group_id
                        )
                        return user_id, None

            tasks = [get_user_with_sem(uid) for uid in user_ids_to_fetch]
            message_timeout = summary_config.get_message_process_timeout()

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks),
                    timeout=message_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"批量获取用户信息整体超时 ({message_timeout}s)，将使用默认用户名",
                    group_id=group_id,
                )
                results = []

            for res in results:
                if res:
                    user_id_str, user_data = res
                    fallback_name = f"用户_{user_id_str[-4:]}"
                    if user_data:
                        sender_name = user_data.card or user_data.name or fallback_name
                        user_info_cache[user_id_str] = sender_name
                    else:
                        user_info_cache[user_id_str] = fallback_name

            logger.debug(
                f"用户信息并发获取完成，缓存了 {len(user_info_cache)} 个用户信息",
                group_id=group_id,
            )

        processed_log: list[dict[str, str]] = []
        for msg in messages:
            user_id = msg.get("user_id")
            if not user_id:
                continue

            user_id_str = str(user_id)
            if exclude_bot and user_id_str == bot_self_id:
                continue

            sender_name = user_info_cache.get(user_id_str, f"用户_{user_id_str[-4:]}")

            raw_segments = msg.get("message", [])
            text_segments: list[str] = []

            for segment in raw_segments:
                if not isinstance(segment, dict):
                    continue
                seg_type = segment.get("type")
                seg_data = segment.get("data", {})
                if seg_type == "text" and "text" in seg_data:
                    text = seg_data["text"].strip()
                    if text:
                        text_segments.append(text)
                elif seg_type == "at" and "qq" in seg_data:
                    qq = str(seg_data["qq"])
                    at_name = user_info_cache.get(qq, f"用户_{qq[-4:]}")
                    text_segments.append(f"@{at_name}")

            if text_segments:
                message_content = "".join(text_segments)
                processed_log.append({"name": sender_name, "content": message_content})

        logger.debug(
            f"消息处理完成，生成 {len(processed_log)} 条处理记录 (已应用Bot排除设置: {exclude_bot})",
            group_id=group_id,
        )
        return processed_log, user_info_cache

    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息时出错: {e}",
            command="消息处理",
            e=e,
            group_id=group_id,
        )
        ex = SummaryException(
            message=f"消息处理失败: {e!s}",
            code=ErrorCode.MESSAGE_PROCESS_FAILED,
            details={
                "error": str(e),
                "group_id": group_id,
                "message_count": len(messages) if messages else 0,
            },
            cause=e,
        )
        raise ex from e


async def check_message_count(
    messages: list[dict[str, Any]], min_count: int | None = None
) -> bool:
    try:
        if not messages:
            return False

        if min_count is None:
            min_len = base_config.get("SUMMARY_MIN_LENGTH")
            max_len = base_config.get("SUMMARY_MAX_LENGTH")

            if min_len is None or max_len is None:
                logger.warning(
                    "无法从配置获取 SUMMARY_MIN/MAX_LENGTH，使用默认检查值 (50)"
                )
                min_count = 50
            else:
                try:
                    min_count = min(int(min_len), int(max_len))
                except (ValueError, TypeError):
                    logger.warning(
                        "配置 SUMMARY_MIN/MAX_LENGTH 值无效，使用默认检查值 (50)"
                    )
                    min_count = 50

        return len(messages) >= min_count
    except Exception as e:
        logger.error(f"检查消息数量时出错: {e}", command="check_message_count", e=e)
        return False


class AvatarEnhancer:
    """头像增强器，为总结内容中的用户名添加头像"""

    def __init__(self):
        self.avatar_cache: dict[str, str | None] = {}
        self.avatar_dir = TEMP_PATH / "summary_group" / "avatar"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"头像缓存目录: {self.avatar_dir}")

        try:
            self.clear_avatar_files()
        except Exception as e:
            logger.warning(f"启动时清理过期头像文件失败: {e}")

    async def enhance_summary_with_avatars(
        self, summary_text: str, user_info_cache: dict[str, str]
    ) -> str:
        """在总结文本中为用户名添加头像或高亮"""

        try:
            name_to_id = {name: uid for uid, name in user_info_cache.items()}
            mentioned_users = self._find_mentioned_users(summary_text, name_to_id)

            if not mentioned_users:
                logger.debug("总结中未发现提及的用户，跳过增强")
                return summary_text

            use_avatars = base_config.get("ENABLE_AVATAR_ENHANCEMENT", False)
            logger.debug(f"用户名增强模式: {'头像' if use_avatars else '高亮'}")

            max_avatars = summary_config.get_avatar_max_count()
            if len(mentioned_users) > max_avatars:
                logger.info(
                    f"提及用户数量 ({len(mentioned_users)}) 超过建议值 ({max_avatars})，继续处理所有用户"
                )

            if use_avatars:
                avatar_io_tasks = await self._fetch_avatars_to_files(mentioned_users)

                if avatar_io_tasks:
                    logger.debug(f"等待 {len(avatar_io_tasks)} 个头像I/O任务完成...")
                    await asyncio.gather(*avatar_io_tasks, return_exceptions=True)
                    logger.debug("所有头像I/O任务已完成。")

            enhanced_text = await self._insert_user_markup_in_text(
                summary_text, mentioned_users
            )

            if len(enhanced_text) > 50000:
                logger.warning(
                    f"增强后的HTML过大 ({len(enhanced_text)} 字符)，返回原始文本"
                )
                return summary_text

            return enhanced_text

        except Exception as e:
            logger.warning(f"用户名增强失败，返回原始文本: {e}")
            return summary_text

    def _find_mentioned_users(
        self, text: str, name_to_id: dict[str, str]
    ) -> dict[str, str]:
        """查找文本中提及的用户"""
        mentioned = {}

        for user_name, user_id in name_to_id.items():
            pattern = rf"\b{re.escape(user_name)}\b"
            if re.search(pattern, text):
                mentioned[user_id] = user_name
                logger.debug(f"发现提及用户: {user_name} (ID: {user_id})")

        return mentioned

    def _should_skip_username(self, user_name: str) -> bool:
        """判断是否应该跳过处理该用户名"""
        if len(user_name) == 1:
            special_chars = set(".,;:!?@#$%^&*()[]{}|\\/<>-_=+`~\"' ")
            if user_name in special_chars:
                return True

        return False

    def _is_avatar_expired(self, avatar_path: Path) -> bool:
        """检查头像文件是否已过期"""
        try:
            import time

            from ..config import summary_config

            expire_days = summary_config.get_avatar_cache_expire_days()
            current_time = time.time()
            cutoff_time = current_time - (expire_days * 24 * 60 * 60)

            return avatar_path.stat().st_mtime < cutoff_time
        except Exception as e:
            logger.warning(f"检查头像文件过期状态时出错: {e}")
            return False

    @Retry.download(
        stop_max_attempt=3,
        log_name="获取用户头像",
        return_on_failure=None,
    )
    async def _fetch_avatar_with_retry(self, user_id: str) -> str | None:
        """带重试机制的头像获取并保存到本地文件 (增加强制同步)"""
        avatar_file = self.avatar_dir / f"{user_id}.jpg"

        if avatar_file.exists():
            if self._is_avatar_expired(avatar_file):
                logger.debug(
                    f"用户 {user_id} 头像文件已过期，将重新获取: {avatar_file}"
                )
                try:
                    avatar_file.unlink()
                except Exception as e:
                    logger.warning(f"删除过期头像文件失败: {e}")
            else:
                logger.debug(f"用户 {user_id} 头像文件已存在且未过期: {avatar_file}")
                return str(avatar_file)

        avatar_bytes = await get_user_avatar(user_id)
        if avatar_bytes:
            async with aiofiles.open(avatar_file, "wb") as f:
                await f.write(avatar_bytes)
                await f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError as e:
                    logger.warning(
                        f"os.fsync for {avatar_file} failed: {e}. "
                        f"The flush() should be sufficient in most cases."
                    )
            logger.debug(f"成功保存并同步了用户 {user_id} 的头像到 {avatar_file}")
            return str(avatar_file)

        logger.debug(f"用户 {user_id} 头像获取失败")
        return None

    async def _fetch_avatars_to_files(
        self, mentioned_users: dict[str, str]
    ) -> list[asyncio.Task]:
        """
        并发批量获取用户头像并保存到本地文件。
        【修改】: 此方法现在返回一个包含所有文件写入任务的列表。
        """
        users_to_fetch = {}

        for user_id, user_name in mentioned_users.items():
            need_fetch = False

            if user_id not in self.avatar_cache:
                need_fetch = True
                logger.debug(f"用户 {user_id} 不在缓存中，需要获取")
            elif self.avatar_cache[user_id] is None:
                need_fetch = True
                logger.debug(f"用户 {user_id} 缓存为 None，需要重新获取")
            else:
                avatar_path = Path(self.avatar_cache[user_id])
                if not avatar_path.exists():
                    need_fetch = True
                    logger.debug(
                        f"用户 {user_id} 缓存的文件不存在，需要重新获取: {avatar_path}"
                    )
                else:
                    if self._is_avatar_expired(avatar_path):
                        need_fetch = True
                        logger.debug(
                            f"用户 {user_id} 头像文件已过期，需要重新获取: {avatar_path}"
                        )
                    else:
                        logger.debug(
                            f"用户 {user_id} 头像文件已存在且未过期: {avatar_path}"
                        )

            if need_fetch:
                users_to_fetch[user_id] = user_name

        if not users_to_fetch:
            logger.debug("所有用户头像都已缓存且文件存在，跳过获取")
            return []

        logger.debug(
            f"开始创建 {len(users_to_fetch)} 个用户的头像获取任务: {list(users_to_fetch.keys())}"
        )

        max_concurrent = min(5, len(users_to_fetch))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_and_cache_avatar(user_id: str):
            async with semaphore:
                try:
                    avatar_path = await self._fetch_avatar_with_retry(user_id)
                    self.avatar_cache[user_id] = avatar_path
                    if avatar_path:
                        logger.debug(f"任务成功: 用户 {user_id} -> {avatar_path}")
                    else:
                        logger.debug(f"任务失败: 用户 {user_id} -> None")
                except Exception as e:
                    logger.warning(f"获取用户 {user_id} 头像的任务中发生异常: {e}")
                    self.avatar_cache[user_id] = None

        tasks = [
            asyncio.create_task(fetch_and_cache_avatar(user_id))
            for user_id in users_to_fetch.keys()
        ]

        return tasks

    async def _insert_user_markup_in_text(
        self, text: str, mentioned_users: dict[str, str]
    ) -> str:
        """在文本中插入头像或高亮标记"""
        enhanced_text = text
        use_avatars = base_config.get("ENABLE_AVATAR_ENHANCEMENT", False)

        for user_id, user_name in mentioned_users.items():
            try:
                if self._should_skip_username(user_name):
                    logger.debug(
                        f"跳过头像替换，特殊字符用户名: {user_name} (ID: {user_id})"
                    )
                    continue

                replacement_html = ""
                if use_avatars:
                    if (
                        user_id in self.avatar_cache
                        and self.avatar_cache[user_id] is not None
                    ):
                        replacement_html = self._create_user_with_avatar_html(
                            user_name, self.avatar_cache[user_id]
                        )
                    else:
                        replacement_html = self._create_user_without_avatar_html(
                            user_name
                        )
                else:
                    replacement_html = self._create_user_mention_html(user_name)

                if replacement_html:
                    pattern = rf"\b{re.escape(user_name)}\b"
                    enhanced_text = re.sub(pattern, replacement_html, enhanced_text)

            except Exception as e:
                logger.warning(f"处理用户 {user_name} 时出错: {e}")
                continue

        return enhanced_text

    def _create_user_with_avatar_html(
        self, user_name: str, avatar_file_path: str
    ) -> str:
        """创建带头像的用户名HTML"""
        escaped_name = (
            user_name.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        )
        abs_path = Path(avatar_file_path).resolve()
        file_url = abs_path.as_uri()
        return (
            f'<span class="user-mention with-avatar">'
            f'<img src="{file_url}" alt="{escaped_name}" class="user-avatar" />'
            f'<span class="user-name">{escaped_name}</span>'
            f"</span>"
        )

    def _create_user_mention_html(self, user_name: str) -> str:
        """创建仅高亮的用户名HTML"""
        escaped_name = (
            user_name.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return f'<span class="user-mention">{escaped_name}</span>'

    def _create_user_without_avatar_html(self, user_name: str) -> str:
        """创建无头像的用户名HTML"""
        escaped_name = (
            user_name.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return f'<span class="user-mention no-avatar">{escaped_name}</span>'

    def clear_cache(self):
        """清空头像缓存"""
        self.avatar_cache.clear()
        logger.debug("头像缓存已清空")

    def clear_avatar_files(self, keep_recent_days: int | None = None):
        """清理头像文件"""
        try:
            import time

            from ..config import summary_config

            if keep_recent_days is None:
                keep_recent_days = summary_config.get_avatar_cache_expire_days()

            current_time = time.time()
            cutoff_time = current_time - (keep_recent_days * 24 * 60 * 60)

            deleted_count = 0
            for avatar_file in self.avatar_dir.glob("*.jpg"):
                if avatar_file.stat().st_mtime < cutoff_time:
                    avatar_file.unlink()
                    deleted_count += 1
                    user_id = avatar_file.stem
                    if user_id in self.avatar_cache:
                        del self.avatar_cache[user_id]

            logger.debug(
                f"清理了 {deleted_count} 个过期头像文件 (保留 {keep_recent_days} 天)"
            )

        except Exception as e:
            logger.warning(f"清理头像文件时出错: {e}")


avatar_enhancer = AvatarEnhancer()
