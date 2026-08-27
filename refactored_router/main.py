import sys
import os
import uuid
import time
import uvicorn
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from .settings import config
from .stats import provider_stats_service
from .rotation import rotation_service
from .provider_api import provider_client
from .ui import dashboard
from .schema import CallRecord
from .legacy import legacy_router, run_health_checks


def _provider_available(provider: dict) -> bool:
    """环境变量 key 已配置 + 未限流(或冷却已过) + 未熔断"""
    if not os.getenv(provider["api_key_env"]):
        return False
    return provider_stats_service.is_available(provider["name"])


async def run_provider_health_checks():
    for provider in config.PROVIDERS:
        if not os.getenv(provider["api_key_env"]):
            continue
        ok, err = await provider_client.health_check(provider)
        st = provider_stats_service.stats.get(provider["name"], {})

        if ok:
            st["is_limited"] = False
            st["limited_since"] = 0
            provider_stats_service.record_success(provider["name"])
        elif "429" in err:
            provider_stats_service.mark_limited(provider["name"])

        provider_stats_service.save_stats()


@asynccontextmanager
async def lifespan(app: FastAPI):
    dashboard.start()
    print(f"Server is running on port {config.PORT}...")
    # 老路由探测：与改造前一致无条件执行（Vercel/Mangum 下 lifespan 不运行，行为不变）
    asyncio.create_task(run_health_checks())
    # 新路由探测：受 HEALTH_PROBE 开关控制（默认本地开、Vercel 关，避免冷启动消耗免费额度）
    if config.HEALTH_PROBE:
        asyncio.create_task(run_provider_health_checks())
    yield
    dashboard.stop()


app = FastAPI(title="多提供商智能路由 (Multi-Provider Router)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 老的单提供商路由原样保留在 /old 前缀下
app.include_router(legacy_router, prefix="/old")


@app.get("/")
async def root():
    return {
        "message": "Multi-Provider Router API",
        "endpoints": ["/v1/chat/completions", "/v1/models", "/health"],
        "legacy": ["/old/v1/chat/completions", "/old/v1/models", "/old/health"],
    }


@app.get("/v1/models")
async def list_models(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if config.TOKEN and auth_header != f"Bearer {config.TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": config.ROUTER_ALIAS,
                "object": "model",
                "created": now,
                "owned_by": "provider-router",
                "name": config.ROUTER_ALIAS,
            }
        ],
    }


@app.get("/health")
async def health():
    snapshot = provider_stats_service.get_snapshot()
    return {
        "status": "ok",
        "rotation": rotation_service.get_state(),
        "providers": [
            {
                "name": p["name"],
                "model_id": p["model_id"],
                "base_url": p["base_url"],
                "quota": p.get("quota", config.ROTATION_QUOTA),
                "api_key_env": p["api_key_env"],
                "key_configured": bool(os.getenv(p["api_key_env"])),
                "available": _provider_available(p),
                "stats": snapshot["stats"].get(p["name"], {}),
            }
            for p in config.PROVIDERS
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if config.TOKEN and auth_header != f"Bearer {config.TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    try:
        body = await request.json()
        req_model = body.get("model")
        is_stream = body.get("stream", False)

        dashboard.log_request(req_model, is_stream)

        providers = config.PROVIDERS
        n = len(providers)
        if n == 0:
            dashboard.log_error("No providers configured!")
            raise HTTPException(status_code=503, detail="没有提供商配置")

        if req_model == config.ROUTER_ALIAS:
            # 轮换游标：当前值日提供商不可用时让出本轮，移到下一个可用者
            moved = 0
            while moved < n and not _provider_available(
                providers[rotation_service.cursor % n]
            ):
                rotation_service.advance()
                moved += 1
            if moved >= n:
                dashboard.log_error("No providers available!")
                raise HTTPException(status_code=503, detail="没有可用的提供商")
            start = rotation_service.cursor % n
        else:
            # 直接指定某提供商的 model_id：从该配置开始尝试（不移动游标）
            start = next(
                (i for i, p in enumerate(providers) if p["model_id"] == req_model),
                None,
            )
            if start is None:
                raise HTTPException(status_code=502, detail="路由失败: No providers tried")

        last_error = "No providers tried"

        for i in range(n):
            provider = providers[(start + i) % n]
            if not _provider_available(provider):
                continue

            dashboard.log_attempt(provider["name"])

            success, response, error_msg, is_limited = await provider_client.call_provider(
                provider, body, is_stream
            )

            if is_limited:
                record = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    model_name=provider["name"],
                    success=False,
                    response_time=0.1,
                    error_message="429 rate limit",
                )
                provider_stats_service.record_call(record)
                dashboard.log_result(record, provider_stats_service, show_limit=False)

            if success:
                return response

            if not is_limited:
                record = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    model_name=provider["name"],
                    success=False,
                    response_time=0.1,
                    error_message=error_msg,
                )
                provider_stats_service.record_call(record)
                dashboard.log_result(record, provider_stats_service, show_limit=False)

            last_error = error_msg
            continue

        raise HTTPException(status_code=502, detail=f"路由失败: {last_error}")

    except HTTPException:
        raise
    except Exception as e:
        dashboard.log_error(str(e))
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # 建议在上一级目录使用 python -m refactored_router.main 运行
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="error")
