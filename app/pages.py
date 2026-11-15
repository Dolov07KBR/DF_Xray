"""HTML-страницы: SPA-оболочка панели и публичная страница подписки."""

from __future__ import annotations

import html
from typing import Any

from . import config, db, qr, repo, xray
from .server import (
    ApiError,
    Request,
    Response,
    get,
    html_response,
    json_response,
    serve_static,
)
from .utils import human_size, iso, to_bool, to_int

# --------------------------------------------------------------------------
# Панель (SPA)
# --------------------------------------------------------------------------


@get("/", auth_required=False)
def index(req: Request) -> Response:
    return serve_static("index.html")


@get(r"/static/(?P<path>.+)", auth_required=False)
def static(req: Request) -> Response:
    return serve_static(req.params["path"])


@get("/favicon.ico", auth_required=False)
def favicon(req: Request) -> Response:
    return serve_static("img/favicon.svg")


@get("/healthz", auth_required=False)
def healthz(req: Request) -> Response:
    return json_response({"status": "ok", "version": config.APP_VERSION, "ts": iso()})


@get("/api/health", auth_required=False)
def api_health(req: Request) -> Response:
    return json_response({"status": "ok", "version": config.APP_VERSION})


# --------------------------------------------------------------------------
# Подписка
# --------------------------------------------------------------------------


def _subscription_for(sub_token: str) -> tuple[Any, dict[str, Any]]:
    user = repo.get_user_by_token(sub_token)
    if user is None:
        raise ApiError(404, "Подписка не найдена")
    settings = db.get_settings()
    nodes = [n for n in repo.list_nodes() if n["enabled"]]
    links = xray.build_links(user, nodes, settings.get("panel_title", "DF_Xray"))
    if links and settings.get("sub_sort_by_latency", "1") == "1":
        from . import latency

        latencies = latency.measure([n for n in nodes if not n["drain"]])
        links = latency.sort_links(links, latencies)
    active = repo.user_status(user) == "active"
    payload = {
        "user": user,
        "settings": settings,
        "links": links if active else [],
        "active": active,
    }
    return user, payload


def _userinfo_header(user: Any) -> str:
    limit = to_int(user["limit_bytes"])
    expire = 0
    if user["expires_at"]:
        import datetime as dt

        try:
            expire = int(
                dt.datetime.fromisoformat(user["expires_at"] + "T23:59:59+00:00").timestamp()
            )
        except ValueError:
            expire = 0
    return (
        f"upload={to_int(user['up_bytes'])}; download={to_int(user['down_bytes'])}; "
        f"total={limit}; expire={expire}"
    )


def _profile_headers(user: Any, settings: dict[str, str], base: str) -> dict[str, str]:
    import base64

    title = settings.get("sub_title") or settings.get("panel_title") or "DF_Xray"
    title_b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
    headers = {
        "subscription-userinfo": _userinfo_header(user),
        "profile-title": f"base64:{title_b64}",
        "profile-update-interval": str(to_int(settings.get("sub_update_interval"), 12)),
        "profile-web-page-url": f"{base}/sub/{user['sub_token']}/page",
        "cache-control": "no-store",
        "x-dfxray-status": repo.user_status(user),
    }
    support = (settings.get("sub_support_url") or "").strip()
    if support:
        headers["support-url"] = support
    return headers


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)", auth_required=False)
def sub_plain_b64(req: Request) -> Response:
    user, payload = _subscription_for(req.params["token"])
    repo.mark_sub_access(user["id"])
    links = [item["link"] for item in payload["links"]]
    text = xray.subscription_text(links) if links else ""
    return Response(
        text,
        content_type="text/plain; charset=utf-8",
        headers=_profile_headers(user, payload["settings"], req.base_url()),
    )


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)/plain", auth_required=False)
def sub_plain(req: Request) -> Response:
    user, payload = _subscription_for(req.params["token"])
    repo.mark_sub_access(user["id"])
    links = "\n".join(item["link"] for item in payload["links"])
    return Response(
        links,
        content_type="text/plain; charset=utf-8",
        headers=_profile_headers(user, payload["settings"], req.base_url()),
    )


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)/info", auth_required=False)
def sub_info(req: Request) -> Response:
    user, payload = _subscription_for(req.params["token"])
    repo.mark_sub_access(user["id"])
    base = req.base_url()
    data = repo.serialize_user(user, base)
    data["links"] = [
        {k: v for k, v in item.items() if k != "link"} for item in payload["links"]
    ]
    return json_response(data, headers={"Cache-Control": "no-store"})


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)/qr\.svg", auth_required=False)
def sub_qr_svg(req: Request) -> Response:
    user, _ = _subscription_for(req.params["token"])
    url = f"{req.base_url()}/sub/{user['sub_token']}"
    return Response(
        qr.svg(url, module_px=10, border=3, title=user["username"]),
        content_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)/qr\.png", auth_required=False)
def sub_qr_png(req: Request) -> Response:
    user, _ = _subscription_for(req.params["token"])
    url = f"{req.base_url()}/sub/{user['sub_token']}"
    return Response(
        qr.png(url, scale=10, border=3),
        content_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


SUB_PAGE_CSS = """
:root{--bg:#070910;--panel:#0f131d;--panel2:#151b28;--line:#212a3b;--text:#e8ecf6;
--muted:#8892a8;--accent:#7c5cff;--mint:#2ee6a8;--warn:#ffb454;--danger:#ff5f6d}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:
radial-gradient(900px 500px at 15% -10%,rgba(124,92,255,.22),transparent 60%),
radial-gradient(700px 400px at 90% 0%,rgba(46,230,168,.12),transparent 55%),var(--bg);
color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;
padding:28px 16px 48px;display:flex;justify-content:center}
.shell{width:100%;max-width:760px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:22px}
.mark{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;font-weight:800;
letter-spacing:-.5px;background:linear-gradient(135deg,var(--accent),#3ea8ff);color:#fff;
box-shadow:0 10px 30px rgba(124,92,255,.35)}
.brand{font-weight:700;font-size:17px;letter-spacing:.2px}
.brand small{display:block;color:var(--muted);font-weight:500;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.card{background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(255,255,255,0)),var(--panel);
border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:0 26px 60px rgba(0,0,0,.45)}
.hero{display:flex;gap:22px;flex-wrap:wrap;align-items:center;justify-content:space-between}
.who{font-size:22px;font-weight:700;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin:0}
.badge{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;
font-size:12px;font-weight:600;border:1px solid var(--line);background:var(--panel2);margin-top:10px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--mint);box-shadow:0 0 12px var(--mint)}
.badge.off .dot{background:var(--danger);box-shadow:0 0 12px var(--danger)}
.ring{position:relative;width:120px;height:120px;flex:0 0 auto}
.ring svg{transform:rotate(-90deg)}
.ring .lbl{position:absolute;inset:0;display:grid;place-items:center;text-align:center;line-height:1.15}
.ring .lbl b{font-size:19px}
.ring .lbl span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-top:20px}
.tile{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.tile span{display:block;color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.tile b{font-size:15px}
.qr{background:#fff;border-radius:16px;padding:10px;display:grid;place-items:center;margin-top:20px}
.qr img{width:100%;max-width:230px;height:auto;display:block}
.suburl{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
input.url{flex:1;min-width:220px;background:var(--panel2);border:1px solid var(--line);color:var(--text);
border-radius:11px;padding:11px 13px;font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
button{cursor:pointer;border:1px solid var(--line);background:var(--panel2);color:var(--text);
border-radius:11px;padding:11px 15px;font-weight:600;font-size:13px;transition:.15s}
button:hover{border-color:var(--accent);color:#fff}
button.primary{background:linear-gradient(135deg,var(--accent),#3ea8ff);border:0;color:#fff}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:26px 0 12px}
.node{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:10px}
.node-h{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
.node h3{margin:0;font-size:14.5px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.chip{font:11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#c9d2e6;background:#0b0f18;
border:1px solid var(--line);border-radius:6px;padding:5px 7px}
.chip b{color:var(--mint);font-weight:600}
.link{margin-top:10px;font:11.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#94a3c4;
word-break:break-all;background:#0b0f18;border:1px solid var(--line);border-radius:10px;padding:10px}
.foot{text-align:center;color:var(--muted);font-size:12px;margin-top:26px;line-height:1.7}
.foot a{color:#a99cff;text-decoration:none}
.empty{padding:18px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);text-align:center}
@media(max-width:520px){.card{padding:18px}.hero{gap:16px}}
"""

SUB_PAGE_JS = """
async function copyText(text, btn){
  try{ await navigator.clipboard.writeText(text); }
  catch(e){
    const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);
    ta.select();document.execCommand('copy');ta.remove();
  }
  const old=btn.textContent;btn.textContent='Скопировано ✓';btn.disabled=true;
  setTimeout(()=>{btn.textContent=old;btn.disabled=false;},1400);
}
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-copy]');if(!btn)return;
  copyText(btn.getAttribute('data-copy'),btn);
});
"""


def _ring(percent: float, limited: bool) -> str:
    radius = 52
    circumference = 2 * 3.14159 * radius
    dash = max(0.0, min(100.0, percent)) / 100 * circumference
    color = "#2ee6a8" if percent < 70 else "#ffb454" if percent < 95 else "#ff5f6d"
    if not limited:
        label = "∞"
        caption = "без лимита"
        dash = circumference * 0.62
        color = "#7c5cff"
    else:
        label = f"{percent:.0f}%"
        caption = "трафика"
    return f"""
    <div class="ring">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="{radius}" fill="none" stroke="#1b2333" stroke-width="10"/>
        <circle cx="60" cy="60" r="{radius}" fill="none" stroke="{color}" stroke-width="10"
          stroke-linecap="round" stroke-dasharray="{dash:.1f} {circumference:.1f}"/>
      </svg>
      <div class="lbl"><div><b>{label}</b><span>{caption}</span></div></div>
    </div>"""


def _sub_page_html(user, payload, base: str) -> str:
    settings = payload["settings"]
    status = repo.user_status(user)
    active = payload["active"]
    title = settings.get("sub_title") or settings.get("panel_title") or "DF_Xray"
    support = (settings.get("sub_support_url") or "").strip()
    sub_url = f"{base}/sub/{user['sub_token']}"
    used = to_int(user["up_bytes"]) + to_int(user["down_bytes"])
    limit = to_int(user["limit_bytes"])
    percent = used / limit * 100 if limit else 0
    expires = user["expires_at"] or "бессрочно"
    if user["expires_at"]:
        try:
            import datetime as _dt

            expires = _dt.date.fromisoformat(user["expires_at"]).strftime("%d.%m.%Y")
        except ValueError:
            expires = user["expires_at"]
    nodes_html = []
    if active and to_bool(settings.get("sub_show_nodes", "1")):
        for item in payload["links"]:
            nodes_html.append(
                f"""
        <div class="node">
          <div class="node-h">
            <h3>{html.escape(item['node_name'])}</h3>
            <button class="primary" data-copy="{html.escape(item['link'], quote=True)}">Скопировать ссылку</button>
          </div>
          <div class="chips">
            <span class="chip"><b>{html.escape(item['protocol'].upper())}</b></span>
            <span class="chip">{html.escape(item['transport'])}</span>
            <span class="chip">{html.escape(item['security'])}</span>
            <span class="chip">{html.escape(item['address'])}:{item['port']}</span>
          </div>
          <div class="link">{html.escape(item['link'])}</div>
        </div>"""
            )
    status_label = {
        "active": "Подписка активна",
        "disabled": "Подписка отключена",
        "expired": "Срок подписки истёк",
        "limited": "Исчерпан лимит трафика",
    }.get(status, status)
    if not active:
        nodes_html.append(
            '<div class="empty">Конфигурации недоступны: '
            + html.escape(status_label.lower())
            + ". Обратитесь к администратору.</div>"
        )
    support_btn = (
        f'<a href="{html.escape(support)}" target="_blank" rel="noopener">'
        "Поддержка</a> · "
        if support
        else ""
    )
    footer_note = (settings.get("footer_note") or "").strip()
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)} · {html.escape(user['username'])}</title>
<link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">
<style>{SUB_PAGE_CSS}</style>
</head>
<body>
<div class="shell">
  <div class="top">
    <div class="mark">DF</div>
    <div class="brand">{html.escape(title)}<small>подписка</small></div>
  </div>

  <div class="card">
    <div class="hero">
      <div>
        <h1 class="who">{html.escape(user['username'])}</h1>
        <p class="sub">Импортируйте ссылку в клиент или отсканируйте QR-код.</p>
        <div class="badge{'' if active else ' off'}"><span class="dot"></span>{html.escape(status_label)}</div>
      </div>
      {_ring(percent, bool(limit))}
    </div>

    <div class="grid">
      <div class="tile"><span>Использовано</span><b>{human_size(used)}</b></div>
      <div class="tile"><span>Лимит</span><b>{human_size(limit) if limit else 'без лимита'}</b></div>
      <div class="tile"><span>Действует до</span><b>{html.escape(str(expires))}</b></div>
      <div class="tile"><span>Нод в подписке</span><b>{len(payload['links'])}</b></div>
    </div>

    <div class="qr">
      <img src="/sub/{html.escape(user['sub_token'])}/qr.svg" alt="QR-код подписки" width="230" height="230">
    </div>
    <div class="suburl">
      <input class="url" value="{html.escape(sub_url)}" readonly onclick="this.select()">
      <button class="primary" data-copy="{html.escape(sub_url, quote=True)}">Копировать</button>
    </div>

    <h2>Конфигурации</h2>
    {''.join(nodes_html) if nodes_html else '<div class="empty">Пока нет доступных нод.</div>'}

    <div class="foot">
      {support_btn}<a href="/">DF_Xray Panel</a> · обновление каждые {to_int(settings.get('sub_update_interval'), 12)} ч
      {('<br>' + html.escape(footer_note)) if footer_note else ''}
    </div>
  </div>
</div>
<script>{SUB_PAGE_JS}</script>
</body>
</html>"""


@get(r"/sub/(?P<token>[A-Za-z0-9_\-]+)/page", auth_required=False)
def sub_page(req: Request) -> Response:
    user, payload = _subscription_for(req.params["token"])
    if not to_bool(payload["settings"].get("sub_page_enabled", "1")):
        raise ApiError(404, "Страница подписки отключена")
    repo.mark_sub_access(user["id"])
    return html_response(_sub_page_html(user, payload, req.base_url()))


# SPA-fallback: любые «человеческие» адреса отдают index.html,
# маршрутизацией занимается фронтенд.
@get(r"/(?!api/|sub/|static/|healthz|favicon\.ico).*", auth_required=False)
def spa_fallback(req: Request) -> Response:
    if "." in req.path.rsplit("/", 1)[-1]:
        raise ApiError(404, "Не найдено")
    return serve_static("index.html")
