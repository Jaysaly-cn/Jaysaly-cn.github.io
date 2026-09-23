"""Adapted from this portfolio's SupportOps single-team local service guard."""
import hmac
import os
import time
from collections import deque
from fastapi.responses import JSONResponse


def install(app):
    history = deque()

    @app.middleware('http')
    async def guard(request, call_next):
        if request.url.path.startswith('/api/'):
            isolated = request.scope.get('isolated_demo_session') is True
            token = os.getenv('MEETINGACTIONS_ACCESS_TOKEN', '')
            supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
            if not isolated and token and not hmac.compare_digest(token, supplied):
                return JSONResponse({'detail': '请输入工作台访问令牌'}, status_code=401)
            if not isolated and not token and (not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient')
                              or request.url.hostname not in ('localhost', '127.0.0.1', '::1', 'testserver')):
                return JSONResponse({'detail': '远程工作台必须配置访问令牌'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '不允许跨站访问'}, status_code=403)
            if request.method not in ('GET', 'HEAD'):
                stamp = time.monotonic()
                while history and stamp - history[0] > 60:
                    history.popleft()
                if len(history) >= 60:
                    return JSONResponse({'detail': '请求过于频繁，请稍后重试'}, status_code=429)
                history.append(stamp)
                body = bytearray()
                async for part in request.stream():
                    if len(body) + len(part) > 400000:
                        return JSONResponse({'detail': '正文超过 400KB'}, status_code=413)
                    body.extend(part)
                request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

