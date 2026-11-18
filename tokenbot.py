#!/usr/bin/env python3
"""tokenbot: Claude Code / Codex 5시간 사용량 윈도우를 끊김 없이 이어 주는 봇.

윈도우가 끝나는 즉시 짧은 메시지(핑)를 보내 다음 윈도우를 시작시킨다.
표준 라이브러리만 사용한다. 자세한 사용법은 README.md 참고.
"""
from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

BOT_HOME = Path(os.environ.get("TOKENBOT_HOME", Path(__file__).resolve().parent))
CONFIG_PATH = BOT_HOME / "config.json"
EXAMPLE_CONFIG_PATH = BOT_HOME / "config.example.json"
DATA_DIR = BOT_HOME / "data"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "bot.log"
LOCK_PATH = DATA_DIR / "tick.lock"
PING_WORKDIR = DATA_DIR / "ping-workdir"

LAUNCHD_LABEL = "com.tokenbot.tick"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

LIMIT_PATTERN = re.compile(r"(usage limit|rate limit|limit reached|hit your limit|quota)", re.I)
MAX_FAILED_ATTEMPTS_KEPT = 50


# ---------------------------------------------------------------- 시간 유틸

def now_local() -> datetime:
    return datetime.now().astimezone()


def parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone()


def fmt(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%m-%d %H:%M") if dt else "-"


def parse_hhmm(text: str) -> time:
    h, m = text.strip().split(":")
    return time(int(h), int(m))


def in_quiet_hours(dt: datetime, ranges: list[str]) -> bool:
    """'01:00-06:00' 형식의 구간 안이면 True. 자정을 넘는 구간('23:00-05:00')도 지원."""
    t = dt.astimezone().time()
    for r in ranges:
        start_s, end_s = r.split("-")
        start, end = parse_hhmm(start_s), parse_hhmm(end_s)
        if start <= end:
            if start <= t < end:
                return True
        elif t >= start or t < end:
            return True
    return False


def next_allowed_time(dt: datetime, ranges: list[str]) -> datetime:
    """dt 이후 처음으로 quiet hours 밖인 시각 (1분 단위)."""
    probe = dt
    for _ in range(24 * 60 + 1):
        if not in_quiet_hours(probe, ranges):
            return probe
        probe = (probe + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return dt  # 하루 종일 quiet 이면 설정 오류이므로 그냥 dt 반환


# ---------------------------------------------------------------- 설정 / 상태

def load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("window_hours", 5)
    cfg.setdefault("buffer_minutes", 2)
    cfg.setdefault("retry_minutes", 10)
    cfg.setdefault("quiet_hours", [])
    cfg.setdefault("notify_on_failure", True)
    cfg.setdefault("ping_timeout_seconds", 180)
    cfg.setdefault("providers", {})
    return cfg


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"providers": {}}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def log(msg: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_local().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    subprocess.run(["osascript", "-e", script], capture_output=True)


# ---------------------------------------------------------------- 윈도우 계산

def collect_activity(pcfg: dict, since: datetime) -> list[datetime]:
    """로컬 로그(jsonl)에서 since 이후의 사용 시각을 모은다."""
    types = set(pcfg.get("activity_types") or [])
    since_epoch = since.timestamp()
    stamps: list[datetime] = []
    for pattern in pcfg.get("log_globs", []):
        for path in glob.glob(os.path.expanduser(pattern), recursive=True):
            try:
                if os.path.getmtime(path) < since_epoch:
                    continue
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"timestamp"' not in line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(obj, dict):
                            continue
                        if types and obj.get("type") not in types:
                            continue
                        ts = parse_ts(obj.get("timestamp", ""))
                        if ts and ts >= since:
                            stamps.append(ts)
            except OSError:
                continue
    return stamps


def compute_window(stamps: list[datetime], window: timedelta, now: datetime,
                   floor_to_hour: bool = False) -> tuple[datetime, datetime] | None:
    """사용 시각 목록으로 현재 활성 윈도우 (시작, 끝)을 구한다. 없으면 None.

    규칙: 윈도우가 없을 때 처음 사용한 순간 새 윈도우가 시작되고 window 동안 유지된다.
    """
    start: datetime | None = None
    for t in sorted(stamps):
        if t > now:
            continue
        if start is None or t >= start + window:
            start = t.replace(minute=0, second=0, microsecond=0) if floor_to_hour else t
    if start is not None and now < start + window:
        return start, start + window
    return None


def provider_window(name: str, pcfg: dict, pstate: dict, cfg: dict, now: datetime
                    ) -> tuple[datetime, datetime] | None:
    window = timedelta(hours=cfg["window_hours"])
    since = now - window * 3
    stamps = collect_activity(pcfg, since)

    # 한도 초과로 실패한 핑이 로그에 남긴 기록은 "사용"으로 치지 않는다.
    failed = [(parse_ts(a["start"]), parse_ts(a["end"])) for a in pstate.get("failed_attempts", [])]
    stamps = [t for t in stamps if not any(s and e and s <= t <= e for s, e in failed)]

    last_ok = parse_ts(pstate.get("last_success", "") or "")
    if last_ok and last_ok >= since:
        stamps.append(last_ok)
    return compute_window(stamps, window, now, pcfg.get("floor_window_start_to_hour", False))


def next_ping_time(win: tuple[datetime, datetime] | None, pstate: dict, cfg: dict,
                   now: datetime) -> datetime:
    buffer = timedelta(minutes=cfg["buffer_minutes"])
    candidate = win[1] + buffer if win else now
    retry_after = parse_ts(pstate.get("retry_after", "") or "")
    if retry_after and retry_after > candidate:
        candidate = retry_after
    return next_allowed_time(candidate, cfg["quiet_hours"])


# ---------------------------------------------------------------- 핑

@dataclass
class PingResult:
    ok: bool
    limited: bool
    output: str


def run_ping(name: str, pcfg: dict, cfg: dict) -> PingResult:
    prompt = pcfg.get("prompt", "Reply with just: ok")
    cmd = [part.replace("{prompt}", prompt) for part in pcfg["command"]]
    PING_WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, cwd=PING_WORKDIR, capture_output=True, text=True,
                              timeout=cfg["ping_timeout_seconds"], stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return PingResult(False, False, f"명령을 찾을 수 없음: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return PingResult(False, False, "시간 초과")
    output = (proc.stdout + "\n" + proc.stderr).strip()
    limited = bool(LIMIT_PATTERN.search(output))
    ok = proc.returncode == 0 and not limited
    return PingResult(ok, limited, output[-500:])


def do_ping(name: str, pcfg: dict, cfg: dict, state: dict, reason: str) -> PingResult:
    pstate = state["providers"].setdefault(name, {})
    started = now_local()
    log(f"{name}: 핑 전송 ({reason})")
    result = run_ping(name, pcfg, cfg)
    ended = now_local()
    pstate["last_attempt"] = started.isoformat()
    if result.ok:
        pstate["last_success"] = started.isoformat()
        pstate["last_result"] = "ok"
        pstate.pop("retry_after", None)
        log(f"{name}: 성공 → 새 윈도우 시작 (~{fmt(started + timedelta(hours=cfg['window_hours']))}까지)")
    else:
        pstate["last_result"] = "limited" if result.limited else "error"
        pstate["last_error"] = result.output
        pstate["retry_after"] = (ended + timedelta(minutes=cfg["retry_minutes"])).isoformat()
        attempts = pstate.setdefault("failed_attempts", [])
        attempts.append({"start": started.isoformat(), "end": (ended + timedelta(seconds=5)).isoformat()})
        del attempts[:-MAX_FAILED_ATTEMPTS_KEPT]
        kind = "한도 도달(아직 윈도우가 남아 있음)" if result.limited else "오류"
        log(f"{name}: 실패 - {kind}: {result.output[:200]!r} → {cfg['retry_minutes']}분 뒤 재시도")
        if cfg["notify_on_failure"] and not result.limited:
            notify("tokenbot", f"{name} 핑 실패: {result.output[:100]}")
    return result


def enabled_providers(cfg: dict, only: str | None = None) -> dict:
    items = {n: p for n, p in cfg["providers"].items() if p.get("enabled", True)}
    if only:
        if only not in cfg["providers"]:
            sys.exit(f"알 수 없는 provider: {only}")
        items = {only: cfg["providers"][only]}
    return items


# ---------------------------------------------------------------- 명령

def cmd_tick(args) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # 이전 tick 이 아직 실행 중
        cfg, state = load_config(), load_state()
        now = now_local()
        for name, pcfg in enabled_providers(cfg).items():
            pstate = state["providers"].setdefault(name, {})
            win = provider_window(name, pcfg, pstate, cfg, now)
            due = next_ping_time(win, pstate, cfg, now)
            if now < due:
                if args.verbose:
                    print(f"{name}: 대기 (윈도우 {fmt(win[0]) if win else '없음'}~{fmt(win[1]) if win else ''}, 다음 핑 {fmt(due)})")
                continue
            if args.dry_run:
                print(f"{name}: [dry-run] 지금 핑을 보낼 차례")
                continue
            do_ping(name, pcfg, cfg, state, "활성 윈도우 없음")
            save_state(state)
        state["last_tick"] = now.isoformat()
        if not args.dry_run:
            save_state(state)


def cmd_status(args) -> None:
    cfg, state = load_config(), load_state()
    now = now_local()
    print(f"현재 시각: {fmt(now)}   설정 파일: {CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_CONFIG_PATH}")
    if cfg["quiet_hours"]:
        print(f"핑 금지 시간: {', '.join(cfg['quiet_hours'])}")
    print(f"launchd 등록: {'예' if PLIST_PATH.exists() else '아니오'}   마지막 tick: {fmt(parse_ts(state.get('last_tick', '') or ''))}")
    print()
    for name, pcfg in enabled_providers(cfg).items():
        pstate = state["providers"].get(name, {})
        win = provider_window(name, pcfg, pstate, cfg, now)
        due = next_ping_time(win, pstate, cfg, now)
        print(f"[{name}]")
        if win:
            left = win[1] - now
            print(f"  활성 윈도우 : {fmt(win[0])} ~ {fmt(win[1])}  (남은 시간 {int(left.total_seconds() // 3600)}h {int(left.total_seconds() % 3600 // 60)}m)")
        else:
            print("  활성 윈도우 : 없음")
        print(f"  다음 핑     : {fmt(due)}{'  (지금)' if due <= now else ''}")
        print(f"  마지막 성공 : {fmt(parse_ts(pstate.get('last_success', '') or ''))}   마지막 결과: {pstate.get('last_result', '-')}")
        if pstate.get("last_result") not in (None, "ok") and pstate.get("last_error"):
            print(f"  마지막 오류 : {pstate['last_error'][:200]}")
        print()


def cmd_plan(args) -> None:
    """사용자가 직접 쓰지 않는다고 가정하고 앞으로의 핑 시각을 시뮬레이션한다."""
    cfg, state = load_config(), load_state()
    now = now_local()
    window = timedelta(hours=cfg["window_hours"])
    buffer = timedelta(minutes=cfg["buffer_minutes"])
    horizon = now + timedelta(hours=args.hours)
    for name, pcfg in enabled_providers(cfg).items():
        win = provider_window(name, pcfg, state["providers"].get(name, {}), cfg, now)
        print(f"[{name}] 앞으로 {args.hours}시간의 예상 핑 / 리셋 시각")
        t = next_allowed_time(win[1] + buffer if win else now, cfg["quiet_hours"])
        while t < horizon:
            print(f"  핑 {fmt(t)}  →  리셋 {fmt(t + window)}")
            t = next_allowed_time(t + window + buffer, cfg["quiet_hours"])
        print()


def cmd_ping(args) -> None:
    cfg, state = load_config(), load_state()
    for name, pcfg in enabled_providers(cfg, args.provider).items():
        do_ping(name, pcfg, cfg, state, "수동")
        save_state(state)


def cmd_log(args) -> None:
    if not LOG_PATH.exists():
        print("로그가 아직 없습니다.")
        return
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    print("\n".join(lines[-args.lines:]))


def cmd_init(args) -> None:
    if CONFIG_PATH.exists() and not args.force:
        print(f"이미 있음: {CONFIG_PATH} (덮어쓰려면 --force)")
        return
    shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
    print(f"생성됨: {CONFIG_PATH}")


def build_launchd_path(cfg: dict) -> str:
    dirs: list[str] = []
    for pcfg in cfg["providers"].values():
        exe = shutil.which(pcfg["command"][0])
        if exe:
            dirs.append(str(Path(exe).parent))
    node = shutil.which("node")
    if node:
        dirs.append(str(Path(node).parent))
    dirs += ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin"),
             "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    seen: list[str] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return ":".join(seen)


def cmd_install(args) -> None:
    if sys.platform != "darwin":
        sys.exit("install 은 macOS(launchd) 전용입니다. Linux 는 README 의 cron 예시를 참고하세요.")
    cfg = load_config()
    for name, pcfg in enabled_providers(cfg).items():
        if not shutil.which(pcfg["command"][0]):
            print(f"경고: {name} 명령({pcfg['command'][0]})을 PATH 에서 찾지 못했습니다.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "tick"],
        "StartInterval": 60,
        "RunAtLoad": True,
        "WorkingDirectory": str(BOT_HOME),
        "EnvironmentVariables": {"PATH": build_launchd_path(cfg), "TOKENBOT_HOME": str(BOT_HOME)},
        "StandardOutPath": str(DATA_DIR / "launchd.out.log"),
        "StandardErrorPath": str(DATA_DIR / "launchd.err.log"),
    }
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"], capture_output=True)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f)
    res = subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"launchctl 등록 실패: {res.stderr.strip()}")
    print(f"설치 완료: {PLIST_PATH}\n1분마다 tick 이 실행됩니다. 상태 확인: python3 tokenbot.py status")


def cmd_uninstall(args) -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"], capture_output=True)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("제거 완료 (data/ 폴더의 상태와 로그는 남겨 두었습니다).")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tokenbot", description="5시간 사용량 윈도우 자동 갱신 봇")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("tick", help="한 번 검사하고 필요하면 핑 (launchd 가 1분마다 실행)")
    s.add_argument("--dry-run", action="store_true", help="핑을 보내지 않고 판단만 출력")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_tick)

    sub.add_parser("status", help="현재 윈도우와 다음 핑 시각").set_defaults(func=cmd_status)

    s = sub.add_parser("plan", help="앞으로의 핑/리셋 시각 시뮬레이션")
    s.add_argument("--hours", type=int, default=24)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("ping", help="지금 바로 핑 보내기")
    s.add_argument("provider", nargs="?", help="claude 또는 codex (생략하면 전부)")
    s.set_defaults(func=cmd_ping)

    s = sub.add_parser("log", help="최근 로그 보기")
    s.add_argument("-n", "--lines", type=int, default=30)
    s.set_defaults(func=cmd_log)

    s = sub.add_parser("init", help="config.example.json 을 config.json 으로 복사")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    sub.add_parser("install", help="launchd 에 등록 (macOS)").set_defaults(func=cmd_install)
    sub.add_parser("uninstall", help="launchd 에서 제거").set_defaults(func=cmd_uninstall)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
