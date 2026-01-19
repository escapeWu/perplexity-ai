"""
Admin, pool management, and heartbeat routes.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse

from .app import mcp, get_pool


# 健康检查端点 (不需要认证)
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """健康检查接口，用于监控服务状态，包含号池摘要"""
    pool = get_pool()
    status = pool.get_status()
    return JSONResponse({
        "status": "healthy",
        "service": "perplexity-mcp",
        "pool": {
            "total": status["total"],
            "available": status["available"],
        }
    })


# 号池状态查询端点 (不需要认证)
@mcp.custom_route("/pool/status", methods=["GET"])
async def pool_status(request: Request) -> JSONResponse:
    """号池状态查询接口，返回详细的token池运行时状态"""
    pool = get_pool()
    return JSONResponse(pool.get_status())


# 号池管理 API 端点 (用于前端管理页面)
@mcp.custom_route("/pool/{action}", methods=["POST"])
async def pool_api(request: Request) -> JSONResponse:
    """号池管理 API 接口，供前端管理页面调用"""
    from perplexity.config import ADMIN_TOKEN

    action = request.path_params.get("action")
    pool = get_pool()

    try:
        body = await request.json()
    except Exception:
        body = {}

    # 需要认证的操作列表
    protected_actions = {"add", "remove", "enable", "disable", "reset"}

    # 验证 admin token
    if action in protected_actions:
        if not ADMIN_TOKEN:
            return JSONResponse({
                "status": "error",
                "message": "Admin token not configured. Set PPLX_ADMIN_TOKEN environment variable."
            }, status_code=403)

        # 从 header 或 body 中获取 token
        provided_token = request.headers.get("X-Admin-Token") or body.get("admin_token")

        if not provided_token:
            return JSONResponse({
                "status": "error",
                "message": "Authentication required. Provide admin token."
            }, status_code=401)

        if provided_token != ADMIN_TOKEN:
            return JSONResponse({
                "status": "error",
                "message": "Invalid admin token."
            }, status_code=401)

    client_id = body.get("id")
    csrf_token = body.get("csrf_token")
    session_token = body.get("session_token")

    if action == "list":
        return JSONResponse(pool.list_clients())
    elif action == "add":
        if not all([client_id, csrf_token, session_token]):
            return JSONResponse({"status": "error", "message": "Missing required parameters"})
        return JSONResponse(pool.add_client(client_id, csrf_token, session_token))
    elif action == "remove":
        if not client_id:
            return JSONResponse({"status": "error", "message": "Missing required parameter: id"})
        return JSONResponse(pool.remove_client(client_id))
    elif action == "enable":
        if not client_id:
            return JSONResponse({"status": "error", "message": "Missing required parameter: id"})
        return JSONResponse(pool.enable_client(client_id))
    elif action == "disable":
        if not client_id:
            return JSONResponse({"status": "error", "message": "Missing required parameter: id"})
        return JSONResponse(pool.disable_client(client_id))
    elif action == "reset":
        if not client_id:
            return JSONResponse({"status": "error", "message": "Missing required parameter: id"})
        return JSONResponse(pool.reset_client(client_id))
    else:
        return JSONResponse({"status": "error", "message": f"Unknown action: {action}"})


# 管理页面路由 - 服务 Vite 构建的静态文件
@mcp.custom_route("/admin", methods=["GET"])
async def admin_page(request: Request):
    """管理页面 - 重定向到 /admin/"""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/admin/", status_code=302)


@mcp.custom_route("/admin/", methods=["GET"])
async def admin_page_index(request: Request):
    """管理页面入口"""
    from starlette.responses import FileResponse
    import pathlib
    dist_path = pathlib.Path(__file__).parent / "web" / "dist" / "index.html"
    return FileResponse(dist_path, media_type="text/html")


@mcp.custom_route("/admin/{path:path}", methods=["GET"])
async def admin_static(request: Request):
    """服务静态资源文件"""
    from starlette.responses import FileResponse, Response
    import pathlib
    import mimetypes

    path = request.path_params.get("path", "")
    dist_dir = pathlib.Path(__file__).parent / "web" / "dist"
    file_path = dist_dir / path

    # 安全检查：确保路径在 dist 目录内
    try:
        file_path = file_path.resolve()
        dist_dir = dist_dir.resolve()
        if not str(file_path).startswith(str(dist_dir)):
            return Response("Forbidden", status_code=403)
    except Exception:
        return Response("Bad Request", status_code=400)

    # 如果文件存在，返回文件
    if file_path.is_file():
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(file_path, media_type=mime_type or "application/octet-stream")

    # 对于 SPA 路由，返回 index.html
    index_path = dist_dir / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")

    return Response("Not Found", status_code=404)


# ==================== Playground 页面路由 ====================

@mcp.custom_route("/playground", methods=["GET"])
async def playground_page(request: Request):
    """Playground 页面 - 重定向到 /playground/"""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/playground/", status_code=302)


@mcp.custom_route("/playground/", methods=["GET"])
async def playground_page_index(request: Request):
    """Playground 页面入口"""
    from starlette.responses import FileResponse
    import pathlib
    dist_path = pathlib.Path(__file__).parent / "web" / "dist" / "index.html"
    return FileResponse(dist_path, media_type="text/html")


@mcp.custom_route("/playground/{path:path}", methods=["GET"])
async def playground_static(request: Request):
    """服务 Playground 静态资源文件"""
    from starlette.responses import FileResponse, Response
    import pathlib
    import mimetypes

    path = request.path_params.get("path", "")
    dist_dir = pathlib.Path(__file__).parent / "web" / "dist"
    file_path = dist_dir / path

    # 安全检查：确保路径在 dist 目录内
    try:
        file_path = file_path.resolve()
        dist_dir = dist_dir.resolve()
        if not str(file_path).startswith(str(dist_dir)):
            return Response("Forbidden", status_code=403)
    except Exception:
        return Response("Bad Request", status_code=400)

    # 如果文件存在，返回文件
    if file_path.is_file():
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(file_path, media_type=mime_type or "application/octet-stream")

    # 对于 SPA 路由，返回 index.html
    index_path = dist_dir / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")

    return Response("Not Found", status_code=404)


# ==================== Heartbeat API 端点 ====================

@mcp.custom_route("/heartbeat/config", methods=["GET"])
async def heartbeat_config(request: Request) -> JSONResponse:
    """获取心跳配置"""
    pool = get_pool()
    return JSONResponse({
        "status": "ok",
        "config": pool.get_heartbeat_config()
    })


@mcp.custom_route("/heartbeat/config", methods=["POST"])
async def heartbeat_config_update(request: Request) -> JSONResponse:
    """更新心跳配置"""
    from perplexity.config import ADMIN_TOKEN

    if not ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Admin token not configured. Set PPLX_ADMIN_TOKEN environment variable."
        }, status_code=403)

    provided_token = request.headers.get("X-Admin-Token")
    if not provided_token or provided_token != ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Invalid or missing admin token."
        }, status_code=401)

    pool = get_pool()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({
            "status": "error",
            "message": "Invalid JSON body"
        }, status_code=400)

    result = pool.update_heartbeat_config(body)

    # Send Telegram notification if configured
    if result.get("status") == "ok":
        config = result.get("config", {})
        if config.get("tg_bot_token") and config.get("tg_chat_id"):
            await pool._send_telegram_notification("Perplexity config updated")

    return JSONResponse(result)


@mcp.custom_route("/heartbeat/start", methods=["POST"])
async def heartbeat_start(request: Request) -> JSONResponse:
    """启动心跳后台任务"""
    from perplexity.config import ADMIN_TOKEN

    if not ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Admin token not configured. Set PPLX_ADMIN_TOKEN environment variable."
        }, status_code=403)

    provided_token = request.headers.get("X-Admin-Token")
    if not provided_token or provided_token != ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Invalid or missing admin token."
        }, status_code=401)

    pool = get_pool()
    started = pool.start_heartbeat()
    if started:
        return JSONResponse({"status": "ok", "message": "Heartbeat started"})
    elif not pool.is_heartbeat_enabled():
        return JSONResponse({"status": "error", "message": "Heartbeat is disabled in config"})
    else:
        return JSONResponse({"status": "ok", "message": "Heartbeat already running"})


@mcp.custom_route("/heartbeat/stop", methods=["POST"])
async def heartbeat_stop(request: Request) -> JSONResponse:
    """停止心跳后台任务"""
    from perplexity.config import ADMIN_TOKEN

    if not ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Admin token not configured. Set PPLX_ADMIN_TOKEN environment variable."
        }, status_code=403)

    provided_token = request.headers.get("X-Admin-Token")
    if not provided_token or provided_token != ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Invalid or missing admin token."
        }, status_code=401)

    pool = get_pool()
    stopped = pool.stop_heartbeat()
    if stopped:
        return JSONResponse({"status": "ok", "message": "Heartbeat stopped"})
    else:
        return JSONResponse({"status": "ok", "message": "Heartbeat not running"})


@mcp.custom_route("/heartbeat/test", methods=["POST"])
async def heartbeat_test(request: Request) -> JSONResponse:
    """手动触发心跳测试"""
    from perplexity.config import ADMIN_TOKEN

    if not ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Admin token not configured. Set PPLX_ADMIN_TOKEN environment variable."
        }, status_code=403)

    provided_token = request.headers.get("X-Admin-Token")
    if not provided_token or provided_token != ADMIN_TOKEN:
        return JSONResponse({
            "status": "error",
            "message": "Invalid or missing admin token."
        }, status_code=401)

    pool = get_pool()
    try:
        body = await request.json()
    except Exception:
        body = {}

    client_id = body.get("id")

    if client_id:
        # Test specific client
        result = await pool.test_client(client_id)
        return JSONResponse(result)
    else:
        # Test all clients
        result = await pool.test_all_clients()
        return JSONResponse(result)
