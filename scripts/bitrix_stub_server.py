import asyncio
import json
from aiohttp import web

async def install(request: web.Request):
    try:
        data = await request.post()
        payload = dict(data)
    except Exception:
        payload = {}
    print("ONAPPINSTALL payload:", payload)
    return web.json_response({"ok": True})

async def oauth_callback(request: web.Request):
    params = dict(request.query)
    print("OAUTH CALLBACK query:", params)
    return web.Response(
        text="OK. Code received. You can close this tab.",
        content_type="text/plain",
    )

def create_app():
    app = web.Application()
    app.router.add_route("*", "/bitrix/install", install)
    app.router.add_route("*", "/bitrix/oauth/callback", oauth_callback)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8090)
