"""持久化同步：DATA_DIR ↔ 私有 HF dataset（或本地-only 模式）。

红线：.env / 任何密钥文件绝不同步；仅同步业务数据（sqlite、reports、discussions、
solutions、taskcards、legacy、joblogs）。单写者锁；启动先 pull 恢复，写后 push，
另有周期兜底 push。HF_TOKEN 未配置时退化为本地持久盘模式（Plan B / 本地开发）。
"""
import hashlib
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("cloud_store")

# 绝不上传的文件名/目录片段
_EXCLUDE_NAMES = {".env", ".env.local", "secrets.json"}
_EXCLUDE_PARTS = {"__pycache__", ".git", ".ipynb_checkpoints"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CloudStore:
    def __init__(self, data_dir, repo=None, token=None):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.repo = repo or ""
        self.token = token or ""
        self.lock = threading.RLock()
        self._hashes = {}
        self._api = None
        if self.repo and self.token:
            try:
                from huggingface_hub import HfApi
                self._api = HfApi(token=self.token)
            except Exception as e:  # noqa: BLE001
                log.warning("huggingface_hub 不可用，退化本地模式: %s", e)

    @property
    def enabled(self):
        return self._api is not None and bool(self.repo)

    @property
    def mode(self):
        return "hf-dataset" if self.enabled else "local-disk"

    def _iter_files(self):
        for p in sorted(self.data.rglob("*")):
            if not p.is_file():
                continue
            if p.name in _EXCLUDE_NAMES:
                continue
            if any(part in _EXCLUDE_PARTS for part in p.parts):
                continue
            yield p

    def pull(self):
        """启动恢复：把 dataset 中已有文件下载到 DATA_DIR（不覆盖本地已存在文件）。"""
        if not self.enabled:
            log.info("持久化=本地盘 %s（未配置 HF dataset）", self.data)
            return
        from huggingface_hub import hf_hub_download
        self._api.create_repo(self.repo, repo_type="dataset", private=True, exist_ok=True)
        files = self._api.list_repo_files(self.repo, repo_type="dataset")
        n = 0
        for rel in files:
            name = Path(rel).name
            if name in _EXCLUDE_NAMES or any(part in _EXCLUDE_PARTS for part in Path(rel).parts):
                continue
            local = self.data / rel
            if local.exists():
                self._hashes[rel] = _sha(local)
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            hf_hub_download(self.repo, rel, repo_type="dataset",
                            local_dir=str(self.data), token=self.token)
            if local.exists():
                self._hashes[rel] = _sha(local)
                n += 1
        log.info("持久化恢复：从 %s 拉取 %d 个文件", self.repo, n)

    def push(self):
        """把 DATA_DIR 中新增/变更文件上传 dataset（按 sha 去重）。"""
        if not self.enabled:
            return
        with self.lock:
            for p in self._iter_files():
                rel = p.relative_to(self.data).as_posix()
                try:
                    h = _sha(p)
                except OSError:
                    continue
                if self._hashes.get(rel) == h:
                    continue
                try:
                    self._api.upload_file(path_or_fileobj=str(p), path_in_repo=rel,
                                          repo_id=self.repo, repo_type="dataset")
                    self._hashes[rel] = h
                except Exception as e:  # noqa: BLE001
                    log.warning("上传 %s 失败（下轮重试）: %s", rel, e)

    def start_background(self, interval=45):
        if not self.enabled:
            return

        def loop():
            while True:
                time.sleep(interval)
                try:
                    self.push()
                except Exception as e:  # noqa: BLE001
                    log.warning("周期同步异常: %s", e)

        threading.Thread(target=loop, daemon=True, name="cloud-sync").start()
