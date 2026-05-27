#!/bin/bash
# session-start.sh — generic pin hook (from claude-dotfiles template)
# .claude/remote-branch があれば pin、なければ dotfiles の display hook へ委譲

set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0

# 1. .claude/remote-branch があればこのブランチに pin (リモート ephemeral コンテナ用 inline)
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] \
   && [ -f ".claude/remote-branch" ] \
   && git rev-parse --git-dir >/dev/null 2>&1; then
  PINNED_BRANCH=$(head -1 .claude/remote-branch | tr -d '\n\r')
  CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
  if [ -n "$PINNED_BRANCH" ] && [ "$CURRENT_BRANCH" != "$PINNED_BRANCH" ]; then
    git fetch origin "$PINNED_BRANCH" --quiet 2>/dev/null || true
    if git checkout "$PINNED_BRANCH" --quiet 2>/dev/null; then
      git pull --ff-only origin "$PINNED_BRANCH" --quiet 2>/dev/null || true
      echo "📌 Pinned: $CURRENT_BRANCH → $PINNED_BRANCH (.claude/remote-branch)"
      echo ""
    else
      echo "⚠️  .claude/remote-branch に $PINNED_BRANCH 指定があるが checkout 失敗"
      echo ""
    fi
  elif [ -n "$PINNED_BRANCH" ]; then
    echo "📌 On pinned branch: $PINNED_BRANCH"
    echo ""
  fi
fi

# 2. 汎用 display hook に委譲
if [ -x "$HOME/.claude/hooks/session-start-display.sh" ]; then
  exec "$HOME/.claude/hooks/session-start-display.sh"
elif [ -x "/root/.claude/hooks/session-start-display.sh" ]; then
  exec "/root/.claude/hooks/session-start-display.sh"
elif [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "⚠️  ~/.claude/hooks/session-start-display.sh が未配置です。"
  echo "    claude-dotfiles を install.sh でセットアップしてください。"
fi
