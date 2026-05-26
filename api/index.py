"""Vercel Python runtime entry point.

Vercel が file path `/api/index.py` を見つけて、その中の `app` (ASGI) を起動する。
ルートパス `/` から `*` まで全部を FastAPI app に流すために vercel.json の rewrites で対応。
"""
from src.web.app import app  # noqa: F401  (re-exported for Vercel)
