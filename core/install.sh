#!/bin/bash
# RateXp installer. Fetches the current skill or session template from the core
# that served this script, with the hook already pointing back at that core.
#
#   curl -fsSL <core>/install.sh | bash -s skill my-skill
#   curl -fsSL <core>/install.sh | bash -s session claude
#
# Bash 3.2+ and curl, nothing else. Writes only under the current directory and
# refuses to touch a path that already exists. `session` never edits the agent's
# settings file: merging JSON needs a parser this script deliberately does not
# have, and that file is the user's own. It prints what to add instead.
set -euo pipefail

DEFAULT_URL='__RATEXP_URL__'
url=${RATEXP_URL:-$DEFAULT_URL}

die() { printf 'ratexp: %s\n' "$1" >&2; exit 1; }

kind=${1:-}
name=${2:-}

if [[ $kind != skill && $kind != session ]]; then
    die "usage: curl -fsSL $url/install.sh | bash -s skill <name>
       curl -fsSL $url/install.sh | bash -s session <coding-agent>"
fi
# Every coding agent keeps its hooks somewhere else and spells the events its own
# way, so the agent is named and each one gets its own arm below. Claude Code is
# the one RateXp is tested against; the rest report themselves as unsupported
# rather than installing hooks that would silently never fire.
if [[ $kind == session ]]; then
    agent=${2:-}
    case $agent in
        claude)
            agent_dir=".claude"
            hook_path="$agent_dir/ratexp-coding-agent.sh"
            settings_path="$agent_dir/settings.json"
            command_path="$agent_dir/commands/ratexp.md"
            settings_template="template/session/settings.json"
            ;;
        '')
            die "usage: curl -fsSL $url/install.sh | bash -s session <coding-agent>
       supported today: claude" ;;
        *)
            die "$agent is not supported yet; RateXp is tested against: claude" ;;
    esac
# The name becomes a directory and is written into a shell command inside SKILL.md,
# so it is restricted to characters that are safe in both. Also blocks path traversal.
elif [[ ! $name =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]]; then
    die "name must be lowercase letters, digits and hyphens, e.g. my-skill"
fi

fetch() {  # fetch <path-on-core> <destination>
    curl -fsSL --proto '=https,http' --connect-timeout 5 --max-time 30 \
        --url "$url/$1" --output "$2" || die "could not download $1 from $url"
}

# A download that fails partway would otherwise leave a half-written skill that
# Claude Code still tries to load. Only ever removes what this run made: a whole
# directory when it created one, and otherwise the individual files it wrote -
# session mode installs into .claude/, which is usually already full of the
# user's own work and must never be removed wholesale.
made=''
leftovers=()
cleanup() {
    if [[ -n $made && -d $made ]]; then rm -rf "$made"; fi
    if (( ${#leftovers[@]} )); then rm -f "${leftovers[@]}"; fi
}
trap cleanup EXIT

if [[ $kind == skill ]]; then
    dir=".claude/skills/$name"
    if [[ -e $dir ]]; then die "$dir already exists; remove it or pick another name"; fi
    mkdir -p "$dir"
    made=$dir
    fetch "template/skill/SKILL.md?name=$name" "$dir/SKILL.md"
    fetch "ratexp-skill.sh" "$dir/ratexp-skill.sh"
    chmod +x "$dir/ratexp-skill.sh"
else
    # The hooks belong in the agent's own settings file, so they are on from the
    # first turn instead of waiting for some skill to be invoked.
    dir=$agent_dir
    if [[ -e $hook_path ]]; then die "$hook_path already exists; remove it first"; fi
    if [[ -d $dir ]]; then leftovers+=("$hook_path"); else mkdir -p "$dir"; made=$dir; fi
    fetch "ratexp-coding-agent.sh" "$hook_path"
    chmod +x "$hook_path"
    # /ratexp asks for the survey by name, rather than waiting for the count.
    if [[ ! -e $command_path ]]; then
        mkdir -p "${command_path%/*}"
        if [[ -z $made ]]; then leftovers+=("$command_path"); fi
        fetch "template/session/ratexp.md" "$command_path"
    fi
fi

made=''; leftovers=()  # everything landed; keep it
printf 'ratexp: %s ready at %s, rating to %s\n' "$kind" "$dir" "$url"

if [[ $kind == session ]]; then
    # Never edit the agent's settings: merging JSON needs a parser this script does
    # not have, and that file is the user's own. Show exactly what to add instead.
    printf '\n'
    printf '  ┌─ one step left ─────────────────────────────────────────────┐\n'
    printf '  │ Add these hooks to: %-39s │\n' "$settings_path"
    printf '  │ If that file already has a "hooks" block, merge them in;    │\n'
    printf '  │ if it does not exist yet, this is the whole file.           │\n'
    printf '  └─────────────────────────────────────────────────────────────┘\n\n'
    curl -fsSL --proto '=https,http' --connect-timeout 5 --max-time 30 \
        --url "$url/$settings_template" || die "could not show the hooks from $url"
    printf '\n  Copy it from: %s/%s\n' "$url" "$settings_template"
fi
