#!/bin/bash
# RateXp installer. Fetches the current skill or plugin template from the core that
# served this script, with the hook already pointing back at that same core.
#
#   curl -fsSL <core>/install.sh | bash -s skill my-skill
#   curl -fsSL <core>/install.sh | bash -s plugin my-plugin
#
# Bash 3.2+ and curl, nothing else. Writes only under the current directory and
# refuses to touch a path that already exists.
set -euo pipefail

DEFAULT_URL='__RATEXP_URL__'
url=${RATEXP_URL:-$DEFAULT_URL}

die() { printf 'ratexp: %s\n' "$1" >&2; exit 1; }

kind=${1:-}
name=${2:-}

if [[ $kind != skill && $kind != plugin ]]; then
    die "usage: curl -fsSL $url/install.sh | bash -s {skill|plugin} <name>"
fi
# The name becomes a directory and is written into a shell command inside SKILL.md,
# so it is restricted to characters that are safe in both. Also blocks path traversal.
if [[ ! $name =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]]; then
    die "name must be lowercase letters, digits and hyphens, e.g. my-skill"
fi

fetch() {  # fetch <path-on-core> <destination>
    curl -fsSL --proto '=https,http' --connect-timeout 5 --max-time 30 \
        --url "$url/$1" --output "$2" || die "could not download $1 from $url"
}

# A download that fails partway would otherwise leave a half-written skill that
# Claude Code still tries to load. Only ever removes the directory this run made:
# we refuse above if it already existed.
made=''
cleanup() {
    if [[ -n $made && -d $made ]]; then rm -rf "$made"; fi
}
trap cleanup EXIT

if [[ $kind == skill ]]; then
    dir=".claude/skills/$name"
    if [[ -e $dir ]]; then die "$dir already exists; remove it or pick another name"; fi
    mkdir -p "$dir"
    made=$dir
    fetch "template/skill/SKILL.md?name=$name" "$dir/SKILL.md"
    fetch "ratexp.sh" "$dir/ratexp.sh"
    chmod +x "$dir/ratexp.sh"
else
    dir=$name
    if [[ -e $dir ]]; then die "$dir already exists; remove it or pick another name"; fi
    mkdir -p "$dir/.claude-plugin" "$dir/skills/$name"
    made=$dir
    fetch "template/plugin/plugin.json?name=$name" "$dir/.claude-plugin/plugin.json"
    fetch "template/plugin/SKILL.md?name=$name" "$dir/skills/$name/SKILL.md"
    fetch "ratexp.sh" "$dir/skills/$name/ratexp.sh"
    chmod +x "$dir/skills/$name/ratexp.sh"
fi

made=''  # everything landed; keep it
printf 'ratexp: %s ready at %s, rating to %s\n' "$kind" "$dir" "$url"
