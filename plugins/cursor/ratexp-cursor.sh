#!/bin/bash
# RateXp for Cursor: Bash 3.2+, curl, and standard macOS/Linux utilities.
#
# The RateXp plugin runs it for whoever uses Cursor. It asks about the whole chat
# every Nth turn on its own, and whenever the user types /ratexp:rate.
# /ratexp:rate <skill> rates only that skill's most recent run - a skill is never
# asked about on its own. An eval's name picks which of core's surveys is asked.
#
#   ask ['/ratexp:rate [skill] [eval]']
#                            what the plugin's ratexp skill runs, with the request
#                            as the user typed it: finds this chat's transcript,
#                            notes what is being rated, and prints the two
#                            questions for the agent to ask
#   report <good|bad> <share|private> [comment]
#                            what the agent runs with the user's answer; owns the
#                            feedback post and the consented transcript upload
#   (no arguments)           a Cursor hook. sessionStart asks core for the surveys
#                            and makes sure ~/.cursor/hooks.json has a stop hook;
#                            stop asks for the survey every Nth turn
#
# Rating itself needs no hook: the Cursor CLI does not always fire them, and the
# transcript it writes is enough. Only the every-Nth-turn survey rides on the stop
# hook. Consent is a required word rather than a default, so an agent that forgets
# an argument cannot upload a private chat.
set -f
set -o pipefail
umask 077
export LC_ALL=C
# Ratings go to the hosted core unless RATEXP_URL names another. That core sends the
# turns between surveys, the default eval and the evals (see fetch_hook_settings);
# RATEXP_EVERY overrides the turns.
DEFAULT_URL=https://ratexp-core.azurewebsites.net
DEFAULT_EVERY=''
DEFAULT_EVAL=''
# The evals core offers, six fields each: the name typed after /ratexp:rate, the
# question - where {subject}, if used, becomes what is rated - then the label and
# description of the good answer, and of the bad one.
EVALS=()

# Strict JSON reader using indexed arrays (also supported by macOS Bash 3.2).
# No eval, menu scanning, or third-party JSON runtime.
# The reader, quote, good_url, post, file_info, open_file_info, ratexp_request,
# request_target, find_eval, evals_offered, unknown_eval_line, fetch_hook_settings,
# load_hook_settings, manifest_version and is_newer are the same in
# ratexp-claude.sh: a test holds the two copies identical, so change them together.
fail() { exit 0; }
white() { while [[ ${json:pos:1} == [$' \t\r\n'] ]]; do pos=$((pos+1)); done; }
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
    (( depth < 24 && id < 2048 )) || fail
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
                        for ((sibling=id+1; sibling<${#kind[@]}; sibling++)); do
                            [[ ${up[sibling]} == "$id" && ${name[sibling]} == "$k" ]] && fail
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
# Consent names what would be uploaded and where.
consent_line() {  # consent_line <url> <what>
    consent="Upload $2, including messages and tool results, to $1?"
}
# A /ratexp:rate request as the user typed it, such as /ratexp:rate poem-creator
# human-time-saved: sets the first and the second word after the command, if any.
# The Cursor CLI also takes plain /ratexp for it. Fails for any other command.
ratexp_request() {  # ratexp_request <request>: sets first, second
    local pattern='^/ratexp(:rate)?([[:space:]]+([^[:space:]]+))?([[:space:]]+([^[:space:]]+))?([[:space:]]|$)'
    first=''; second=''
    [[ $1 =~ $pattern ]] || return 1
    first=${BASH_REMATCH[3]}; second=${BASH_REMATCH[5]}
}
# What a request rates. Two words are a skill, then an eval. One word is an eval
# when core offers an eval by that name, and a skill otherwise. No word is the
# whole session. An empty eval_name means core's default eval.
request_target() {  # request_target <first> <second>: sets target, eval_name
    target=$1; eval_name=$2
    [[ -z $2 ]] && find_eval "$1" && { target=''; eval_name=$1; }
    return 0
}
# One of the evals in EVALS, by name: sets its question, and the label and
# description of each answer. Fails for a name core does not offer.
find_eval() {  # find_eval <name>
    local i
    for ((i=0; i+5<${#EVALS[@]}; i+=6)); do
        [[ ${EVALS[i]} == "$1" ]] || continue
        eval_question=${EVALS[i+1]}
        good_label=${EVALS[i+2]}; good_description=${EVALS[i+3]}
        bad_label=${EVALS[i+4]}; bad_description=${EVALS[i+5]}
        return 0
    done
    return 1
}
# The names of the evals core offers, comma-separated.
evals_offered() {  # evals_offered: sets offered
    local i
    offered=''
    for ((i=0; i+5<${#EVALS[@]}; i+=6)); do offered=$offered${offered:+, }${EVALS[i]}; done
}
# What a user who names an eval core does not offer is told instead.
unknown_eval_line() {  # unknown_eval_line <name>: sets unknown
    local offered
    evals_offered
    unknown="RateXp: there is no eval named $1. Choose one of: $offered."
}
# Asks core for the surveys and the turns between them, and keeps the answer in
# <file> for the times core cannot be reached. Each field ends in a NUL:
# the newest plugin version, the turns between surveys, the default eval, then the
# six fields of each eval in the order EVALS holds them.
fetch_hook_settings() {  # fetch_hook_settings <file>
    local response
    [[ ! -L $1 && ! -L $1.tmp ]] && mkdir -p -- "${1%/*}" || return 1
    response=$(curl -q --silent --connect-timeout 5 --max-time 10 --max-filesize 65536 \
        --proto '=https,http' --write-out '\n%{http_code}' --url "$url/hook-settings") || return 1
    [[ ${response##*$'\n'} == 200 ]] || return 1
    (
        # The reader's fail ends the hook with success; here it must fail the fetch.
        fail() { exit 1; }
        json=${response%$'\n'*}; kind=(); name=(); up=(); val=(); last=(); pos=0
        (( ${#json} <= 65536 )) || fail
        value -1 '' 0; white
        (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || fail
        get 0 plugin_version
        [[ $type == string && $found =~ ^[0-9]{1,9}(\.[0-9]{1,9}){0,3}$ ]] || fail
        printf '%s\0' "$found"
        get 0 every; [[ $type == number && $found =~ ^[1-9][0-9]{0,4}$ ]] || fail
        printf '%s\0' "$found"
        get 0 default_eval; [[ $type == string && -n $found ]] || fail
        printf '%s\0' "$found"
        get 0 evals; list=$node; [[ $type == '[' ]] || fail
        for ((i=0; ; i++)); do
            get "$list" "$i"; (( node >= 0 )) || break
            entry=$node
            for key in name question good_label good_description bad_label bad_description; do
                get "$entry" "$key"; [[ $type == string ]] || fail
                printf '%s\0' "$found"
            done
        done
    ) > "$1.tmp" && mv -- "$1.tmp" "$1"
}
# What fetch_hook_settings kept: sets latest, DEFAULT_EVERY, DEFAULT_EVAL and EVALS.
load_hook_settings() {  # load_hook_settings <file>
    local field
    local -a fields
    [[ -f $1 && ! -L $1 ]] || return 1
    while IFS= read -r -d '' field; do fields+=("$field"); done < "$1"
    (( ${#fields[@]} >= 9 && (${#fields[@]} - 3) % 6 == 0 )) || return 1
    latest=${fields[0]}; DEFAULT_EVERY=${fields[1]}; DEFAULT_EVAL=${fields[2]}
    EVALS=("${fields[@]:3}")
}
# The version a plugin manifest names, printed; nothing for a manifest it cannot read.
manifest_version() {  # manifest_version <plugin.json>
    [[ -f $1 && ! -L $1 ]] || return 1
    (
        fail() { exit 1; }
        json=''; IFS= read -r -d '' -n 65537 json < "$1" && fail
        (( ${#json} <= 65536 )) || fail
        kind=(); name=(); up=(); val=(); last=(); pos=0
        value -1 '' 0; white
        (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || fail
        get 0 version; [[ $type == string ]] || fail
        printf '%s' "$found"
    )
}
# Whether the first dotted version is newer than the second, such as 1.10.0 and 1.9.2.
is_newer() {  # is_newer <version> <than version>
    local a=$1. b=$2. x y pattern='^[0-9]{1,9}(\.[0-9]{1,9}){0,3}$'
    [[ $1 =~ $pattern && $2 =~ $pattern ]] || return 1
    while [[ -n $a$b ]]; do
        x=${a%%.*}; y=${b%%.*}; a=${a#*.}; b=${b#*.}
        x=$((10#${x:-0})); y=$((10#${y:-0}))
        (( x == y )) || { (( x > y )); return; }
    done
    return 1
}
# Either https, or plain http on loopback so a local dashboard still works.
good_url() {
    [[ $1 =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?(/[a-zA-Z0-9_./-]*)?$ ||
       $1 =~ ^http://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?(/[a-zA-Z0-9_./-]*)?$ ]]
}
post() {
    local endpoint=$1 status
    shift
    # --url keeps a leading '-' in the address from being read as an option.
    status=$(curl -q --silent --show-error --connect-timeout 5 --max-time 20 \
        --proto '=https,http' --output /dev/null --write-out '%{http_code}' \
        "${fields[@]}" "$@" --url "$url/$endpoint") || return 1
    [[ $status == 201 ]]
}
file_info() {
    stat -L -c '%d:%i:%s' -- "$1" 2>/dev/null || stat -L -f '%d:%i:%z' -- "$1" 2>/dev/null
}
# fstat of the file open on stdin. macOS stats /dev/fd/N as a device of its own,
# so file_info on that path never matches the transcript's path. GNU stat reads
# '-' as stdin and BSD stat reads no file as stdin; BusyBox does neither, but on
# Linux /dev/stdin leads to the open file itself.
open_file_info() {
    stat -L -c '%d:%i:%s' - 2>/dev/null || stat -f '%d:%i:%z' 2>/dev/null ||
        stat -L -c '%d:%i:%s' /dev/stdin 2>/dev/null
}
file_mtime() {
    stat -L -c '%Y' -- "$1" 2>/dev/null || stat -L -f '%m' -- "$1" 2>/dev/null
}
# Where this script lives, the core it sends to, and its state. The plugin's folder
# changes with each version, so state is keyed by the plugin, not by the folder: a
# survey count carries over an update.
where_am_i() {
    local script=${BASH_SOURCE[0]}
    [[ $script == */* ]] || script=./$script
    here=$(cd -P -- "${script%/*}" && pwd) || return 1
    self=$here/${script##*/}
    root=${XDG_STATE_HOME:-$HOME/.local/state}/ratexp
    url=${RATEXP_URL:-$DEFAULT_URL}; url=${url%/}
    project=$(printf '%s' cursor-plugin | cksum); project=${project%% *}
    settings=$(printf '%s' "$url" | cksum); settings=$root/settings-${settings%% *}
    [[ ! -L $root ]]
}
# Cursor runs a plugin's stop hook only when a hooks file also has a stop hook (Cursor
# CLI 2026.11), so without one the every-Nth-turn survey never comes. sessionStart
# therefore adds a stop hook that does nothing to ~/.cursor/hooks.json when that
# file has none, and keeps everything else in the file. The first change keeps the
# old file beside it. Run in a subshell: the reader's arrays hold the hook's event.
STOP_ENTRY='{"command": "true # RateXp: lets Cursor run the stop hook of the RateXp plugin"}'
cursor_stop_hook() {
    local file=$HOME/.cursor/hooks.json hooks stop out='' add_to=0 addition
    [[ ! -L $HOME/.cursor && ! -L $file && ! -L $file.tmp && ! -L $file.ratexp-backup ]] || return
    addition="\"hooks\": {\"stop\": [$STOP_ENTRY]}"
    if [[ ! -e $file ]]; then
        mkdir -p -- "$HOME/.cursor" || return
        out="{\"version\": 1, $addition}"
    else
        [[ -f $file ]] || return
        # NUL is the delimiter: a successful read means NUL or the size limit was hit.
        json=''; IFS= read -r -d '' -n 1048577 json < "$file" && return
        kind=(); name=(); up=(); val=(); last=(); pos=0
        value -1 '' 0; white
        (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || return
        get 0 hooks; hooks=$node
        if (( hooks >= 0 )); then
            [[ $type == '{' ]] || return
            add_to=$hooks; addition="\"stop\": [$STOP_ENTRY]"
            get "$hooks" stop; stop=$node
            if (( stop >= 0 )); then
                # A stop list with an entry already makes Cursor run the plugin's.
                [[ $type == '[' ]] && (( last[stop] == stop + 1 )) || return
                add_to=$stop; addition=$STOP_ENTRY
            fi
        fi
        [[ -e $file.ratexp-backup ]] || printf '%s' "$json" > "$file.ratexp-backup" || return
        emit_json 0 ''
    fi
    printf '%s\n' "$out" > "$file.tmp" && mv -f -- "$file.tmp" "$file"
}
# Write node <id> of the parsed file into out, indented, with the addition put at the
# end of node add_to.
emit_json() {  # emit_json <id> <indent>
    local id=$1 indent=$2 i first=1 close='}'
    case ${kind[id]} in
        '{'|'[')
            [[ ${kind[id]} == '[' ]] && close=']'
            out=$out${kind[id]}
            for ((i=id+1; i<${last[id]}; i++)); do
                [[ ${up[i]} == "$id" ]] || continue
                (( first )) || out=$out,
                first=0; out=$out$'\n'"$indent  "
                if [[ ${kind[id]} == '{' ]]; then quote "${name[i]}"; out="$out$quoted: "; fi
                emit_json "$i" "$indent  "
            done
            if (( id == add_to )); then
                (( first )) || out=$out,
                first=0; out=$out$'\n'"$indent  $addition"
            fi
            (( first )) || out=$out$'\n'"$indent"
            out=$out$close ;;
        string) quote "${val[id]}"; out=$out$quoted ;;
        *) out=$out${val[id]} ;;
    esac
}
# Count a turn once, however often its stop fires; succeed on every Nth.
turn_is_due() {  # turn_is_due <state dir> <turn key>
    local count
    [[ ! -L $1/count && ! -L $1/last-turn ]] || return 1
    [[ -f $1/last-turn && $(< "$1/last-turn") == "$2" ]] && return 1
    printf '%s' "$2" > "$1/last-turn"
    count=0; [[ -f $1/count ]] && count=$(< "$1/count")
    [[ $count =~ ^[0-9]{1,9}$ ]] || count=0
    count=$((count+1)); printf '%s' "$count" > "$1/count"
    (( count % every == 0 ))
}
# Whether a chat's newest user message asks for a rating: /ratexp:rate, or the stop
# hook's followup. Cursor sends the ratexp skill's text along, which opens with
# "RateXp survey"; a bare /ratexp counts only at the start of what the user typed,
# since a path like plugins/cursor/ratexp-cursor.sh names it too.
asked_to_rate() {  # asked_to_rate <transcript>
    tail -c 65536 -- "$1" | grep -e '"role":"user"' -e '"role": "user"' | tail -n 1 |
        grep -q -F -e 'RateXp survey' -e '<user_query>\n/ratexp'
}
# This chat's transcript. Cursor's editor and CLI both write each chat to
# ~/.cursor/projects/<folder>/agent-transcripts/<chat>/<chat>.jsonl, and both
# tell every command the agent runs its chat and that folder. Those variables are
# not documented, so without them the chat is the newest one from the last few
# minutes whose latest user message is the request - never one that only
# mentions RateXp, or was rated earlier.
find_transcript() {
    local f m newest_m=0 now id=${CURSOR_CONVERSATION_ID-}
    now=$(date +%s); transcript=''
    f=${AGENT_TRANSCRIPTS-}/$id/$id.jsonl
    if [[ -n ${AGENT_TRANSCRIPTS-} && $id =~ ^[a-zA-Z0-9_-]{1,128}$ && -f $f && ! -L $f ]]; then
        transcript=$f; return 0
    fi
    set +f
    for f in "$HOME"/.cursor/projects/*/agent-transcripts/*/*.jsonl; do
        [[ -f $f && ! -L $f ]] || continue
        m=$(file_mtime "$f") || continue
        (( now - m < 600 && m >= newest_m )) || continue
        asked_to_rate "$f" || continue
        newest_m=$m; transcript=$f
    done
    set -f
    [[ -n $transcript ]]
}

# Where a skill's run ends. It starts where the skill was called and ends at the
# first user message after the agent has replied - unless that reply asked the
# user something, in which case the answer is still part of the run. This reads
# the transcript only to find the boundary; nothing of it is kept or printed.
run_end() {  # run_end <file> <start> <limit>: sets end
    local line at=$2 agent=0 asked=0
    end=$3
    while IFS= read -r line; do
        if [[ $line == *'"role":"user"'* || $line == *'"role": "user"'* ]]; then
            if (( agent && !asked )); then end=$at; return; fi
            asked=0
        elif [[ $line == *'"role":"assistant"'* || $line == *'"role": "assistant"'* ]]; then
            agent=1; asked=0
            case $line in *'"AskQuestion"'* | *'?"'* | *'?\n'* | *'? '*) asked=1 ;; esac
        fi
        at=$((at+${#line}+1))
    done < <(tail -c "+$(($2+1))" -- "$1" 2>/dev/null | head -c "$(($3-$2))")
}

hook() {
    local event token session generation transcript base every latest
    for token in cksum mkdir rmdir tail grep; do command -v "$token" >/dev/null || return; done
    # NUL is the delimiter: a successful read means NUL or the size limit was hit.
    json=''; IFS= read -r -d '' -n 131073 json && return
    (( ${#json} <= 131072 )) || return
    [[ $json == *'"sessionStart"'* || $json == *'"stop"'* ]] || return
    kind=(); name=(); up=(); val=(); last=(); pos=0
    value -1 '' 0; white
    (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || return
    get 0 hook_event_name; event=$found
    where_am_i || return
    if [[ $event == sessionStart ]]; then
        fetch_hook_settings "$settings"
        ( cursor_stop_hook )
        return
    fi
    [[ $event == stop ]] || return
    # An aborted or errored turn is not a result anyone can rate.
    get 0 status; [[ $type != string || $found == completed ]] || return
    get 0 conversation_id; session=$found
    [[ $type == string && $session =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return
    get 0 generation_id; generation=$found
    [[ $type == string && $generation =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return
    get 0 transcript_path; transcript=$found
    [[ $type == string && -f $transcript && ! -L $transcript ]] || return
    base=$root/$project-$session
    [[ ! -L $base ]] || return
    mkdir -p -- "$base" || return
    # Which model answered is in the event, and nowhere in Cursor's transcript, so
    # it is kept here for `report`. Cursor names Auto "default". A space would split
    # the agent label it ends up in, so anything unexpected is not kept.
    get 0 model
    [[ $found == default ]] && found=auto
    [[ $type == string && $found =~ ^[a-zA-Z0-9._/-]{1,64}$ && ! -L $base/model ]] &&
        printf '%s' "$found" > "$base/model"
    # A turn the user spent rating is not work, so it is not counted: /ratexp:rate,
    # this hook's own followup, or the answer to either - which the user may give
    # in a message of their own, so `report` marks that turn.
    rmdir -- "$base/answered" 2>/dev/null && return
    asked_to_rate "$transcript" && return
    # It uses what core sent at session start. When core was out of reach then, a
    # turn's end asks again, once per chat, so a core that stays down slows nothing.
    if ! load_hook_settings "$settings"; then
        mkdir -- "$base/asked-core" 2>/dev/null && fetch_hook_settings "$settings" &&
            load_hook_settings "$settings" || return
    fi
    # RATEXP_EVERY overrides the turns core sent.
    every=${RATEXP_EVERY:-$DEFAULT_EVERY}
    [[ $every =~ ^[1-9][0-9]{0,4}$ ]] && (( every <= 32768 )) || return
    turn_is_due "$base" "$generation" || return
    # The same survey /ratexp:rate starts, so the agent is sent down the same path.
    quote "RateXp survey for this whole chat: run \`bash \"$self\" ask\` and follow what it prints, word for word. Do nothing else, and do not summarise the session."
    printf '{"followup_message":%s}\n' "$quoted"
}

ask() {
    local url session identity size start request dir what subject question token end unknown
    local first second target eval_name eval_question good_label good_description bad_label bad_description
    local latest mine offered
    for token in cksum date mkdir od stat head tail grep; do command -v "$token" >/dev/null || return 1; done
    where_am_i || return 1
    # No request at all is the stop hook's survey of the whole chat.
    ratexp_request "${*:-/ratexp:rate}" || {
        printf 'RateXp: pass ask the /ratexp:rate request as the user typed it, such as %s\n' \
            "'/ratexp:rate <skill> <eval>'" >&2
        return 1
    }
    good_url "$url" || return 1
    # It asks core for the evals each time, as the user waits for a survey anyway,
    # and uses the answer it kept when core is out of reach.
    fetch_hook_settings "$settings"
    load_hook_settings "$settings" || {
        printf 'RateXp: the surveys could not be loaded from %s, so no survey can be asked.\n' "$url" >&2
        return 1
    }
    mine=$(manifest_version "$here/.cursor-plugin/plugin.json")
    is_newer "$latest" "$mine" &&
        printf '%s\n' "First tell the user: RateXp $latest is out, and they have $mine. To update RateXp, type /plugin in the Cursor CLI, and update the ratexp plugin there."
    request_target "$first" "$second"
    [[ -z $target || $target =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] ||
        { printf 'RateXp: %s is not a skill name.\n' "$target" >&2; return 1; }
    # A request that names no eval asks core's default one.
    find_eval "${eval_name:=$DEFAULT_EVAL}" ||
        { unknown_eval_line "$eval_name"; printf '%s\n' "$unknown" >&2; return 1; }
    find_transcript ||
        { printf 'RateXp: could not find this chat'"'"'s transcript, so nothing can be rated.\n' >&2; return 1; }
    session=${transcript##*/}; session=${session%.jsonl}
    [[ $session =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return 1
    identity=$(file_info "$transcript") || return 1
    size=${identity##*:}; identity=${identity%:*}
    # The whole chat starts at byte zero. A skill starts at its newest run: the
    # last line naming its SKILL.md - attached by /<skill>, or read by the agent.
    start=0
    if [[ -n $target ]]; then
        start=$(grep -b -F -- "/skills/$target/SKILL.md" "$transcript" | tail -n 1)
        start=${start%%:*}
        if [[ ! $start =~ ^[0-9]{1,10}$ ]] || (( start >= size )); then
            # One word that names no eval was read as a skill; it may be either.
            if [[ -z $second ]]; then
                evals_offered
                printf 'RateXp: %s is neither an eval nor a skill that ran in this chat. The evals are: %s.\n' \
                    "$target" "$offered" >&2
            else
                printf 'RateXp: there is no run of %s in this chat to rate yet.\n' "$target" >&2
            fi
            return 1
        fi
        # Only the skill's own turns: the rest of the chat is not what is rated.
        run_end "$transcript" "$start" "$size"; size=$end
    fi
    request=$(od -An -N16 -tx1 /dev/urandom) || return 1
    request=${request//[[:space:]]/}
    [[ ${#request} == 32 ]] || return 1
    request=${request:0:8}-${request:8:4}-${request:12:4}-${request:16:4}-${request:20:12}
    dir=$root/$project-$session/runs/$request
    [[ ! -L $root/$project-$session ]] || return 1
    mkdir -p -- "$dir" || return 1
    printf '%s\0' "$request" "$(date +%s)" "$session" "$transcript" "$size" "$start" \
        "$identity" "$url" "$target" "$eval_name" > "$dir/pending"
    what='this whole chat'; subject='this session'
    [[ -n $target ]] && { what="this run of $target"; subject=$target; }
    consent_line "$url" "$what"
    question=${eval_question//"{subject}"/$subject}
    printf '%s\n' \
        "RateXp survey for $what. Ask the user these two questions - with AskQuestion if it" \
        'is available, titled RateXp, otherwise both in one message - and wait for the answer:' \
        "1. verdict: \"$question\" - options $good_label ($good_description), $bad_label ($bad_description)" \
        "2. transcript: \"$consent\" - options share, private" \
        "Then run this once, with exactly what the user chose - good for $good_label, bad for $bad_label:" \
        "bash \"$self\" report <good|bad> <share|private> '<comment>'" \
        'The transcript stays private unless the user chose share. The comment is only what' \
        "the user typed, if anything, in single quotes with each ' written as '\\''. Print" \
        'what that command prints, word for word, and nothing else. Never rate it yourself.'
}

report() {
    local verdict=${1-} sharing=${2-} comment=${3-} score share token candidate newest newest_born chat
    local now dir pending request born session transcript size start identity url target current
    local fields reason model eval_name
    for token in curl cksum mkdir date stat head tail; do command -v "$token" >/dev/null || return 1; done
    case $verdict in
        good) score=1 ;;
        bad) score=2 ;;
        *) printf 'RateXp: first argument must be good or bad\n' >&2; return 1 ;;
    esac
    case $sharing in
        share) share=1 ;;
        private) share=0 ;;
        *) printf 'RateXp: second argument must be share or private\n' >&2; return 1 ;;
    esac
    (( ${#comment} <= 4096 )) || comment=${comment:0:4096}
    where_am_i || return 1
    now=$(date +%s)
    # The newest survey this copy handed out, if it is still fresh and unanswered -
    # from this chat when Cursor names it, so an answer given in one chat never
    # sends another. `done` marks one already sent: a second call cannot post it twice.
    chat=${CURSOR_CONVERSATION_ID-}; [[ $chat =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || chat='*'
    newest=''; newest_born=0
    set +f
    for candidate in "$root/$project"-$chat/runs/*/pending; do
        [[ -f $candidate && ! -L $candidate ]] || continue
        [[ -e ${candidate%/pending}/done ]] && continue
        { IFS= read -r -d '' request; IFS= read -r -d '' born; } < "$candidate" || continue
        [[ $born =~ ^[0-9]+$ ]] || continue
        (( now >= born && now-born < 900 && born >= newest_born )) || continue
        newest_born=$born; newest=$candidate
    done
    set -f
    [[ -n $newest ]] || { printf 'RateXp: no survey is waiting for an answer\n' >&2; return 1; }
    pending=$newest; dir=${pending%/pending}
    {
        IFS= read -r -d '' request; IFS= read -r -d '' born; IFS= read -r -d '' session
        IFS= read -r -d '' transcript; IFS= read -r -d '' size; IFS= read -r -d '' start
        IFS= read -r -d '' identity; IFS= read -r -d '' url; IFS= read -r -d '' target
        IFS= read -r -d '' eval_name
    } < "$pending" || return 1
    good_url "$url" || return 1
    [[ $session =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return 1
    [[ -z $target || $target =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] || return 1
    # Consume before sending: a retried command cannot upload the same run twice.
    mkdir -- "$dir/done" 2>/dev/null || { printf 'RateXp: already answered\n' >&2; return 1; }
    [[ ! -L $pending ]] || return 1
    : > "$pending"
    mkdir -- "${dir%/runs/*}/answered" 2>/dev/null
    # Harness first, model second, the way the dashboard splits the label. The
    # model is the one the stop hook last saw in this chat, if Cursor fired it.
    model=''
    [[ -f ${dir%/runs/*}/model && ! -L ${dir%/runs/*}/model ]] && model=$(< "${dir%/runs/*}/model")
    [[ $model =~ ^[a-zA-Z0-9._/-]{1,64}$ ]] || model=''
    # A session rating names no skill; a skill's rating names the skill.
    fields=(--form-string "agent=cursor${model:+ $model}" --form-string "eval_name=$eval_name"
        --form-string "session_id=$session" --form-string "request_id=$request"
        --form-string "score=$score")
    [[ -n $target ]] && fields+=(--form-string "skill_name=$target")
    [[ -n $comment ]] && fields+=(--form-string "comment=$comment")
    # The survey is spent either way. Exit 0 so a network blip does not read as a
    # bad command the agent should try again - the retry would find nothing.
    post feedback || { printf 'RateXp: feedback could not be sent to %s.\n' "$url"; return 0; }
    if (( !share )); then
        printf 'RateXp: feedback accepted by %s. Transcript kept private.\n' "$url"
        return 0
    fi
    reason="RateXp: feedback accepted by $url. Transcript could not be sent."
    [[ $size =~ ^[0-9]{1,10}$ && $start =~ ^[0-9]{1,10}$ && -n $identity ]] ||
        { printf '%s\n' "$reason"; return 0; }
    [[ -f $transcript && ! -L $transcript ]] || { printf '%s\n' "$reason"; return 0; }
    exec 3< "$transcript" || { printf '%s\n' "$reason"; return 0; }
    current=$(open_file_info <&3) || { printf '%s\n' "$reason"; return 0; }
    # Match the device and inode noted when asking, so a swapped file is refused.
    [[ ${current%:*} == "$identity" ]] || { printf '%s\n' "$reason"; return 0; }
    # What is rated ends where the request was made; the survey is not part of it.
    (( ${current##*:} >= size )) || { printf '%s\n' "$reason"; return 0; }
    (( start < size && size-start <= 4194304 )) || { printf '%s\n' "$reason"; return 0; }
    # tail uses 1-based offsets; head bounds the slice at the noted end.
    tail -c "+$((start+1))" <&3 | head -c "$((size-start))" | post transcript --form 'transcript=<-' &&
        reason="RateXp: feedback and transcript accepted by $url."
    exec 3<&-
    printf '%s\n' "$reason"
}

case ${1-} in
    ask) shift; ask "$@"; exit $? ;;
    report) shift; report "$@"; exit $? ;;
    '') ;;
    *) printf 'usage: %s ask [request] | report <good|bad> <share|private> [comment]\n' "$0" >&2; exit 1 ;;
esac
# Cursor may read an empty reply as a malformed one, so every event gets an
# answer - `{}` when there is nothing to say.
reply=$(hook 2>/dev/null)
[[ -n $reply ]] || reply='{}'
printf '%s\n' "$reply"
exit 0
