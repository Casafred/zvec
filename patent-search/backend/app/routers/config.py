"""配置相关路由"""
import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field
from openai import OpenAI

router = APIRouter(prefix="/api/config", tags=["配置"])

# 配置文件路径
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 默认配置值
DEFAULT_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"


class ConfigRequest(BaseModel):
    """配置请求模型"""
    api_key: str = Field(..., description="API 密钥")
    model_name: str = Field(default=DEFAULT_MODEL_NAME, description="模型名称")
    base_url: str = Field(default=DEFAULT_BASE_URL, description="API 地址")


class ConfigResponse(BaseModel):
    """配置响应模型（脱敏）"""
    api_key: str = Field(..., description="脱敏后的 API 密钥")
    model_name: str = Field(..., description="模型名称")
    base_url: str = Field(..., description="API 地址")


class ValidateResponse(BaseModel):
    """验证响应模型"""
    valid: bool = Field(..., description="是否验证通过")
    error: str | None = Field(default=None, description="错误信息")
    dimension: int | None = Field(default=None, description="向量维度")


def _ensure_config_dir():
    """确保配置目录存在"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_config_raw() -> dict | None:
    """读取原始配置（未脱敏）"""
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _mask_api_key(api_key: str) -> str:
    """脱敏 API 密钥，仅显示最后 4 位"""
    if len(api_key) <= 4:
        return "****"
    return "*" * (len(api_key) - 4) + api_key[-4:]


@router.post("", response_model=ConfigResponse)
async def save_config(req: ConfigRequest):
    """保存配置到本地 JSON 文件"""
    _ensure_config_dir()
    config_data = req.model_dump()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)
    return ConfigResponse(
        api_key=_mask_api_key(req.api_key),
        model_name=req.model_name,
        base_url=req.base_url,
    )


@router.get("", response_model=ConfigResponse)
async def get_config():
    """读取配置，API 密钥脱敏后返回"""
    config = _read_config_raw()
    if config is None:
        return ConfigResponse(
            api_key="",
            model_name=DEFAULT_MODEL_NAME,
            base_url=DEFAULT_BASE_URL,
        )
    return ConfigResponse(
        api_key=_mask_api_key(config.get("api_key", "")),
        model_name=config.get("model_name", DEFAULT_MODEL_NAME),
        base_url=config.get("base_url", DEFAULT_BASE_URL),
    )


@router.post("/validate", response_model=ValidateResponse)
async def validate_config():
    """验证已保存的 API 配置，调用 embedding 接口测试连通性"""
    config = _read_config_raw()
    if config is None:
        return ValidateResponse(valid=False, error="未找到配置，请先保存配置")

    api_key = config.get("api_key", "")
    model_name = config.get("model_name", DEFAULT_MODEL_NAME)
    base_url = config.get("base_url", DEFAULT_BASE_URL)

    if not api_key:
        return ValidateResponse(valid=False, error="API 密钥为空，请先配置")

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.embeddings.create(
            model=model_name,
            input="测试",
            dimensions=512,
        )
        dimension = len(response.data[0].embedding)
        return ValidateResponse(valid=True, dimension=dimension)
    except Exception as e:
        return ValidateResponse(valid=False, error=str(e))
