import sys
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
from .stats import stats_service
from .network import api_client
from .ui import dashboard
from .schema import CallRecord


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    dashboard.start()
    print(f"Server is running on port {config.PORT}...")
    asyncio.create_task(run_health_checks())
    yield
    dashboard.stop()


app = FastAPI(title="ModelScope 智能路由 (Refactored)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "ModelScope Router API", "endpoints": ["/v1/chat/completions"]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
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


if __name__ == "__main__":
    # 建议在上一级目录使用 python -m refactored_router.main 运行
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level="error")
