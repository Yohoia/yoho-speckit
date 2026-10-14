"""Shared run contract; no network, credentials or third-party dependencies."""
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl

STATUS = {"observed", "inferred", "proposed", "unknown"}
SENSITIVE = re.compile(r"token|secret|password|signature|session|authorization|api.?key|^code$|jwt", re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=path.name+".",suffix=".tmp",delete=False) as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(handle.name)
    try: os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


@contextmanager
def evidence_lock(run):
    path=Path(run)/"evidence"/".index.lock"
    path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open("a+b")
    if handle.tell()==0: handle.write(b"0");handle.flush()
    def acquire():
        handle.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    def release():
        handle.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
    try:
        for attempt in range(50):
            try: acquire();break
            except (BlockingIOError,OSError):
                if attempt==49: raise ValueError("证据正被其他进程写入，稍后重试") from None
                time.sleep(.1)
        try: yield
        finally: release()
    finally: handle.close()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def url(value):
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("需要不含账号密码的 HTTP(S) URL")
    if any(SENSITIVE.search(k) for k, _ in parse_qsl(parts.query)):
        raise ValueError("URL 含疑似凭据参数；请使用公开页面地址")
    # Accessing port validates malformed ports, even when netloc is preserved.
    _ = parts.port
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def origin(value):
    p = urlsplit(url(value))
    return (p.scheme, p.hostname, p.port or (443 if p.scheme == "https" else 80))


def local_file(run, relative):
    root = Path(run).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError("文件必须在运行目录内")
    return result


def plan_for(run):
    plan = read_json(Path(run) / "plan.json")
    original = url(plan["originalUrl"])
    pages = [url(item) for item in plan["pages"]]
    cap = plan["maxPages"]
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("maxPages 必须为正整数")
    mode = plan.get("mode")
    if mode not in {"single", "standard", "extended"}:
        raise ValueError("未知采集模式")
    if mode == "single" and (len(pages) != 1 or cap != 1):
        raise ValueError("single 必须只有输入页")
    if mode == "standard" and cap > 5:
        raise ValueError("standard 最多 5 页")
    if not pages or len(pages) > cap or len(pages) != len(set(pages)):
        raise ValueError("页面数超限、为空或存在重复")
    if original not in pages:
        raise ValueError("计划必须包含原输入页面")
    allowed = [origin(original)] + [origin(x) for x in plan.get("authorizedOrigins", [])]
    if any(origin(item) not in allowed for item in pages):
        raise ValueError("计划包含未明确授权的跨源页面")
    for view in plan.get("viewports", []):
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", view.get("name", "")):
            raise ValueError("视口名称无效")
        if any(not isinstance(view.get(k), int) or view[k] < 1 for k in ("width", "height")):
            raise ValueError("视口尺寸必须为正整数")
    plan["pages"] = pages
    return plan


def index_for(run):
    path = Path(run) / "evidence" / "index.json"
    return read_json(path) if path.exists() else {"snapshots": [], "failures": []}


def snapshot_key(requested, viewport_name, state):
    return digest([url(requested), viewport_name, state])[:16]


def validate_observation(obs):
    if obs.get("method") != "dom-computed-style" or obs.get("schemaVersion") != 1:
        raise ValueError("需要共用探针的 DOM 实测结果，branding/Markdown 不能代替")
    url(obs["url"])
    if not obs.get("capturedAt") or not obs.get("elements"):
        raise ValueError("观察时间或元素缺失，可能未加载目标页面")
    for k in ("width", "height"):
        if not isinstance(obs.get("viewport", {}).get(k), (int, float)) or obs["viewport"][k] <= 0:
            raise ValueError("缺少实测视口")
    ids = set()
    for element in obs["elements"]:
        if element.get("id") in ids or not element.get("id") or not element.get("selector"):
            raise ValueError("元素 ID 重复或选择器缺失")
        ids.add(element["id"])
        if not isinstance(element.get("styles"), dict) or not element["styles"]:
            raise ValueError("元素实测样式缺失")
        if any(not isinstance(v, str) for v in element["styles"].values()):
            raise ValueError("样式值必须为字符串")


def ingest(run, obs, backend, viewport_name, state="default", requested_url=None, screenshot=None, replace=False):
    with evidence_lock(run):
        return _ingest(run,obs,backend,viewport_name,state,requested_url,screenshot,replace)


def _ingest(run, obs, backend, viewport_name, state="default", requested_url=None, screenshot=None, replace=False):
    run = Path(run).resolve()
    plan = plan_for(run)
    validate_observation(obs)
    requested = url(requested_url or obs["url"])
    if requested not in plan["pages"]:
        raise ValueError("观察页面不在计划中；先审核并更新 plan")
    allowed = [origin(plan["originalUrl"])] + [origin(x) for x in plan.get("authorizedOrigins", [])]
    if origin(obs["url"]) not in allowed:
        raise ValueError("最终 URL 跨源；核对重定向身份并明确授权其源后恢复")
    viewport = next((v for v in plan["viewports"] if v["name"] == viewport_name), None)
    if not viewport:
        raise ValueError("视口名称不在计划中")
    if any(abs(obs["viewport"][k] - viewport[k]) > 1 for k in ("width", "height")):
        raise ValueError("实测视口与计划不符")
    if not state or len(state) > 100:
        raise ValueError("状态名称无效")
    index = index_for(run)
    key = snapshot_key(requested, viewport_name, state)
    exists = next((x for x in index["snapshots"] if x["id"] == key), None)
    if exists and not replace:
        return {"status": "unchanged", "id": key}
    shot = None
    if screenshot:
        path = local_file(run, screenshot)
        if not path.is_file():
            raise ValueError("截图文件不存在")
        shot = path.relative_to(run).as_posix()
    path = run / "evidence" / "observations" / (key + ".json")
    write_json(path, obs)
    row = {"id": key, "requestedUrl": requested, "url": url(obs["url"]), "viewport": viewport_name,
           "state": state, "backend": backend, "capturedAt": obs["capturedAt"],
           "file": path.relative_to(run).as_posix(), "sha256": digest(obs), "screenshot": shot,
           "screenshotSha256": hashlib.sha256(local_file(run,shot).read_bytes()).hexdigest() if shot else None}
    for old in index["failures"]:
        if old.get("url") == requested and old.get("viewport") == viewport_name and old.get("stage") != "cleanup":
            old["resolvedAt"] = now()
    index["snapshots"] = [x for x in index["snapshots"] if x["id"] != key] + [row]
    write_json(run / "evidence" / "index.json", index)
    return {"status": "saved", "id": key}


def coverage(run):
    plan, index = plan_for(run), index_for(run)
    gaps = list(plan.get("gaps", []))
    successful = {(x["requestedUrl"], x["viewport"], x["state"]) for x in index["snapshots"]}
    missing = [{"url": p, "viewport": v["name"], "state": "default"}
               for p in plan["pages"] for v in plan["viewports"] if (p, v["name"], "default") not in successful]
    candidates = {}
    for row in index["snapshots"]:
        obs = read_json(local_file(run, row["file"]))
        if digest(obs) != row["sha256"]:
            raise ValueError("证据摘要不一致：" + row["id"])
        if row.get("screenshot") and hashlib.sha256(local_file(run,row["screenshot"]).read_bytes()).hexdigest() != row.get("screenshotSha256"):
            raise ValueError("截图摘要不一致：" + row["id"])
        for link in obs.get("links", []):
            try:
                target = url(link["url"])
                if origin(target) == origin(plan["originalUrl"]) and target not in plan["pages"]:
                    candidates[target] = link
            except (KeyError, ValueError):
                continue
        for flag in ("truncated", "declarationsTruncated"):
            if obs.get("sampling", {}).get(flag): gaps.append(row["id"] + ": " + flag)
        if obs.get("walkComplete") is False: gaps.append(row["id"] + ": scroll walk incomplete")
        if obs.get("fontStatus") != "loaded": gaps.append(row["id"] + ": fonts not ready")
        if obs.get("inaccessibleStylesheets"): gaps.append(row["id"] + ": some stylesheet declarations unreadable")
        if not row.get("screenshot"): gaps.append(row["id"] + ": screenshot missing")
        if obs.get("canvasCount"): gaps.append(row["id"] + ": canvas graphics not measured as DOM styles")
    if not any(x["state"] != "default" for x in index["snapshots"]):
        gaps.append("Only default states captured; hover/focus/expanded states remain unverified")
    return {"plannedPages": plan["pages"], "pageCount": len({x["requestedUrl"] for x in index["snapshots"]}),
            "snapshotCount": len(index["snapshots"]), "snapshots": index["snapshots"],
            "missing": missing, "failures": [x for x in index["failures"] if not x.get("resolvedAt")],
            "failureHistory":index["failures"], "gaps": sorted(set(gaps)),
            "unvisitedCandidates": sorted(candidates.values(), key=lambda x: (not x.get("inNavigation"), x["url"])),
            "selectionNotes": plan.get("selectionNotes", [])}
