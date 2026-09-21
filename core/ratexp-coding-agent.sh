#!/bin/bash
# RateXp: Bash 3.2+, curl, and standard macOS/Linux utilities. No packages.
# The model draws the supplied picker; this file owns its text and all I/O.
set -f
set -o pipefail
umask 077
export LC_ALL=C
DEFAULT_URL='__RATEXP_URL__'
DEFAULT_EVERY='__RATEXP_EVERY__'

# Strict JSON reader using indexed arrays (also supported by macOS Bash 3.2).
# No eval, menu scanning, or third-party JSON runtime.
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
# Consent names the destination that will receive the transcript.
consent_line() {
    consent="Upload this session, including messages and tool results, to $1."
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
arm() {
    # Deduplicate invocations by key; $2 marks the run's initial byte offset.
    # $3 asks regardless of the count, for a survey the user asked for by name.
    local key=$1 from=$2 force=$3 count
    mkdir -p -- "$base/runs" "$base/tools" || return
    mkdir -- "$base/lock" 2>/dev/null || return
    # Refuse symlinks in writable state; always release the lock.
    if [[ ! -L $base/count && ! -L $base/current.tmp ]] &&
       mkdir -- "$base/runs/$key" 2>/dev/null; then
        count=0; [[ -f $base/count ]] && count=$(< "$base/count")
        [[ $count =~ ^[0-9]{1,9}$ ]] || count=0
        count=$((count+1)); printf '%s' "$count" > "$base/count"
        { (( count % every == 0 )) || [[ -n $force ]]; } && : > "$base/runs/$key/ask"
        printf '%s' "$from" > "$base/runs/$key/start"
        printf '%s' "$key" > "$base/current.tmp"
        mv -- "$base/current.tmp" "$base/current"
    fi
    rmdir -- "$base/lock"
}
report() {
    quote "$1"
    [[ -L $dir/status ]] || printf '{"systemMessage":%s}\n' "$quoted" > "$dir/status"
    printf '{"systemMessage":%s}\n' "$quoted"
}
# Skip unrelated or oversized tool payloads before parsing.
triage() {
    case $json in
        *'"AskUserQuestion"'*)
            # Allow longer answers only for our survey, within the outer cap.
            (( ${#json} <= 32768 )) || return 1
            (( ${#json} <= 8192 )) || [[ $json == *'"RateXp"'* ]] || return 1 ;;
        *'"Stop"'*|*'"UserPromptExpansion"'*) ;;
        *) return 1 ;;
    esac
}

main() {
    local event session script url every root base dir run now request question picker reason
    local input response answers annotations answer tool stored_tool born transcript size start identity current
    local good=0 bad=0 share=0 keep=0 comment='' score='' rest part fields
    local metadata questions signature expected token force
    for token in curl cksum mkdir rmdir mv date od stat head tail sort; do command -v "$token" >/dev/null || return; done
    # NUL is the delimiter: a successful read means NUL or the size limit was hit.
    json=''; IFS= read -r -d '' -n 131073 json && return
    (( ${#json} <= 131072 )) || return
    triage || return
    kind=(); name=(); up=(); val=(); last=(); pos=0
    value -1 '' 0; white
    (( pos == ${#json} )) && [[ ${kind[0]} == '{' ]] || return
    get 0 hook_event_name; event=$found
    get 0 session_id; session=$found
    [[ $type == string && $session =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return
    get 0 agent_id; [[ $node == -1 || $type == null ]] || return
    script=${BASH_SOURCE[0]}; [[ $script == */* ]] || script=./$script
    script=$(cd -P -- "${script%/*}" && pwd) || return
    url=${RATEXP_URL:-$DEFAULT_URL}; url=${url%/}
    good_url "$url" || return
    # Environment settings override the distributed defaults.
    every=${RATEXP_EVERY:-$DEFAULT_EVERY}
    [[ $every =~ ^[1-9][0-9]{0,4}$ ]] && (( every <= 32768 )) || return
    root=${XDG_STATE_HOME:-$HOME/.local/state}/ratexp
    token=$(printf '%s' "$script" | cksum); token=${token%% *}
    base=$root/$token-$session
    [[ ! -L $root && ! -L $base ]] || return
    mkdir -p -- "$base" || return
    now=$(date +%s)
    if [[ $event == UserPromptExpansion ]]; then
        # /ratexp asks for the survey by name, instead of waiting for the count.
        get 0 command_name; token=$found
        [[ $token == ratexp || $token == *:ratexp ]] || return
        mkdir -- "$base/rate-now" 2>/dev/null
        return
    fi
    if [[ $event == Stop ]]; then
        get 0 stop_hook_active; [[ $type != true ]] || return
        # Every turn counts, so the survey lands wherever the Nth falls - part way
        # through a long session, at the end of a short one. It always starts at
        # byte zero, because what is rated is the session so far.
        get 0 transcript_path
        token=$(file_info "$found") || return
        force=''
        # rmdir consumes the /ratexp request, so it arms exactly one survey.
        rmdir -- "$base/rate-now" 2>/dev/null && force=now
        arm "turn-${token//:/-}" 0 "$force"
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
        question="Rate this Claude Code session — check all that apply or type a comment."
        [[ -f $dir/ask ]] || return
        mkdir -- "$dir/stopped" 2>/dev/null || return
        # Record only metadata at Stop; no transcript contents are read here.
        get 0 transcript_path; transcript=$found; size=0; identity=''
        if [[ $type == string && -f $transcript && ! -L $transcript ]]; then
            identity=$(file_info "$transcript") || identity=''
            size=${identity##*:}; identity=${identity%:*}
        fi
        # What is rated is the session so far, so every survey starts at byte zero.
        start=0
        request=$(od -An -N16 -tx1 /dev/urandom) || return
        request=${request//[[:space:]]/}
        [[ ${#request} == 32 ]] || return
        request=${request:0:8}-${request:8:4}-${request:12:4}-${request:16:4}-${request:20:12}
        quote "$question"; question=$quoted
        consent_line "$url"; quote "$consent"; reason=$quoted
        picker='{"questions":[{"question":'$question',"header":"RateXp","multiSelect":true,"options":[{"label":"Good","description":"The result was helpful."},{"label":"Bad","description":"The result was not helpful."},{"label":"Yes, store trajectory","description":'$reason'},{"label":"No, do not store","description":"Keep this session on my machine."}]}]}'
        [[ ! -L $dir/pending ]] || return
        printf '%s\0' "$request" "$now" "$picker" "$transcript" "$size" "$start" "$identity" "$url" \
            > "$dir/pending"
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
        IFS= read -r -d '' request; IFS= read -r -d '' born; IFS= read -r -d '' picker
        IFS= read -r -d '' token; IFS= read -r -d '' size; IFS= read -r -d '' start
        IFS= read -r -d '' identity; IFS= read -r -d '' url
    } < "$dir/pending" || return
    # Revalidate the saved destination against the pending consent text.
    good_url "$url" || return
    consent_line "$url"; [[ $picker == *"$consent"* ]] || return
    [[ $born =~ ^[0-9]+$ ]] && (( now >= born && now-born < 900 )) || return
    get 0 tool_input; input=$node; [[ $type == '{' ]] || return
    get "$input" metadata; metadata=$node
    get "$input" questions; questions=$node; [[ $type == '[' ]] || return
    get "$questions" 0; token=$node
    get "$token" header; [[ $found == RateXp ]] || return
    get "$token" question; question=$found; [[ $type == string ]] || return
    [[ $question == "Rate this Claude Code session — "* ]] || return
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
    mkdir -- "$dir/done" 2>/dev/null || return
    # Consume before parsing/sending: replay and parallel hooks cannot upload twice.
    [[ ! -L $dir/pending ]] || return
    : > "$dir/pending"
    [[ $event == PostToolUse ]] || return
    get 0 tool_response; response=$node; [[ $type == '{' ]] || return
    get "$response" answers; answers=$node; [[ $type == '{' ]] || return
    get "$answers" "$question"; answer=$found; [[ $type == string ]] || return
    rest=$answer
    while [[ -n $rest ]]; do
        # Match whole labels first because consent labels themselves contain commas.
        part=''
        for token in 'Good' 'Bad' 'Yes, store trajectory' 'No, do not store'; do
            if [[ $rest == "$token" || $rest == "$token, "* ]]; then part=$token; break; fi
        done
        if [[ -z $part ]]; then comment=$rest; break; fi
        case $part in Good) good=1 ;; Bad) bad=1 ;; 'Yes, store trajectory') share=1 ;; *) keep=1 ;; esac
        rest=${rest#"$part"}; rest=${rest#', '}
    done
    get "$response" annotations; annotations=$node
    get "$annotations" "$question"; annotations=$node
    get "$annotations" notes; [[ $type == string ]] && comment=$found
    (( good != bad )) && { if (( good )); then score=1; else score=2; fi; }
    [[ -n $score || -n $comment || $good == 1 || $bad == 1 || $share == 1 ]] || return
    # A session rating is about the session itself, so it sends no skill_name.
    fields=(--form-string 'agent=claude-code'
        --form-string "session_id=$session" --form-string "request_id=$request")
    [[ -n $score ]] && fields+=(--form-string "score=$score")
    [[ -n $comment ]] && fields+=(--form-string "comment=$comment")
    post feedback || { report "RateXp: feedback could not be sent to $url."; return; }
    # Only the bound tool answer grants consent. Notes cannot; No overrides Yes.
    if (( !share || keep )); then
        report "RateXp: feedback accepted by $url. Transcript kept private."
        return
    fi
    reason="RateXp: feedback accepted by $url. Transcript could not be sent."
    [[ $size =~ ^[0-9]{1,10}$ ]] && [[ $start =~ ^[0-9]{1,10}$ ]] || { report "$reason"; return; }
    # Use the runtime's path, not the writable pending state's path.
    get 0 transcript_path; transcript=$found
    [[ $type == string && -f $transcript && ! -L $transcript ]] || { report "$reason"; return; }
    # Open after consent and match Stop's device/inode to prevent file swaps.
    exec 3< "$transcript" || { report "$reason"; return; }
    current=$(file_info /dev/fd/3) || { report "$reason"; return; }
    [[ ${current%:*} == "$identity" ]] || { report "$reason"; return; }
    # Include the closing message written after Stop; reject a truncated file.
    (( ${current##*:} >= size )) || { report "$reason"; return; }
    size=${current##*:}
    # Cap the run's slice, not the full session file.
    (( start < size && size-start <= 4194304 )) || { report "$reason"; return; }
    # tail uses 1-based offsets; head bounds the slice at the measured end.
    tail -c "+$((start+1))" <&3 | head -c "$((size-start))" | post transcript --form 'transcript=<-' &&
        reason="RateXp: feedback and transcript accepted by $url."
    exec 3<&-
    report "$reason"
}
main 2>/dev/null
exit 0
