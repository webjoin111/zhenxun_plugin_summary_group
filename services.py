from nonebot.adapters.onebot.v11 import Bot
from nonebot_plugin_alconna.uniseg import MsgTarget, UniMessage
from pydantic import BaseModel, Field

from zhenxun.services.llm import LLMException
from zhenxun.services.log import logger

from . import base_config
from .utils.core import SummaryException
from .utils.message_processing import get_group_messages
from .utils.summary_generation import messages_summary, send_summary


class SummaryParameters(BaseModel):
    """封装单次总结任务所需的所有参数"""

    bot: Bot
    target_group_id: int
    message_count: int
    style: str | None = None
    content_filter: str | None = None
    target_user_ids: set[str] | None = Field(default_factory=set)
    response_target: MsgTarget

    class Config:
        arbitrary_types_allowed = True


class SummaryService:
    """封装群聊总结的核心业务逻辑"""

    def __init__(self, params: SummaryParameters):
        self.params = params
        self.logger = logger
        self.user_info_cache: dict[str, str] = {}
        self.processed_messages: list[dict[str, str]] = []

    async def _fetch_and_process_messages(self):
        """
        私有方法：获取和处理消息。
        将原 handler 中的消息获取逻辑移到此处。
        """
        self.logger.debug(
            f"Service: 开始获取群 {self.params.target_group_id} 的原始消息: count={self.params.message_count}",
            command="总结服务",
        )
        use_db = base_config.get("USE_DB_HISTORY", False)

        self.processed_messages, self.user_info_cache = await get_group_messages(
            self.params.bot,
            self.params.target_group_id,
            self.params.message_count,
            use_db=use_db,
            target_user_ids=self.params.target_user_ids,
        )

        if not self.processed_messages:
            if self.params.target_user_ids:
                msg = f"在群聊 {self.params.target_group_id} 中未能获取到指定用户的有效聊天记录。"
            else:
                msg = f"未能获取到群聊 {self.params.target_group_id} 的聊天记录。"
            raise SummaryException(msg)

        self.logger.debug(
            f"Service: 成功获取并处理消息，得到 {len(self.processed_messages)} 条记录",
            command="总结服务",
        )

    async def _generate_summary(self) -> str:
        """
        私有方法：生成总结文本。
        """
        target_user_names = []
        if self.params.target_user_ids:
            target_user_names = [
                self.user_info_cache.get(uid, f"用户{uid[-4:]}")
                for uid in self.params.target_user_ids
            ]

        summary_content_target = MsgTarget(str(self.params.target_group_id))

        summary = await messages_summary(
            target=summary_content_target,
            messages=self.processed_messages,
            content=self.params.content_filter,
            target_user_names=target_user_names or None,
            style=self.params.style,
        )
        self.logger.debug(
            f"Service: 群 {self.params.target_group_id} 总结生成成功，长度: {len(summary)} 字符",
            command="总结服务",
        )
        return summary

    async def _send_summary(self, summary_text: str) -> bool:
        """
        私有方法：发送总结。
        """
        return await send_summary(
            self.params.bot,
            self.params.response_target,
            summary_text,
            self.user_info_cache,
        )

    async def execute(self) -> bool:
        """
        执行完整的总结流程，并集中处理所有可预见的异常。
        """
        try:
            await self._fetch_and_process_messages()
            summary_text = await self._generate_summary()
            success = await self._send_summary(summary_text)
            return success

        except SummaryException as e:
            self.logger.warning(
                f"总结服务执行失败 (业务异常): {e}",
                command="总结服务",
                e=e,
            )
            await UniMessage.text(e.user_friendly_message).send(
                self.params.response_target
            )
            return False
        except LLMException as e:
            self.logger.error(
                f"总结服务执行失败 (LLM异常): {e}",
                command="总结服务",
                e=e,
            )
            await UniMessage.text(e.user_friendly_message).send(
                self.params.response_target
            )
            return False
        except Exception as e:
            self.logger.error(
                f"总结服务执行时发生未知错误: {e}", command="总结服务", e=e
            )
            await UniMessage.text(
                "处理总结时发生了一个未知的内部错误，请联系管理员。"
            ).send(self.params.response_target)
            return False
