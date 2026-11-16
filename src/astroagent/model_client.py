"""Bounded protocol adapters sharing the existing LangChain message/tool boundary."""

import json
import logging
from urllib.parse import quote
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from astroagent.errors import ServiceError

LOGGER = logging.getLogger(__name__)


def upstream_failure(protocol, status, content):
    # Classify bounded upstream errors; never expose their raw text, headers or keys.
    try:
        payload = json.loads(content)
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message", ""))[:4096].lower() if isinstance(error, dict) else ""
    except (ValueError, TypeError, UnicodeError):
        message = ""
    if status == 402:
        if protocol == "gemini":
            detail = (
                "当前 Gemini 项目的预付费余额已耗尽，请在 Google AI Studio 的项目结算中充值后重试。"
                if "prepayment credits" in message and "depleted" in message
                else "Gemini 服务需要处理余额或计费问题，"
                "请在 Google AI Studio 检查当前项目的结算状态。"
            )
            failure = ServiceError(503, "gemini_billing_required", detail)
        else:
            failure = ServiceError(
                503,
                "model_billing_required",
                "模型服务商返回计费错误，请检查此服务商的余额与结算状态。",
            )
    elif status in (401, 403):
        failure = ServiceError(
            503,
            "model_authentication_failed",
            "模型服务拒绝访问，请检查密钥、项目权限及服务商访问限制。",
        )
    elif status == 429:
        failure = ServiceError(
            503,
            "model_rate_limited",
            "模型额度或请求速率受限，请检查服务商限额后重试。",
            retryable=True,
        )
    elif status == 404:
        failure = ServiceError(
            502,
            "model_not_found",
            "服务商未找到所选模型或请求端点，请核对模型 ID、协议及 API 根地址。",
        )
    elif status in (400, 422):
        failure = ServiceError(
            502,
            "model_request_invalid",
            "服务商拒绝请求参数，请核对所选模型支持的协议与工具调用能力。",
        )
    else:
        failure = ServiceError(
            502,
            "model_unavailable",
            "模型服务暂时未能完成请求，请稍后重试。",
            retryable=status >= 500,
        )
    LOGGER.warning(
        "Model request rejected: protocol=%s status=%d category=%s",
        protocol,
        status,
        failure.error.code,
    )
    return failure


def provider_headers(protocol, key):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if protocol == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif protocol == "gemini":
        headers["x-goog-api-key"] = key
    else:
        headers["Authorization"] = "Bearer " + key
    return headers


def chat_model(settings, *, tools=None, max_tokens=1500, json_mode=False, parallel=True):
    if settings.model_protocol != "openai_chat":
        return ProtocolModel(settings, tools or [], max_tokens, json_mode, parallel)
    model = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=str(settings.deepseek_base_url),
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
        max_tokens=max_tokens,
        extra_body=settings.non_thinking_body(),
    )
    if tools:
        return model.bind_tools(tools, **({} if parallel else {"parallel_tool_calls": False}))
    return model.bind(response_format={"type": "json_object"}) if json_mode else model


def tool_call(name, arguments, identifier):
    arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(name, str) or not name or not isinstance(arguments, dict):
        raise ValueError("Invalid function call")
    if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
        raise ValueError("Invalid function call identifier")
    return {"name": name, "args": arguments, "id": identifier, "type": "tool_call"}


def append_blocks(items, role, blocks):
    if not blocks:
        return
    if items and items[-1]["role"] == role:
        items[-1]["content"].extend(blocks)
    else:
        items.append({"role": role, "content": blocks})


class ProtocolModel:
    def __init__(self, settings, tools, max_tokens, json_mode, parallel):
        self.settings, self.tools = settings, [tool["function"] for tool in tools]
        self.max_tokens, self.json_mode, self.parallel = max_tokens, json_mode, parallel

    def invoke(self, messages):
        protocol = self.settings.model_protocol
        try:
            path, body = getattr(self, protocol + "_request")(messages)
            url = str(self.settings.deepseek_base_url).rstrip("/") + path
            with httpx.Client(
                timeout=self.settings.llm_timeout_seconds, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream(
                    "POST",
                    url,
                    json=body,
                    headers=provider_headers(
                        protocol, self.settings.deepseek_api_key.get_secret_value()
                    ),
                ) as response:
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        limit = 2 * 1024 * 1024 if response.status_code == 200 else 65536
                        if len(content) > limit:
                            if response.status_code != 200:
                                raise upstream_failure(protocol, response.status_code, b"")
                            raise ValueError("Response exceeds limit")
                    if response.status_code != 200:
                        raise upstream_failure(protocol, response.status_code, content)
            return getattr(self, protocol + "_response")(json.loads(content))
        except ServiceError:
            raise
        except httpx.TimeoutException as exc:
            raise ServiceError(
                504, "model_timeout", "模型响应超时，请稍后重试。", retryable=True
            ) from exc
        except httpx.RequestError as exc:
            raise ServiceError(
                502, "model_unavailable", "模型服务连接失败，请核对服务地址。", retryable=True
            ) from exc
        except Exception as exc:
            raise ServiceError(
                502, "model_invalid_response", "模型响应与所选协议不符，或返回了无效的工具参数。"
            ) from exc

    def openai_responses_request(self, messages):
        items = []
        for message in messages:
            if isinstance(message, AIMessage):
                items.extend(message.additional_kwargs["protocol_blocks"])
            elif isinstance(message, ToolMessage):
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
            else:
                items.append(
                    {
                        "role": "system" if isinstance(message, SystemMessage) else "user",
                        "content": message.content,
                    }
                )
        body = {
            "model": self.settings.deepseek_model,
            "input": items,
            "store": False,
            "max_output_tokens": self.max_tokens,
            "include": ["reasoning.encrypted_content"],
        }
        if self.tools:
            body.update(
                tools=[{"type": "function", **tool, "strict": False} for tool in self.tools],
                parallel_tool_calls=self.parallel,
            )
        if self.json_mode:
            body["text"] = {"format": {"type": "json_object"}}
        return "/responses", body

    def openai_responses_response(self, data):
        blocks = data["output"]
        texts, calls = [], []
        for item in blocks:
            if item["type"] == "function_call":
                calls.append(tool_call(item["name"], item["arguments"], item["call_id"]))
            elif item["type"] == "message":
                texts.extend(
                    part["text"] for part in item["content"] if part["type"] == "output_text"
                )
        complete = data.get("status") == "completed"
        return self.message(
            texts, calls, blocks, data.get("usage", {}), data.get("model"), complete
        )

    def anthropic_request(self, messages):
        system, items = [], []
        for message in messages:
            if isinstance(message, SystemMessage):
                system.append(message.content)
            elif isinstance(message, AIMessage):
                append_blocks(items, "assistant", message.additional_kwargs["protocol_blocks"])
            elif isinstance(message, ToolMessage):
                append_blocks(
                    items,
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content,
                        }
                    ],
                )
            else:
                append_blocks(items, "user", [{"type": "text", "text": message.content}])
        body = {
            "model": self.settings.deepseek_model,
            "system": "\n\n".join(system),
            "messages": items,
            "max_tokens": self.max_tokens,
        }
        if self.tools:
            body["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool["parameters"],
                }
                for tool in self.tools
            ]
            body["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": not self.parallel}
        return "/messages", body

    def anthropic_response(self, data):
        blocks = data["content"]
        texts = [part["text"] for part in blocks if part["type"] == "text"]
        calls = [
            tool_call(part["name"], part["input"], part["id"])
            for part in blocks
            if part["type"] == "tool_use"
        ]
        complete = data.get("stop_reason") in {"end_turn", "stop_sequence", "tool_use"}
        return self.message(
            texts, calls, blocks, data.get("usage", {}), data.get("model"), complete
        )

    def gemini_request(self, messages):
        system, items, call_ids = [], [], {}
        for message in messages:
            if isinstance(message, SystemMessage):
                system.append(message.content)
                continue
            if isinstance(message, AIMessage):
                parts = message.additional_kwargs["protocol_blocks"]
                function_parts = [part["functionCall"] for part in parts if "functionCall" in part]
                for call, part in zip(message.tool_calls, function_parts, strict=True):
                    call_ids[call["id"]] = part.get("id")
                role = "model"
            elif isinstance(message, ToolMessage):
                try:
                    result = json.loads(message.content)
                except ValueError:
                    result = {"result": message.content}
                function = {
                    "name": message.name,
                    "response": result if isinstance(result, dict) else {"result": result},
                }
                if call_ids.get(message.tool_call_id):
                    function["id"] = call_ids[message.tool_call_id]
                parts, role = [{"functionResponse": function}], "user"
            else:
                parts, role = [{"text": message.content}], "user"
            if items and items[-1]["role"] == role:
                items[-1]["parts"].extend(parts)
            else:
                items.append({"role": role, "parts": parts})
        body = {
            "contents": items,
            "systemInstruction": {"parts": [{"text": "\n\n".join(system)}]},
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        if self.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parametersJsonSchema": tool["parameters"],
                        }
                        for tool in self.tools
                    ]
                }
            ]
        if self.json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        model = self.settings.deepseek_model.removeprefix("models/")
        return "/models/" + quote(model, safe="") + ":generateContent", body

    def gemini_response(self, data):
        candidate = data["candidates"][0]
        blocks = candidate["content"]["parts"]
        texts = [part["text"] for part in blocks if "text" in part and not part.get("thought")]
        calls = [
            tool_call(
                part["functionCall"]["name"],
                part["functionCall"].get("args", {}),
                part["functionCall"].get("id") or "call_" + uuid4().hex,
            )
            for part in blocks
            if "functionCall" in part
        ]
        usage = data.get("usageMetadata", {})
        normalized = {
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0)
            + usage.get("thoughtsTokenCount", 0),
        }
        return self.message(
            texts,
            calls,
            blocks,
            normalized,
            data.get("modelVersion"),
            candidate.get("finishReason") == "STOP",
        )

    def message(self, texts, calls, blocks, usage, model, complete):
        if not complete:
            # Never execute partial tools or publish a token-limited/safety-blocked answer.
            raise ServiceError(
                502,
                "model_incomplete_response",
                "模型回答未完整生成或被服务商中止；未执行不完整的工具调用。",
            )
        if len(calls) > 32:
            raise ValueError("Too many tool calls")
        input_tokens, output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        return AIMessage(
            content="\n".join(texts),
            tool_calls=calls,
            additional_kwargs={"protocol_blocks": blocks},
            response_metadata={
                "model_name": model or self.settings.deepseek_model,
                "finish_reason": "tool_calls" if calls else "stop",
            },
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )
