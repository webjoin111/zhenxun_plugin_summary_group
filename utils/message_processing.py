import asyncio
import os
from pathlib import Path
import re
from typing import Any

import aiofiles
from nonebot.adapters.onebot.v11 import Bot

from zhenxun.configs.path_config import TEMP_PATH
from zhenxun.services.log import logger
from zhenxun.utils.platform import PlatformUtils
from zhenxun.utils.utils import get_user_avatar

from .. import base_config
from ..config import summary_config
from .core import ErrorCode, MessageFetchException, MessageProcessException, with_retry

try:
    from zhenxun.models.chat_history import ChatHistory
except ImportError:
    ChatHistory = None
    logger.warning("无法导入 ChatHistory 模型，数据库历史记录功能不可用。")


async def get_group_messages(
    bot: Bot, group_id: int, count: int, use_db: bool = False, target_user_ids: set[str] | None = None
) -> tuple[list[dict], dict[str, str]]:
    """获取群聊消息，支持从数据库或API获取，可选用户过滤和消息处理"""

    group_id_str = str(group_id)

    raw_messages = []

    if use_db and ChatHistory:
        logger.debug(f"尝试从数据库获取群 {group_id} 的最近 {count} 条聊天记录", command="DB历史")
        try:
            db_messages = (
                await ChatHistory.filter(group_id=group_id_str).order_by("-create_time").limit(count).all()
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
                        "sender": {"user_id": int(msg.user_id) if msg.user_id.isdigit() else 0},
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
            ex = MessageFetchException(
                message=f"数据库历史记录获取失败: {e!s}",
                code=ErrorCode.DB_QUERY_ERROR,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e
    else:
        if use_db and not ChatHistory:
            logger.warning("配置了使用数据库历史但 ChatHistory 模型导入失败，回退到 API 获取。")

        logger.debug(f"通过 API 获取群 {group_id} 的最近 {count} 条聊天记录", command="API历史")
        try:

            async def fetch():
                response = await bot.get_group_msg_history(group_id=group_id, count=count)
                raw_messages = response.get("messages", [])
                logger.debug(
                    f"从群 {group_id} API 获取了 {len(raw_messages)} 条原始消息",
                    command="API历史",
                    group_id=group_id,
                )
                return raw_messages

            max_retries = summary_config.get_max_retries()
            retry_delay = summary_config.get_retry_delay()
            raw_messages = await with_retry(
                fetch,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
        except Exception as e:
            logger.error(
                f"通过 API 获取群 {group_id} 的原始消息历史失败 (with_retry后): {e}",
                command="API历史",
                group_id=group_id,
                e=e,
            )
            ex = MessageFetchException(
                message=f"API 消息历史获取失败: {e!s}",
                code=ErrorCode.MESSAGE_FETCH_FAILED,
                details={"error": str(e), "group_id": group_id, "count": count},
                cause=e,
            )
            raise ex from e

    filtered_messages = raw_messages
    if target_user_ids:
        filtered_messages = [msg for msg in raw_messages if str(msg.get("user_id")) in target_user_ids]
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
        processed_data, user_info_cache = await process_message(filtered_messages, bot, group_id)
        return processed_data, user_info_cache
    except Exception as e:
        logger.error(
            f"处理群 {group_id} 消息失败: {e}",
            command="get_group_messages",
            group_id=group_id,
            e=e,
        )
        ex = MessageFetchException(
            message=f"消息处理失败: {e!s}",
            code=ErrorCode.MESSAGE_PROCESS_FAILED,
            details={"error": str(e), "group_id": group_id, "count": count},
            cause=e,
        )
        raise ex from e


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

            async def safe_get_user_with_retry(bot, user_id_str, group_id_str):
                """带重试机制的安全用户信息获取"""
                import uuid

                task_id = str(uuid.uuid4())[:8]

                max_retries = summary_config.get_user_info_max_retries()
                retry_delay = summary_config.get_user_info_retry_delay()
                user_info_timeout = summary_config.get_user_info_timeout()

                for attempt in range(max_retries + 1):
                    try:
                        logger.debug(
                            f"[{task_id}] 获取用户 {user_id_str} 信息 "
                            f"(尝试 {attempt + 1}/{max_retries + 1})，超时: {user_info_timeout}s"
                        )

                        result = await asyncio.wait_for(
                            PlatformUtils.get_user(bot, user_id_str, group_id_str), timeout=user_info_timeout
                        )

                        if result:
                            display_name = result.card or result.name or f"用户_{user_id_str[-4:]}"
                            logger.debug(f"[{task_id}] 成功获取用户 {user_id_str} 信息: {display_name}")
                            return result
                        else:
                            logger.debug(
                                f"[{task_id}] 用户 {user_id_str} 信息获取返回空结果 (尝试 {attempt + 1})"
                            )

                    except asyncio.TimeoutError:
                        logger.warning(
                            f"[{task_id}] 获取用户 {user_id_str} 信息超时 "
                            f"(尝试 {attempt + 1}/{max_retries + 1}, {user_info_timeout}s)",
                            group_id=group_id,
                        )
                    except Exception as e:
                        logger.warning(
                            f"[{task_id}] 获取用户 {user_id_str} 信息失败 "
                            f"(尝试 {attempt + 1}/{max_retries + 1}): {type(e).__name__}: {e}",
                            group_id=group_id,
                        )

                    if attempt < max_retries:
                        logger.debug(f"[{task_id}] 用户 {user_id_str} 信息获取失败，{retry_delay}s后重试")
                        await asyncio.sleep(retry_delay)

                logger.debug(f"[{task_id}] 用户 {user_id_str} 信息获取最终失败，已重试 {max_retries} 次")
                return None

            concurrent_limit = summary_config.get_concurrent_user_fetch_limit()
            semaphore = asyncio.Semaphore(concurrent_limit)

            async def limited_safe_get_user(bot, user_id_str, group_id_str):
                async with semaphore:
                    return await safe_get_user_with_retry(bot, user_id_str, group_id_str)

            user_id_list = list(user_ids_to_fetch)
            logger.debug(f"准备为 {len(user_id_list)} 个用户创建获取任务: {sorted(user_id_list)}")

            unique_user_ids = list(set(user_id_list))
            if len(unique_user_ids) != len(user_id_list):
                logger.warning(f"发现重复的用户ID！原始: {len(user_id_list)}, 去重后: {len(unique_user_ids)}")
                user_id_list = unique_user_ids

            tasks = []
            for i, user_id_str in enumerate(user_id_list):
                logger.debug(f"创建任务 {i + 1}/{len(user_id_list)} for 用户 {user_id_str}")
                task = limited_safe_get_user(bot, user_id_str, group_id_str)
                tasks.append(task)

            logger.debug(f"实际创建了 {len(tasks)} 个任务，用户列表: {sorted(user_id_list)}")

            message_timeout = summary_config.get_message_process_timeout()
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=message_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"批量获取用户信息整体超时 ({message_timeout}s)，将使用默认用户名",
                    group_id=group_id,
                )
                results = [None] * len(user_id_list)

            for user_id_str, result in zip(user_id_list, results):
                fallback_name = f"用户_{user_id_str[-4:]}"
                if isinstance(result, Exception):
                    logger.debug(
                        f"并发获取用户 {user_id_str} 信息失败: {result}. 使用默认值",
                        group_id=group_id,
                        e=result,
                    )
                    user_info_cache[user_id_str] = fallback_name
                elif result:
                    user_data = result
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
        ex = MessageProcessException(
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


async def check_message_count(messages: list[dict[str, Any]], min_count: int | None = None) -> bool:
    try:
        if not messages:
            return False

        if min_count is None:
            min_len = base_config.get("SUMMARY_MIN_LENGTH")
            max_len = base_config.get("SUMMARY_MAX_LENGTH")

            if min_len is None or max_len is None:
                logger.warning("无法从配置获取 SUMMARY_MIN/MAX_LENGTH，使用默认检查值 (50)")
                min_count = 50
            else:
                try:
                    min_count = min(int(min_len), int(max_len))
                except (ValueError, TypeError):
                    logger.warning("配置 SUMMARY_MIN/MAX_LENGTH 值无效，使用默认检查值 (50)")
                    min_count = 50

        return len(messages) >= min_count
    except Exception as e:
        logger.error(f"检查消息数量时出错: {e}", command="check_message_count", e=e)
        return False


def check_cooldown(user_id: int | str) -> bool:
    from .. import summary_cd_limiter

    try:
        user_id_str = str(user_id)
        is_ready = summary_cd_limiter.check(user_id_str)
        if not is_ready:
            left = summary_cd_limiter.left_time(user_id_str)
            logger.debug(
                f"用户 {user_id_str} 冷却检查：否 (剩余 {left:.1f}s)",
                command="check_cooldown",
            )

        return is_ready
    except Exception as e:
        logger.error(f"检查冷却时间时出错: {e}", command="check_cooldown", session=user_id, e=e)

        return True


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

    async def enhance_summary_with_avatars(self, summary_text: str, user_info_cache: dict[str, str]) -> str:
        """在总结文本中为用户名添加头像"""
        if not base_config.get("ENABLE_AVATAR_ENHANCEMENT", False):
            logger.debug("头像增强已禁用，跳过头像增强")
            return summary_text

        try:
            name_to_id = {name: uid for uid, name in user_info_cache.items()}

            mentioned_users = self._find_mentioned_users(summary_text, name_to_id)

            if not mentioned_users:
                logger.debug("总结中未发现提及的用户，跳过头像增强")
                return summary_text

            max_avatars = summary_config.get_avatar_max_count()
            if len(mentioned_users) > max_avatars:
                logger.info(
                    f"提及用户数量 ({len(mentioned_users)}) 超过建议值 ({max_avatars})，继续处理所有用户"
                )

            await self._fetch_avatars_to_files(mentioned_users)

            enhanced_text = await self._insert_avatars_in_text(summary_text, mentioned_users)

            if len(enhanced_text) > 50000:
                logger.warning(f"增强后的HTML过大 ({len(enhanced_text)} 字符)，返回原始文本")
                return summary_text

            logger.debug(f"头像增强完成，处理了 {len(mentioned_users)} 个用户")
            return enhanced_text

        except Exception as e:
            logger.warning(f"头像增强失败，返回原始文本: {e}")
            return summary_text

    def _find_mentioned_users(self, text: str, name_to_id: dict[str, str]) -> dict[str, str]:
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
        # 只过滤单个特殊字符或者空格的名称
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

    async def _fetch_avatar_with_retry(self, user_id: str, max_retries: int = 3) -> str | None:
        """带重试机制的头像获取并保存到本地文件 (增加强制同步)"""
        avatar_file = self.avatar_dir / f"{user_id}.jpg"

        if avatar_file.exists():
            if self._is_avatar_expired(avatar_file):
                logger.debug(f"用户 {user_id} 头像文件已过期，将重新获取: {avatar_file}")
                try:
                    avatar_file.unlink()
                except Exception as e:
                    logger.warning(f"删除过期头像文件失败: {e}")
            else:
                logger.debug(f"用户 {user_id} 头像文件已存在且未过期: {avatar_file}")
                return str(avatar_file)

        for attempt in range(max_retries + 1):
            try:
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

                    logger.debug(
                        f"成功保存并同步了用户 {user_id} 的头像到 {avatar_file} (尝试 {attempt + 1})"
                    )
                    return str(avatar_file)
                else:
                    logger.debug(f"用户 {user_id} 头像获取失败 (尝试 {attempt + 1})")

            except Exception as e:
                logger.debug(f"获取用户 {user_id} 头像时出错 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries:
                retry_delay = 0.5 * (2**attempt)
                logger.debug(f"用户 {user_id} 头像获取失败，{retry_delay}秒后重试")
                await asyncio.sleep(retry_delay)

        logger.debug(f"用户 {user_id} 头像获取最终失败，已重试 {max_retries} 次")
        return None

    async def _fetch_avatars_to_files(self, mentioned_users: dict[str, str]):
        """并发批量获取用户头像并保存到本地文件"""
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
                    logger.debug(f"用户 {user_id} 缓存的文件不存在，需要重新获取: {avatar_path}")
                else:
                    if self._is_avatar_expired(avatar_path):
                        need_fetch = True
                        logger.debug(f"用户 {user_id} 头像文件已过期，需要重新获取: {avatar_path}")
                    else:
                        logger.debug(f"用户 {user_id} 头像文件已存在且未过期: {avatar_path}")

            if need_fetch:
                users_to_fetch[user_id] = user_name

        if not users_to_fetch:
            logger.debug("所有用户头像都已缓存且文件存在，跳过获取")
            return

        logger.debug(f"开始并发获取 {len(users_to_fetch)} 个用户的头像: {list(users_to_fetch.keys())}")

        max_concurrent = min(5, len(users_to_fetch))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(user_id: str):
            async with semaphore:
                try:
                    return user_id, await self._fetch_avatar_with_retry(user_id, max_retries=2)
                except Exception as e:
                    logger.warning(f"获取用户 {user_id} 头像失败: {e}")
                    return user_id, None

        tasks = [fetch_with_semaphore(user_id) for user_id in users_to_fetch.keys()]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"头像获取任务异常: {result}")
                    continue

                if result:
                    user_id, avatar_path = result
                    self.avatar_cache[user_id] = avatar_path
                    if avatar_path:
                        logger.debug(f"成功获取并缓存用户 {user_id} 的头像: {avatar_path}")
                    else:
                        logger.debug(f"用户 {user_id} 头像获取失败，缓存为 None")

        except Exception as e:
            logger.error(f"头像批量获取出错: {e}")

        for user_id in mentioned_users.keys():
            if user_id not in self.avatar_cache:
                avatar_file = self.avatar_dir / f"{user_id}.jpg"
                if avatar_file.exists():
                    self.avatar_cache[user_id] = str(avatar_file)
                    logger.debug(f"发现已存在的头像文件并缓存: {user_id} -> {avatar_file}")
                else:
                    self.avatar_cache[user_id] = None
                    logger.debug(f"用户 {user_id} 头像文件不存在，缓存为 None")

        mentioned_user_avatars = {
            user_id: self.avatar_cache.get(user_id) for user_id in mentioned_users.keys()
        }
        successful_count = len([v for v in mentioned_user_avatars.values() if v is not None])
        failed_count = len([v for v in mentioned_user_avatars.values() if v is None])

        logger.debug(
            f"头像获取完成，本次提及的 {len(mentioned_users)} 个用户中："
            f"成功 {successful_count} 个，失败 {failed_count} 个。"
            f"总缓存: {len([v for v in self.avatar_cache.values() if v is not None])} 个头像"
        )

    async def _insert_avatars_in_text(self, text: str, mentioned_users: dict[str, str]) -> str:
        """在文本中插入头像"""
        enhanced_text = text

        for user_id, user_name in mentioned_users.items():
            try:
                if self._should_skip_username(user_name):
                    logger.debug(f"跳过头像替换，特殊字符用户名: {user_name} (ID: {user_id})")
                    continue

                # 优先处理 代码块包裹的用户名
                code_pattern = rf"`{re.escape(user_name)}`"
                if user_id in self.avatar_cache and self.avatar_cache[user_id] is not None:
                    avatar_html = self._create_user_with_avatar_html(user_name, self.avatar_cache[user_id])
                    enhanced_text = re.sub(code_pattern, f"{avatar_html}`{user_name}`", enhanced_text)
                else:
                    user_html = self._create_user_without_avatar_html(user_name)
                    enhanced_text = re.sub(code_pattern, f"{user_html}`{user_name}`", enhanced_text)

                # 再处理 非代码块包裹的用户名
                pattern = rf"(?<!`)\\b{re.escape(user_name)}\\b(?!`)"
                if user_id in self.avatar_cache and self.avatar_cache[user_id] is not None:
                    avatar_html = self._create_user_with_avatar_html(user_name, self.avatar_cache[user_id])
                    enhanced_text = re.sub(pattern, avatar_html, enhanced_text)
                else:
                    user_html = self._create_user_without_avatar_html(user_name)
                    enhanced_text = re.sub(pattern, user_html, enhanced_text)
            except Exception as e:
                logger.warning(f"处理用户 {user_name} 时出错: {e}")
                continue

        return enhanced_text

    def _create_user_with_avatar_html(self, user_name: str, avatar_file_path: str) -> str:
        """创建带头像的用户名HTML"""
        escaped_name = user_name.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        abs_path = Path(avatar_file_path).resolve()
        file_url = abs_path.as_uri()
        return (
            f'<span class="user-mention">'
            f'<img src="{file_url}" alt="{escaped_name}" class="user-avatar" />'
            f'<span class="user-name">{escaped_name}</span>'
            f"</span>"
        )

    def _create_user_without_avatar_html(self, user_name: str) -> str:
        """创建无头像的用户名HTML"""
        escaped_name = user_name.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<span class="user-name">{escaped_name}</span>'

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

            logger.debug(f"清理了 {deleted_count} 个过期头像文件 (保留 {keep_recent_days} 天)")

        except Exception as e:
            logger.warning(f"清理头像文件时出错: {e}")


avatar_enhancer = AvatarEnhancer()
