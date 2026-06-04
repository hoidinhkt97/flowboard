from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = Path(os.getenv("FLOWBOARD_STORAGE", ROOT / "storage"))
DB_PATH = Path(os.getenv("FLOWBOARD_DB", STORAGE_DIR / "flowboard.db"))
DATABASE_URL = os.getenv("FLOWBOARD_DATABASE_URL", f"sqlite:///{DB_PATH}")

# --- Auth / security config ---
JWT_SECRET = os.getenv("FLOWBOARD_JWT_SECRET", "dev-insecure-jwt-secret-change-me")
JWT_ALG = "HS256"
ACCESS_TOKEN_TTL_MIN = int(os.getenv("FLOWBOARD_ACCESS_TTL_MIN", "15"))
REFRESH_TOKEN_TTL_DAYS = int(os.getenv("FLOWBOARD_REFRESH_TTL_DAYS", "30"))
DEVICE_TOKEN_TTL_DAYS = int(os.getenv("FLOWBOARD_DEVICE_TOKEN_TTL_DAYS", "90"))
# Fernet key (urlsafe-base64, 32 bytes). Empty in dev/tests → a fixed insecure
# dev key is derived in services/security.py so encryption round-trips locally.
ENCRYPTION_KEY = os.getenv("FLOWBOARD_ENCRYPTION_KEY", "")

HTTP_PORT = int(os.getenv("FLOWBOARD_HTTP_PORT", "8101"))

PLANNER_MODEL = os.getenv("FLOWBOARD_PLANNER_MODEL", "claude-sonnet-4-6")
# "cli" → always use claude CLI; "mock" → always mock; "auto" → CLI if available,
# otherwise mock. Default auto.
PLANNER_BACKEND = os.getenv("FLOWBOARD_PLANNER_BACKEND", "auto")

# S3-compatible object storage (optional — omit to keep using local disk)
S3_ENDPOINT   = os.getenv("FLOWBOARD_S3_ENDPOINT")    # e.g. https://s3.amazonaws.com or MinIO URL
S3_BUCKET     = os.getenv("FLOWBOARD_S3_BUCKET")      # bucket name; must be set to enable S3
S3_ACCESS_KEY = os.getenv("FLOWBOARD_S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("FLOWBOARD_S3_SECRET_KEY")
S3_REGION     = os.getenv("FLOWBOARD_S3_REGION", "auto")

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
