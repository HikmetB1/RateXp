#!/bin/bash
# RateXp for Cursor: Bash 3.2+, curl, and standard macOS/Linux utilities.
#
# Installed once, for every project, as ~/.cursor/ratexp-cursor.sh by whoever uses
# Cursor. It asks about the whole chat every Nth turn on its own, and whenever the
# user types /ratexp. /ratexp <skill> (or /ratexp:<skill>) rates only that skill's
# most recent run - a skill is never asked about on its own.
#
#   ask [skill]              what the /ratexp command runs: finds this chat's
#                            transcript, notes what is being rated, and prints
#                            the two questions for the agent to ask
#   report <good|bad> <share|private> [comment]
#                            what the agent runs with the user's answer; owns the
#                            feedback post and the consented transcript upload
#   (no arguments)           a Cursor hook. sessionStart writes the /ratexp
#                            command; stop asks for the survey every Nth turn
#
# Rating itself needs no hook: the Cursor CLI does not always fire them, and the
# transcript it writes is enough. Only the every-Nth-turn survey rides on the stop
# hook. Consent is a required word rather than a default, so an agent that forgets
# an argument cannot upload a private chat.
set -f
set -o pipefail
umask 077
export LC_ALL=C
DEFAULT_URL='__RATEXP_URL__'
DEFAULT_EVERY='__RATEXP_EVERY__'

# Strict JSON reader using indexed arrays (also supported by macOS Bash 3.2).
# No eval, menu scanning, or third-party JSON runtime.
# The reader, quote, good_url, post and file_info are the same in
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
file_mtime() {
    stat -L -c '%Y' -- "$1" 2>/dev/null || stat -L -f '%m' -- "$1" 2>/dev/null
}
# Where this install lives. State is keyed by its folder, so two installs on one
# machine never share a survey.
where_am_i() {
    local script=${BASH_SOURCE[0]}
    [[ $script == */* ]] || script=./$script
    here=$(cd -P -- "${script%/*}" && pwd) || return 1
    self=$here/${script##*/}
    root=${XDG_STATE_HOME:-$HOME/.local/state}/ratexp
    project=$(printf '%s' "$here" | cksum); project=${project%% *}
    [[ ! -L $root ]]
}
# The /ratexp command, naming this script by its full path. Written once and never
# overwritten: the file is the user's to edit or delete. Cursor reads
# /ratexp:<skill> as /ratexp followed by the skill's name, and ignores a file named
# ratexp:<skill>.md, so this one file serves both spellings.
ratexp_command() {
    local dir=$here/commands file=$here/commands/ratexp.md
    [[ -e $file || -L $file || -L $dir ]] && return
    # The path lands inside a shell command the agent runs.
    [[ $self =~ ^[a-zA-Z0-9_./\ -]+$ ]] || return
    mkdir -p -- "$dir" || return
    printf '%s\n' '# RateXp survey' '' \
        "If the user wrote a skill name after /ratexp - as \`/ratexp <name>\` or \`/ratexp:<name>\` -" \
        "run \`bash \"$self\" ask <that-name>\`; otherwise run \`bash \"$self\" ask\`. Then follow" \
        'what it prints, word for word. Do nothing else, and do not summarise the session.' > "$file"
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
# Whether a chat's newest user message asks for a rating: /ratexp, however the
# skill after it is written, or the stop hook's followup. The editor sends a
# command's body along, which opens with "RateXp survey"; a bare /ratexp counts
# only at the start of what the user typed, since a path like
# .cursor/ratexp-cursor.sh names it too.
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
    local event token session generation transcript base every
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
        ratexp_command
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
    # A turn the user spent rating is not work, so it is not counted: /ratexp,
    # this hook's own followup, or the answer to either - which the user may give
    # in a message of their own, so `report` marks that turn.
    rmdir -- "$base/answered" 2>/dev/null && return
    asked_to_rate "$transcript" && return
    # Environment settings override the distributed defaults.
    every=${RATEXP_EVERY:-$DEFAULT_EVERY}
    [[ $every =~ ^[1-9][0-9]{0,4}$ ]] && (( every <= 32768 )) || return
    mkdir -p -- "$base" || return
    turn_is_due "$base" "$generation" || return
    # The same survey /ratexp starts, so the agent is sent down the same path.
    quote "RateXp survey for this whole chat: run \`bash \"$self\" ask\` and follow what it prints, word for word. Do nothing else, and do not summarise the session."
    printf '{"followup_message":%s}\n' "$quoted"
}

ask() {
    local target=${1-} url session identity size start request dir what who token end
    for token in cksum date mkdir od stat head tail grep; do command -v "$token" >/dev/null || return 1; done
    where_am_i || return 1
    [[ -z $target || $target =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] ||
        { printf 'RateXp: %s is not a skill name.\n' "$target" >&2; return 1; }
    url=${RATEXP_URL:-$DEFAULT_URL}; url=${url%/}
    good_url "$url" || return 1
    # The CLI may never fire sessionStart, and the stop hook's followup reaches
    # here too, so /ratexp is also written here.
    ratexp_command
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
        [[ $start =~ ^[0-9]{1,10}$ ]] && (( start < size )) ||
            { printf 'RateXp: there is no run of %s in this chat to rate yet.\n' "$target" >&2; return 1; }
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
        "$identity" "$url" "$target" > "$dir/pending"
    what='this whole chat'; who='this session'
    [[ -n $target ]] && { what="this run of $target"; who=$target; }
    consent_line "$url" "$what"
    printf '%s\n' \
        "RateXp survey for $what. Ask the user these two questions - with AskQuestion if it" \
        'is available, titled RateXp, otherwise both in one message - and wait for the answer:' \
        "1. verdict: \"Rate $who:\" - options good, bad" \
        "2. transcript: \"$consent\" - options share, private" \
        'Then run this once, with exactly what the user chose:' \
        "bash \"$self\" report <good|bad> <share|private> '<comment>'" \
        'The transcript stays private unless the user chose share. The comment is only what' \
        "the user typed, if anything, in single quotes with each ' written as '\\''. Print" \
        'what that command prints, word for word, and nothing else. Never rate it yourself.'
}

report() {
    local verdict=${1-} sharing=${2-} comment=${3-} score share token candidate newest newest_born chat
    local now dir pending request born session transcript size start identity url target current
    local fields reason
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
    } < "$pending" || return 1
    good_url "$url" || return 1
    [[ $session =~ ^[a-zA-Z0-9_-]{1,128}$ ]] || return 1
    [[ -z $target || $target =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] || return 1
    # Consume before sending: a retried command cannot upload the same run twice.
    mkdir -- "$dir/done" 2>/dev/null || { printf 'RateXp: already answered\n' >&2; return 1; }
    [[ ! -L $pending ]] || return 1
    : > "$pending"
    mkdir -- "${dir%/runs/*}/answered" 2>/dev/null
    # A session rating names no skill; a skill's rating names the skill.
    fields=(--form-string 'agent=cursor' --form-string "session_id=$session"
        --form-string "request_id=$request" --form-string "score=$score")
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
    current=$(file_info /dev/fd/3) || { printf '%s\n' "$reason"; return 0; }
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
    *) printf 'usage: %s ask [skill] | report <good|bad> <share|private> [comment]\n' "$0" >&2; exit 1 ;;
esac
# Cursor may read an empty reply as a malformed one, so every event gets an
# answer - `{}` when there is nothing to say.
reply=$(hook 2>/dev/null)
[[ -n $reply ]] || reply='{}'
printf '%s\n' "$reply"
exit 0
