"""
claude_design_mcp — claude.ai/design 网页封装 MCP 连接器
用 Playwright 浏览器自动化控制 claude.ai/design，暴露为 MCP 工具。
"""

import asyncio
import json
import os
import base64
import tempfile
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

# ── 初始化 ──────────────────────────────────────────────────────────────
mcp = FastMCP("claude_design_mcp")

CLAUDE_EMAIL    = os.environ.get("CLAUDE_EMAIL", "")
CLAUDE_PASSWORD = os.environ.get("CLAUDE_PASSWORD", "")
SESSION_FILE    = os.environ.get("SESSION_FILE", "/tmp/claude_design_session.json")
BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "60000"))   # ms
HEADLESS        = os.environ.get("HEADLESS", "true").lower() == "true"

_browser_ctx = None   # 全局浏览器上下文（复用 session）


# ── 浏览器管理 ────────────────────────────────────────────────────────────
async def _get_browser():
    """获取或创建 Playwright 浏览器实例，复用已有 session。"""
    from playwright.async_api import async_playwright
    global _browser_ctx

    if _browser_ctx and not _browser_ctx["browser"].is_connected():
        _browser_ctx = None

    if _browser_ctx is None:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=HEADLESS)

        storage_state = SESSION_FILE if Path(SESSION_FILE).exists() else None
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            storage_state=storage_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        _browser_ctx = {"pw": pw, "browser": browser, "context": context}

    return _browser_ctx["context"]


async def _ensure_logged_in(page) -> bool:
    """检查是否已登录；如未登录则用环境变量自动登录。"""
    await page.goto("https://claude.ai/design", wait_until="domcontentloaded",
                    timeout=BROWSER_TIMEOUT)
    await asyncio.sleep(2)

    # 判断：如果看到 /login 或登录表单，就登录
    if "login" in page.url or await page.query_selector('input[type="email"]'):
        if not CLAUDE_EMAIL or not CLAUDE_PASSWORD:
            return False

        await page.fill('input[type="email"]', CLAUDE_EMAIL)
        await page.click('button[type="submit"]')
        await asyncio.sleep(1)
        await page.fill('input[type="password"]', CLAUDE_PASSWORD)
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/design**", timeout=BROWSER_TIMEOUT)

        # 保存 session
        ctx = _browser_ctx["context"]
        await ctx.storage_state(path=SESSION_FILE)

    return True


# ── Pydantic 输入模型 ─────────────────────────────────────────────────────
class CreateDesignInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    prompt: str = Field(
        ...,
        description="设计描述。例如：'设计一个冥想 App 首页，柔和配色，大字体，暗色模式切换'",
        min_length=5,
        max_length=2000,
    )
    export_format: str = Field(
        default="html",
        description="导出格式：html | screenshot | none",
        pattern="^(html|screenshot|none)$",
    )
    wait_seconds: int = Field(
        default=30,
        description="等待 Claude Design 生成完成的秒数（复杂设计可调高）",
        ge=10,
        le=180,
    )


class RefineDesignInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    instruction: str = Field(
        ...,
        description="修改指令。例如：'把主色改成深蓝色，增加暗色模式切换按钮'",
        min_length=3,
        max_length=1000,
    )
    export_format: str = Field(
        default="screenshot",
        description="导出格式：html | screenshot | none",
        pattern="^(html|screenshot|none)$",
    )
    wait_seconds: int = Field(
        default=20,
        description="等待修改完成的秒数",
        ge=5,
        le=120,
    )


class ExportDesignInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    format: str = Field(
        ...,
        description="导出格式：html | screenshot | pdf（pdf 支持取决于页面功能）",
        pattern="^(html|screenshot|pdf)$",
    )


class SessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(..., description="Claude 账号邮箱")
    password: str = Field(..., description="Claude 账号密码")


# ── 工具实现 ──────────────────────────────────────────────────────────────
@mcp.tool(
    name="design_login",
    annotations={
        "title": "登录 Claude.ai",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def design_login(params: SessionInput) -> str:
    """登录 Claude.ai 并保存 session，后续工具调用将复用。

    Args:
        params.email: Claude 账号邮箱
        params.password: Claude 账号密码

    Returns:
        str: 登录结果 JSON，包含 success 和 message 字段
    """
    global CLAUDE_EMAIL, CLAUDE_PASSWORD
    CLAUDE_EMAIL = params.email
    CLAUDE_PASSWORD = params.password

    try:
        ctx = await _get_browser()
        page = await ctx.new_page()
        ok = await _ensure_logged_in(page)
        await page.close()

        if ok:
            return json.dumps({"success": True, "message": "登录成功，session 已保存"})
        else:
            return json.dumps({"success": False, "message": "登录失败：邮箱或密码错误"})
    except Exception as e:
        return json.dumps({"success": False, "message": f"登录异常：{str(e)}"})


@mcp.tool(
    name="design_create",
    annotations={
        "title": "用 Claude Design 生成设计稿",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def design_create(params: CreateDesignInput) -> str:
    """在 claude.ai/design 中输入 prompt，生成设计稿，并可选导出。

    Args:
        params.prompt: 设计描述文字
        params.export_format: html | screenshot | none
        params.wait_seconds: 等待生成的秒数

    Returns:
        str: JSON，包含 success、message、export_type、export_data（base64 或 HTML 字符串）
    """
    try:
        ctx = await _get_browser()
        page = await ctx.new_page()

        ok = await _ensure_logged_in(page)
        if not ok:
            await page.close()
            return json.dumps({
                "success": False,
                "message": "未登录。请先调用 design_login 或设置环境变量 CLAUDE_EMAIL / CLAUDE_PASSWORD",
            })

        # 等待输入框出现
        textarea_sel = 'textarea, [contenteditable="true"], [role="textbox"]'
        await page.wait_for_selector(textarea_sel, timeout=BROWSER_TIMEOUT)
        await asyncio.sleep(1)

        # 填写 prompt 并提交
        textarea = page.locator(textarea_sel).first
        await textarea.fill(params.prompt)
        await asyncio.sleep(0.5)
        await textarea.press("Enter")

        # 等待生成
        await asyncio.sleep(params.wait_seconds)

        # 导出
        export_data = None
        export_type = params.export_format

        if params.export_format == "screenshot":
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
            await page.screenshot(path=tmp_path, full_page=True)
            with open(tmp_path, "rb") as f:
                export_data = base64.b64encode(f.read()).decode()
            os.unlink(tmp_path)

        elif params.export_format == "html":
            export_data = await page.content()

        await page.close()
        return json.dumps({
            "success": True,
            "message": f"设计稿已生成，等待了 {params.wait_seconds}s",
            "export_type": export_type,
            "export_data": export_data,
            "note": "export_data 为 base64 PNG（screenshot）或 HTML 字符串（html）",
        })

    except Exception as e:
        return json.dumps({"success": False, "message": f"生成失败：{str(e)}"})


@mcp.tool(
    name="design_refine",
    annotations={
        "title": "修改当前 Claude Design 设计稿",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def design_refine(params: RefineDesignInput) -> str:
    """在当前打开的 claude.ai/design 页面中，追加修改指令并等待更新。

    Args:
        params.instruction: 修改指令
        params.export_format: html | screenshot | none
        params.wait_seconds: 等待修改完成的秒数

    Returns:
        str: JSON，包含 success、message、export_type、export_data
    """
    try:
        ctx = await _get_browser()
        pages = ctx.pages

        # 找到 design 页面
        design_page = None
        for p in pages:
            if "design" in p.url:
                design_page = p
                break

        if not design_page:
            return json.dumps({
                "success": False,
                "message": "没有找到已打开的 design 页面，请先调用 design_create",
            })

        # 输入修改指令
        textarea_sel = 'textarea, [contenteditable="true"], [role="textbox"]'
        textarea = design_page.locator(textarea_sel).first
        await textarea.fill(params.instruction)
        await asyncio.sleep(0.5)
        await textarea.press("Enter")

        # 等待修改完成
        await asyncio.sleep(params.wait_seconds)

        # 导出
        export_data = None
        if params.export_format == "screenshot":
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
            await design_page.screenshot(path=tmp_path, full_page=True)
            with open(tmp_path, "rb") as f:
                export_data = base64.b64encode(f.read()).decode()
            os.unlink(tmp_path)
        elif params.export_format == "html":
            export_data = await design_page.content()

        return json.dumps({
            "success": True,
            "message": f"修改完成，等待了 {params.wait_seconds}s",
            "export_type": params.export_format,
            "export_data": export_data,
        })

    except Exception as e:
        return json.dumps({"success": False, "message": f"修改失败：{str(e)}"})


@mcp.tool(
    name="design_export",
    annotations={
        "title": "导出当前 Claude Design 设计稿",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def design_export(params: ExportDesignInput) -> str:
    """导出当前已打开的 claude.ai/design 页面内容。

    Args:
        params.format: html | screenshot | pdf

    Returns:
        str: JSON，包含 success、export_type、export_data（base64 或 HTML 字符串）
    """
    try:
        ctx = await _get_browser()
        pages = ctx.pages

        design_page = None
        for p in pages:
            if "design" in p.url:
                design_page = p
                break

        if not design_page:
            return json.dumps({
                "success": False,
                "message": "没有找到已打开的 design 页面",
            })

        export_data = None

        if params.format == "screenshot":
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp_path = f.name
            await design_page.screenshot(path=tmp_path, full_page=True)
            with open(tmp_path, "rb") as f:
                export_data = base64.b64encode(f.read()).decode()
            os.unlink(tmp_path)

        elif params.format == "html":
            export_data = await design_page.content()

        elif params.format == "pdf":
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                tmp_path = f.name
            await design_page.pdf(path=tmp_path)
            with open(tmp_path, "rb") as f:
                export_data = base64.b64encode(f.read()).decode()
            os.unlink(tmp_path)

        return json.dumps({
            "success": True,
            "export_type": params.format,
            "export_data": export_data,
            "note": "screenshot/pdf 为 base64；html 为原始字符串",
        })

    except Exception as e:
        return json.dumps({"success": False, "message": f"导出失败：{str(e)}"})


@mcp.tool(
    name="design_status",
    annotations={
        "title": "查看 Claude Design 当前页面状态",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def design_status() -> str:
    """返回当前浏览器中 claude.ai/design 页面的状态信息。

    Returns:
        str: JSON，包含 url、title、is_logged_in、open_pages
    """
    try:
        ctx = await _get_browser()
        pages = ctx.pages

        info = []
        for p in pages:
            info.append({"url": p.url, "title": await p.title()})

        design_pages = [i for i in info if "design" in i["url"]]
        is_logged_in = SESSION_FILE and Path(SESSION_FILE).exists()

        return json.dumps({
            "success": True,
            "is_logged_in": is_logged_in,
            "open_pages": len(pages),
            "design_pages": design_pages,
            "session_file": SESSION_FILE,
        })

    except Exception as e:
        return json.dumps({"success": False, "message": f"状态查询失败：{str(e)}"})


# ── 入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.environ.get("PORT", "8090")))
