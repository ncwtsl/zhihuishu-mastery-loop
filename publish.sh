#!/usr/bin/env bash
# Point this repo at YOUR remote and push it. Fill the two values, then run.
#
#   ./publish.sh                 # uses the values below
#   ./publish.sh <remote-url>    # e.g. git@github.com:you/zhihuishu-mastery-loop.git
#
# Credentials: git will use your platform's helper (Git Credential Manager on
# Windows). If it prompts, paste a Personal Access Token as the password -
# GitHub/Gitee no longer accept account passwords over HTTPS.
set -eu

REMOTE_URL="${1:-<REMOTE_URL>}"     # TODO: replace, e.g. https://github.com/<you>/<repo>.git
BRANCH="${BRANCH:-main}"

case "$REMOTE_URL" in
  "<REMOTE_URL>"|"")
    echo "Set REMOTE_URL first, or pass it as the first argument." >&2
    exit 2
    ;;
esac

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

echo "pushing $BRANCH -> $REMOTE_URL"
git push -u origin "$BRANCH"
echo
echo "done. check: git ls-remote --heads origin"
