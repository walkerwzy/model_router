import uuid
import time
from fastapi import APIRouter, HTTPException, Request

from .settings import config
from .stats import stats_service
from .network import api_client
from .ui import dashboard
from .schema import CallRecord

# 老的单提供商路由（ModelScope 全局 key + level 优先级），
# 原样冻结，由 main.py 以 /old 前缀挂载。


async def run_health_checks():
    for model in config.MODELS:
        ok, err = await api_client.health_check(model)
        st = stats_service.stats.get(model["name"], {})

        if ok:
            st["is_limited"] = False
            stats_service.record_success(model["name"])
        else:
            if "429" in err:
                st["is_limited"] = True

        stats_service.save_stats()


legacy_router = APIRouter()


@legacy_router.get("/")
async def root():
    return {"message": "ModelScope Router API", "endpoints": ["/v1/chat/completions", "/v1/models"]}


@legacy_router.get("/v1/models")
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
                "owned_by": "modelscope-router",
                "name": config.ROUTER_ALIAS,
            }
        ],
    }


@legacy_router.get("/health")
async def health():
    stats = stats_service.get_snapshot()
    models = stats_service.get_available_models()
    return {
        "status": "ok",
        "available_models": len(models),
        "stats": stats["stats"],
        "limits": stats["limits"],
    }


@legacy_router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if config.TOKEN and auth_header != f"Bearer {config.TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    try:
        body = await request.json()
        req_model = body.get("model")
        is_stream = body.get("stream", False)

        dashboard.log_request(req_model, is_stream)

        candidates = stats_service.get_available_models()
        if not candidates:
            dashboard.log_error("No models available!")
            raise HTTPException(status_code=503, detail="没有可用的模型")

        last_error = "No models tried"

        for model in candidates:
            is_alias = req_model == config.ROUTER_ALIAS
            is_match = is_alias or req_model == model["model_id"]
            if not is_match:
                continue

            dashboard.log_attempt(model["name"])

            success, response, error_msg, is_limited = await api_client.call_model(
                model, body, is_stream
            )

            if is_limited:
                record = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    model_name=model["name"],
                    success=False,
                    response_time=0.1,
                    error_message="429 rate limit",
                )
                stats_service.record_call(record)
                dashboard.log_result(record)

            if success:
                return response

            if not is_limited:
                record = CallRecord(
                    id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    model_name=model["name"],
                    success=False,
                    response_time=0.1,
                    error_message=error_msg,
                )
                stats_service.record_call(record)
                dashboard.log_result(record)

            last_error = error_msg
            continue

        raise HTTPException(status_code=502, detail=f"路由失败: {last_error}")

    except HTTPException:
        raise
    except Exception as e:
        dashboard.log_error(str(e))
        raise HTTPException(status_code=500, detail=str(e))
