"""本地嵌入编码器：替换 Co-STORM 的 Encoder（DeepSeek 无 embedding API）。

背景（2026-11-20 读源码实证；2026-11-21 全量核查补证）：
knowledge_storm.encoder.Encoder 强制 ENCODER_API_TYPE=openai/azure，
调 text-embedding-3-small。DeepSeek 官方 API 文档截至 2026-11-21 未提供
embedding 接口（证据链与终验命令见 _系统迭代/DeepSeek_API能力清单.md）。
为守住"脑和手都 DeepSeek，一个 key"，用 knowledge-storm 自带依赖
sentence-transformers 做本地嵌入。

用法（在自己的脚本里替换，零 fork）：
    import knowledge_storm.collaborative_storm.engine as cs_engine
    cs_engine.Encoder = LocalEncoder
首次运行会从 HuggingFace 下载模型（约 60MB）；
国内网络可设 HF_ENDPOINT=https://hf-mirror.com。
"""

from typing import List, Union

import numpy as np

# 本机网络 HF/hf-mirror 均不可达（2026-11-21 实测），模型从 ModelScope 下载到本地目录
_LOCAL_MODEL = __import__("pathlib").Path(__file__).resolve().parent.parent / "models" / "all-MiniLM-L6-v2"


class LocalEncoder:
    def __init__(self, model_name: str = None, **kwargs):
        from sentence_transformers import SentenceTransformer

        model_name = model_name or (str(_LOCAL_MODEL) if _LOCAL_MODEL.exists()
                                    else "sentence-transformers/all-MiniLM-L6-v2")
        self.model = SentenceTransformer(model_name)
        self.total_token_usage = 0  # 本地嵌入不耗 API token

    def get_total_token_usage(self, reset: bool = False) -> int:
        usage = self.total_token_usage
        if reset:
            self.total_token_usage = 0
        return usage

    def encode(self, texts: Union[str, List[str]], max_workers: int = 5) -> np.ndarray:
        # 与官方 Encoder.encode 语义一致：str → 1D 向量；list → 2D 矩阵
        if isinstance(texts, str):
            return np.array(self.model.encode([texts])[0])
        return np.array(self.model.encode(list(texts)))
