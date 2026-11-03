# shellcheck shell=sh disable=SC2154

# Report OOM kills in the job script's memory cgroup on the job's stderr, where Galaxy's
# output check finds them. A kill inside a pipeline can otherwise leave exit code 0.
_galaxy_oom_kills() {
    (
        if [ -f "$cgroup_mount/cgroup.controllers" ]; then
            _galaxy_cgroup=$(awk -F: '$1 == "0" {print $3}' "$proc_cgroup")
            _galaxy_oom_kill_file="$cgroup_mount$_galaxy_cgroup/memory.events"
        else
            _galaxy_cgroup=$(awk -F: '$2 ~ /(^|,)memory(,|$)/ {print $3}' "$proc_cgroup")
            _galaxy_oom_kill_file="$cgroup_mount/memory$_galaxy_cgroup/memory.oom_control"
        fi
        awk '$1 == "oom_kill" {print $2}' "$_galaxy_oom_kill_file"
    ) 2>/dev/null
}

_galaxy_report_oom_kills() {
    _galaxy_job_rc=$?
    _galaxy_oom_kills_after=$(_galaxy_oom_kills)
    if [ -n "$_GALAXY_OOM_KILLS_BEFORE" ] && [ -n "$_galaxy_oom_kills_after" ] \
        && [ "$_galaxy_oom_kills_after" -gt "$_GALAXY_OOM_KILLS_BEFORE" ] 2>/dev/null; then
        echo "galaxy: Detected $((_galaxy_oom_kills_after - _GALAXY_OOM_KILLS_BEFORE)) oom-kill event(s) in the job's memory cgroup." >&2
    fi
    return $_galaxy_job_rc
}

_GALAXY_OOM_KILLS_BEFORE=$(_galaxy_oom_kills)
