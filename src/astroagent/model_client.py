"""Bounded protocol adapters sharing the existing LangChain message/tool boundary."""

import json
import logging
from urllib.parse import quote
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from astroagent.errors import ServiceError
from astroagent.usage import reserve_request

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
        stream_usage=True,
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


def _extract_chunk_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def invoke_model(model, messages, on_delta=None):
    reserve_request("model_requests")
    if on_delta is None:
        return model.invoke(messages)
    if isinstance(model, ProtocolModel):
        return model.invoke_streaming(messages, on_delta)
    if hasattr(model, "stream"):
        combined = None
        for chunk in model.stream(messages):
            combined = chunk if combined is None else combined + chunk
            delta = _extract_chunk_text(getattr(chunk, "content", ""))
            if delta:
                on_delta(delta)
        if combined is None:
            return AIMessage(content="")
        return AIMessage(
            content=combined.content,
            tool_calls=list(getattr(combined, "tool_calls", None) or ()),
            invalid_tool_calls=list(getattr(combined, "invalid_tool_calls", None) or ()),
            additional_kwargs=dict(getattr(combined, "additional_kwargs", None) or {}),
            response_metadata=dict(getattr(combined, "response_metadata", None) or {}),
            usage_metadata=getattr(combined, "usage_metadata", None),
            id=getattr(combined, "id", None),
        )
    response = model.invoke(messages)
    text = _extract_chunk_text(getattr(response, "content", ""))
    if text:
        on_delta(text)
    return response


def _read_error_body(response, protocol):
    content = bytearray()
    for chunk in response.iter_bytes():
        content.extend(chunk)
        if len(content) > 65536:
            return upstream_failure(protocol, response.status_code, b"")
    return upstream_failure(protocol, response.status_code, content)


def _iter_sse_events(response):
    total_bytes = 0
    event_name = ""
    data_lines: list[str] = []
    for raw_line in response.iter_lines():
        total_bytes += len(raw_line.encode("utf-8")) + 1
        if total_bytes > 2 * 1024 * 1024:
            raise ValueError("Response exceeds limit")
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines = []
                current_event = event_name
                event_name = ""
                if payload != "[DONE]":
                    yield current_event, payload
            else:
                event_name = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        payload = "\n".join(data_lines)
        if payload != "[DONE]":
            yield event_name, payload


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

    def invoke_streaming(self, messages, on_delta):
        protocol = self.settings.model_protocol
        try:
            path, body = getattr(self, protocol + "_request")(messages)
            headers = provider_headers(protocol, self.settings.deepseek_api_key.get_secret_value())
            headers["Accept"] = "text/event-stream"
            if protocol == "gemini":
                path = path.replace(":generateContent", ":streamGenerateContent?alt=sse", 1)
            else:
                body = {**body, "stream": True}
            url = str(self.settings.deepseek_base_url).rstrip("/") + path
            with httpx.Client(
                timeout=self.settings.llm_timeout_seconds, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream("POST", url, json=body, headers=headers) as response:
                    if response.status_code != 200:
                        raise _read_error_body(response, protocol)
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/event-stream" not in content_type:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 2 * 1024 * 1024:
                                raise ValueError("Response exceeds limit")
                        parsed = json.loads(content)
                        if protocol == "gemini" and isinstance(parsed, list):
                            return self._consume_gemini_chunks(parsed, on_delta)
                        message = getattr(self, protocol + "_response")(parsed)
                        if isinstance(message.content, str) and message.content:
                            on_delta(message.content)
                        return message
                    return getattr(self, protocol + "_stream_response")(response, on_delta)
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

    def openai_responses_stream_response(self, response, on_delta):
        completed = None
        for _, payload in _iter_sse_events(response):
            event = json.loads(payload)
            event_type = event.get("type", "")
            if event_type == "response.output_text.delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    on_delta(delta)
            elif event_type in {
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                if isinstance(event.get("response"), dict):
                    completed = event["response"]
        if completed is None:
            LOGGER.warning(
                "Model stream ended without terminal response: protocol=%s model=%s max_tokens=%d",
                self.settings.model_protocol,
                self.settings.deepseek_model,
                self.max_tokens,
            )
            raise ServiceError(
                502,
                "model_incomplete_response",
                "模型回答未完整生成或被服务商中止；未执行不完整的工具调用。",
            )
        return self.openai_responses_response(completed)

    def anthropic_stream_response(self, response, on_delta):
        blocks: dict[int, dict] = {}
        tool_buffers: dict[int, list[str]] = {}
        model_name = None
        usage: dict[str, int] = {}
        stop_reason = None
        for event_name, payload in _iter_sse_events(response):
            event = json.loads(payload)
            kind = event.get("type") or event_name
            if kind == "message_start":
                message = event.get("message") or {}
                model_name = message.get("model") or model_name
                if isinstance(message.get("usage"), dict):
                    usage.update(message["usage"])
            elif kind == "content_block_start":
                index = int(event["index"])
                block = dict(event.get("content_block") or {})
                blocks[index] = block
                if block.get("type") == "tool_use":
                    tool_buffers[index] = []
            elif kind == "content_block_delta":
                index = int(event["index"])
                delta = event.get("delta") or {}
                block = blocks.setdefault(index, {})
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        block["text"] = block.get("text", "") + text
                        on_delta(text)
                elif delta_type == "input_json_delta":
                    tool_buffers.setdefault(index, []).append(delta.get("partial_json", ""))
                elif delta_type == "thinking_delta":
                    block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
                elif delta_type == "signature_delta":
                    block["signature"] = delta.get("signature", "")
            elif kind == "content_block_stop":
                index = int(event["index"])
                block = blocks.get(index)
                if block and block.get("type") == "tool_use":
                    raw_json = "".join(tool_buffers.get(index, ())).strip()
                    if raw_json:
                        block["input"] = json.loads(raw_json)
                    elif not isinstance(block.get("input"), dict):
                        block["input"] = {}
            elif kind == "message_delta":
                delta = event.get("delta") or {}
                if delta.get("stop_reason") is not None:
                    stop_reason = delta["stop_reason"]
                if isinstance(event.get("usage"), dict):
                    usage.update(event["usage"])
        ordered = [blocks[idx] for idx in sorted(blocks)]
        return self.anthropic_response(
            {
                "content": ordered,
                "stop_reason": stop_reason,
                "usage": usage,
                "model": model_name,
            }
        )

    def gemini_stream_response(self, response, on_delta):
        return self._consume_gemini_chunks(
            (json.loads(payload) for _, payload in _iter_sse_events(response)),
            on_delta,
        )

    def _consume_gemini_chunks(self, chunks, on_delta):
        blocks: list[dict] = []
        texts: list[str] = []
        calls: list[dict] = []
        usage: dict = {}
        model_version = None
        finish_reason = None
        for data in chunks:
            if data.get("modelVersion"):
                model_version = data["modelVersion"]
            if isinstance(data.get("usageMetadata"), dict):
                usage = data["usageMetadata"]
            candidates = data.get("candidates") or []
            if not candidates:
                continue
            candidate = candidates[0]
            reason = candidate.get("finishReason")
            if reason and reason != "FINISH_REASON_UNSPECIFIED":
                finish_reason = reason
            parts = (candidate.get("content") or {}).get("parts") or []
            for part in parts:
                if "text" in part and not part.get("thought"):
                    text = part["text"]
                    if text:
                        on_delta(text)
                        texts.append(text)
                    if (
                        blocks
                        and set(part.keys()) == {"text"}
                        and set(blocks[-1].keys()) == {"text"}
                    ):
                        blocks[-1]["text"] += text
                    else:
                        blocks.append(dict(part))
                elif (
                    blocks
                    and set(part.keys()) == {"thought", "text"}
                    and part.get("thought") is True
                    and isinstance(part.get("text"), str)
                    and set(blocks[-1].keys()) == {"thought", "text"}
                    and blocks[-1].get("thought") is True
                    and isinstance(blocks[-1].get("text"), str)
                ):
                    blocks[-1]["text"] += part["text"]
                else:
                    blocks.append(dict(part))
                if "functionCall" in part:
                    calls.append(
                        tool_call(
                            part["functionCall"]["name"],
                            part["functionCall"].get("args", {}),
                            part["functionCall"].get("id") or "call_" + uuid4().hex,
                        )
                    )
        normalized = {
            "input_tokens": usage.get("promptTokenCount", 0),
            "output_tokens": usage.get("candidatesTokenCount", 0)
            + usage.get("thoughtsTokenCount", 0),
        }
        return self.message(
            ["".join(texts)] if texts else [],
            calls,
            blocks,
            normalized,
            model_version,
            finish_reason == "STOP",
            finish_reason=finish_reason,
        )

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
        status = data.get("status")
        complete = status == "completed"
        details = data.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        return self.message(
            texts,
            calls,
            blocks,
            data.get("usage", {}),
            data.get("model"),
            complete,
            finish_reason=reason or status,
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
        stop_reason = data.get("stop_reason")
        complete = stop_reason in {"end_turn", "stop_sequence", "tool_use"}
        return self.message(
            texts,
            calls,
            blocks,
            data.get("usage", {}),
            data.get("model"),
            complete,
            finish_reason=stop_reason,
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
        finish_reason = candidate.get("finishReason")
        return self.message(
            texts,
            calls,
            blocks,
            normalized,
            data.get("modelVersion"),
            finish_reason == "STOP",
            finish_reason=finish_reason,
        )

    def message(self, texts, calls, blocks, usage, model, complete, *, finish_reason=None):
        if not complete:
            # Never execute partial tools or publish a token-limited/safety-blocked answer.
            LOGGER.warning(
                "Model response incomplete: protocol=%s model=%s finish_reason=%s "
                "max_tokens=%d input_tokens=%d output_tokens=%d calls=%d",
                self.settings.model_protocol,
                model or self.settings.deepseek_model,
                finish_reason or "unknown",
                self.max_tokens,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                len(calls),
            )
            detail = (
                "模型思考与输出达到长度上限而中止，请缩小范围或重试；未执行不完整的工具调用。"
                if str(finish_reason or "").lower() in {"max_tokens", "max_output_tokens"}
                else "模型回答未完整生成或被服务商中止；未执行不完整的工具调用。"
            )
            raise ServiceError(502, "model_incomplete_response", detail)
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
