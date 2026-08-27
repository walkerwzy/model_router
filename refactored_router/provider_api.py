import os
import time
import uuid
import httpx
import json
from typing import Tuple, Any
from fastapi.responses import StreamingResponse, JSONResponse
from .schema import CallRecord
from .stats import provider_stats_service
from .rotation import rotation_service
from .ui import dashboard

# 探测配置
HEALTH_CHECK_PROMPT = [{"role": "user", "content": "hi"}]


class ProviderAPIClient:
    """多提供商网络层：每条配置自带 base_url 与 api_key 环境变量。

    结构与 network.py 对齐（含流式包装与健康探测），但老模块保持冻结，
    保证 /old 链路字节级不变。
    """

    def _headers(self, provider: dict) -> dict:
        return {
            "Authorization": f"Bearer {os.getenv(provider['api_key_env'], '')}",
            "Content-Type": "application/json",
        }

    def _url(self, provider: dict) -> str:
        return f"{provider['base_url'].rstrip('/')}/chat/completions"

    async def call_provider(
        self, provider: dict, payload: dict, is_stream: bool
    ) -> Tuple[bool, Any, str, bool]:
        provider_name = provider["name"]

        current_payload = payload.copy()
        current_payload["model"] = provider["model_id"]

        start_time = time.time()
        client = httpx.AsyncClient(timeout=60.0)

        try:
            request_obj = client.build_request(
                "POST",
                self._url(provider),
                json=current_payload,
                headers=self._headers(provider),
            )

            response = await client.send(request_obj, stream=True)

            if response.status_code != 200:
                error_text = await response.aread()
                await client.aclose()
                error_msg = f"HTTP {response.status_code}: {error_text.decode('utf-8', errors='ignore')[:100]}"
                is_limited = response.status_code == 429
                return False, None, error_msg, is_limited

            if is_stream:
                record_template = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=start_time,
                    model_name=provider_name,
                    success=False,
                    response_time=0,
                )

                return (
                    True,
                    StreamingResponse(
                        self._stream_wrapper(client, response, record_template),
                        media_type="text/event-stream",
                    ),
                    "",
                    False,
                )
            else:
                data = await response.aread()
                await client.aclose()

                duration = time.time() - start_time
                record = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=start_time,
                    model_name=provider_name,
                    success=True,
                    response_time=duration,
                )
                provider_stats_service.record_call(record)
                rotation_service.record_success(provider_name)
                dashboard.log_result(record, provider_stats_service, show_limit=False)

                return True, JSONResponse(json.loads(data)), "", False

        except Exception as e:
            await client.aclose()
            return False, None, str(e), False

    async def _stream_wrapper(
        self, client: httpx.AsyncClient, response: httpx.Response, record: CallRecord
    ):
        """包装流式响应以监控完成状态；流正常结束才计成功并消耗轮换配额"""
        try:
            async for chunk in response.aiter_bytes():
                yield chunk

            record.response_time = time.time() - record.timestamp
            record.success = True
            provider_stats_service.record_call(record)
            rotation_service.record_success(record.model_name)
            dashboard.log_result(record, provider_stats_service, show_limit=False)

        except Exception as e:
            record.error_message = f"Stream broken: {str(e)}"
            record.response_time = time.time() - record.timestamp
            provider_stats_service.record_call(record)
            dashboard.log_result(record, provider_stats_service, show_limit=False)
            raise e
        finally:
            await client.aclose()

    async def health_check(self, provider: dict) -> Tuple[bool, str]:
        """健康探测（用该配置自己的 base_url / key）"""
        payload = {
            "model": provider["model_id"],
            "messages": HEALTH_CHECK_PROMPT,
            "max_tokens": 1,
        }

        client = httpx.AsyncClient(timeout=10.0)

        try:
            request_obj = client.build_request(
                "POST",
                self._url(provider),
                json=payload,
                headers=self._headers(provider),
            )

            response = await client.send(request_obj)
            await client.aclose()

            if response.status_code == 200:
                return True, ""
            elif response.status_code == 429:
                return False, "429 rate limit"
            else:
                text = response.text[:50]
                return False, f"HTTP {response.status_code}: {text}"

        except Exception as e:
            await client.aclose()
            return False, str(e)


provider_client = ProviderAPIClient()
