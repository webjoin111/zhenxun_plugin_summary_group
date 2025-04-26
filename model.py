from abc import ABC, abstractmethod
import json
import random
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from zhenxun.configs.config import Config
from zhenxun.services.log import logger
from zhenxun.utils.http_utils import AsyncHttpx
from zhenxun.utils.user_agent import get_user_agent

base_config = Config.get("summary_group")


class ModelException(Exception):
    pass


class ModelConfig(BaseModel):
    name: str = Field(..., description="模型的唯一名称标识")
    api_key: str | list[str] = Field(
        ..., description="该模型对应的 API Key 或 Key 列表"
    )
    model_name: str = Field(
        ..., description="模型的具体名称 (例如 gemini-1.5-flash, deepseek-chat)"
    )
    api_base: str = Field(..., description="该模型对应的 API Base URL")
    api_type: str | None = Field(
        None,
        description="API 类型 (如 openai, claude, gemini, baidu 等)，留空则自动推断",
    )
    openai_compat: bool = Field(
        False, description="是否对 Gemini API 使用 OpenAI 兼容模式"
    )
    max_tokens: int | None = Field(None, description="（可选）模型最大输出 token 限制")
    temperature: float | None = Field(None, description="（可选）模型温度参数")


class ModelDetail(BaseModel):
    """单个模型的具体配置"""

    model_name: str = Field(
        ..., description="模型的具体名称 (例如 gemini-1.5-flash, deepseek-chat)"
    )
    temperature: float | None = Field(
        None, description="（可选）覆盖 Provider 的温度参数"
    )
    max_tokens: int | None = Field(
        None, description="（可选）覆盖 Provider 的最大 token 限制"
    )


class ProviderConfig(BaseModel):
    """AI 服务提供商的配置"""

    name: str = Field(
        ..., description="Provider 的唯一名称标识 (例如 Gemini, DeepSeek)"
    )
    api_key: str | list[str] = Field(
        ..., description="该 Provider 对应的 API Key 或 Key 列表"
    )
    api_base: str = Field(..., description="该 Provider 对应的 API Base URL")
    api_type: str | None = Field(
        None,
        description="API 类型 (如 openai, claude, gemini, baidu 等)，留空则自动推断",
    )
    openai_compat: bool = Field(
        False, description="是否对 Gemini API 使用 OpenAI 兼容模式"
    )
    temperature: float | None = Field(
        None, description="（可选）Provider 的默认温度参数"
    )
    max_tokens: int | None = Field(
        None, description="（可选）Provider 的默认最大 token 限制"
    )
    models: list[ModelDetail] = Field(..., description="该 Provider 支持的模型列表")


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
        api_keys: str | list[str],
        api_base: str = "https://generativelanguage.googleapis.com",
        summary_model: str = "gemini-2.0-flash",
        api_type: str | None = None,
        openai_compat: bool = False,
        proxy: str | None = None,
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: int = 2,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        logger.debug("[LLMModel.__init__] 正在初始化LLMModel...")
        logger.debug(
            f"[LLMModel.__init__] 收到的api_keys参数: {api_keys!r} (类型: {type(api_keys)})"
        )

        processed_keys = []
        if isinstance(api_keys, str):
            if api_keys:
                processed_keys = [api_keys]
        elif isinstance(api_keys, list):
            processed_keys = [str(k) for k in api_keys if k]
        else:
            logger.warning(
                f"[LLMModel.__init__] api_keys 类型未预期: {type(api_keys)}，将视为空。"
            )

        self.api_keys = processed_keys

        logger.debug(
            f"[LLMModel.__init__] 最终处理的 api_keys 数量: {len(self.api_keys)}"
        )
        if not self.api_keys:
            logger.error("[LLMModel.__init__] 初始化错误：没有提供有效的 API 密钥。")
            raise ValueError("LLMModel requires at least one valid API key.")

        self.api_base = api_base
        self.summary_model = summary_model
        self.openai_compat = openai_compat
        self.proxy = proxy
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.api_type = self._determine_api_type(api_type, summary_model)
        logger.debug(f"[LLMModel.__init__] 确定的api_type: {self.api_type}")

        if self.openai_compat and self.api_type == "gemini":
            self.api_type = "gemini_openai"
            logger.debug(
                f"[LLMModel.__init__] 启用OpenAI兼容模式，覆盖api_type为: {self.api_type}"
            )

        logger.debug(f"[LLMModel.__init__] 模型 '{summary_model}' 初始化完成。")

    def _determine_api_type(self, explicit_type: str | None, model_name: str) -> str:
        if explicit_type:
            logger.debug(
                f"[LLMModel._determine_api_type] 使用显式指定的API类型: {explicit_type}",
                "LLMModel",
            )
            return explicit_type.lower()

        model_name_lower = model_name.lower()
        for prefix, api_type in self.MODEL_PREFIX_MAP.items():
            if model_name_lower.startswith(prefix):
                logger.debug(
                    f"[LLMModel._determine_api_type] 根据模型前缀 '{prefix}' 检测到API类型 '{api_type}'",
                    "LLMModel",
                )
                return api_type

        default_type = "general"
        logger.debug(
            f"[LLMModel._determine_api_type] 无法从模型名称 '{model_name}' 确定API类型，使用默认值 '{default_type}'",
            "LLMModel",
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
            logger.error(
                "[LLMModel._request_summary] No API keys available.", "LLMModel"
            )
            raise ModelException("错误：未配置有效的 API 密钥。")

        api_key = random.choice(self.api_keys)
        logger.debug(
            f"使用模型 '{self.summary_model}' (随机选择 Key: {api_key[:5]}...) 发起请求",
            "LLMModel",
        )

        try:
            url, headers, data = self._prepare_request_params(api_key, messages, prompt)
            logger.debug(f"Request URL: {url}", "LLMModel")

            proxy_config = None
            use_proxy_config = True
            if self.proxy:
                proxy_config = {"http://": self.proxy, "https://": self.proxy}
                use_proxy_config = False
                logger.debug(f"Using specific proxy: {self.proxy}", "LLMModel")

            response = await AsyncHttpx.post(
                url,
                json=data,
                headers=headers,
                timeout=self.timeout,
                proxy=proxy_config,
                use_proxy=use_proxy_config,
            )

            logger.debug(f"Response Status Code: {response.status_code}", "LLMModel")
            response.raise_for_status()

            result = response.json()
            response_text = self._extract_response_text(result)

            logger.debug(
                f"API request successful with key starting: {api_key[:5]}...",
                "LLMModel",
            )
            return response_text

        except httpx.TimeoutException as e:
            logger.warning(
                f"API request timed out for key {api_key[:5]}...: {e}",
                "LLMModel",
            )
            raise ModelException(f"API 请求超时: {e}") from e
        except httpx.HTTPStatusError as e:
            error_text = e.response.text[:200]
            logger.error(
                f"API request failed for key {api_key[:5]}... "
                f"with status {e.response.status_code}: {error_text}",
                "LLMModel",
                e=e,
            )
            raise ModelException(
                f"API 请求失败 (状态码 {e.response.status_code}): {error_text}"
            ) from e
        except httpx.RequestError as e:
            logger.error(
                f"API network request error for key {api_key[:5]}...: {e}",
                "LLMModel",
                e=e,
            )
            raise ModelException(f"网络请求错误: {e}") from e
        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"Error processing API response for key {api_key[:5]}...: {e}",
                "LLMModel",
                e=e,
            )
            raise ModelException(f"处理 API 响应失败: {e}") from e
        except Exception as e:
            logger.error(
                f"Unexpected error during API request for key {api_key[:5]}...: {e}",
                "LLMModel",
            )
            raise ModelException(f"发生意外错误: {e}") from e

    def _format_url(self, api_type: str, api_key: str) -> str:
        if api_type == "baidu":
            url_format = self.API_URL_FORMAT[api_type]

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
        data: dict[str, Any] = {}

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
                ],
                "generationConfig": {},
            }
            if self.temperature is not None:
                data["generationConfig"]["temperature"] = self.temperature
            if self.max_tokens is not None:
                data["generationConfig"]["maxOutputTokens"] = self.max_tokens
            if not data["generationConfig"]:
                del data["generationConfig"]
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
            if self.temperature is not None:
                data["temperature"] = self.temperature
            if self.max_tokens is not None:
                data["max_tokens"] = self.max_tokens
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
            if self.temperature is not None:
                data["temperature"] = self.temperature
            if self.max_tokens is not None:
                data["max_tokens"] = self.max_tokens
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
            if self.temperature is not None:
                data["temperature"] = self.temperature
            if self.max_tokens is not None:
                data["max_tokens"] = self.max_tokens
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
            if self.temperature is not None:
                data["temperature"] = self.temperature
        else:
            logger.warning(
                f"API 类型 '{self.api_type}' 未显式处理参数，尝试使用 OpenAI 格式。"
            )
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
            if self.temperature is not None:
                data["temperature"] = self.temperature
            if self.max_tokens is not None:
                data["max_tokens"] = self.max_tokens

        final_headers = get_user_agent()
        final_headers.update(headers)

        return url, final_headers, data

    def _extract_response_text(self, result: dict[str, Any]) -> str:
        if self.api_type == "gemini":
            try:
                if (
                    result.get("candidates")
                    and result["candidates"][0].get("finishReason") == "SAFETY"
                ):
                    safety_ratings = result["candidates"][0].get("safetyRatings", [])
                    blocked_categories = [
                        r["category"]
                        for r in safety_ratings
                        if r["probability"] != "NEGLIGIBLE"
                    ]
                    logger.warning(
                        f"Gemini API 因安全原因阻止了响应: {blocked_categories}"
                    )
                    return "抱歉，生成的内容可能违反了安全规则，无法显示。"
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                logger.error(
                    f"Failed to extract text from Gemini response: {e} | Response: {result}",
                    "LLMModel",
                )
                return "无法解析API响应"
        elif self.api_type == "baidu":
            try:
                if error_code := result.get("error_code"):
                    error_msg = result.get("error_msg", "未知错误")
                    logger.error(
                        f"Baidu API 返回错误: code={error_code}, msg={error_msg}"
                    )
                    return f"API 请求失败: {error_msg}"
                return result["result"]
            except KeyError as e:
                logger.error(
                    f"Failed to extract text from Baidu response: {e} | Response: {result}",
                    "LLMModel",
                )
                return "无法解析API响应"
        elif self.api_type == "claude":
            try:
                if result.get("type") == "message":
                    content_blocks = result.get("content", [])
                    text_parts = [
                        block["text"]
                        for block in content_blocks
                        if block.get("type") == "text"
                    ]
                    return "\n".join(text_parts)
                elif result.get("completion"):
                    return result["completion"]
                elif error_info := result.get("error"):
                    error_type = error_info.get("type", "unknown_error")
                    error_message = error_info.get("message", "未知错误")
                    logger.error(
                        f"Claude API 返回错误: type={error_type}, message={error_message}"
                    )
                    return f"API 请求失败: {error_message}"
                else:
                    logger.error(f"无法从 Claude 响应中提取内容 | Response: {result}")
                    return "无法解析API响应"
            except (KeyError, IndexError, TypeError) as e:
                logger.error(
                    f"Failed to extract text from Claude response: {e} | Response: {result}",
                    "LLMModel",
                )
                return "无法解析API响应"
        else:
            try:
                if error_info := result.get("error"):
                    error_message = error_info.get("message", "未知错误")
                    error_type = error_info.get("type", "")
                    logger.error(
                        f"API 返回错误: type={error_type}, message={error_message}"
                    )
                    return f"API 请求失败: {error_message}"
                choice = result["choices"][0]
                if message := choice.get("message"):
                    return message.get("content", "")
                elif text_content := choice.get("text"):
                    return text_content
                else:
                    logger.error(f"无法从 API 响应的 choice 中提取内容: {choice}")
                    return "无法解析API响应"
            except (KeyError, IndexError) as e:
                logger.error(
                    f"Failed to extract text from response: {e} | Response: {result}",
                    "LLMModel",
                )
                return "无法解析API响应"


def get_configured_models() -> list[ModelConfig]:
    """从配置中安全地获取模型列表"""
    models_raw = base_config.get("SUMMARY_MODELS", [])
    if not isinstance(models_raw, list):
        logger.error("配置项 SUMMARY_MODELS 不是一个列表，将使用空列表。")
        return []

    models = []
    for i, item in enumerate(models_raw):
        if isinstance(item, dict):
            try:
                model_conf = ModelConfig(**item)
                if not all(
                    [
                        model_conf.name,
                        model_conf.api_key,
                        model_conf.model_name,
                        model_conf.api_base,
                    ]
                ):
                    logger.warning(
                        f"配置文件中第 {i + 1} 个模型缺少必要的字段 (name, api_key, model_name, api_base)，已跳过。"
                    )
                    continue
                models.append(model_conf)
            except Exception as e:
                logger.warning(
                    f"解析配置文件中第 {i + 1} 个模型时出错: {e}，已跳过。配置: {item}"
                )
        else:
            logger.warning(
                f"配置文件 SUMMARY_MODELS 中第 {i + 1} 项不是字典格式，已跳过。"
            )
    return models


def get_default_model_name() -> str | None:
    """获取默认模型名称"""
    return base_config.get("SUMMARY_DEFAULT_MODEL_NAME")


def detect_model() -> Model:
    """根据当前配置和状态选择并实例化模型"""
    try:
        from .handlers.model_control import (
            find_model,
            get_configured_providers,
            parse_provider_model_string,
        )

        logger.debug("[detect_model] 开始模型检测...")

        active_model_name_str = base_config.get("CURRENT_ACTIVE_MODEL_NAME")
        logger.debug(
            f"[detect_model] 当前激活模型名称 (来自配置): {active_model_name_str}"
        )

        selected_provider: ProviderConfig | None = None
        selected_model_detail: ModelDetail | None = None

        active_prov_name, active_mod_name = parse_provider_model_string(
            active_model_name_str
        )

        if active_prov_name and active_mod_name:
            if found := find_model(active_prov_name, active_mod_name):
                selected_provider, selected_model_detail = found
                logger.debug(
                    f"[detect_model] 找到当前激活模型: {active_model_name_str}"
                )
            else:
                logger.warning(
                    f"[detect_model] 配置的激活模型 '{active_model_name_str}' 无效或未找到，尝试回退..."
                )

        if not selected_provider:
            default_model_name_str = base_config.get("SUMMARY_DEFAULT_MODEL_NAME")
            default_prov_name, default_mod_name = parse_provider_model_string(
                default_model_name_str
            )
            if default_prov_name and default_mod_name:
                if found := find_model(default_prov_name, default_mod_name):
                    selected_provider, selected_model_detail = found
                    logger.warning(
                        f"[detect_model] 回退到默认模型: {default_model_name_str}"
                    )
                else:
                    logger.warning(
                        f"[detect_model] 配置的默认模型 '{default_model_name_str}' 也无效或未找到。"
                    )

        if not selected_provider:
            providers = get_configured_providers()
            if providers and providers[0].models:
                selected_provider = providers[0]
                selected_model_detail = providers[0].models[0]
                fallback_name = (
                    f"{selected_provider.name}/{selected_model_detail.model_name}"
                )
                logger.warning(f"[detect_model] 回退到第一个可用模型: {fallback_name}")
            else:
                logger.error("[detect_model] 无法找到任何可用模型配置！")
                raise ModelException("错误：未配置任何有效的 AI 模型。")

        assert selected_model_detail is not None
        final_api_keys = selected_provider.api_key
        final_api_base = selected_provider.api_base
        final_model_name = selected_model_detail.model_name
        final_api_type = selected_provider.api_type
        final_openai_compat = selected_provider.openai_compat
        final_temperature = (
            selected_model_detail.temperature
            if selected_model_detail.temperature is not None
            else selected_provider.temperature
        )
        final_max_tokens = (
            selected_model_detail.max_tokens
            if selected_model_detail.max_tokens is not None
            else selected_provider.max_tokens
        )

        logger.debug(
            f"[detect_model] 最终选定 Provider: {selected_provider.name}, Model: {final_model_name}"
        )

        proxy = base_config.get("PROXY")
        timeout = base_config.get("TIME_OUT", 180)
        max_retries = base_config.get("MAX_RETRIES", 2)
        retry_delay = base_config.get("RETRY_DELAY", 3)

        try:
            return LLMModel(
                api_keys=final_api_keys,
                api_base=final_api_base,
                summary_model=final_model_name,
                api_type=final_api_type,
                openai_compat=final_openai_compat,
                temperature=final_temperature,
                max_tokens=final_max_tokens,
                proxy=proxy,
                timeout=timeout,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
        except Exception as e:
            logger.error("[detect_model] 实例化 LLMModel 时出错", e=e)
            raise ModelException(f"初始化模型时发生错误: {e}")
    except Exception as e:
        logger.error(f"[detect_model] 模型检测失败: {e}")
        raise ModelException(f"模型初始化失败: {e}")
