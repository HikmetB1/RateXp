#!/bin/bash
# RateXp: Bash 3.2+, curl, and standard macOS/Linux utilities. No packages.
# The model draws the supplied picker; this file owns its text and all I/O.
# Installed once, for every project, as ~/.claude/ratexp-claude.sh by whoever uses
# Claude Code. It asks about the whole session every Nth turn on its own, and
# whenever the user types /ratexp. /ratexp:<skill> rates only that skill's most
# recent run - a skill is never asked about on its own. A word after either picks
# the eval: which of core's surveys is asked. It notes where every skill run
# starts so it can do this, and writes /ratexp itself.
set -f
set -o pipefail
umask 077
export LC_ALL=C
DEFAULT_URL='__RATEXP_URL__'
DEFAULT_EVERY='__RATEXP_EVERY__'
DEFAULT_EVAL='__RATEXP_EVAL__'
# The evals core offers, one per line: the name typed after /ratexp, the question -
# where {subject}, if used, becomes what is rated - then the label and description
# of the good answer, and of the bad one.
EVALS=('__RATEXP_EVALS__')

# Strict JSON reader using indexed arrays (also supported by macOS Bash 3.2).
# No eval, menu scanning, or third-party JSON runtime.
# The reader, quote, good_url, post, file_info, ratexp_request, find_eval and
# unknown_eval_line are the same in ratexp-cursor.sh: a test holds the two copies
# identical, so change them together.
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
# Consent names what will be uploaded - the session, or one skill's run - and where.
consent_line() {  # consent_line <url> [skill]
    local what='this session'
    [[ -n ${2-} ]] && what="this run of $2"
    consent="Upload $what, including messages and tool results, to $1."
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
    local key=$1 from=$2
    mkdir -p -- "$base/runs" "$base/tools" || return
    mkdir -- "$base/lock" 2>/dev/null || return
    # Refuse symlinks in writable state; always release the lock.
    if [[ ! -L $base/current.tmp ]] && mkdir -- "$base/runs/$key" 2>/dev/null; then
        : > "$base/runs/$key/ask"
        printf '%s' "$from" > "$base/runs/$key/start"
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
    printf '{"systemMessage":%s}\n' "$quoted"
}
# Skip unrelated or oversized tool payloads before parsing. The dashboard's install
# popup (app/FE/src/App.jsx) has users hook up exactly these events; keep in step.
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
# A /ratexp request as the user typed it: /ratexp:<skill> rates that skill's newest
# run, and a word after the command names the eval. Fails for any other command.
ratexp_request() {  # ratexp_request <request>: sets target, eval_name
    local pattern='^/ratexp(:([^[:space:]]+))?([[:space:]]+([^[:space:]]+))?([[:space:]]|$)'
    target=''; eval_name=''
    [[ $1 =~ $pattern ]] || return 1
    target=${BASH_REMATCH[2]}; eval_name=${BASH_REMATCH[4]}
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
# What a user who names an eval core does not offer is told instead.
unknown_eval_line() {  # unknown_eval_line <name>: sets unknown
    local i offered=''
    for ((i=0; i+5<${#EVALS[@]}; i+=6)); do offered=$offered${offered:+, }${EVALS[i]}; done
    unknown="RateXp: there is no eval named $1. Choose one of: $offered. To rate a skill, type /ratexp:<skill>."
}
# A command file: /ratexp itself, or the /ratexp:<skill> menu entry that makes a
# skill's name autocomplete after /ratexp; an eval's name may follow either.
# Written once and never overwritten: the file is the user's to edit or delete.
# The model may not run it: the hook only hears commands the user typed, so a
# model-run /ratexp would promise a survey that never comes.
ratexp_command() {  # ratexp_command <file> <description> <target>
    local file=$1 dir=${1%/*}
    [[ -e $file || -L $file || -L $dir ]] && return
    mkdir -p -- "$dir" || return
    printf '%s\n' '---' "description: $2" 'argument-hint: "[eval]"' 'disable-model-invocation: true' \
        '---' '' "RateXp target: $3" '' \
        'Say only: "Opening the RateXp survey." Do not summarise the session, do not draw' \
        'any picker yourself - the hook supplies one as soon as this turn ends.' > "$file"
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
    [[ ! -L $base/skills/${started//:/--} ]] || return
    printf '%s' "${info##*:}" > "$base/skills/${started//:/--}"
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

main() {
    local event session script url every root base dir run now request question picker reason end
    local input response answers annotations answer tool stored_tool born transcript size start identity current
    local good=0 bad=0 share=0 keep=0 comment='' score='' rest part fields
    local metadata questions signature expected token target cwd asked subject unknown
    local eval_name eval_question good_label good_description bad_label bad_description
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
    get 0 cwd; cwd=$found
    if [[ $event == SessionStart ]]; then
        # Claude Code reads command files only when a session starts, so what is
        # written here shows from the next session on.
        ratexp_command "$script/commands/ratexp.md" \
            "Rate this session with RateXp; add an eval's name to pick the survey." 'this session'
        # One /ratexp:<skill> entry per installed skill, so every name autocompletes.
        # The entries are global, so one project's skills are listed in another too;
        # rating one there is refused, because it never ran in that session.
        set +f
        for token in "$cwd"/.claude/skills/*/SKILL.md "$HOME"/.claude/skills/*/SKILL.md; do
            [[ -f $token ]] || continue
            token=${token%/SKILL.md}; token=${token##*/}
            [[ $token =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$ ]] &&
                ratexp_command "$script/commands/ratexp/$token.md" \
                    "Rate your most recent run of $token with RateXp." "$token"
        done
        set -f
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
        get 0 command_args; [[ $type == string ]] || found=''
        if ! ratexp_request "/$token $found"; then
            skill_started "$token"  # any other command is a skill starting
            return
        fi
        # The newest request decides: one whose turn the user interrupted fired no
        # Stop, so it can still be waiting here. No target means the whole session,
        # and no eval the one core asks by default.
        [[ ! -L $base/rate-now ]] && mkdir -p -- "$base/rate-now" || return
        [[ ! -L $base/rate-now/target ]] && printf '%s' "$target" > "$base/rate-now/target"
        [[ ! -L $base/rate-now/eval ]] && printf '%s' "$eval_name" > "$base/rate-now/eval"
        return
    fi
    if [[ $event == Stop ]]; then
        get 0 stop_hook_active; [[ $type != true ]] || return
        get 0 transcript_path
        token=$(file_info "$found") || return
        target=''; eval_name=''; start=0
        if [[ -d $base/rate-now ]]; then
            # /ratexp asks, and moving the request aside consumes it: one request,
            # one survey. It keeps the skill and the eval it named, if any. That
            # turn was the user asking to rate, not work, so it is not counted.
            asked=$base/asked-${token//:/-}
            mv -- "$base/rate-now" "$asked" 2>/dev/null || return
            [[ -f $asked/target && ! -L $asked/target ]] && target=$(< "$asked/target")
            [[ -f $asked/eval && ! -L $asked/eval ]] && eval_name=$(< "$asked/eval")
        else
            # Every Nth turn the whole session is asked about on its own.
            turn_is_due "${token//:/-}" || return
        fi
        # A request that names no eval, and every Nth turn, ask core's default one.
        if ! find_eval "${eval_name:=$DEFAULT_EVAL}"; then
            unknown_eval_line "$eval_name"; quote "$unknown"
            printf '{"systemMessage":%s}\n' "$quoted"
            return
        fi
        # The whole session starts at byte zero; a skill at its newest run.
        if [[ -n $target ]]; then
            [[ $target =~ ^[a-zA-Z0-9][a-zA-Z0-9_:.-]{0,127}$ ]] || return
            if [[ ! -f $base/skills/${target//:/--} || -L $base/skills/${target//:/--} ]]; then
                quote "RateXp: there is no run of $target in this session to rate yet."
                printf '{"systemMessage":%s}\n' "$quoted"
                return
            fi
            start=$(< "$base/skills/${target//:/--}")
            [[ $start =~ ^[0-9]{1,10}$ ]] || return
        fi
        arm "turn-${token//:/-}" "$start"
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
        subject='this Claude Code session'; [[ -n $target ]] && subject=$target
        question=${eval_question//"{subject}"/$subject}
        question="$question — check all that apply or type a comment."
        [[ -f $dir/ask ]] || return
        mkdir -- "$dir/stopped" 2>/dev/null || return
        # Record only metadata at Stop. A skill's rating reads the transcript here
        # only to find where its run ends (run_end); nothing of it is kept.
        get 0 transcript_path; transcript=$found; size=0; identity=''
        if [[ $type == string && -f $transcript && ! -L $transcript ]]; then
            identity=$(file_info "$transcript") || identity=''
            size=${identity##*:}; identity=${identity%:*}
        fi
        [[ -f $dir/start && ! -L $dir/start ]] && start=$(< "$dir/start")
        [[ $start =~ ^[0-9]{1,10}$ ]] && (( start <= size )) || start=0
        # A skill's rating covers only its own turns, not the rest of the session.
        if [[ -n $target && -n $identity ]]; then
            run_end "$transcript" "$start" "$size"; size=$end
        fi
        request=$(od -An -N16 -tx1 /dev/urandom) || return
        request=${request//[[:space:]]/}
        [[ ${#request} == 32 ]] || return
        request=${request:0:8}-${request:8:4}-${request:12:4}-${request:16:4}-${request:20:12}
        quote "$question"; question=$quoted
        consent_line "$url" "$target"; quote "$consent"; reason=$quoted
        quote "$good_label"; good_label=$quoted; quote "$good_description"; good_description=$quoted
        quote "$bad_label"; bad_label=$quoted; quote "$bad_description"; bad_description=$quoted
        picker='{"questions":[{"question":'$question',"header":"RateXp","multiSelect":true,"options":[{"label":'$good_label',"description":'$good_description'},{"label":'$bad_label',"description":'$bad_description'},{"label":"Yes, store trajectory","description":'$reason'},{"label":"No, do not store","description":"Keep this session on my machine."}]}]}'
        [[ ! -L $dir/pending ]] || return
        printf '%s\0' "$request" "$now" "$picker" "$transcript" "$size" "$start" "$identity" "$url" \
            "$target" "$eval_name" > "$dir/pending"
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
        IFS= read -r -d '' identity; IFS= read -r -d '' url; IFS= read -r -d '' target
        IFS= read -r -d '' eval_name
    } < "$dir/pending" || return
    # Revalidate the saved destination against the pending consent text.
    good_url "$url" || return
    consent_line "$url" "$target"; [[ $picker == *"$consent"* ]] || return
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
    # A session rating names no skill; a skill's rating names the skill.
    fields=(--form-string 'agent=claude-code' --form-string "eval_name=$eval_name"
        --form-string "session_id=$session" --form-string "request_id=$request")
    [[ -n $target ]] && fields+=(--form-string "skill_name=$target")
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
    # The session so far includes the turn that ended as the survey was asked;
    # a skill's run ended before it, where it was noted.
    [[ -n $target ]] || size=${current##*:}
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
