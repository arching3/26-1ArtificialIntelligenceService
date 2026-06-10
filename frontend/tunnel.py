from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from pyngrok import ngrok
from dotenv import load_dotenv
load_dotenv()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expose the Streamlit app through ngrok.")
    parser.add_argument("--port", type=int, default=8501, help="Local Streamlit port.")
    parser.add_argument(
        "--url-file",
        type=Path,
        help="File where the ngrok public URL will be written.",
    )
    return parser.parse_args()


def write_url(path: Path, public_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(f"{public_url}\n", encoding="utf-8")
    temporary_path.replace(path)


def main() -> int:
    args = parse_args()
    tunnel = None

    try:
        tunnel = ngrok.connect(addr=str(args.port), proto="http", bind_tls=True)
        public_url = tunnel.public_url
        if args.url_file:
            write_url(args.url_file, public_url)

        print(f"ngrok public URL: {public_url}", flush=True)

        def stop_tunnel(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop_tunnel)
        signal.signal(signal.SIGINT, stop_tunnel)

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"failed to start ngrok tunnel: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        try:
            if tunnel is not None:
                ngrok.disconnect(tunnel.public_url)
        except Exception as exc:
            print(f"failed to disconnect ngrok tunnel: {exc}", file=sys.stderr, flush=True)
        if args.url_file:
            args.url_file.unlink(missing_ok=True)
        try:
            ngrok.kill()
        except Exception as exc:
            print(f"failed to stop ngrok process: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
