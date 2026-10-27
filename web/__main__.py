"""Start the web service from the unified project environment."""

import os
import uvicorn


def main():
    uvicorn.run("web.app:app", host=os.environ.get("HOK_WEB_HOST", "127.0.0.1"),
                port=int(os.environ.get("HOK_WEB_PORT", "8000")))


if __name__ == "__main__":
    main()
