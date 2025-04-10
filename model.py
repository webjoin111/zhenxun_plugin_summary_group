from abc import ABC, abstractmethod
import asyncio
from typing import List, Union, Dict, Any, Optional, Tuple
import random
import httpx
import json
import re

from zhenxun.services.log import logger


from zhenxun.configs.config import Config


class Model(ABC):
    @abstractmethod
    async def summary_history(self, messages: List[Dict[str, str]], prompt: str) -> str:
        pass


class LLMModel(Model):

    MODEL_PREFIX_MAP = {
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

    API_URL_FORMAT = {
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
        api_keys: Union[List[str], str, None] = None,
        api_base: str = "https://generativelanguage.googleapis.com",
        summary_model: str = "gemini-1.5-flash",
        api_type: Optional[str] = None,
        openai_compat: bool = False,
        proxy: Optional[str] = None,
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: int = 2,
    ):

        logger.debug(f"[LLMModel.__init__] 正在初始化LLMModel...")
        logger.debug(
            f"[LLMModel.__init__] 收到的api_keys参数: {repr(api_keys)} (类型: {type(api_keys)})"
        )

        raw_keys = api_keys
        processed_keys = []

        logger.debug(f"[LLMModel.__init__] 开始处理raw_keys: {repr(raw_keys)}")

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
                    exc_info=True,
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
            f"[LLMModel.__init__] 最终的self.api_keys赋值: {repr(self.api_keys)} (类型: {type(self.api_keys)}, 数量: {len(self.api_keys)})"
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

    def _determine_api_type(self, explicit_type: Optional[str], model_name: str) -> str:
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

    async def summary_history(self, messages: List[Dict[str, str]], prompt: str) -> str:

        logger.debug(f"[LLMModel.summary_history] 方法被调用")
        logger.debug(
            f"[LLMModel.summary_history] 检查self.api_keys: {repr(self.api_keys)} (数量: {len(self.api_keys)})"
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
        self, messages: List[Dict[str, str]], prompt: str
    ) -> str:
        tried_indices = set()

        for retry in range(self.max_retries):
            if not self.api_keys:
                return "错误：无可用 API 密钥。"

            curr_index = self.current_key_index

            available_indices = [
                i for i in range(len(self.api_keys)) if i not in tried_indices
            ]
            if not available_indices:

                if retry < self.max_retries - 1:
                    logger.warning(
                        f"All API keys failed, retrying after delay ({self.retry_delay}s)...",
                        command="LLMModel",
                    )
                    await asyncio.sleep(self.retry_delay)
                    tried_indices.clear()
                    curr_index = 0
                else:
                    logger.error(
                        "All API keys failed after maximum retries.", command="LLMModel"
                    )
                    return "所有API密钥均请求失败，请检查配置或网络。"
            else:

                if curr_index not in available_indices:
                    curr_index = random.choice(available_indices)

            tried_indices.add(curr_index)
            api_key = self.api_keys[curr_index]
            logger.debug(
                f"Attempting API request with key index {curr_index} (Retry {retry+1}/{self.max_retries})",
                command="LLMModel",
            )

            try:
                url, headers, data = self._prepare_request_params(
                    api_key, messages, prompt
                )
                logger.debug(f"Request URL: {url}", command="LLMModel")
                logger.debug(f"Request Headers: {headers}", command="LLMModel")

                client_params = {}

                if self.proxy:
                    client_params["proxy"] = self.proxy
                if self.timeout:
                    client_params["timeout"] = self.timeout

                async with httpx.AsyncClient(**client_params) as client:
                    response = await client.post(url, json=data, headers=headers)

                logger.debug(
                    f"Response Status Code: {response.status_code}", command="LLMModel"
                )

                response.raise_for_status()
                result = response.json()
                response_text = self._extract_response_text(result)

                self.current_key_index = curr_index
                self.key_failure_count[curr_index] = 0
                logger.debug(
                    f"API request successful with key index {curr_index}.",
                    command="LLMModel",
                )
                return response_text

            except httpx.TimeoutException:
                logger.warning(
                    f"API request timed out for key index {curr_index}.",
                    command="LLMModel",
                )
                self.key_failure_count[curr_index] += 1

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"API request failed for key index {curr_index} with status {e.response.status_code}: {e.response.text[:200]}",
                    command="LLMModel",
                    e=e,
                )
                self.key_failure_count[curr_index] += 1
                if e.response.status_code == 429:
                    logger.warning(
                        f"Rate limit hit for key index {curr_index}.",
                        command="LLMModel",
                    )

            except (
                httpx.RequestError,
                KeyError,
                ValueError,
                json.JSONDecodeError,
            ) as e:
                logger.error(
                    f"API request error for key index {curr_index}: {type(e).__name__} - {e}",
                    command="LLMModel",
                    e=e,
                )
                self.key_failure_count[curr_index] += 1

            if retry < self.max_retries - 1:
                logger.debug(
                    f"Retrying after delay ({self.retry_delay}s)...", command="LLMModel"
                )
                await asyncio.sleep(self.retry_delay)

        return "API 请求失败，已达最大重试次数。"

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
        self, api_key: str, messages: List[Dict[str, str]], prompt: str
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        url = self._format_url(self.api_type, api_key)
        headers = {}
        data = {}

        if self.api_type == "gemini":
            headers = {"Content-Type": "application/json"}
            data = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}"
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
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}",
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
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}",
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
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}",
                    }
                ],
            }
        elif self.api_type == "baidu":
            headers = {"Content-Type": "application/json"}
            data = {
                "messages": [
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}",
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
                        "content": f"{prompt}\n\n以下是需要总结的对话内容：\n\n{messages}",
                    }
                ],
            }

        return url, headers, data

    def _extract_response_text(self, result: Dict[str, Any]) -> str:
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

        logger.debug("[detect_model] Starting model detection...")

        base_config = Config.get("zhenxun_plugin_summary_group")

        if base_config:
            logger.debug(f"[detect_model] Found 'zhenxun_plugin_summary_group' config section.")
        else:
            logger.warning(
                "[detect_model] Could not find 'zhenxun_plugin_summary_group' config section in global config!"
            )
            base_config = {}

        model_type = base_config.get("model_type", "llm")

        logger.debug(f"[detect_model] Determined model_type: {model_type}")

        if model_type and model_type.lower() == "llm":

            logger.debug(
                "[detect_model] Model type is LLM. Reading LLM specific configs."
            )

            raw_api_keys_from_config = base_config.get("SUMMARY_API_KEYS")

            logger.debug(
                f"[detect_model] Raw value for SUMMARY_API_KEYS from config: {repr(raw_api_keys_from_config)} (Type: {type(raw_api_keys_from_config)})"
            )

            api_keys = base_config.get("SUMMARY_API_KEYS", None)

            api_type = base_config.get("SUMMARY_API_TYPE")
            api_base = base_config.get(
                "SUMMARY_API_BASE", "https://generativelanguage.googleapis.com"
            )
            model_name = base_config.get("SUMMARY_MODEL", "gemini-1.5-flash")
            openai_compat = base_config.get("SUMMARY_OPENAI_COMPAT", False)
            proxy = base_config.get("PROXY")
            timeout = base_config.get("TIME_OUT", 120)
            max_retries = base_config.get("MAX_RETRIES", 3)
            retry_delay = base_config.get("RETRY_DELAY", 2)

            logger.debug(f"[detect_model] Preparing to initialize LLMModel with:")
            logger.debug(f"  api_keys (value passed to init): {repr(api_keys)}")
            logger.debug(f"  api_base: {api_base}")
            logger.debug(f"  summary_model: {model_name}")
            logger.debug(f"  api_type: {api_type}")
            logger.debug(f"  openai_compat: {openai_compat}")
            logger.debug(f"  proxy: {proxy}")
            logger.debug(f"  timeout: {timeout}")
            logger.debug(f"  max_retries: {max_retries}")
            logger.debug(f"  retry_delay: {retry_delay}")

            return LLMModel(
                api_keys=api_keys,
                api_base=api_base,
                summary_model=model_name,
                api_type=api_type,
                openai_compat=openai_compat,
                proxy=proxy,
                timeout=timeout,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )

        logger.warning(
            f"[detect_model] Unsupported model_type '{model_type}' or model_type not specified. Falling back to default LLMModel()."
        )

        return LLMModel()

    except Exception as e:
        logger.error(
            f"[detect_model] Error during model detection: {e}",
            command="detect_model",
            exc_info=True,
        )

        logger.error(
            "[detect_model] Falling back to default LLMModel() due to exception."
        )

        return LLMModel()
