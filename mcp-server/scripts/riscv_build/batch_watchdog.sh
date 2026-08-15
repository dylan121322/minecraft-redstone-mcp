#!/bin/bash
# batch_watchdog.sh — keep the Win batch alive: if the launcher process tree
# died (python count < 2) and batch_done.txt is absent, re-run the schtask.
#
# 敏感信息全部走环境变量（不硬编码）：
#   SSH_HOST / SSH_PORT / SSH_PASS（同 batch_loop.sh）
#   WIN_PROJECT_DIR   Windows 侧项目目录
#   WIN_TASK_NAME     Windows 计划任务名（默认 batchjob）
SSH_HOST="${SSH_HOST:?set SSH_HOST}"
SSH_PORT="${SSH_PORT:?set SSH_PORT}"
SSHPASS="${SSH_PASS:?set SSH_PASS}"
WIN_DIR="${WIN_PROJECT_DIR:?set WIN_PROJECT_DIR}"
TASK="${WIN_TASK_NAME:-batchjob}"
SSHOPTS='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15'
MARK="${WIN_DIR}\\redstone3d\\batch_done.txt"

for round in $(seq 1 400); do
  STATE=$(sshpass -p "$SSHPASS" ssh $SSHOPTS -p "$SSH_PORT" "$SSH_HOST" \
    "powershell -Command \"if (Test-Path '$MARK') { 'DONE' } else { \$c=(Get-Process python -ErrorAction SilentlyContinue | Measure-Object).Count; if (\$c -lt 2) { 'DEAD' } else { 'RUNNING:' + \$c } }\"" 2>/dev/null | tr -d '\r' | tail -1)
  case "$STATE" in
    DONE*)
      echo "[watchdog $round] BATCH COMPLETE"
      exit 0 ;;
    DEAD*)
      echo "[watchdog $round] tree dead — rerunning task"
      sshpass -p "$SSHPASS" ssh $SSHOPTS -p "$SSH_PORT" "$SSH_HOST" \
        "powershell -Command \"schtasks /Run /TN $TASK\"" >/dev/null 2>&1 ;;
    RUNNING*)
      echo "[watchdog $round] $STATE" ;;
    *)
      echo "[watchdog $round] no state (conn issue)" ;;
  esac
  sleep 480
done
echo "WATCHDOG MAX ROUNDS"
