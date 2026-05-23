"""Entry point for the bundled desktop agent.

PyInstaller uses this as the main module. Calls uvicorn programmatically
instead of going through the CLI so we don't depend on its argv parser.
"""
import uvicorn

from flowboard.config import HTTP_PORT


def main() -> None:
    uvicorn.run(
        "flowboard.main:app",
        host="127.0.0.1",
        port=HTTP_PORT,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
