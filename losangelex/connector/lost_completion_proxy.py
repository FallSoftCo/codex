"""Disposable real-HTTP fault: commit completion upstream, then lose its reply."""
import argparse
import json
from pathlib import Path

from aiohttp import ClientSession, web


def application(receipt):
    async def forward(request):
        data = await request.read()
        async with ClientSession() as client:
            async with client.request(request.method, "http://127.0.0.1:18768" + request.raw_path,
                                      data=data or None, headers={k: v for k, v in request.headers.items()
                                                               if k.lower() in ("authorization", "content-type")}) as upstream:
                body = await upstream.read()
                if request.method == "POST" and request.path.endswith("/transition") and upstream.status == 200:
                    payload = json.loads(data)
                    if payload["state"] == "completed" and not receipt.exists():
                        receipt.write_text(json.dumps({"state": "completion-committed-reply-lost", "request": payload,
                                                       "upstreamReceipt": json.loads(body)}, indent=2))
                        receipt.chmod(0o600)
                        return web.json_response({"error": "Injected lost completion acknowledgement"}, status=503)
                return web.Response(body=body, status=upstream.status, content_type="application/json")
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", forward)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    web.run_app(application(args.receipt), host="127.0.0.1", port=18769, access_log=None)
