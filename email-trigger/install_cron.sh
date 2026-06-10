#!/usr/bin/env bash
# install_cron.sh — 装/更新 WSL crontab，让 dispatch.py 每 N 分钟轮询一次。
# 幂等：重复执行只更新那一行。用法： bash install_cron.sh [分钟间隔，默认5]
set -euo pipefail

INTERVAL="${1:-5}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
BINDIR="$(dirname "$PY")"   # 让 cron 子进程(run_job→kimi→pandoc)能找到 pandoc 等
DISPATCH="$HERE/dispatch.py"
LOG="$HERE/state/cron.log"
MARKER="# litreview-dispatch"
mkdir -p "$HERE/state"

# PATH 前缀作用于 $PY 及其所有子进程；否则 cron 极简 PATH 下 pandoc 缺失、docx 退化
LINE="*/$INTERVAL * * * * cd $HERE && PATH=$BINDIR:/usr/bin:/bin $PY $DISPATCH >> $LOG 2>&1 $MARKER"

# 取现有 crontab（没有也不报错），删掉旧的本标记行，追加新行
CUR="$(crontab -l 2>/dev/null || true)"
NEW="$(printf '%s\n' "$CUR" | grep -vF "$MARKER" || true)"
NEW="$(printf '%s\n%s\n' "$NEW" "$LINE" | sed '/^$/d')"
printf '%s\n' "$NEW" | crontab -

echo "✅ 已安装 crontab（每 $INTERVAL 分钟）："
crontab -l | grep -F "$MARKER" || true
echo
echo "日志： $LOG"
echo
# 检查 cron 服务是否在跑（WSL 默认可能没起）
if pgrep -x cron >/dev/null 2>&1; then
  echo "✅ cron 服务运行中"
else
  echo "⚠️  cron 服务似乎没运行。WSL 里启动它："
  echo "    sudo service cron start"
  echo "  （想开机自启：把 'sudo service cron start' 加进 ~/.bashrc 或配 WSL systemd）"
fi
echo
echo "卸载： crontab -l | grep -vF '$MARKER' | crontab -"
