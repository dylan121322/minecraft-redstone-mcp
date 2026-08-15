#!/bin/bash
# batch_loop.sh — restart-safe batch driver: relaunches the Win batch
# launcher whenever the FRP connection drops; finished configs are skipped.
#
# 敏感信息全部走环境变量（不硬编码）：
#   SSH_HOST      例: user@frp-host.example.com
#   SSH_PORT      例: 59325
#   SSH_PASS      例: xxxxxxxx
#   WIN_PROJECT_DIR   Windows 侧项目目录，例: E:\project\<name>
#   WIN_PYTHON        Windows 侧 python.exe 完整路径
SSH_HOST="${SSH_HOST:?set SSH_HOST}"
SSH_PORT="${SSH_PORT:?set SSH_PORT}"
SSHPASS="${SSH_PASS:?set SSH_PASS}"
WIN_DIR="${WIN_PROJECT_DIR:?set WIN_PROJECT_DIR}"
PY="${WIN_PYTHON:?set WIN_PYTHON}"
SSHOPTS='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=3'
REMOTE_DIR="${WIN_DIR}\\redstone3d"

for attempt in $(seq 1 200); do
  # check for the done marker
  DONE=$(sshpass -p "$SSHPASS" ssh $SSHOPTS -p "$SSH_PORT" "$SSH_HOST" \
    "cmd /c \"if exist $REMOTE_DIR\\batch_done.txt (echo DONE) else (echo RUNNING)\"" 2>/dev/null | tr -d '\r')
  if [ "$DONE" = "DONE" ]; then
    echo "BATCH COMPLETE (attempt $attempt)"
    exit 0
  fi
  echo "[attempt $attempt] state=$DONE — launching launcher"
  sshpass -p "$SSHPASS" ssh $SSHOPTS -p "$SSH_PORT" "$SSH_HOST" \
    "cmd /c \"cd /d $REMOTE_DIR && $PY batch_launcher.py >> launcher.log 2>&1\"" 2>&1 | tail -3
  echo "[attempt $attempt] launcher session ended (drop or finish); re-checking"
  sleep 10
done
echo "MAX ATTEMPTS REACHED"
exit 1
