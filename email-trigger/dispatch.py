#!/usr/bin/env python3
"""
dispatch.py — cron 每 N 分钟调一次：轮询邮箱 → 缺主题的回澄清信 → 并发≤cap 拉起 job。

设计：dispatch 本身跑得快就退出；真正干活的 run_job.py 在后台（detached）跑，
一任务一进程=一"窗口"。并发上限靠 state/running/*.lock 计数控制；超额的任务留在
队列里，等下一次 cron tick 有空位再拉起。

用法：
  python dispatch.py                # cron 调用（轮询+派发）
  python dispatch.py --status       # 看队列/运行/完成数
"""
import argparse
import fcntl
import glob
import json
import os
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
QUEUE = os.path.join(STATE, "queue")
RUNNING = os.path.join(STATE, "running")
DONE = os.path.join(STATE, "done")
sys.path.insert(0, HERE)  # 供 import send_result


def load_config():
    for n in ("config.yaml", "config.example.yaml"):
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            return yaml.safe_load(open(p, encoding="utf-8"))
    sys.exit("缺少 config.yaml")


def running_count():
    # 运行中的任务 = running/ 里的 json（dispatch claim 时移入，run_job 结束移出）
    return len(glob.glob(os.path.join(RUNNING, "*.json")))


def status():
    for d in (QUEUE, RUNNING, DONE):
        os.makedirs(d, exist_ok=True)
    print(f"队列: {len(glob.glob(os.path.join(QUEUE,'*.json')))}  "
          f"运行中: {running_count()}  完成: {len(glob.glob(os.path.join(DONE,'*.json')))}")


def main():
    ap = argparse.ArgumentParser(description="综述邮件触发调度器")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-poll", action="store_true", help="不轮询，只派发队列里已有任务")
    args = ap.parse_args()
    cfg = load_config()
    for d in (QUEUE, RUNNING, DONE):
        os.makedirs(d, exist_ok=True)

    if args.status:
        status(); return

    # 单实例：拿不到锁=上个 tick 还在跑，直接退出（防重叠 tick 各自读旧计数超额拉起）
    lock_fh = open(os.path.join(STATE, "dispatch.lock"), "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("# 另一个 dispatch 正在运行，跳过本次", file=sys.stderr)
        return

    # 1) 轮询 → 写队列（含 .clarify.json）
    if not args.no_poll:
        subprocess.run([sys.executable, os.path.join(HERE, "poll_inbox.py"), "--emit-queue"])

    # 2) 缺主题的澄清信
    for cl in glob.glob(os.path.join(QUEUE, "*.clarify.json")):
        try:
            import send_result
            send_result.send_clarify(json.load(open(cl, encoding="utf-8")))
        except Exception as e:
            print(f"# 澄清信失败 {cl}: {e}", file=sys.stderr)
        os.replace(cl, os.path.join(DONE, os.path.basename(cl)))

    # 3) 并发受限派发
    cap = cfg["execution"].get("max_concurrent", 3)
    tasks = sorted(p for p in glob.glob(os.path.join(QUEUE, "*.json"))
                   if not p.endswith(".clarify.json"))
    launched = 0
    for tp in tasks:
        # claim 已把任务移入 running/，running_count() 自身就反映真实在跑数，不要再 + launched（会双计）
        if running_count() >= cap:
            print(f"# 并发已满({cap})，{len(tasks)-launched} 个任务留队列等下轮", file=sys.stderr)
            break
        # 先 claim：移到 running/ 再启动，避免下一次 tick 把同一任务重复拉起
        claimed = os.path.join(RUNNING, os.path.basename(tp))
        try:
            os.replace(tp, claimed)
        except OSError:
            continue
        logf = open(os.path.join(STATE, "dispatch.log"), "a", encoding="utf-8")
        subprocess.Popen([sys.executable, os.path.join(HERE, "run_job.py"), claimed],
                         stdout=logf, stderr=subprocess.STDOUT,
                         start_new_session=True)
        launched += 1
        print(f"# 拉起 job {os.path.basename(claimed)}", file=sys.stderr)

    status()


if __name__ == "__main__":
    main()
