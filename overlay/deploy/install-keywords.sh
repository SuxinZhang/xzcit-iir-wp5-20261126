#!/usr/bin/env bash
# Install the keyword file the spotter actually reads.
# 安装唤醒词检测器实际读取的关键词文件。
#
# An existing file with different content is left alone: it may hold on-site
# tuning that a reinstall must not silently revert.  The operator gets the
# source path so the replacement stays a deliberate act.
# 已存在且内容不同的文件保持不动，避免重装静默覆盖现场调参结果；
# 脚本打印仓库内路径，替换仍需人工确认。
set -euo pipefail
src=${1:?keyword source file}
dest=${2:?keyword destination file}
test -f "$src" || { printf 'Keyword source missing: %s\n' "$src" >&2; exit 1; }
test -s "$src" || { printf 'Keyword source is empty: %s\n' "$src" >&2; exit 1; }
mkdir -p "$(dirname "$dest")"
if test -f "$dest"; then
    if cmp -s "$src" "$dest"; then
        printf 'Keywords already current: %s\n' "$dest"
        exit 0
    fi
    printf 'Keeping existing keywords: %s\n' "$dest" >&2
    printf 'Repository copy: %s\n' "$src" >&2
    exit 0
fi
install -m 0644 "$src" "$dest"
printf 'Keywords installed: %s\n' "$dest"
