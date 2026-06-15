#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/dev/null
[[ -f deploy.env ]] && source deploy.env

HOST="${DEPLOY_HOST:?set DEPLOY_HOST in deploy.env}"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/oracle}"
REMOTE_DIR=rl-tournament-notification-bot
SSH="ssh -i $SSH_KEY $HOST"

usage() {
    echo "Usage: $0 <command>"
    echo "  env     — sync .env.production to server and restart container"
    echo "  update  — git pull on server, rebuild image, recreate container"
    echo "  logs    — tail container logs"
    echo "  restart — restart container"
}

sync_env() {
    rsync -e "ssh -i $SSH_KEY" .env.production "$HOST:$REMOTE_DIR/.env"
}

recreate() {
    $SSH "cd $REMOTE_DIR && docker rm -f rlbot; docker run -d --name rlbot --restart unless-stopped --env-file .env rlbot"
    echo "Waiting for bot to start..."
    $SSH "docker logs -f rlbot 2>&1 | grep -m1 'Application started'"
    echo "Bot is up."
}

case "${1:-}" in
    env)
        echo "Syncing .env.production..."
        sync_env
        echo "Recreating container..."
        recreate
        $SSH "docker logs --tail 20 rlbot"
        ;;
    update)
        echo "Pulling latest code and rebuilding..."
        $SSH "cd $REMOTE_DIR && git fetch origin && git reset --hard origin/main && docker build -t rlbot ."
        echo "Recreating container..."
        recreate
        $SSH "docker logs --tail 20 rlbot"
        ;;
    logs)
        $SSH "docker logs -f rlbot"
        ;;
    restart)
        $SSH "docker rm -f rlbot"
        recreate
        $SSH "docker logs --tail 20 rlbot"
        ;;
    *)
        usage
        exit 1
        ;;
esac
