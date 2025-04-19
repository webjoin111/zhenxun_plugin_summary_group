from abc import ABC, abstractmethod
import json
import random
from typing import Any, ClassVar

import httpx

from zhenxun.configs.config import Config
from zhenxun.services.log import logger
from zhenxun.utils.http_utils import AsyncHttpx
from zhenxun.utils.user_agent import get_user_agent

base_config = Config.get("summary_group")
if base_config is None:
    logger.error("[model.py] 无法加载 'summary_group' 配置!")
    base_config = {}

class ModelException(Exception):
    pass


class Model(ABC):
    @abstractmethod
    async def summary_history(self, messages: list[dict[str, str]], prompt: str) -> str:
        pass


class LLMModel(Model):

    MODEL_PREFIX_MAP: ClassVar[dict[str, str]] = {
        "gemini": "gemini",
        "palm": "gemini",
        "gpt": "openai",
        "text-davinci": "openai",
        "claude": "claude",
        "deepseek": "deepseek",
        "mistral": "mistral",
        "open-mistral": "mistral",
        "mixtral": "mistral",
        "llama": "openai",
        "qwen": "qwen",
        "ernie": "baidu",
        "wenxin": "baidu",
        "spark": "xunfei",
        "chatglm": "zhipu",
        "glm": "zhipu",
    }

    API_URL_FORMAT: ClassVar[dict[str, str]] = {
        "gemini": "{base}/v1beta/models/{model}:generateContent?key={key}",
        "gemini_openai": "{base}/v1beta/openai/chat/completions",
        "openai": "{base}/chat/completions",
        "claude": "{base}/v1/messages",
        "deepseek": "{base}/v1/chat/completions",
        "mistral": "{base}/v1/chat/completions",
        "zhipu": "{base}/v4/chat/completions",
        "xunfei": "{base}/v1/chat/completions",
        "baidu": "{base}/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{model}?access_token={key}",
        "qwen": "{base}/v1/chat/completions",
        "general": "{base}/v1/chat/completions",
    }

    def __init__(
        self,
        api_keys: list[str] | str | None = None,
        api_base: str = "https://generativelanguage.googleapis.com",
        summary_model: str = "gemini-1.5-flash",
        api_type: str | None = None,
        openai_compat: bool = False,
        proxy: str | None = None,
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: int = 2,
    ):

        logger.debug("[LLMModel.__init__] 正在初始化LLMModel...")
        logger.debug(
            f"[LLMModel.__init__] 收到的api_keys参数: {api_keys!r} (类型: {type(api_keys)})"
        )

        raw_keys = api_keys
        processed_keys = []

        logger.debug(f"[LLMModel.__init__] 开始处理raw_keys: {raw_keys!r}")

        if isinstance(raw_keys, str):

            logger.debug(
                "[LLMModel.__init__] raw_keys是字符串类型，尝试解析JSON或直接使用"
            )

            try:

                parsed = json.loads(raw_keys)
                if isinstance(parsed, list):

                    logger.debug("[LLMModel.__init__] 成功将字符串解析为JSON列表")

                    processed_keys = [str(k) for k in parsed if k]
                elif parsed:

                    logger.debug(
                        "[LLMModel.__init__] 成功将字符串解析为非列表JSON值，作为单个密钥处理"
                    )

                    processed_keys = [str(parsed)]
                else:

                    logger.debug("[LLMModel.__init__] 解析得到空JSON值")

                    processed_keys = []
            except json.JSONDecodeError:

                logger.debug(
                    "[LLMModel.__init__] 字符串不是有效的JSON格式，如果非空则直接作为单个密钥使用"
                )

                processed_keys = [raw_keys] if raw_keys else []
            except Exception as e:
                logger.error(
                    f"[LLMModel.__init__] 处理字符串API密钥时发生意外错误: {e}",
                )
                processed_keys = []

        elif isinstance(raw_keys, list):

            logger.debug("[LLMModel.__init__] raw_keys是列表类型，处理列表元素")

            processed_keys = [str(k) for k in raw_keys if k]
        elif raw_keys is None:

            logger.debug("[LLMModel.__init__] raw_keys为None，设置为空列表")

            processed_keys = []
        else:

            logger.warning(
                f"[LLMModel.__init__] raw_keys的类型未预期: {type(raw_keys)}，设置为空列表"
            )

            processed_keys = []

        self.api_keys = processed_keys

        logger.debug(
            f"[LLMModel.__init__] 最终的self.api_keys赋值: {self.api_keys!r} "
            f"(类型: {type(self.api_keys)}, 数量: {len(self.api_keys)})"
        )

        self.api_base = api_base
        self.summary_model = summary_model
        self.openai_compat = openai_compat
        self.proxy = proxy
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.current_key_index = 0
        self.key_failure_count = {i: 0 for i in range(len(self.api_keys))}
        self.api_type = self._determine_api_type(api_type, summary_model)

        logger.debug(f"[LLMModel.__init__] 确定的api_type: {self.api_type}")

        if self.openai_compat and self.api_type == "gemini":
            self.api_type = "gemini_openai"

            logger.debug(
                f"[LLMModel.__init__] 启用OpenAI兼容模式，覆盖api_type为: {self.api_type}"
            )

        if not self.api_keys:

            logger.warning(
                "[LLMModel.__init__] 初始化完成但没有有效的API密钥", command="LLMModel"
            )

    def _determine_api_type(self, explicit_type: str | None, model_name: str) -> str:
        if explicit_type:
            logger.debug(
                f"[LLMModel._determine_api_type] 使用显式指定的API类型: {explicit_type}",
                command="LLMModel",
            )
            return explicit_type.lower()

        model_name_lower = model_name.lower()
        for prefix, api_type in self.MODEL_PREFIX_MAP.items():
            if model_name_lower.startswith(prefix):
                logger.debug(
                    f"[LLMModel._determine_api_type] 根据模型前缀 '{prefix}' 检测到API类型 '{api_type}'",
                    command="LLMModel",
                )
                return api_type

        default_type = "general"
        logger.debug(
            f"[LLMModel._determine_api_type] 无法从模型名称 '{model_name}' 确定API类型，使用默认值 '{default_type}'",
            command="LLMModel",
        )
        return default_type

    async def summary_history(self, messages: list[dict[str, str]], prompt: str) -> str:

        logger.debug("[LLMModel.summary_history] 方法被调用")
        logger.debug(
            f"[LLMModel.summary_history] 检查self.api_keys: {self.api_keys!r} (数量: {len(self.api_keys)})"
        )

        if not self.api_keys:

            logger.error(
                "[LLMModel.summary_history] 条件'not self.api_keys'为真，没有可用的API密钥，返回错误消息"
            )

            return "错误：未配置有效的 API 密钥。"

        logger.debug(
            "[LLMModel.summary_history] 条件'not self.api_keys'为假，继续执行_request_summary"
        )

        return await self._request_summary(messages, prompt)

    async def _request_summary(
        self, messages: list[dict[str, str]], prompt: str
    ) -> str:
        if not self.api_keys:
            logger.error("[LLMModel._request_summary] No API keys available.", command="LLMModel")
            raise ModelException("错误：未配置有效的 API 密钥。")

        api_key = random.choice(self.api_keys)
        logger.debug(f"Attempting API request with key starting: {api_key[:5]}...", command="LLMModel")

        try:
            url, headers, data = self._prepare_request_params(api_key, messages, prompt)
            logger.debug(f"Request URL: {url}", command="LLMModel")

            proxy_config = None
            use_proxy_config = True
            if self.proxy:
                proxy_config = {"http://": self.proxy, "https://": self.proxy}
                use_proxy_config = False
                logger.debug(f"Using specific proxy: {self.proxy}", command="LLMModel")

            response = await AsyncHttpx.post(
                url,
                json=data,
                headers=headers,
                timeout=self.timeout,
                proxy=proxy_config,
                use_proxy=use_proxy_config
            )

            logger.debug(f"Response Status Code: {response.status_code}", command="LLMModel")
            response.raise_for_status()

            result = response.json()
            response_text = self._extract_response_text(result)

            logger.debug(f"API request successful with key starting: {api_key[:5]}...", command="LLMModel")
            return response_text

        except httpx.TimeoutException as e:
            logger.warning(f"API request timed out for key {api_key[:5]}...: {e}", command="LLMModel")
            raise ModelException(f"API 请求超时: {e}") from e
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:200]
            logger.error(
                f"API request failed for key {api_key[:5]}... "
                f"with status {e.response.status_code}: {error_text}",
                command="LLMModel", e=e
            )
            raise ModelException(f"API 请求失败 (状态码 {e.response.status_code}): {error_text}") from e
        except httpx.RequestError as e:
            logger.error(f"API network request error for key {api_key[:5]}...: {e}", command="LLMModel", e=e)
            raise ModelException(f"网络请求错误: {e}") from e
        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
            logger.error(f"Error processing API response for key {api_key[:5]}...: {e}", command="LLMModel", e=e)
            raise ModelException(f"处理 API 响应失败: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during API request for key {api_key[:5]}...: {e}", command="LLMModel", exc_info=True)
            raise ModelException(f"发生意外错误: {e}") from e

    def _format_url(self, api_type: str, api_key: str) -> str:

        if api_type == "baidu":
            url_format = self.API_URL_FORMAT[api_type]

            return url_format.format(
                base=self.api_base, model=self.summary_model, key=api_key
            )
        else:
            url_format = self.API_URL_FORMAT.get(
                api_type, self.API_URL_FORMAT["general"]
            )
            return url_format.format(
                base=self.api_base, model=self.summary_model, key=api_key
            )

    def _prepare_request_params(
        self, api_key: str, messages: list[dict[str, str]], prompt: str
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = self._format_url(self.api_type, api_key)
        headers = {}
        data = {}

        # 将消息列表转换为文本格式
        message_texts = []
        for msg in messages:
            name = msg.get("name", "未知用户")
            content = msg.get("content", "")
            if name and content:
                message_texts.append(f"{name}: {content}")

        content_str = "\n".join(message_texts)

        if self.api_type == "gemini":
            headers = {"Content-Type": "application/json"}
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}"
                            }
                        ]
                    }
                ]
            }
        elif self.api_type == "gemini_openai":
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            data = {
                "model": self.summary_model,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}",
                    }
                ],
            }
        elif self.api_type == "openai":
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            data = {
                "model": self.summary_model,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}",
                    }
                ],
            }
        elif self.api_type == "claude":
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            data = {
                "model": self.summary_model,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}",
                    }
                ],
            }
        elif self.api_type == "baidu":
            headers = {"Content-Type": "application/json"}
            data = {
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}",
                    }
                ]
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            data = {
                "model": self.summary_model,
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{content_str}",
                    }
                ],
            }

        final_headers = get_user_agent()
        final_headers.update(headers)

        return url, final_headers, data

    def _extract_response_text(self, result: dict[str, Any]) -> str:
        if self.api_type == "gemini":
            try:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                logger.error(
                    f"Failed to extract text from Gemini response: {e}",
                    command="LLMModel",
                )
                return "无法解析API响应"
        elif self.api_type == "baidu":
            try:
                return result["result"]
            except KeyError as e:
                logger.error(
                    f"Failed to extract text from Baidu response: {e}",
                    command="LLMModel",
                )
                return "无法解析API响应"
        else:
            try:
                return result["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as e:
                logger.error(
                    f"Failed to extract text from response: {e}", command="LLMModel"
                )
                return "无法解析API响应"


def detect_model() -> Model:
    try:

        logger.debug("[detect_model] Starting model detection using preloaded base_config...")

        model_type = base_config.get("model_type") or "llm"

        if model_type.lower() == "llm":
            api_keys = base_config.get("SUMMARY_API_KEYS")
            api_base = base_config.get("SUMMARY_API_BASE")
            model_name = base_config.get("SUMMARY_MODEL")
            api_type = base_config.get("SUMMARY_API_TYPE")
            openai_compat = base_config.get("SUMMARY_OPENAI_COMPAT")
            proxy = base_config.get("PROXY")
            timeout = base_config.get("TIME_OUT")
            max_retries = base_config.get("MAX_RETRIES")
            retry_delay = base_config.get("RETRY_DELAY")


            return LLMModel(
                api_keys=api_keys,
                api_base=api_base or "https://generativelanguage.googleapis.com",
                summary_model=model_name or "gemini-1.5-flash",
                api_type=api_type,
                openai_compat=openai_compat or False,
                proxy=proxy,
                timeout=timeout if timeout is not None else 120,
                max_retries=max_retries if max_retries is not None else 3,
                retry_delay=retry_delay if retry_delay is not None else 2,
            )

        logger.warning(f"Unsupported model_type '{model_type}'. Falling back to default LLMModel.")
        return LLMModel()
    except Exception as e:
        logger.error(f"Model detection failed: {e}. Falling back to default LLMModel.")
        return LLMModel()
