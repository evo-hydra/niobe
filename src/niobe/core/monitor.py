"""Process metrics capture via psutil."""

from __future__ import annotations

import logging

import psutil

from niobe.models.enums import ServiceStatus
from niobe.models.runtime import ProcessMetrics, ServiceInfo

logger = logging.getLogger("niobe.monitor")

_PSUTIL_STATUS_MAP: dict[str, str] = {
    psutil.STATUS_RUNNING: ServiceStatus.RUNNING.value,
    psutil.STATUS_SLEEPING: ServiceStatus.SLEEPING.value,
    psutil.STATUS_STOPPED: ServiceStatus.STOPPED.value,
    psutil.STATUS_ZOMBIE: ServiceStatus.ZOMBIE.value,
    psutil.STATUS_DEAD: ServiceStatus.DEAD.value,
}


def _map_status(psutil_status: str) -> str:
    """Map a psutil status string to ServiceStatus value."""
    return _PSUTIL_STATUS_MAP.get(psutil_status, ServiceStatus.UNKNOWN.value)


def _find_pid_by_port(port: int) -> int | None:
    """Find a PID listening on the given port."""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                return conn.pid
    except (psutil.AccessDenied, OSError):
        logger.debug("Access denied scanning network connections")
    return None


def _resolve_pid(service: ServiceInfo) -> int | None:
    """Resolve a PID from the service info — direct pid or via port lookup."""
    if service.pid is not None:
        return service.pid
    if service.port is not None:
        return _find_pid_by_port(service.port)
    return None


def capture_metrics(
    service: ServiceInfo, cpu_interval: float = 0.5
) -> ProcessMetrics | None:
    """Capture point-in-time process metrics for a service. Returns None if unavailable."""
    pid = _resolve_pid(service)
    if pid is None:
        logger.warning("Cannot resolve PID for service %s", service.name)
        return None

    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=cpu_interval)
        mem = proc.memory_info().rss / (1024 * 1024)
        status = _map_status(proc.status())
        threads = proc.num_threads()
        try:
            connections = len(proc.net_connections(kind="inet"))
        except (psutil.AccessDenied, OSError):
            connections = 0

        return ProcessMetrics(
            pid=pid,
            status=status,
            cpu_percent=round(cpu, 1),
            memory_mb=round(mem, 2),
            num_threads=threads,
            num_connections=connections,
        )
    except psutil.NoSuchProcess:
        logger.warning("Process %d no longer exists for service %s", pid, service.name)
    except psutil.AccessDenied:
        logger.warning("Access denied reading process %d for service %s", pid, service.name)
    except psutil.ZombieProcess:
        logger.warning("Zombie process %d for service %s", pid, service.name)
    return None
