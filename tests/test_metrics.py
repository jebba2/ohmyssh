"""Tests for the remote probe script and metric parsers."""

from ohmyssh.core.metrics import (
    HostMetrics,
    ProcessInfo,
    buildProbeScript,
    metricsFromProbeOutput,
    parseCpuPercent,
    parseDiskPercent,
    parseDockerCount,
    parseLoadAverage,
    parseMemory,
    parseOsName,
    parseProbeOutput,
    parseProcesses,
    parseUptime,
)

LINUX_TOP = """top - 09:12:01 up 12 days,  3:04,  1 user,  load average: 0.52, 0.58, 0.59
Tasks: 212 total,   1 running, 211 sleeping,   0 stopped,   0 zombie
%Cpu(s):  7.8 us,  2.1 sy,  0.0 ni, 88.9 id,  1.0 wa,  0.0 hi,  0.2 si,  0.0 st
MiB Mem :  15902.4 total,   1234.5 free,   8000.0 used,   6667.9 buff/cache
"""

MACOS_TOP = """Processes: 512 total, 2 running, 510 sleeping, 2480 threads
CPU usage: 5.26% user, 10.52% sys, 84.21% idle
"""

LINUX_FREE = """              total        used        free      shared  buff/cache   available
Mem:    16675868672  8388608000   987654321   123456789  7299605951  7700000000
Swap:    2147483648           0  2147483648
"""

LINUX_FREE_NO_AVAILABLE = """             total       used       free     shared    buffers     cached
Mem:    8000000000 6000000000 2000000000          0  100000000  500000000
"""

DF_OUTPUT = """Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1       51474912 20589964  28243404  43% /
"""

DF_CAPACITY_OUTPUT = """Filesystem   1024-blocks      Used Available Capacity  Mounted on
/dev/disk3s1   488245288 212345678 270000000    45%    /
"""

OS_RELEASE = """PRETTY_NAME="Ubuntu 24.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.1 LTS (Noble Numbat)"
"""

OS_RELEASE_NO_PRETTY = """NAME="Debian GNU/Linux"
VERSION="12 (bookworm)"
"""

PS_OUTPUT = """%CPU %MEM COMMAND
12.3  4.5 python3
 3.2 10.1 postgres
 0.5  0.3 sshd
 0.1  0.1 cron
"""


def test_cpu_percent_linux_top() -> None:
    assert parseCpuPercent(LINUX_TOP) == 11.1


def test_cpu_percent_macos_top() -> None:
    assert parseCpuPercent(MACOS_TOP) == 15.79


def test_cpu_percent_unparseable() -> None:
    assert parseCpuPercent("garbage") is None
    assert parseCpuPercent("") is None


def test_memory_uses_available_column() -> None:
    memory = parseMemory(LINUX_FREE)
    assert memory is not None
    usedPercent, totalBytes = memory
    assert totalBytes == 16675868672
    assert usedPercent == 53.83


def test_memory_falls_back_to_free_column() -> None:
    memory = parseMemory(LINUX_FREE_NO_AVAILABLE)
    assert memory is not None
    assert memory == (75.0, 8000000000)


def test_memory_unparseable() -> None:
    assert parseMemory("nothing here") is None


def test_disk_percent_use_column() -> None:
    assert parseDiskPercent(DF_OUTPUT) == 43.0


def test_disk_percent_capacity_column() -> None:
    assert parseDiskPercent(DF_CAPACITY_OUTPUT) == 45.0


def test_disk_percent_unparseable() -> None:
    assert parseDiskPercent("Filesystem Size\n") is None


def test_uptime_keeps_only_days_when_present() -> None:
    assert parseUptime(" 09:12:01 up 12 days,  3:04,  1 user,  load average: 0.52") == "12 days"
    assert parseUptime(" 09:12:01 up 1 day,  3:04,  1 user") == "1 day"


def test_uptime_short_form() -> None:
    assert parseUptime(" 09:12:01 up  3:04,  1 user,  load average: 0.1, 0.2, 0.3") == "3:04"
    assert parseUptime("09:12:01 up 45 min, 1 user, load average: 0.1") == "45 min"


def test_uptime_unparseable() -> None:
    assert parseUptime("") is None


def test_load_average_from_proc() -> None:
    assert parseLoadAverage("0.52 0.58 0.59 2/412 12345") == (0.52, 0.58, 0.59)


def test_load_average_from_uptime_tail() -> None:
    line = "09:12:01 up 3 days, load average: 1,20, 0,80, 0,40"
    assert parseLoadAverage(line) == (1.2, 0.8, 0.4)


def test_load_average_unparseable() -> None:
    assert parseLoadAverage("") is None


def test_os_name_prefers_pretty_name() -> None:
    assert parseOsName(OS_RELEASE) == "Ubuntu 24.04.1 LTS"


def test_os_name_combines_name_and_version() -> None:
    assert parseOsName(OS_RELEASE_NO_PRETTY) == "Debian GNU/Linux 12 (bookworm)"


def test_os_name_falls_back_to_uname_line() -> None:
    assert parseOsName("FreeBSD 14.1-RELEASE\n") == "FreeBSD 14.1-RELEASE"


def test_os_name_unparseable() -> None:
    assert parseOsName("") is None


def test_docker_count_reads_wc_output() -> None:
    assert parseDockerCount("3\n") == 3
    assert parseDockerCount("  0  \n") == 0


def test_docker_count_absent_when_docker_missing() -> None:
    assert parseDockerCount("") is None
    assert parseDockerCount("junk") is None


def test_processes_top_three_skipping_header() -> None:
    processes = parseProcesses(PS_OUTPUT)
    assert processes == [
        ProcessInfo(name="python3", cpuPercent=12.3, memPercent=4.5),
        ProcessInfo(name="postgres", cpuPercent=3.2, memPercent=10.1),
        ProcessInfo(name="sshd", cpuPercent=0.5, memPercent=0.3),
    ]


def test_processes_skip_malformed_lines() -> None:
    assert parseProcesses("%CPU %MEM COMMAND\nbroken line\n1.0 2.0 ok\n") == [
        ProcessInfo(name="ok", cpuPercent=1.0, memPercent=2.0)
    ]


def test_probe_output_sections() -> None:
    text = (
        "ignored preamble\n"
        "===OHMYSSH:OS===\n"
        'PRETTY_NAME="Ubuntu"\n'
        "===OHMYSSH:EMPTY===\n"
        "===OHMYSSH:DF===\n"
        "line one\nline two\n"
    )
    sections = parseProbeOutput(text)
    assert sections == {"OS": 'PRETTY_NAME="Ubuntu"', "EMPTY": "", "DF": "line one\nline two"}


def test_probe_output_garbage() -> None:
    assert parseProbeOutput("") == {}
    assert parseProbeOutput("no markers at all") == {}


def test_probe_script_contains_every_section_marker() -> None:
    script = buildProbeScript()
    for section in ["OS", "CPU", "MEM", "DISK", "UPTIME", "LOAD", "DOCKER", "PROCS"]:
        assert f"===OHMYSSH:{section}===" in script
    assert "df -k /" in script
    assert "2>/dev/null" in script


def test_metrics_from_probe_output_full() -> None:
    text = "\n".join(
        [
            "===OHMYSSH:OS===",
            OS_RELEASE,
            "===OHMYSSH:CPU===",
            LINUX_TOP,
            "===OHMYSSH:MEM===",
            LINUX_FREE,
            "===OHMYSSH:DISK===",
            DF_OUTPUT,
            "===OHMYSSH:UPTIME===",
            " 09:12:01 up 12 days,  3:04,  1 user,  load average: 0.52, 0.58, 0.59",
            "===OHMYSSH:LOAD===",
            "0.52 0.58 0.59 2/412 12345",
            "===OHMYSSH:DOCKER===",
            "3",
            "===OHMYSSH:PROCS===",
            PS_OUTPUT,
        ]
    )
    metrics = metricsFromProbeOutput(text)
    assert metrics == HostMetrics(
        osName="Ubuntu 24.04.1 LTS",
        cpuPercent=11.1,
        memPercent=53.83,
        memTotalBytes=16675868672,
        diskPercent=43.0,
        uptime="12 days",
        loadAverage=(0.52, 0.58, 0.59),
        dockerContainers=3,
        processes=[
            ProcessInfo(name="python3", cpuPercent=12.3, memPercent=4.5),
            ProcessInfo(name="postgres", cpuPercent=3.2, memPercent=10.1),
            ProcessInfo(name="sshd", cpuPercent=0.5, memPercent=0.3),
        ],
    )


def test_metrics_from_probe_output_empty_is_all_unknown() -> None:
    metrics = metricsFromProbeOutput("")
    assert metrics == HostMetrics()
    assert metrics.dockerContainers is None
    assert metrics.processes == []


def test_metrics_load_falls_back_to_uptime_when_loadavg_missing() -> None:
    text = "===OHMYSSH:UPTIME===\n09:12:01 up 3 days, load average: 1.5, 1.0, 0.5\n"
    metrics = metricsFromProbeOutput(text)
    assert metrics.loadAverage == (1.5, 1.0, 0.5)
    assert metrics.uptime == "3 days"
