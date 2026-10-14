import argparse
from pathlib import Path

import uvicorn
import yaml

from .server import create_app


def main():
    parser = argparse.ArgumentParser(
        description="Run the external local UI adapter for agent_runtime"
    )
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--config", default=str(Path(__file__).parents[1] / "config.yaml")
    )
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text()).get("LocalAgent", {})
    uvicorn.run(
        create_app(config_path=args.config),
        host="127.0.0.1",
        port=args.port or config.get("port", 8765),
        log_level="info",
    )


if __name__ == "__main__":
    main()
