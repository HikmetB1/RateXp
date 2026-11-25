#!/bin/bash
# RateXp: Bash 3.2+, curl, and standard macOS/Linux utilities. No packages.
# The RateXp plugin runs it for whoever uses Claude Code, and it owns all I/O. On
# /ratexp:rate, and every Nth turn on its own, the plugin's rating panel
# (hooks/rating-panel.tsx) asks what to rate, the evals and consent, and hands the
# answers to `send`. Where Claude Code runs no panel, the model draws a picker this
# file supplies instead: core's default eval, about the whole session. It notes
# where every skill run starts, so the panel can rate a skill's newest run.
#
#   panel-on <session>   the panel runs in this session, so Stop leaves the survey to it
#   panel <session>      what the panel shows, as JSON (see panel)
#   send <session>       sends the panel's ratings, read from stdin (see send)
#   (no arguments)       a Claude Code hook, with its event on stdin
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
# The evals core offers, six fields each: the eval's name, its question - where
# {subject}, if used, becomes what is rated - then the label and description of the
# good answer, and of the bad one.
EVALS=()

# Strict JSON reader using indexed arrays (also supported by macOS Bash 3.2).
# No eval, menu scanning, or third-party JSON runtime.
# The reader, quote, good_url, post, file_info, open_file_info, new_request_id,
# upload_slice, send_ratings, sent_line, find_eval, fetch_hook_settings,
# load_hook_settings, manifest_version and is_newer are the same in
# ratexp-cursor.sh: a test holds the two copies identical, so change them together.
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
# Full field paths preserve array positions and allow object keys in any order.
fingerprint() {
    local id=$1 path=$2 omit=${3:--1} i
    quote "${name[id]}"; path=$path/$quoted
    quote "${val[id]}"
    printf '%s:%s:%s\n' "$path" "${kind[id]}" "$quoted"
    for ((i=id+1; i<${last[id]}; i++)); do
        [[ ${up[i]} == "$id" && $i != "$omit" ]] && fingerprint "$i" "$path" "$omit"
    done
}
# Consent names what will be uploaded and where.
consent_line() {  # consent_line <url> <what>
    consent="Upload $2, including messages and tool results, to $1."
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
# A random UUID for a rating: sets request. Core stores each rating once by it.
new_request_id() {
    request=$(od -An -N16 -tx1 /dev/urandom) || return 1
    request=${request//[[:space:]]/}
    [[ ${#request} == 32 ]] || return 1
    request=${request:0:8}-${request:8:4}-${request:12:4}-${request:16:4}-${request:20:12}
}
# Uploads bytes <start> to <end> of transcript with the rating in fields. Opens the
# file after consent and matches the device and inode noted in identity, so a
# swapped file is refused, as is one now shorter than <end>.
upload_slice() {  # upload_slice <start> <end>
    local current status
    (( $1 < $2 && $2 - $1 <= 4194304 )) || return 1
    [[ -f $transcript && ! -L $transcript ]] || return 1
    exec 3< "$transcript" || return 1
    current=$(open_file_info <&3) && [[ ${current%:*} == "$identity" ]] && (( ${current##*:} >= $2 )) ||
        { exec 3<&-; return 1; }
    # tail uses 1-based offsets; head bounds the slice at <end>.
    tail -c "+$(($1+1))" <&3 | head -c "$(($2-$1))" | post transcript --form 'transcript=<-'
    status=$?
    exec 3<&-
    return $status
}
# Sends rating i of rate_skill (empty for the whole session), rate_eval, rate_score
# (empty for none) and rate_comment, each under a request of its own, and, when share
# is 1, bytes rate_start[i] to rate_end[i] of transcript with it. Sets sent, the
# ratings core stored, and stored, the transcripts it stored with them.
send_ratings() {  # send_ratings <agent>
    local i request
    sent=0; stored=0
    for ((i=0; i<${#rate_eval[@]}; i++)); do
        new_request_id || return 1
        fields=(--form-string "agent=$1" --form-string "eval_name=${rate_eval[i]}"
            --form-string "session_id=$session" --form-string "request_id=$request")
        [[ -n ${rate_skill[i]} ]] && fields+=(--form-string "skill_name=${rate_skill[i]}")
        [[ -n ${rate_score[i]} ]] && fields+=(--form-string "score=${rate_score[i]}")
        [[ -n ${rate_comment[i]} ]] && fields+=(--form-string "comment=${rate_comment[i]}")
        post feedback || continue
        sent=$((sent+1))
        (( share )) && upload_slice "${rate_start[i]}" "${rate_end[i]}" && stored=$((stored+1))
    done
    return 0
}
# The one line that tells the user what core stored of what send_ratings sent: sets
# line. Several ratings also say how many.
sent_line() {
    local n=${#rate_eval[@]} count='' s=''
    if (( n > 1 )); then
        s=s; count=" for $sent of $n ratings"
        (( sent == n )) && count=" for $n ratings"
    fi
    if (( !sent )); then
        line="RateXp: feedback could not be sent to $url."
    elif (( !share )); then
        line="RateXp: feedback accepted by $url$count. Transcript$s kept private."
    elif (( stored == sent )); then
        line="RateXp: feedback and transcript$s accepted by $url$count."
    elif (( n == 1 )); then
        line="RateXp: feedback accepted by $url. Transcript could not be sent."
    else
        line="RateXp: feedback accepted by $url$count. $((sent-stored)) of the transcripts could not be sent."
    fi
}
arm() {
    # Deduplicate invocations by key.
    local key=$1
    mkdir -p -- "$base/runs" "$base/tools" || return
    mkdir -- "$base/lock" 2>/dev/null || return
    # Refuse symlinks in writable state; always release the lock.
    if [[ ! -L $base/current.tmp ]] && mkdir -- "$base/runs/$key" 2>/dev/null; then
        : > "$base/runs/$key/ask"
        printf '%s' "$key" > "$base/current.tmp"
        mv -- "$base/current.tmp" "$base/current"
    fi
    rmdir -- "$base/lock"
}
# Where a skill's run ends. It starts where the skill was called and ends at the
# first user message after the agent has replied - unless that reply asked the
# user something, in which case the answer is still part of the run. Tool results
# ride on user-role lines in Claude Code and are not the user speaking. This reads
# the transcript only to find the boundary; nothing of it is kept or printed.
run_end() {  # run_end <file> <start> <limit>: sets end
    local line at=$2 agent=0 asked=0 user
    end=$3
    while IFS= read -r line; do
        user=0
        case $line in
            *'"type":"user"'* | *'"type": "user"'* | *'"role":"user"'* | *'"role": "user"'*)
                case $line in *'"tool_result"'* | *'"isMeta":true'* | *'"isMeta": true'*) ;; *) user=1 ;; esac ;;
        esac
        if (( user )); then
            if (( agent && !asked )); then end=$at; return; fi
            asked=0
        elif [[ $line == *'"type":"assistant"'* || $line == *'"type": "assistant"'* ||
                $line == *'"role":"assistant"'* || $line == *'"role": "assistant"'* ]]; then
            agent=1; asked=0
            case $line in *'AskUserQuestion'* | *'?"'* | *'?\n'* | *'? '*) asked=1 ;; esac
        fi
        at=$((at+${#line}+1))
    done < <(tail -c "+$(($2+1))" -- "$1" 2>/dev/null | head -c "$(($3-$2))")
}
report() {
    quote "$1"
    [[ -L $dir/status ]] || printf '{"systemMessage":%s}\n' "$quoted" > "$dir/status"
    # The survey is over: end the turn, so the model cannot answer the picker itself
    # and say something about the upload that is not true. Claude Code then shows
    # the stopReason, not the systemMessage, so both hold the report.
    printf '{"systemMessage":%s,"continue":false,"stopReason":%s}\n' "$quoted" "$quoted"
}
# Skip unrelated or oversized tool payloads before parsing. The plugin
# (.claude-plugin/plugin.json) hooks up exactly these events; keep in step.
triage() {
    case $json in
        *'"AskUserQuestion"'*)
            # Allow longer answers only for our survey, within the outer cap.
            (( ${#json} <= 32768 )) || return 1
            (( ${#json} <= 8192 )) || [[ $json == *'"RateXp"'* ]] || return 1 ;;
        *'"Stop"'*|*'"UserPromptExpansion"'*|*'"SessionStart"'*|*'"Skill"'*) ;;
        *) return 1 ;;
    esac
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
# Note where a skill's newest run starts: the transcript's length right now.
skill_started() {  # skill_started <skill>
    # Not `name`: that is the JSON reader's own array, and `get` needs it.
    local started=$1 info
    [[ $started =~ ^[a-zA-Z0-9][a-zA-Z0-9_:.-]{0,127}$ && $started != ratexp && $started != ratexp:* ]] || return
    get 0 transcript_path; [[ $type == string ]] || return
    # A session's first prompt comes before its transcript exists: the run starts at 0.
    info=0; [[ -e $found || -L $found ]] && { info=$(file_info "$found") || return; }
    mkdir -p -- "$base/skills" || return
    [[ ! -L $base/skills/${started//:/--} && ! -L $base/last-skill ]] || return
    printf '%s' "${info##*:}" > "$base/skills/${started//:/--}"
    printf '%s' "$started" > "$base/last-skill"
}
# Count a turn once, however often its Stop fires; succeed on every Nth.
turn_is_due() {  # turn_is_due <turn key>
    local count
    [[ ! -L $base/count && ! -L $base/last-turn ]] || return 1
    [[ -f $base/last-turn && $(< "$base/last-turn") == "$1" ]] && return 1
    printf '%s' "$1" > "$base/last-turn"
    count=0; [[ -f $base/count ]] && count=$(< "$base/count")
    [[ $count =~ ^[0-9]{1,9}$ ]] || count=0
    count=$((count+1)); printf '%s' "$count" > "$base/count"
    (( count % every == 0 ))
}
# Where this copy keeps the state of <session>, and the core it sends to: sets url,
# root, base and settings. The plugin's folder changes with each version, so state
# is keyed by the plugin, not by the folder: a survey count carries over an update.
where_am_i() {  # where_am_i <session>
    local token
    [[ $1 =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return 1
    url=${RATEXP_URL:-$DEFAULT_URL}; url=${url%/}
    good_url "$url" || return 1
    root=${XDG_STATE_HOME:-$HOME/.local/state}/ratexp
    token=$(printf '%s' claude-plugin | cksum); token=${token%% *}
    base=$root/$token-$1
    [[ ! -L $root && ! -L $base ]] || return 1
    mkdir -p -- "$base" || return 1
    settings=$(printf '%s' "$url" | cksum); settings=$root/settings-${settings%% *}
}
# The evals core sent at session start, or asks core for them now when it could not
# answer then: sets latest, DEFAULT_EVERY, DEFAULT_EVAL and EVALS.
evals_loaded() {
    load_hook_settings "$settings" || { fetch_hook_settings "$settings" && load_hook_settings "$settings"; }
}
# What the panel shows, as one JSON object: whether the every-Nth-turn survey is due
# (the call consumes that), the newest skill that ran in the session (null for none),
# and each eval's name, question, and the label and meaning of its good and its bad
# answer. An object with only `error` when the evals cannot
# be loaded.
panel() {  # panel <session>
    local due=false skill='' out i
    where_am_i "$1" || return 1
    rmdir -- "$base/panel-due" 2>/dev/null && due=true
    if ! evals_loaded; then
        quote "RateXp: the surveys could not be loaded from $url, so no survey can be asked."
        printf '{"error":%s}\n' "$quoted"
        return 0
    fi
    if [[ -f $base/last-skill && ! -L $base/last-skill ]]; then
        skill=$(< "$base/last-skill")
        [[ -f $base/skills/${skill//:/--} && ! -L $base/skills/${skill//:/--} ]] || skill=''
    fi
    out='{"due":'$due',"skill":'
    if [[ -n $skill ]]; then quote "$skill"; out=$out$quoted; else out=${out}null; fi
    out=$out',"evals":['
    for ((i=0; i+5<${#EVALS[@]}; i+=6)); do
        (( i )) && out=$out,
        quote "${EVALS[i]}"; out=$out'{"name":'$quoted
        # One question serves the session and the skill alike.
        quote "${EVALS[i+1]//"{subject}"/it}"; out=$out',"question":'$quoted
        quote "${EVALS[i+2]}"; out=$out',"good":'$quoted
        quote "${EVALS[i+3]}"; out=$out',"good_description":'$quoted
        quote "${EVALS[i+4]}"; out=$out',"bad":'$quoted
        quote "${EVALS[i+5]}"; out=$out',"bad_description":'$quoted'}'
    done
    printf '%s]}\n' "$out"
}
# Sends the ratings the panel collected and prints the line that tells the user what
# core stored. stdin holds NUL-ended fields: the session's transcript, yes or no to
# storing it, then four for each rating - the skill rated (empty for the whole
# session), the eval, good or bad, and the comment. A skill's rating carries only its
# newest run; the session's carries the whole transcript.
send() {  # send <session>
    local session=$1 field skill eval_name verdict comment start end size i
    local skill_done='' skill_start skill_end share sent stored line request fields transcript identity
    local eval_question good_label good_description bad_label bad_description
    local -a answers rate_skill rate_eval rate_score rate_comment rate_start rate_end
    where_am_i "$session" || return 1
    evals_loaded || { printf 'RateXp: feedback not sent: the surveys could not be loaded from %s.\n' "$url"; return 0; }
    while IFS= read -r -d '' field; do answers+=("$field"); done
    transcript=${answers[0]-}
    case ${answers[1]-} in yes) share=1 ;; no) share=0 ;; *) answers=() ;; esac
    if [[ ! -f $transcript || -L $transcript ]] || (( ${#answers[@]} < 6 || ${#answers[@]} % 4 != 2 )); then
        printf 'RateXp: feedback not sent: the ratings could not be read.\n'
        return 0
    fi
    identity=$(file_info "$transcript") || return 1
    size=${identity##*:}; identity=${identity%:*}
    for ((i=2; i<${#answers[@]}; i+=4)); do
        skill=${answers[i]}; eval_name=${answers[i+1]}; verdict=${answers[i+2]}; comment=${answers[i+3]}
        find_eval "$eval_name" && [[ $verdict == good || $verdict == bad ]] ||
            { printf 'RateXp: feedback not sent: the ratings could not be read.\n'; return 0; }
        start=0; end=$size
        if [[ -n $skill ]]; then
            if [[ $skill != "$skill_done" ]]; then
                [[ $skill =~ ^[a-zA-Z0-9][a-zA-Z0-9_:.-]{0,127}$ && -f $base/skills/${skill//:/--} &&
                    ! -L $base/skills/${skill//:/--} ]] ||
                    { printf 'RateXp: feedback not sent: there is no run of %s in this session to rate.\n' "$skill"; return 0; }
                skill_start=$(< "$base/skills/${skill//:/--}")
                [[ $skill_start =~ ^[0-9]{1,10}$ ]] && (( skill_start <= size )) || skill_start=$size
                # Only the skill's own turns: the rest of the session is not what is rated.
                run_end "$transcript" "$skill_start" "$size"; skill_end=$end; skill_done=$skill
            fi
            start=$skill_start; end=$skill_end
        fi
        rate_skill+=("$skill"); rate_eval+=("$eval_name"); rate_comment+=("${comment:0:4096}")
        if [[ $verdict == good ]]; then rate_score+=(1); else rate_score+=(2); fi
        rate_start+=("$start"); rate_end+=("$end")
    done
    send_ratings claude-code || return 1
    sent_line
    printf '%s\n' "$line"
}

main() {
    local event session script url every root base dir run now question picker reason end
    local input response answers annotations answer tool stored_tool born transcript size identity current
    local good=0 bad=0 share=0 keep=0 comment='' score='' rest part fields sent stored line
    local metadata questions signature expected token
    local eval_name eval_question good_label good_description bad_label bad_description
    local settings mine latest
    local -a rate_skill rate_eval rate_score rate_comment rate_start rate_end
    for token in curl cksum mkdir rmdir mv date od stat head tail sort; do command -v "$token" >/dev/null || return; done
    # Cursor also runs Claude Code's hooks and plugins, with events in its own shape.
    # RateXp's Cursor hook rates there.
    [[ -z ${CURSOR_VERSION-} ]] || return
    # NUL is the delimiter: a successful read means NUL or the size limit was hit.
    json=''; IFS= read -r -d '' -n 131073 json && return
    (( ${#json} <= 131072 )) || return
    triage || return
    kind=(); name=(); up=(); val=(); last=(); pos=0
    value -1 '' 0; white
    (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || return
    get 0 hook_event_name; event=$found
    get 0 session_id; session=$found
    [[ $type == string ]] || return
    get 0 agent_id; [[ $node == -1 || $type == null ]] || return
    script=${BASH_SOURCE[0]}; [[ $script == */* ]] || script=./$script
    script=$(cd -P -- "${script%/*}" && pwd) || return
    where_am_i "$session" || return
    now=$(date +%s)
    if [[ $event == SessionStart ]]; then
        fetch_hook_settings "$settings"
        mine=$(manifest_version "$script/.claude-plugin/plugin.json")
        if load_hook_settings "$settings" && is_newer "$latest" "$mine"; then
            quote "RateXp $latest is out, and you have $mine. To update RateXp, run: claude plugin marketplace update ratexp && claude plugin update ratexp@ratexp"
            printf '{"systemMessage":%s}\n' "$quoted"
        fi
        return
    fi
    if [[ $event == PreToolUse ]]; then
        get 0 tool_name
        if [[ $found == Skill ]]; then
            get 0 tool_input; get "$node" skill
            [[ $type == string ]] && skill_started "$found"
            return
        fi
    fi
    if [[ $event == UserPromptExpansion ]]; then
        get 0 command_name; token=$found
        if [[ $token != ratexp:rate ]]; then
            skill_started "$token"  # any other command is a skill starting
            return
        fi
        # The rating panel answers /ratexp:rate itself. Without it, the request waits
        # here for Stop: one whose turn the user interrupted fired no Stop, so the
        # newest request decides. Words typed after the command change nothing.
        [[ -d $base/panel || -L $base/rate-now ]] || mkdir -p -- "$base/rate-now"
        return
    fi
    # Only a survey needs the turns and the evals. It uses what core sent at session
    # start. When core was out of reach then, the first turn's end asks again, once,
    # so a core that stays down does not slow every turn.
    if ! load_hook_settings "$settings"; then
        [[ $event == Stop ]] && mkdir -- "$base/asked-core" 2>/dev/null &&
            fetch_hook_settings "$settings" && load_hook_settings "$settings" || {
            # A /ratexp:rate that cannot be asked is consumed, so it is reported once.
            [[ $event == Stop && -d $base/rate-now ]] && mv -- "$base/rate-now" "$base/unasked-$now" || return
            quote "RateXp: the surveys could not be loaded from $url, so no survey can be asked."
            printf '{"systemMessage":%s}\n' "$quoted"
            return
        }
    fi
    # RATEXP_EVERY overrides the turns core sent.
    every=${RATEXP_EVERY:-$DEFAULT_EVERY}
    [[ $every =~ ^[1-9][0-9]{0,4}$ ]] && (( every <= 32768 )) || return
    if [[ $event == Stop ]]; then
        get 0 stop_hook_active; [[ $type != true ]] || return
        get 0 transcript_path
        token=$(file_info "$found") || return
        if [[ -d $base/panel ]]; then
            # The rating panel asks every Nth turn: it opens the survey this marks due.
            turn_is_due "${token//:/-}" && mkdir -- "$base/panel-due" 2>/dev/null
            return
        fi
        if [[ -d $base/rate-now ]]; then
            # /ratexp:rate asks, and moving the request aside consumes it: one
            # request, one survey. That turn was the user asking to rate, not work,
            # so it is not counted.
            mv -- "$base/rate-now" "$base/asked-${token//:/-}" 2>/dev/null || return
        else
            # Every Nth turn the whole session is asked about on its own.
            turn_is_due "${token//:/-}" || return
        fi
        eval_name=$DEFAULT_EVAL
        find_eval "$eval_name" || return
        arm "turn-${token//:/-}"
    fi
    dir=$base
    if [[ -f $base/current ]]; then
        run=$(< "$base/current"); [[ $run =~ ^[a-zA-Z0-9_-]+$ ]] || return
        dir=$base/runs/$run
    fi
    if [[ $event == PostToolUse || $event == PostToolUseFailure ]]; then
        get 0 tool_use_id
        [[ $found =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return
        if [[ -f $base/tools/$found ]]; then
            run=$(< "$base/tools/$found"); [[ $run =~ ^[a-zA-Z0-9_-]+$ ]] || return
            dir=$base/runs/$run
        fi
    fi
    if [[ $event == Stop ]]; then
        question=${eval_question//"{subject}"/this Claude Code session}
        question="$question — check all that apply or type a comment."
        [[ -f $dir/ask ]] || return
        mkdir -- "$dir/stopped" 2>/dev/null || return
        # Record only metadata at Stop; nothing of the transcript is kept.
        get 0 transcript_path; transcript=$found; size=0; identity=''
        if [[ $type == string && -f $transcript && ! -L $transcript ]]; then
            identity=$(file_info "$transcript") || identity=''
            size=${identity##*:}; identity=${identity%:*}
        fi
        quote "$question"; question=$quoted
        consent_line "$url" 'this session'; quote "$consent"; reason=$quoted
        quote "$good_label"; good_label=$quoted; quote "$good_description"; good_description=$quoted
        quote "$bad_label"; bad_label=$quoted; quote "$bad_description"; bad_description=$quoted
        picker='{"questions":[{"question":'$question',"header":"RateXp","multiSelect":true,"options":[{"label":'$good_label',"description":'$good_description'},{"label":'$bad_label',"description":'$bad_description'},{"label":"Yes, store trajectory","description":'$reason'},{"label":"No, do not store","description":"Keep this session on my machine."}]}]}'
        [[ ! -L $dir/pending ]] || return
        printf '%s\0' "$now" "$picker" "$transcript" "$size" "$identity" "$url" "$eval_name" > "$dir/pending"
        quote $'Draw this exact AskUserQuestion picker, without answers or extra fields. The hook reports delivery; do not claim it was saved or uploaded yourself.\n'"$picker"
        printf '{"decision":"block","reason":%s}\n' "$quoted"
        return
    fi
    [[ $event == PreToolUse || $event == PostToolUse || $event == PostToolUseFailure ]] || return
    [[ -f $dir/pending && ! -e $dir/done && ! -L $dir/pending ]] || return
    get 0 tool_name; [[ $found == AskUserQuestion ]] || return
    get 0 tool_use_id; tool=$found; [[ $type == string && -n $tool ]] || return
    # Skip the saved path; only the current hook event can name the upload file.
    {
        IFS= read -r -d '' born; IFS= read -r -d '' picker; IFS= read -r -d '' token
        IFS= read -r -d '' size; IFS= read -r -d '' identity; IFS= read -r -d '' url
        IFS= read -r -d '' eval_name
    } < "$dir/pending" || return
    # Revalidate the saved destination against the pending consent text.
    good_url "$url" || return
    consent_line "$url" 'this session'; [[ $picker == *"$consent"* ]] || return
    # The answer is read back by the labels of the eval that was asked.
    find_eval "$eval_name" || return
    [[ $born =~ ^[0-9]+$ ]] && (( now >= born && now-born < 900 )) || return
    get 0 tool_input; input=$node; [[ $type == '{' ]] || return
    get "$input" metadata; metadata=$node
    get "$input" questions; questions=$node; [[ $type == '[' ]] || return
    get "$questions" 0; token=$node
    get "$token" header; [[ $found == RateXp ]] || return
    get "$token" question; question=$found; [[ $type == string ]] || return
    # Bind the survey and tool call; Claude may omit metadata.
    if [[ $event == PreToolUse ]]; then
        signature=$(fingerprint "$input" '' "$metadata" | sort)
    else
        # Post events add answers; compare questions and the bound tool ID.
        signature=$(fingerprint "$questions" '' | sort)
    fi
    expected=$(
        json=$picker; kind=(); name=(); up=(); val=(); last=(); pos=0
        value -1 tool_input 0
        if [[ $event == PreToolUse ]]; then
            get 0 metadata; fingerprint 0 '' "$node" | sort
        else
            get 0 questions; fingerprint "$node" '' | sort
        fi
    )
    if [[ $signature != "$expected" ]]; then
        if [[ $event == PreToolUse ]]; then
            printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Use the exact unanswered RateXp picker supplied by the Stop hook."}}'
        fi
        return
    fi
    if [[ $event == PreToolUse ]]; then
        (set -o noclobber; printf '%s' "$tool" > "$dir/tool") 2>/dev/null
        if [[ $dir != "$base" && $tool =~ ^[a-zA-Z0-9_-]{1,128}$ && ! -L $base/tools/$tool ]]; then
            printf '%s' "${dir##*/}" > "$base/tools/$tool"
        fi
        return
    fi
    [[ -f $dir/tool && ! -L $dir/tool ]] || return
    stored_tool=$(< "$dir/tool"); [[ $stored_tool == "$tool" ]] || return
    # Consume before parsing/sending: replay and parallel hooks cannot upload twice.
    # A noclobber file, not mkdir: the uutils mkdir of Ubuntu 26.04 tells two racing
    # hooks that each one made the folder.
    (set -o noclobber; : > "$dir/done") 2>/dev/null || return
    [[ ! -L $dir/pending ]] || return
    : > "$dir/pending"
    [[ $event == PostToolUse ]] || return
    get 0 tool_response; response=$node; [[ $type == '{' ]] || return
    get "$response" answers; answers=$node; [[ $type == '{' ]] || return
    get "$answers" "$question"; answer=$found; [[ $type == string ]] || return
    rest=$answer
    while [[ -n $rest ]]; do
        # Match whole labels, consent ones first: they contain commas, and an eval's
        # label may be a consent label's first word, like Yes.
        part=''
        # Claude Code quotes a label that holds a comma, so both spellings count.
        for token in 'Yes, store trajectory' 'No, do not store' \
            '"Yes, store trajectory"' '"No, do not store"' "$good_label" "$bad_label"; do
            if [[ $rest == "$token" || $rest == "$token, "* ]]; then part=$token; break; fi
        done
        if [[ -z $part ]]; then comment=$rest; break; fi
        case $part in
            'Yes, store trajectory' | '"Yes, store trajectory"') share=1 ;;
            'No, do not store' | '"No, do not store"') keep=1 ;;
            "$good_label") good=1 ;;
            *) bad=1 ;;
        esac
        rest=${rest#"$part"}; rest=${rest#', '}
    done
    get "$response" annotations; annotations=$node
    get "$annotations" "$question"; annotations=$node
    get "$annotations" notes; [[ $type == string ]] && comment=$found
    (( good != bad )) && { if (( good )); then score=1; else score=2; fi; }
    [[ -n $score || -n $comment || $good == 1 || $bad == 1 || $share == 1 ]] || return
    # Only the bound tool answer grants consent. Notes cannot; No overrides Yes.
    (( keep )) && share=0
    # Use the runtime's path, not the writable pending state's path. The session so far
    # includes the turn that ended as the survey was asked; a file shorter than at
    # Stop was truncated and is not sent.
    get 0 transcript_path; transcript=$found; end=0
    current=$(file_info "$transcript") && [[ $size =~ ^[0-9]{1,10}$ ]] &&
        (( ${current##*:} >= size )) && end=${current##*:}
    rate_skill=(''); rate_eval=("$eval_name"); rate_score=("$score"); rate_comment=("$comment")
    rate_start=(0); rate_end=("$end")
    send_ratings claude-code || return
    sent_line
    report "$line"
}

case ${1-} in
    panel-on) where_am_i "${2-}" && mkdir -- "$base/panel" 2>/dev/null; exit 0 ;;
    panel) panel "${2-}"; exit $? ;;
    send) send "${2-}"; exit $? ;;
esac
main 2>/dev/null
exit 0
