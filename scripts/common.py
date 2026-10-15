"""Shared run contract; no network, credentials or third-party dependencies."""
import hashlib
import gzip
import zlib
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
    path=Path(path)
    try:data=json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_text(encoding='utf-8'))
    except (gzip.BadGzipFile,EOFError,zlib.error) as error:raise ValueError('压缩JSON损坏：'+str(path)) from error
    if isinstance(data,dict) and (data.get('storageVersion')==1 or data.get('method')=='dom-computed-style'):
        from storage import expand
        return expand(path,data)
    return data


def write_json(path, data):
    path = Path(path)
    if path.suffix=='.gz':
        from storage import atomic_gzip
        atomic_gzip(path,data);return
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
    if not plan.get('viewports') or len({v['name'] for v in plan['viewports']})!=len(plan['viewports']):
        raise ValueError('视口必须非空且名称唯一')
    plan["pages"] = pages
    return plan


def index_for(run):
    path = Path(run) / "evidence" / "index.json"
    return read_json(path) if path.exists() else {"snapshots": [], "failures": []}


def snapshot_key(requested, viewport_name, state):
    return digest([url(requested), viewport_name, state])[:16]


def validate_observation(obs):
    if obs.get("method") != "dom-computed-style" or obs.get("schemaVersion") != 1:
        raise ValueError("需要采集器的 DOM 实测结果，文字摘要不能代替")
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
        data=path.read_bytes();image_hash=hashlib.sha256(data).hexdigest()
        shot='evidence/screenshots/'+key+'-'+image_hash[:16]+path.suffix
        target=local_file(run,shot);target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():target.write_bytes(data)
    from storage import store_observation
    path = store_observation(run,key,obs)
    row = {"id": key, "requestedUrl": requested, "url": url(obs["url"]), "viewport": viewport_name,
           "state": state, "backend": backend, "capturedAt": obs["capturedAt"],
           "file": path.relative_to(run).as_posix(), "sha256": digest(obs), "screenshot": shot,
           "screenshotSha256": hashlib.sha256(local_file(run,shot).read_bytes()).hexdigest() if shot else None}
    if obs.get('captureConfig'):row['configSha256']=digest(obs['captureConfig'])
    if obs.get('captureAttempt'):row['attemptId']=obs['captureAttempt']
    if exists and exists!=row:index.setdefault('history',[]).append(exists)
    for old in index["failures"]:
        if not old.get('tasks') and old.get("url") == requested and old.get("viewport") == viewport_name and old.get('state')==state and old.get("stage") != "cleanup":
            old["resolvedAt"] = now()
    index["snapshots"] = [x for x in index["snapshots"] if x["id"] != key] + [row]
    write_json(run / "evidence" / "index.json", index)
    return {"status": "saved", "id": key}


def coverage(run):
    from ledger import coverage as current_coverage
    return current_coverage(run)
