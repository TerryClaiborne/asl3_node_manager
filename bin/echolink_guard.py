#!/usr/bin/env python3
"""Single guarded EchoLink driver transition shared by Link and Connections.

Preserves incoming sessions: never unload chan_echolink when the configured
node reports an EchoLink session, an app_rpt session ID is present, or the
Asterisk channel driver use count cannot be positively verified as zero.
"""
import re
import subprocess
import time
from pathlib import Path

ASTERISK = '/usr/sbin/asterisk' if Path('/usr/sbin/asterisk').is_file() else '/usr/bin/asterisk'


def command(text, timeout=10):
    cp = subprocess.run([ASTERISK, '-rx', text], capture_output=True, text=True,
                        timeout=timeout, check=False)
    result = (cp.stdout or cp.stderr).strip()
    if cp.returncode or any(word in result.lower() for word in (
        'no such command', 'invalid command', 'not found', 'unable to', 'failed', 'error:')):
        raise RuntimeError('EchoLink Asterisk command failed: ' + (result[:140] or 'unknown error'))
    return result


def live_echolink_in_status(state):
    return any(str(link.get('connection_type') or '').lower() == 'echolink'
               or re.fullmatch(r'3\d{6}', str(link.get('node') or ''))
               for link in (state.get('adjacent_links') or []))


def module_line(report):
    return next((line for line in report.splitlines()
                 if 'chan_echolink.so' in line.lower()), '')


def driver_idle(report):
    line = module_line(report)
    count = re.search(r'\s(\d+)\s+Running\b', line, re.IGNORECASE)
    return bool(count and int(count.group(1)) == 0)


def driver_running(report):
    """After a reload, match AllStar Connect's loaded-driver verification.

    A new incoming caller or driver-internal use can increase Use Count
    immediately after module load. That is not evidence of a failed reload.
    The zero-use requirement applies BEFORE an unload, not after a load.
    """
    return bool(re.search(r'\bRunning\b', module_line(report), re.IGNORECASE))


def reset_when_idle(local, read_status, *, require_idle):
    """Reset with AllStar Connect's 1s after unload + 2s after reload.

    If require_idle is False (post-disconnect cleanup), return False without
    altering the driver when another caller is active or status is ambiguous.
    If True (outbound connect), refuse the connection in those conditions.
    """
    def refuse(message):
        if require_idle:
            raise RuntimeError(message)
        return False

    try:
        state = read_status(local)
        if live_echolink_in_status(state):
            return refuse('EchoLink is in use; existing callers will not be interrupted.')
        lstats = command('rpt lstats ' + str(local))
        if any(re.match(r'^3\d{6}\b', row.strip()) for row in lstats.splitlines()):
            return refuse('EchoLink app_rpt session is active; reset refused.')
        report = command('module show like echolink')
        if not driver_idle(report):
            return refuse('EchoLink driver busy, unloaded, or its use count unknown; reset refused.')
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        if require_idle:
            raise
        return False

    # AllStar Connect's protected transition; no generic artificial cooldown.
    command('module unload chan_echolink.so')
    time.sleep(1.0)
    if module_line(command('module show like echolink')):
        raise RuntimeError('EchoLink channel driver did not unload; connection refused.')
    try:
        command('module load chan_echolink.so')
    except Exception as error:
        raise RuntimeError('EchoLink driver failed to reload; operator attention required.') from error
    time.sleep(2.0)
    # AllStar Connect checks that the module reloaded successfully, not that
    # its Use Count remains zero after reload. Requiring post-load idle
    # incorrectly labels successful disconnects as failures when Asterisk
    # begins using the driver during the settling interval.
    if not driver_running(command('module show like echolink')):
        raise RuntimeError('EchoLink driver reload was not verified running; operator attention required.')
    return True
