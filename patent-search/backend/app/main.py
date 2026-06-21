"""专利语义搜索系统 - FastAPI 后端应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import config, upload, import_data, search

app = FastAPI(title="专利语义搜索系统", version="0.1.0")

# 跨域配置（开发环境允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(config.router)
app.include_router(upload.router)
app.include_router(import_data.router)
app.include_router(search.router)


@app.get("/api/healthz")
async def healthz():
    """健康检查接口"""
    return {"status": "ok"}
