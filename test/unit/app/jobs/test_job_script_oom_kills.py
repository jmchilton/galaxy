import subprocess

import pytest

from galaxy.jobs.runners.util.job_script import job_script
from galaxy.tool_util.output_checker import oom_kill_job_messages

V2_EVENTS = "low 0\nhigh 0\nmax 12\noom {oom}\noom_kill {oom_kill}\noom_group_kill 0\n"
V1_OOM_CONTROL = "oom_kill_disable 0\nunder_oom 0\noom_kill {oom_kill}\n"


def _fake_cgroup(tmp_path, version):
    """Lay out a fake cgroup mount; return it, the /proc/<pid>/cgroup stand-in and the counter file."""
    mount = tmp_path / "cgroup"
    proc_cgroup = tmp_path / "proc_cgroup"
    if version == 2:
        (mount / "cgroup.controllers").parent.mkdir(parents=True)
        (mount / "cgroup.controllers").write_text("cpu memory\n")
        counter = mount / "job_1" / "step_batch" / "task_0" / "memory.events"
        proc_cgroup.write_text("0::/job_1/step_batch/task_0\n")
        template = V2_EVENTS
    else:
        counter = mount / "memory" / "job_1" / "memory.oom_control"
        proc_cgroup.write_text("12:cpu,cpuacct:/job_1\n4:memory:/job_1\n")
        template = V1_OOM_CONTROL
    counter.parent.mkdir(parents=True)
    counter.write_text(template.format(oom=1, oom_kill=1))
    return mount, proc_cgroup, counter, template


@pytest.fixture(params=["bash", "sh"])
def shell(request):
    return request.param


def _run(tmp_path, shell, command, **kwds):
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    script = tmp_path / "galaxy_1.sh"
    script.write_text(job_script(working_directory=str(working_directory), command=command, **kwds))
    return subprocess.run([shell, str(script)], capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("version", [1, 2])
def test_reports_kills_during_the_job(tmp_path, shell, version):
    mount, proc_cgroup, counter, template = _fake_cgroup(tmp_path, version)
    bump = template.format(oom=3, oom_kill=3).replace("\n", "\\n")
    result = _run(
        tmp_path,
        shell,
        f"printf '{bump}' > '{counter}'; sh -c 'exit 3'",
        check_cgroup_oom_kills=True,
        cgroup_mount=str(mount),
        proc_cgroup=str(proc_cgroup),
    )

    assert result.returncode == 3
    assert "galaxy: Detected 2 oom-kill event(s) in the job's memory cgroup." in result.stderr
    (message,) = oom_kill_job_messages(result.stderr)
    assert message["match"] == "galaxy: Detected 2 oom-kill event(s) in the job's memory cgroup."


@pytest.mark.parametrize("version", [1, 2])
def test_ignores_kills_before_the_job(tmp_path, shell, version):
    mount, proc_cgroup, _, _ = _fake_cgroup(tmp_path, version)
    result = _run(
        tmp_path, shell, "true", check_cgroup_oom_kills=True, cgroup_mount=str(mount), proc_cgroup=str(proc_cgroup)
    )

    assert result.returncode == 0
    assert oom_kill_job_messages(result.stderr) == []


def test_without_a_readable_cgroup(tmp_path, shell):
    result = _run(
        tmp_path,
        shell,
        "true",
        check_cgroup_oom_kills=True,
        cgroup_mount=str(tmp_path / "missing"),
        proc_cgroup=str(tmp_path / "missing_proc_cgroup"),
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_off_by_default(tmp_path):
    assert "_galaxy_oom_kills" not in job_script(working_directory=str(tmp_path), command="true")
