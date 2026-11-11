#!/bin/bash
# Agent Gateway — background runner with auto-restart.
# Usage: ./start_gateway.sh        (start in background)
#        ./start_gateway.sh stop   (stop)
#        ./start_gateway.sh status (check status)

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$HOME/.ag_data/gateway.pid"
LOGDIR="$HOME/.ag_data/logs"
STDOUT="$LOGDIR/gateway.stdout.log"
STDERR="$LOGDIR/gateway.stderr.log"

mkdir -p "$LOGDIR"

case "${1:-start}" in
  start)
    # Kill existing if running
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Gateway already running (PID $(cat "$PIDFILE")). Use '$0 stop' first."
      exit 1
    fi

    echo "Starting Agent Gateway..."
    cd "$DIR"
    nohup python3 -u main.py --gateway >> "$STDOUT" 2>> "$STDERR" &
    echo $! > "$PIDFILE"
    sleep 3

    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ Gateway started (PID $(cat "$PIDFILE"))"
      echo "   Logs: $STDOUT"
    else
      echo "❌ Gateway failed to start. Check: $STDERR"
      rm -f "$PIDFILE"
      exit 1
    fi
    ;;

  stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping gateway (PID $PID)..."
        kill "$PID"
        sleep 3
        # Force kill if still alive
        kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
        echo "✅ Gateway stopped."
      else
        echo "Gateway not running (stale PID file)."
      fi
      rm -f "$PIDFILE"
    else
      echo "No PID file found. Gateway not running."
      pkill -f "main.py --gateway" 2>/dev/null
    fi
    ;;

  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      PID=$(cat "$PIDFILE")
      echo "✅ Gateway running (PID $PID)"
      echo "   Uptime: $(ps -o etime= -p "$PID" | xargs)"
      tail -3 "$STDOUT"
    else
      echo "❌ Gateway not running."
    fi
    ;;

  restart)
    "$0" stop
    sleep 35  # Wait for Telegram session lock to clear
    "$0" start
    ;;

  *)
    echo "Usage: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
