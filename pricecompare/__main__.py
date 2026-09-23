"""Usage:
    python -m pricecompare update [--out web/data.json]
    python -m pricecompare images [--cache .cache/thumbs]
    python -m pricecompare serve  [--port 8000]
"""

import argparse
import functools
import http.server
import os

from . import build

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def main():
    parser = argparse.ArgumentParser(prog="pricecompare")
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("update", help="download current prices for the region")
    up.add_argument("--out", default=os.path.join(WEB_DIR, "data.json"))
    im = sub.add_parser("images", help="build product thumbnails for the web app")
    im.add_argument("--cache", default=os.path.join(os.path.dirname(WEB_DIR), ".cache", "thumbs"))
    sv = sub.add_parser("serve", help="serve the web app")
    sv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.cmd == "update":
        build.main(args.out)
    elif args.cmd == "images":
        import logging
        from . import images
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        images.build_images(os.path.join(WEB_DIR, "data.json"), os.path.join(WEB_DIR, "img"), args.cache)
    else:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=WEB_DIR)
        print(f"http://localhost:{args.port}")
        http.server.ThreadingHTTPServer(("", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
