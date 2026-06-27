"""zvec 集合生命周期管理"""
from pathlib import Path

import zvec

# 集合存储路径
COLLECTION_PATH = str(Path(__file__).resolve().parent.parent.parent / "data" / "patent_db")
COLLECTION_NAME = "patents"

# 模块级单例（懒初始化）
_collection: zvec.Collection | None = None


def _build_schema(dimension: int = 512) -> zvec.CollectionSchema:
    """构建专利集合的 schema（三向量：标题摘要 + 说明书 + 权利要求）"""
    return zvec.CollectionSchema(
        name=COLLECTION_NAME,
        fields=[
            zvec.FieldSchema("patent_no", zvec.DataType.STRING),
            zvec.FieldSchema("applicant", zvec.DataType.STRING),
            zvec.FieldSchema("title", zvec.DataType.STRING),
            zvec.FieldSchema("abstract", zvec.DataType.STRING),
            zvec.FieldSchema("description", zvec.DataType.STRING),
            zvec.FieldSchema("claims", zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema(
                "title_abs_vec",
                zvec.DataType.VECTOR_FP32,
                dimension=dimension,
                index_param=zvec.HnswIndexParam(
                    metric_type=zvec.MetricType.COSINE,
                ),
            ),
            zvec.VectorSchema(
                "desc_vec",
                zvec.DataType.VECTOR_FP32,
                dimension=dimension,
                index_param=zvec.HnswIndexParam(
                    metric_type=zvec.MetricType.COSINE,
                ),
            ),
            zvec.VectorSchema(
                "claims_vec",
                zvec.DataType.VECTOR_FP32,
                dimension=dimension,
                index_param=zvec.HnswIndexParam(
                    metric_type=zvec.MetricType.COSINE,
                ),
            ),
        ],
    )


def get_or_create_collection(dimension: int = 512) -> zvec.Collection:
    """获取或创建集合（懒初始化单例）

    如果路径已存在则打开，否则创建并打开。
    """
    global _collection
    if _collection is not None:
        return _collection

    collection_path = Path(COLLECTION_PATH)
    if collection_path.exists():
        _collection = zvec.open(COLLECTION_PATH)
    else:
        schema = _build_schema(dimension)
        collection_path.parent.mkdir(parents=True, exist_ok=True)
        _collection = zvec.create_and_open(COLLECTION_PATH, schema)

    return _collection


def get_collection() -> zvec.Collection | None:
    """打开已有集合，不存在则返回 None"""
    global _collection
    if _collection is not None:
        return _collection

    collection_path = Path(COLLECTION_PATH)
    if collection_path.exists():
        _collection = zvec.open(COLLECTION_PATH)
        return _collection

    return None
