#!/bin/bash

# Server management script for RunPod deployment

# Default to staging environment
export ENV=${ENV:-staging}

case "$1" in
    start)
        echo "Starting server..."
        nohup uv run uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
        echo $! > server.pid
        echo "Server started with PID $(cat server.pid)"
        echo "Use './run_server.sh logs' to view logs"
        ;;
    stop)
        echo "Stopping server..."
        pkill -f "uvicorn main:app"
        rm -f server.pid
        echo "Server stopped"
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    logs)
        tail -f server.log
        ;;
    status)
        if pgrep -f "uvicorn main:app" > /dev/null; then
            echo "Server is running (PID: $(pgrep -f 'uvicorn main:app'))"
        else
            echo "Server is not running"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|status}"
        echo "Environment: ENV=${ENV} (override with ENV=local $0 start)"
        exit 1
        ;;
esac
