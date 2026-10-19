# -*- coding: utf-8 -*-
"""日志初始化失败不得让模块导入崩溃（启动期回归）。

回归背景（用户实测，1.2.4）：从受限环境/沙箱启动 exe（或数据区被运行中实例占住）时，
`template/log_kit` 在 `%LOCALAPPDATA%\\opencodex-helper\\log\\` 上抛 PermissionError，
而 `src/main.py` 的模块级 `get_logger` 调用**不在任何 try 里** ⇒ PyInstaller 启动即崩，
用户看到的是英文 traceback。同一条路径上还有第二处地雷：`load_config()` 里的
`paths.seed_config()` 会 mkdir LOG_DIR，同样会抛。

本测试的判据（机械、不依赖真实 AppData）：
  0) **负对照**：正常数据区导入必须**没有**失败信号（证明信号来自被阻断的日志路径）；
  1) 子进程 import main，数据区 `log` 路径预创建成**普通文件**（mkdir/打开必失败）→
     exit=0、无 Traceback、stderr 有 "log init failed" 失败信号；
  2) 兜底 `_log` 仍是 print 形态（可变参数可调用）、`open_log_dir` 可调用且不抛；
  3) `LOG_INIT_ERROR` 记下真实原因（不是静默吞掉）。

不依赖真实 AppData、不启 GUI / 服务、不占用生产数据区。
"""
import os
import subprocess
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def run_python(code, env):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def env_for(data_dir):
    env = {**os.environ,
           "OPENCODEX_HELPER_DATA_DIR": str(data_dir),
           "PYTHONUTF8": "1"}
    env.pop("OPENCODEX_HELPER_CONFIG", None)
    return env


# 子进程探针：导入 main → 打印日志初始化状态 → 调用兜底闭包（print 形态 + 打开目录）
PROBE_CODE = (
    "import sys; sys.path.insert(0, %r); "
    "import main; "
    "print('IMPORT OK'); "
    "print('LOG_INIT_ERROR', type(main.LOG_INIT_ERROR).__name__); "
    "main._log('fallback', 'accepts', 3, 'parts'); "
    "main.open_log_dir(); "
    "print('FALLBACK CALL OK')" % str(SRC)
)


def main() -> int:
    # ---- 0) 负对照：正常数据区不该出现失败信号（否则"有信号"证明不了任何事）----
    normal = Path(scratch_dir("ocx-logfail-normal-"))
    try:
        result = run_python(PROBE_CODE, env_for(normal))
        out = result.stdout or ""
        err = result.stderr or ""
        check("control: import exits 0 on a writable data root", result.returncode == 0,
              (result.returncode, err[-300:]))
        check("control: no failure signal when logging works",
              "log init failed" not in err and "user dirs seed failed" not in err,
              err[-300:])
        check("control: LOG_INIT_ERROR is None", "LOG_INIT_ERROR NoneType" in out, out[-300:])
    finally:
        check("control temp dir cleaned up (no leak)", rmtree_cleanup(normal), str(normal))

    # ---- 1) 被阻断的日志路径：数据区里的 `log` 预创建成普通文件 -----------------
    data = Path(scratch_dir("ocx-logfail-blocked-"))
    try:
        probe = run_python(
            "import sys; sys.path.insert(0, %r); "
            "from template.paths.paths import LOG_DIR; print(str(LOG_DIR))" % str(SRC),
            env_for(data))
        check("probe: log path resolved", probe.returncode == 0 and bool(probe.stdout.strip()),
              (probe.returncode, probe.stdout, (probe.stderr or "")[-300:]))
        if probe.returncode != 0 or not probe.stdout.strip():
            print("LOG FAIL-OPEN TEST FAILED: " + ",".join(FAILS), flush=True)
            return 1
        log_path = Path(probe.stdout.strip().splitlines()[-1])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("blocked by the log fail-open regression test", encoding="utf-8")
        check("setup: log path is a regular file (blocks mkdir/handler)", log_path.is_file(),
              str(log_path))

        result = run_python(PROBE_CODE, env_for(data))
        out = result.stdout or ""
        err = result.stderr or ""
        combined = out + err
        check("import exits 0 with the log path blocked", result.returncode == 0,
              (result.returncode, combined[-500:]))
        check("module import completed", "IMPORT OK" in out, out[-300:])
        check("no uncaught traceback", "Traceback" not in combined, combined[-500:])
        check("failure was signalled on stderr (not silent)",
              "log init failed" in err, err[-300:])
        check("second startup landmine (paths.seed_config -> LOG_DIR.mkdir) is fail-open too",
              "user dirs seed failed" in err, err[-300:])
        check("LOG_INIT_ERROR carries the real reason (not swallowed)",
              "LOG_INIT_ERROR NoneType" not in out, out[-300:])
        check("fallback _log/open_log_dir callable without raising",
              "FALLBACK CALL OK" in out, out[-300:])
    finally:
        check("blocked temp dir cleaned up (no leak)", rmtree_cleanup(data), str(data))

    print("LOG FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
