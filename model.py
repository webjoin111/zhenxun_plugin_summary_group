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
        
        raw_keys = api_keys
        processed_keys = []
        if isinstance(raw_keys, str):
             
            try:
                parsed = json.loads(raw_keys)
                if isinstance(parsed, list):
                    processed_keys = [str(k) for k in parsed if k] 
                elif parsed: 
                    processed_keys = [str(parsed)]
                else: 
                     processed_keys = []
            except json.JSONDecodeError:
                
                processed_keys = [raw_keys] if raw_keys else []
        elif isinstance(raw_keys, list):
             processed_keys = [str(k) for k in raw_keys if k] 
        else:
            processed_keys = []

        self.api_keys = processed_keys
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

        if self.openai_compat and self.api_type == "gemini":
            self.api_type = "gemini_openai"

        if not self.api_keys:
            logger.warning("LLMModel initialized without valid API keys.", command="LLMModel")
            

    
    def _determine_api_type(self, explicit_type: Optional[str], model_name: str) -> str:
        if explicit_type:
            logger.debug(f"Using explicit API type: {explicit_type}", command="LLMModel")
            return explicit_type.lower()

        model_name_lower = model_name.lower()
        for prefix, api_type in self.MODEL_PREFIX_MAP.items():
            if model_name_lower.startswith(prefix):
                logger.debug(f"Detected API type '{api_type}' based on model prefix '{prefix}'", command="LLMModel")
                return api_type

        
        default_type = "general" 
        logger.debug(f"Could not determine API type from model name, defaulting to '{default_type}'", command="LLMModel")
        return default_type

    async def summary_history(self, messages: List[Dict[str, str]], prompt: str) -> str:
        if not self.api_keys:
            return "错误：未配置有效的 API 密钥。"
        return await self._request_summary(messages, prompt)

    async def _request_summary(
        self, messages: List[Dict[str, str]], prompt: str
    ) -> str:
        tried_indices = set()

        
        for retry in range(self.max_retries):
            if not self.api_keys: 
                 return "错误：无可用 API 密钥。"

            
            curr_index = self.current_key_index
            
            available_indices = [i for i in range(len(self.api_keys)) if i not in tried_indices]
            if not available_indices:
                 
                 if retry < self.max_retries - 1:
                     logger.warning(f"All API keys failed, retrying after delay ({self.retry_delay}s)...", command="LLMModel")
                     await asyncio.sleep(self.retry_delay)
                     tried_indices.clear() 
                     curr_index = 0 
                 else:
                     logger.error("All API keys failed after maximum retries.", command="LLMModel")
                     return "所有API密钥均请求失败，请检查配置或网络。"
            else:
                 
                 if curr_index not in available_indices:
                      curr_index = random.choice(available_indices) 

            tried_indices.add(curr_index)
            api_key = self.api_keys[curr_index]
            logger.debug(f"Attempting API request with key index {curr_index} (Retry {retry+1}/{self.max_retries})", command="LLMModel")

            try:
                url, headers, data = self._prepare_request_params(api_key, messages, prompt)
                logger.debug(f"Request URL: {url}", command="LLMModel")
                logger.debug(f"Request Headers: {headers}", command="LLMModel")
                

                client_params = {}
                
                if self.proxy:
                    client_params["proxy"] = self.proxy
                if self.timeout:
                    client_params["timeout"] = self.timeout
                

                async with httpx.AsyncClient(**client_params) as client:
                    response = await client.post(url, json=data, headers=headers)

                logger.debug(f"Response Status Code: {response.status_code}", command="LLMModel")
                

                response.raise_for_status()
                result = response.json()
                response_text = self._extract_response_text(result)

                self.current_key_index = curr_index 
                self.key_failure_count[curr_index] = 0 
                logger.debug(f"API request successful with key index {curr_index}.", command="LLMModel")
                return response_text

            except httpx.TimeoutException:
                logger.warning(f"API request timed out for key index {curr_index}.", command="LLMModel")
                self.key_failure_count[curr_index] += 1
                

            except httpx.HTTPStatusError as e:
                logger.warning(f"API request failed for key index {curr_index} with status {e.response.status_code}: {e.response.text[:200]}", command="LLMModel", e=e)
                self.key_failure_count[curr_index] += 1
                if e.response.status_code == 429: 
                    logger.warning(f"Rate limit hit for key index {curr_index}.", command="LLMModel")
                

            except (httpx.RequestError, KeyError, ValueError, json.JSONDecodeError) as e:
                logger.error(f"API request error for key index {curr_index}: {type(e).__name__} - {e}", command="LLMModel", e=e)
                self.key_failure_count[curr_index] += 1
                

            
            if retry < self.max_retries - 1:
                logger.debug(f"Retrying after delay ({self.retry_delay}s)...", command="LLMModel")
                await asyncio.sleep(self.retry_delay)

        
        return "API 请求失败，已达最大重试次数。"


    
    def _format_url(self, api_type: str, api_key: str) -> str:
        
        if api_type == "baidu":
             url_format = self.API_URL_FORMAT[api_type]
             
             return url_format.format(base=self.api_base, model=self.summary_model, key=api_key)
        else:
            url_format = self.API_URL_FORMAT.get(api_type, self.API_URL_FORMAT["general"])
            return url_format.format(base=self.api_base, model=self.summary_model, key=api_key)

    def _prepare_request_params(
        self, api_key: str, messages: List, prompt: str
    ) -> Tuple[str, Dict, Dict]:
        api_type = self.api_type.lower()

        url = self._format_url(api_type, api_key)
        headers = {"Content-Type": "application/json"}
        data = {}
        content_str = json.dumps(messages, ensure_ascii=False)

        if api_type == "gemini":
            headers = {"Content-Type": "application/json"}
            
            data = {
                "contents": [
                    {"parts": [{"text": prompt}], "role": "user"}, 
                    {"parts": [{"text": content_str}], "role": "user"}, 
                ],
                "generationConfig": { 
                     "temperature": 0.7,
                     
                }
            }
        elif api_type == "gemini_openai":
             headers = {
                 "Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}", 
                 
             }
             data = {
                 "model": self.summary_model,
                 "messages": [
                     {"role": "system", "content": prompt},
                     {"role": "user", "content": content_str}, 
                 ],
             }
        elif api_type == "baidu":
             headers = {"Content-Type": "application/json"} 
             
             data = {
                 "messages": [
                     
                     {"role": "user", "content": f"{prompt}\n\n以下是聊天记录：\n{content_str}"},
                 ]
                 
             }
        elif api_type == "claude":
             headers = {
                 "Content-Type": "application/json",
                 "x-api-key": api_key,
                 "anthropic-version": "2023-06-01", 
             }
             data = {
                 "model": self.summary_model,
                 "system": prompt, 
                 "messages": [{"role": "user", "content": content_str}],
                 "max_tokens": 4096, 
             }
        
        elif api_type == "zhipu":
            headers = {
                "Content-Type": "application/json",
                
                "Authorization": f"Bearer {api_key}",
            }
            data = {
                "model": self.summary_model, 
                "messages": [
                    
                    
                    {"role": "system", "content": prompt},
                    
                    {"role": "user", "content": content_str},
                ],
                
                
                
            }
        
        
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            data = {
                "model": self.summary_model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content_str},
                ],
            }

        return url, headers, data

    def _extract_response_text(self, result: Dict[str, Any]) -> str:
        api_type = self.api_type.lower()

        try:
            if api_type == "gemini" or api_type == "gemini_openai":
                
                if "candidates" in result:
                    
                    candidates = result.get("candidates", [])
                    if not candidates:
                        
                        if "promptFeedback" in result:
                            prompt_feedback = result["promptFeedback"]
                            if "blockReason" in prompt_feedback:
                                block_reason = prompt_feedback["blockReason"]
                                safety_ratings = prompt_feedback.get("safetyRatings", [])
                                logger.error(f"Gemini API blocked request: {block_reason}", command="LLMModel", e=None)
                                logger.error(f"Safety Ratings: {safety_ratings}", command="LLMModel")
                                return f"请求被 Gemini 安全系统拦截: {block_reason}"
                            
                        logger.error(f"Could not extract text from Gemini response: {result}", command="LLMModel")
                        return "生成的响应为空，请尝试修改内容后重试。"
                    
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    return "\n".join(part.get("text", "") for part in parts if "text" in part)
                elif "choices" in result:
                    
                    return self._extract_openai_text(result)
            
            elif api_type == "claude":
                if "content" in result:
                    
                    contents = result.get("content", [])
                    return "\n".join(
                        item.get("text", "") for item in contents 
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                logger.error(f"Could not extract text from Claude response: {result}", command="LLMModel")
                return "无法从 Claude 响应中提取文本。"
                
            elif api_type == "baidu":
                if "error_code" in result:
                    logger.error(f"Baidu API Error: {result.get('error_code')} - {result['error_msg']}", command="LLMModel")
                    return f"百度 API 错误: {result.get('error_msg', '未知错误')}"
                    
                text = result.get("result", "")
                if not text:
                    logger.error(f"Could not extract text from Baidu response: {result}", command="LLMModel")
                    return "生成的响应为空，请尝试修改内容后重试。"
                return text
                
            
            elif "choices" in result:
                try:
                    choices = result.get("choices", [])
                    if not choices:
                        logger.error(f"No 'choices' found in {api_type} compatible response: {result}")
                        return "API响应中未找到 'choices'。"
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    if content is None:
                        
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content is None:
                            logger.error(f"No 'content' found in message/delta of {api_type} compatible response: {result}")
                            return "API响应的消息中未找到 'content'。"
                    return str(content)  
                except (IndexError, KeyError, AttributeError) as extract_e:
                    logger.error(f"Error extracting text from {api_type} compatible response: {extract_e}", e=extract_e)
                    logger.error(f"Raw response causing extraction error: {result}")
                    return "无法解析API响应中的文本内容。"
            

            
            logger.warning(f"Unknown response format for api_type '{api_type}'. Returning raw result string.", command="LLMModel")
            return str(result)

        except Exception as e:
            logger.error(f"Error extracting response text: {e}", command="LLMModel", e=e)
            logger.error(f"Raw response causing error: {result}")
            return f"处理API响应时发生错误: {str(e)}"


def detect_model() -> Model:
    try:
        
        base_config = Config.get("summary_group")
        
        model_type = base_config.get("model_type", "llm")
        
        if model_type and model_type.lower() == "llm":  
            api_type = base_config.get("SUMMARY_API_TYPE")  
            api_keys = base_config.get("SUMMARY_API_KEYS", [])
            api_base = base_config.get("SUMMARY_API_BASE", "https://generativelanguage.googleapis.com")
            model_name = base_config.get("SUMMARY_MODEL", "gemini-1.5-flash")  
            openai_compat = base_config.get("SUMMARY_OPENAI_COMPAT", False)
            proxy = base_config.get("PROXY")
            timeout = base_config.get("TIME_OUT", 120)  
            max_retries = base_config.get("MAX_RETRIES", 3)
            retry_delay = base_config.get("RETRY_DELAY", 2)
            
            return LLMModel(
                api_keys=api_keys, 
                api_base=api_base, 
                summary_model=model_name,
                api_type=api_type,
                openai_compat=openai_compat,
                proxy=proxy,
                timeout=timeout,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
            
        
        
        
        return LLMModel()
        
    except Exception as e:
        logger.error(f"Error detecting model: {e}", command="detect_model", e=e)
        
        return LLMModel()
