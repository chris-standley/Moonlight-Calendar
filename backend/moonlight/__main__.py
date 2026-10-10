import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "moonlight.main:app",
        host=os.environ.get("MOONLIGHT_HOST", "0.0.0.0"),
        port=int(os.environ.get("MOONLIGHT_PORT", "8091")),
        log_level=os.environ.get("MOONLIGHT_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
