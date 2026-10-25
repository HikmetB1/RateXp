#!/bin/bash
# RateXp installer: Bash 3.2+, curl, and standard macOS/Linux utilities. No packages.
# Run straight from core by whoever uses the coding agent:
#   curl -fsSL <core>/install.sh | bash -s -- install claude
# It saves the agent's hook script next to the agent's settings file and adds RateXp's
# hooks to that file, keeping everything else in it. Running it again replaces
# RateXp's hooks instead of adding them twice; uninstall takes them out again.
set -f
set -o pipefail
umask 077
export LC_ALL=C
DEFAULT_URL='__RATEXP_URL__'
# The hooks each agent needs. Claude Code's are every event ratexp-claude.sh handles
# (its triage()); the dashboard's install popup (app/ratexp/FE/src/App.jsx) lists the same
# ones for pasting by hand. Keep the three in step.
CLAUDE_EVENTS=(SessionStart UserPromptExpansion Stop PreToolUse PostToolUse PostToolUseFailure)
CLAUDE_MATCHERS=('' '' '' 'Skill|AskUserQuestion' AskUserQuestion AskUserQuestion)
# PostToolUse posts the rating and transcript, which a cold core can take ~30s to take.
CLAUDE_TIMEOUTS=('' '' '' '' 60 '')
CURSOR_EVENTS=(sessionStart stop)

# The JSON reader is the hooks' own: hex4, utf8, string, get, quote and good_url
# are the same in ratexp-claude.sh, and a test holds them identical. fail reports a
# bad settings file instead of skipping it, and value takes far more than one hook
# event. white reads the file a line at a time: Bash measures the whole string on
# every ${json:pos:1}, so one string holding a large file would take minutes. No
# token spans lines - a JSON string cannot hold a raw newline - so only white
# ever moves to the next line.
fail() { cannot_edit 'it is not valid JSON'; }
white() {
    while :; do
        while [[ ${json:pos:1} == [$' \t\r'] ]]; do pos=$((pos+1)); done
        (( pos >= ${#json} && row + 1 < ${#lines[@]} )) || return 0
        row=$((row+1)); json=${lines[row]}; pos=0
    done
}
hex4() {
    local h=${json:pos:4}
    [[ $h =~ ^[0-9a-fA-F]{4}$ ]] || fail
    code=$((16#$h)); pos=$((pos+4))
}
utf8() {
    local n=$1 b bytes='' oct
    (( n > 0 && n <= 1114111 )) || fail
    if (( n < 128 )); then b=("$n")
    elif (( n < 2048 )); then b=("$((192+n/64))" "$((128+n%64))")
    elif (( n < 65536 )); then b=("$((224+n/4096))" "$((128+n/64%64))" "$((128+n%64))")
    else b=("$((240+n/262144))" "$((128+n/4096%64))" "$((128+n/64%64))" "$((128+n%64))"); fi
    for n in "${b[@]}"; do printf -v oct '\\%03o' "$n"; bytes=$bytes$oct; done
    printf -v char '%b' "$bytes"
}
string() {
    local c code high rest run
    str=''; pos=$((pos+1))
    while (( pos < ${#json} )); do
        # Consume plain runs together to avoid quadratic parsing of long messages.
        rest=${json:pos}; run=${rest%%[\"\\]*}
        if (( ${#run} )); then
            [[ $run == *[$'\001'-$'\037']* ]] && fail
            str=$str$run; pos=$((pos+${#run}))
        fi
        c=${json:pos:1}; pos=$((pos+1))
        case $c in
            '"') return ;;
            '\')
                c=${json:pos:1}; pos=$((pos+1))
                case $c in
                    '"'|'\'|'/') str=$str$c ;;
                    b) str=$str$'\b' ;; f) str=$str$'\f' ;;
                    n) str=$str$'\n' ;; r) str=$str$'\r' ;; t) str=$str$'\t' ;;
                    u)
                        hex4
                        if (( code >= 55296 && code <= 56319 )); then
                            high=$code
                            [[ ${json:pos:2} == '\u' ]] || fail
                            pos=$((pos+2)); hex4
                            (( code >= 56320 && code <= 57343 )) || fail
                            code=$((65536+(high-55296)*1024+code-56320))
                        elif (( code >= 56320 && code <= 57343 )); then fail; fi
                        utf8 "$code"; str=$str$char ;;
                    *) fail ;;
                esac ;;
            *) fail ;;
        esac
    done
    fail
}
value() {
    local parent=$1 key=$2 depth=$3 id=${#kind[@]} c end k child token sibling
    (( depth < 64 )) || fail
    kind[id]=''; name[id]=$key; up[id]=$parent; val[id]=''
    white; c=${json:pos:1}
    case $c in
        '{'|'[')
            kind[id]=$c; end='}'; [[ $c == '[' ]] && end=']'
            pos=$((pos+1)); white
            if [[ ${json:pos:1} != "$end" ]]; then
                child=0
                while :; do
                    k=$child
                    if [[ $c == '{' ]]; then
                        [[ ${json:pos:1} == '"' ]] || fail
                        string; k=$str; white
                        # Hop sibling to sibling: every earlier one is already complete.
                        for ((sibling=id+1; sibling<${#kind[@]}; sibling=last[sibling])); do
                            [[ ${name[sibling]} == "$k" ]] && fail
                        done
                        [[ ${json:pos:1} == ':' ]] || fail
                        pos=$((pos+1))
                    fi
                    value "$id" "$k" "$((depth+1))"; child=$((child+1)); white
                    [[ ${json:pos:1} == "$end" ]] && break
                    [[ ${json:pos:1} == ',' ]] || fail
                    pos=$((pos+1)); white
                done
            fi
            pos=$((pos+1)) ;;
        '"') kind[id]=string; string; val[id]=$str ;;
        *)
            token=''
            while (( pos < ${#json} )); do
                c=${json:pos:1}
                [[ $c == [\},\]\ $'\t\r\n'] ]] && break
                token=$token$c; pos=$((pos+1))
            done
            case $token in
                true|false|null) kind[id]=$token ;;
                *) [[ $token =~ ^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$ ]] || fail; kind[id]=number ;;
            esac
            val[id]=$token ;;
    esac
    last[id]=${#kind[@]}
}
get() {
    local p=$1 k=$2 i
    node=-1; found=''; type=''
    (( p >= 0 )) || return 0
    for ((i=p+1; i<${last[p]}; i++)); do
        if [[ ${up[i]} == "$p" && ${name[i]} == "$k" ]]; then
            node=$i; found=${val[i]}; type=${kind[i]}; return
        fi
    done
}
quote() {
    local s=$1 i c n out='"'
    for ((i=0; i<${#s}; i++)); do
        c=${s:i:1}
        case $c in
            '"'|'\') out=$out\\$c ;;
            *) if [[ $c < ' ' ]]; then printf -v n '\\u%04x' "'$c"; out=$out$n; else out=$out$c; fi ;;
        esac
    done
    quoted=$out'"'
}
# Either https, or plain http on loopback so a local dashboard still works.
good_url() {
    [[ $1 =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?(/[a-zA-Z0-9_./-]*)?$ ||
       $1 =~ ^http://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?(/[a-zA-Z0-9_./-]*)?$ ]]
}

say() { printf 'RateXp: %s\n' "$1"; }
die() { printf 'RateXp: %s\n' "$1" >&2; exit 1; }
usage() {
    printf '%s\n' "Usage: curl -fsSL $url/install.sh | bash -s -- <action> <agent> [--settings FILE]" \
        '  action           install, uninstall or status' \
        '  agent            claude (Claude Code) or cursor (Cursor)' \
        '  --settings FILE  the settings file to use instead of ~/.claude/settings.json' \
        '                   or ~/.cursor/hooks.json; the hook script is saved beside it' >&2
    exit 2
}
# The settings file cannot be changed safely, so nothing is. An install still shows
# the section to add by hand: the same one the dashboard's install popup shows.
cannot_edit() {  # cannot_edit <reason>
    [[ -n ${download-} ]] && rm -f -- "$download"
    printf 'RateXp: %s was left unchanged: %s.\n' "$settings" "$1" >&2
    if [[ $action == install ]]; then
        kind=(); name=(); up=(); val=(); last=(); drop=(); extra=(); lines=('{}'); row=0; json='{}'; pos=0
        value -1 '' 0; add_ratexp_hooks; parts=(); emit 0 ''; printf -v out '%s' "${parts[@]}"
        printf '%s\n' 'Fix it, or add this section to it by hand (also in the Install RateXp popup on the dashboard):' \
            '' "$out" >&2
    fi
    exit 1
}

# A node's direct children: its own in file order, then any grafted onto it.
children() {  # children <node>: sets kids
    local i
    kids=()
    for ((i=$1+1; i<${last[$1]}; i=last[i])); do kids+=("$i"); done
    for i in ${extra[$1]-}; do kids+=("$i"); done
}
# Parse a JSON value as a new last child of a node, so emit writes it after the rest.
graft() {  # graft <parent> <key> <json>: sets grafted
    grafted=${#kind[@]}
    lines=("$3"); row=0; json=$3; pos=0
    value "$1" "$2" 1
    extra[$1]="${extra[$1]-} $grafted"
}
# Write a node back as JSON with two-space indents, leaving out anything dropped.
emit() {  # emit <node> <indent>: appends to parts
    local id=$1 pad=$2 kids child first=1 close
    case ${kind[id]} in
        '{'|'[')
            close='}'; [[ ${kind[id]} == '[' ]] && close=']'
            parts+=("${kind[id]}")
            children "$id"
            for child in "${kids[@]}"; do
                [[ -n ${drop[child]-} ]] && continue
                (( first )) || parts+=(,)
                first=0; parts+=($'\n'"$pad  ")
                [[ ${kind[id]} == '{' ]] && { quote "${name[child]}"; parts+=("$quoted: "); }
                emit "$child" "$pad  "
            done
            (( first )) || parts+=($'\n'"$pad")
            parts+=("$close") ;;
        string) quote "${val[id]}"; parts+=("$quoted") ;;
        *) parts+=("${val[id]}") ;;
    esac
}

# One event's RateXp entry, as JSON.
ratexp_entry() {  # ratexp_entry <event index>: sets entry
    local hook
    quote "$hook_command"
    if [[ $agent == cursor ]]; then entry="{\"command\": $quoted}"; return; fi
    hook="{\"type\": \"command\", \"command\": $quoted"
    [[ -n ${CLAUDE_TIMEOUTS[$1]} ]] && hook="$hook, \"timeout\": ${CLAUDE_TIMEOUTS[$1]}"
    entry="{\"hooks\": [$hook}]}"
    [[ -n ${CLAUDE_MATCHERS[$1]} ]] && entry="{\"matcher\": \"${CLAUDE_MATCHERS[$1]}\", \"hooks\": [$hook}]}"
}
# Add RateXp's entry to each of its events, creating hooks and events as needed.
add_ratexp_hooks() {
    local i
    if [[ $agent == cursor ]]; then get 0 version; (( node >= 0 )) || graft 0 version 1; fi
    get 0 hooks; hooks=$node
    (( hooks >= 0 )) || { graft 0 hooks '{}'; hooks=$grafted; }
    for ((i=0; i<${#events[@]}; i++)); do
        ratexp_entry "$i"
        get "$hooks" "${events[i]}"
        if (( node < 0 )); then graft "$hooks" "${events[i]}" "[$entry]"
        else unset "drop[$node]"; graft "$node" '' "$entry"; fi
    done
    unset "drop[$hooks]"
}
# Whether an entry runs this agent's RateXp script, wherever it was saved.
runs_ratexp() {  # runs_ratexp <entry>
    get "$1" command
    [[ $type == string && $found == *"$script_name"* ]]
}
# Drop every RateXp entry, then any group, event or hooks it leaves empty.
drop_ratexp_hooks() {  # sets removed
    local event group entry kids hits kept_events kept_groups kept_entries
    removed=0
    (( hooks >= 0 )) || return 0
    children "$hooks"; kept_events=0
    for event in "${kids[@]}"; do
        [[ ${kind[event]} == '[' ]] || { kept_events=1; continue; }
        children "$event"; kept_groups=0
        # An event list the user left empty stays; one emptied here goes.
        (( ${#kids[@]} )) || kept_groups=1
        for group in "${kids[@]}"; do
            if [[ $agent == cursor ]]; then
                if runs_ratexp "$group"; then drop[group]=1; removed=$((removed+1)); else kept_groups=1; fi
                continue
            fi
            get "$group" hooks
            [[ $type == '[' ]] || { kept_groups=1; continue; }
            children "$node"; hits=0; kept_entries=0
            for entry in "${kids[@]}"; do
                if runs_ratexp "$entry"; then drop[entry]=1; hits=$((hits+1)); else kept_entries=1; fi
            done
            removed=$((removed+hits))
            if (( hits && !kept_entries )); then drop[group]=1; else kept_groups=1; fi
        done
        if (( kept_groups )); then kept_events=1; else drop[event]=1; fi
    done
    (( removed && !kept_events )) && drop[hooks]=1
    return 0
}
# Whether an event already runs exactly this install's hook command.
has_ratexp_hook() {  # has_ratexp_hook <event index>
    local group entry kids matcher
    (( hooks >= 0 )) || return 1
    get "$hooks" "${events[$1]}"; [[ $type == '[' ]] || return 1
    children "$node"
    for group in "${kids[@]}"; do
        if [[ $agent == cursor ]]; then
            get "$group" command; [[ $type == string && $found == "$hook_command" ]] && return 0
            continue
        fi
        get "$group" matcher; matcher=''; [[ $type == string ]] && matcher=$found
        [[ $matcher == "${CLAUDE_MATCHERS[$1]}" ]] || continue
        get "$group" hooks; [[ $type == '[' ]] || continue
        children "$node"
        for entry in "${kids[@]}"; do
            get "$entry" command; [[ $type == string && $found == "$hook_command" ]] && return 0
        done
    done
    return 1
}

# Read the settings file into the reader's arrays; a missing or blank one is {}.
read_settings() {
    local line
    kind=(); name=(); up=(); val=(); last=(); drop=(); extra=(); original=''; lines=()
    if [[ -e $settings ]]; then
        [[ -f $settings ]] || cannot_edit 'it is not a file'
        original=$(< "$settings") || cannot_edit 'it cannot be read'
        while IFS= read -r line || [[ -n $line ]]; do lines+=("$line"); done < "$settings"
    fi
    row=0; json=${lines[0]-}; pos=0; white
    (( pos < ${#json} )) || { lines=('{}'); row=0; json='{}'; pos=0; }
    value -1 '' 0; white
    (( pos == ${#json} )) || fail
    [[ ${kind[0]} == '{' ]] || cannot_edit 'it is not a JSON object'
    get 0 hooks; hooks=$node
    (( hooks < 0 )) || [[ ${kind[hooks]} == '{' ]] || cannot_edit 'its "hooks" is not an object'
}
# Save the new settings in place, so a symlinked file stays a symlink, after
# keeping a copy of what was there. An unchanged file is left alone.
write_settings() {
    parts=(); emit 0 ''; printf -v out '%s' "${parts[@]}"
    [[ $out == "$original" ]] && return 1
    if [[ -e $settings ]]; then
        cp -p -- "$settings" "$settings.ratexp-backup" || die "could not back up $settings."
        say "kept the old file as $settings.ratexp-backup"
    fi
    printf '%s\n' "$out" > "$settings" || die "could not write $settings."
}

# The core this hook script posts to, read from its baked-in default.
script_core_url() {  # sets script_url
    local line
    script_url=''
    while IFS= read -r line; do
        [[ $line == DEFAULT_URL=* ]] || continue
        script_url=${line#DEFAULT_URL=}; script_url=${script_url//\'/}
        return
    done < "$script"
}
# RateXp's /ratexp command files, which the hook script wrote beside itself.
is_ratexp_command() {  # is_ratexp_command <file>
    local line
    [[ -f $1 && ! -L $1 ]] || return 1
    while IFS= read -r line; do
        [[ $agent == cursor && $line == '# RateXp survey' ]] && return 0
        [[ $agent == claude && $line == 'RateXp target: '* ]] && return 0
        [[ $agent == cursor ]] && return 1
    done < "$1"
    return 1
}

install_ratexp() {
    mkdir -p -- "$dir" || die "could not create $dir."
    download=$dir/.$script_name.download
    curl -q -fsSL --proto '=https,http' --connect-timeout 10 --max-time 60 \
        -o "$download" --url "$url/$script_name" || { rm -f -- "$download"; die "could not download $url/$script_name."; }
    local first=''
    IFS= read -r first < "$download"
    [[ $first == '#!/bin/bash' ]] || { rm -f -- "$download"; die "$url/$script_name is not a RateXp hook script."; }
    read_settings
    drop_ratexp_hooks
    add_ratexp_hooks
    mv -f -- "$download" "$script" || die "could not save $script."
    download=''
    say "saved $script"
    if write_settings; then say "added its hooks to $settings"
    else say "its hooks were already in $settings"; fi
    if [[ $agent == claude ]]; then say 'done. Start a new Claude Code session, then type /ratexp.'
    else say 'done. Start a new Cursor chat, then type /ratexp.'; fi
}
uninstall_ratexp() {
    local file
    if [[ -e $settings ]]; then
        read_settings
        drop_ratexp_hooks
        if (( removed )) && write_settings; then say "removed $removed RateXp hooks from $settings"
        else say "no RateXp hooks in $settings"; fi
    fi
    if [[ -f $script ]]; then rm -f -- "$script" && say "removed $script"; fi
    set +f
    for file in "$dir/commands/ratexp.md" "$dir/commands/ratexp/"*.md; do
        is_ratexp_command "$file" && rm -f -- "$file" && say "removed $file"
    done
    set -f
    rmdir -- "$dir/commands/ratexp" 2>/dev/null
    return 0
}
show_status() {
    local i missing=0
    printf 'Settings: %s\n' "$settings"
    read_settings
    for ((i=0; i<${#events[@]}; i++)); do
        if has_ratexp_hook "$i"; then printf '  hook %-20s present\n' "${events[i]}"
        else printf '  hook %-20s missing\n' "${events[i]}"; missing=1; fi
    done
    if [[ -f $script ]]; then
        script_core_url
        printf 'Script:   %s (posts to %s)\n' "$script" "${script_url:-an unknown core}"
    else
        printf 'Script:   %s missing\n' "$script"; missing=1
    fi
    (( missing )) && { say "not fully installed; run install to fix it."; return 1; }
    say 'installed.'
}

url=${RATEXP_URL:-$DEFAULT_URL}; url=${url%/}
action=${1-}; agent=${2-}
case $action in install|uninstall|status) ;; *) usage ;; esac
case $agent in
    claude) home=$HOME/.claude; script_name=ratexp-claude.sh; settings=$home/settings.json
            events=("${CLAUDE_EVENTS[@]}") ;;
    cursor) home=$HOME/.cursor; script_name=ratexp-cursor.sh; settings=$home/hooks.json
            events=("${CURSOR_EVENTS[@]}") ;;
    *) usage ;;
esac
if (( $# == 4 )) && [[ $3 == --settings && -n $4 ]]; then settings=$4
elif (( $# != 2 )); then usage; fi
[[ -n ${HOME-} ]] || die 'HOME is not set.'
for token in curl mkdir mv cp rm rmdir; do command -v "$token" >/dev/null || die "needs $token."; done
good_url "$url" || die "$url is not an https address (or http on this machine)."
[[ $settings == /* ]] || settings=$PWD/$settings
[[ $settings == */ ]] && usage
dir=${settings%/*}; dir=${dir:-/}
# Name existing folders by their real paths, so ~/.claude reached another way is
# still global. One not made yet is compared as written; install makes it.
[[ -d $dir ]] && dir=$(cd -P -- "$dir" && pwd)
[[ -d $home ]] && home=$(cd -P -- "$home" && pwd)
settings=$dir/${settings##*/}; script=$dir/$script_name
# The command each hook runs. The agent's own folder keeps the command the install
# popup shows; a project's folder gets one that works wherever the project is
# checked out; anything else names the script by its full path.
if [[ $dir == "$home" && $agent == claude ]]; then hook_command='bash "$HOME/.claude/ratexp-claude.sh"'
elif [[ $dir == "$home" ]]; then hook_command='bash ./ratexp-cursor.sh'
elif [[ $agent == claude && $dir == */.claude ]]; then hook_command='bash "$CLAUDE_PROJECT_DIR/.claude/ratexp-claude.sh"'
elif [[ $agent == cursor && $dir == */.cursor ]]; then hook_command='bash .cursor/ratexp-cursor.sh'
else
    # The path lands inside a shell command the agent runs.
    [[ $script =~ ^[a-zA-Z0-9_./\ -]+$ ]] || die "$script has characters a hook command cannot hold; pick a plainer path."
    hook_command="bash \"$script\""
fi
case $action in
    install) install_ratexp ;;
    uninstall) uninstall_ratexp ;;
    status) show_status ;;
esac
