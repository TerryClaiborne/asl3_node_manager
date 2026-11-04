#!/usr/bin/env python3
"""Narrow, node-locked outbound linking and private Link Favorites storage.
No shell evaluation, no remote node selection, no Asterisk configuration writes.
"""
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from echolink_guard import reset_when_idle

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / 'run'
FAVORITES = RUN / 'link_favorites.json'
LOCKS = RUN / 'locks'
ASTERISK = '/usr/sbin/asterisk' if Path('/usr/sbin/asterisk').is_file() else '/usr/bin/asterisk'
NODE = re.compile(r'^[0-9]{1,7}$')


def output(ok, message='', **extra):
    print(json.dumps(dict(ok=ok, message=message, **extra), ensure_ascii=True, separators=(',', ':')))
    return 0 if ok else 1


def ast(cmd, timeout=5):
    cp = subprocess.run([ASTERISK, '-rx', cmd], capture_output=True, text=True, timeout=timeout, check=False)
    result = (cp.stdout or cp.stderr).strip()
    if cp.returncode or any(x in result.lower() for x in ('no such command', 'invalid command', 'not found', 'unable to', 'failed', 'error:')):
        raise RuntimeError('Asterisk command failed: ' + (result[:160] or 'unknown error'))
    return result


def node_status(local):
    cmd = [sys.executable, str(ROOT / 'bin' / 'asl3-node-manager-status.py'), '--node', local, '--json']
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=9, check=False)
    if cp.returncode and not cp.stdout:
        raise RuntimeError('Current node status could not be read.')
    data = json.loads(cp.stdout)
    if str(data.get('node', '')) != local:
        raise RuntimeError('Node status was not for the configured local node.')
    return data


def reported_link_mode(local, target):
    """Read AMI XStat's explicit T/R mode for the *requested node* only.

    RPT_LINKS may contain other clients, e.g. KC3KMV, and cannot establish
    the mode of numeric AllStar node 67565. Missing mode stays unknown.
    """
    path = ROOT / 'bin' / 'asl3-node-manager-status.py'
    spec = importlib.util.spec_from_file_location('node_manager_status_for_link', path)
    if spec is None or spec.loader is None:
        return ''
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.fetch_xstat_modes(local).get(target, ''))


def check_initial_link_mode(local, target, mode, current):
    """Interpret the requested *outgoing* node using AllStar Connect's modes.

    Monitor.php maps XStat LinkedNodes T to Transceive and a connected
    non-T link to Local Monitor.  ASL3 local-monitor sessions can be present
    in rpt xnode / lstats but absent from RPT_LINKS and rpt nodes entirely.
    Only treat that absence as supporting local monitor when the same numeric
    target is independently established OUT and marked xnode_only.  Never
    substitute the mode of a different connection (e.g. KC3KMV).
    """
    expected = 'R' if mode == 'local_monitor' else 'T'
    label = 'Local Monitor' if mode == 'local_monitor' else 'Transceive'
    observed = reported_link_mode(local, target)
    if observed == expected:
        return 'verified', label
    if observed in ('T', 'R'):
        return 'mismatch', ('Transceive' if observed == 'T' else 'Local Monitor')

    # AMI may omit a local-monitor entry from LinkedNodes.  Use the actual
    # RPT_LINKS list for this exact target; never infer from its first entry.
    for link in current.get('all_links') or []:
        if str(link.get('node', '')) != target:
            continue
        code = str(link.get('mode_code', '')).upper()
        if code in ('T', 'R'):
            if code == expected:
                return 'verified', label
            return 'mismatch', ('Transceive' if code == 'T' else 'Local Monitor')

    for link in current.get('adjacent_links') or []:
        if str(link.get('node', '')) != target:
            continue
        if str(link.get('direction', '')).upper() != 'OUT':
            continue
        if mode == 'local_monitor' and link.get('xnode_only') is True:
            # Independent established OUT from xnode, absent from the
            # ordinary RPT_LINKS/RPT_ALINKS lists.  This is consistent with
            # the known app_rpt local-monitor presentation, without falsely
            # saying an AMI R flag was reported.
            return 'consistent', label
    return 'unreported', ''


def echolink_capability():
    """Read-only capability check. No driver reload or new link is attempted."""
    try:
        result = ast('module show like echolink', timeout=3)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False
    return any('chan_echolink.so' in line.lower() and
               re.search(r'\s\d+\s+Running\b', line, re.IGNORECASE)
               for line in result.splitlines())


def favorites_list():
    if not FAVORITES.exists():
        return []
    if FAVORITES.is_symlink():
        raise RuntimeError('Unsafe Favorites file.')
    raw = FAVORITES.read_text(encoding='utf-8')
    if len(raw) > 300000:
        raise RuntimeError('Favorites file is too large.')
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError('Invalid Favorites file.')
    return data[:300]


def favorites_save(items):
    RUN.mkdir(mode=0o755, parents=True, exist_ok=True)
    content = json.dumps(items, ensure_ascii=True, indent=2) + '\n'
    tmp = FAVORITES.with_name(FAVORITES.name + '.' + str(os.getpid()) + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FAVORITES)
    os.chmod(FAVORITES, 0o600)


def validate(payload):
    network = str(payload.get('network', 'ASL')).upper()
    target = str(payload.get('target', '')).strip()
    mode = str(payload.get('mode', 'transceive')).strip()
    if network not in ('ASL', 'ECHO'):
        raise ValueError('Choose AllStarLink or EchoLink.')
    if not NODE.fullmatch(target):
        raise ValueError('A resolved numeric node number is required. Use Search first for callsigns.')
    if network == 'ECHO':
        if not re.fullmatch(r'3\d{6}', target):
            raise ValueError('EchoLink target must be the mapped 3xxxxxx node.')
    elif re.fullmatch(r'3\d{6}', target):
        raise ValueError('Select EchoLink for a mapped 3xxxxxx node.')
    elif 1000 <= int(target) <= 1999:
        raise ValueError('Private AllStar nodes 1000–1999 cannot be used here.')
    if mode not in ('transceive', 'local_monitor'):
        raise ValueError('Unsupported link mode.')
    return network, target, mode


def clean_text(text, limit):
    text = ' '.join(str(text).replace('|', ' ').split())
    if len(text) > limit or any(ord(c) < 32 for c in text):
        raise ValueError('Invalid Favorite text.')
    return text


def connect(local, payload):
    network, target, mode = validate(payload)
    if target == local:
        raise ValueError('Cannot link a node to itself.')
    state = node_status(local)
    ctl = state.get('controller') or {}
    if str(ctl.get('sys_ena')) != '1' or str(ctl.get('link_ena')) != '1':
        raise RuntimeError('ASL3 node or linking commands are disabled.')
    links = state.get('adjacent_links') or []
    for link in links:
        if str(link.get('node', '')) == target:
            raise RuntimeError('That station is already connected. Disconnect it before connecting in a different mode.')
    if network == 'ECHO':
        # Follow AllStar Connect: classify live EchoLink sessions by direction
        # BEFORE consulting the driver's use count. A live outgoing session
        # is normal use=1, not an unidentifiable driver failure.
        live_echo = [x for x in links if str(x.get('connection_type', '')).lower() == 'echolink'
                     or re.fullmatch(r'3\d{6}', str(x.get('node', '')))]
        lstats = ast('rpt lstats ' + local)
        lstats_echo = []
        for row in lstats.splitlines():
            cols = row.split()
            if cols and re.fullmatch(r'3\d{6}', cols[0]):
                direction = next((c.upper() for c in cols[1:] if c.upper() in ('IN', 'OUT')), 'UNKNOWN')
                lstats_echo.append((cols[0], direction))
        # The Connections status can temporarily lag behind rpt lstats, so
        # evaluate both without conflating unknown with OUT or IN.
        directions = [str(x.get('direction') or '').upper() for x in live_echo]
        directions.extend(d for _, d in lstats_echo)
        if 'IN' in directions:
            raise RuntimeError('Inbound EchoLink is active; outbound connect is blocked to protect that caller.')
        if 'OUT' in directions:
            raise RuntimeError('Only one outgoing EchoLink connection is allowed.')
        if live_echo or lstats_echo:
            raise RuntimeError('EchoLink direction could not be verified; outbound connect is blocked.')
        mod = ast('module show like echolink')
        driver_line = next((ln for ln in mod.splitlines()
                            if 'chan_echolink.so' in ln.lower() and 'running' in ln.lower()), '')
        if not driver_line:
            raise RuntimeError('EchoLink channel driver is not loaded; outgoing EchoLink is unavailable.')
        usage = re.search(r'\s(\d+)\s+Running\b', driver_line, re.IGNORECASE)
        if usage is None:
            raise RuntimeError('EchoLink driver use count could not be verified; outgoing connection blocked.')
        if int(usage.group(1)) != 0:
            raise RuntimeError('EchoLink driver is busy; outgoing connection blocked to protect current users.')
        official = str(int(target[1:]))
        db = ast('echolink dbget nodename ' + official)
        if not any(re.match(r'^' + re.escape(official) + r'\|', ln.strip()) for ln in db.splitlines()):
            raise RuntimeError('EchoLink station is not confirmed online in the channel-driver directory.')
        # Reference sequence is reached only after the caller, module-use, and
        # on-line checks succeed, while this per-node request lock is held.
        reset_when_idle(local, node_status, require_idle=True)
        if any(str(x.get('connection_type') or '').lower() == 'echolink'
               for x in node_status(local).get('adjacent_links') or []):
            raise RuntimeError('An incoming EchoLink session appeared; outgoing connect cancelled.')
    code = '8' if mode == 'local_monitor' else '3'
    ast('rpt cmd ' + local + ' ilink ' + code + ' ' + target, timeout=8)
    with (RUN / 'control.log').open('a', encoding='utf-8') as log:
        log.write(f'link node={local} target={target} network={network} mode={mode} command=accepted\n')
    # The EchoLink reset/waits are above and apply only to EchoLink. Normal
    # AllStar commands have no additional fixed delay, only bounded polling.
    deadline = time.monotonic() + (8.0 if network == 'ASL' else 6.0)
    connected = False
    while time.monotonic() < deadline:
        current = node_status(local)
        if any(str(link.get('node', '')) == target and
               str(link.get('direction', '')).upper() == 'OUT'
               for link in current.get('adjacent_links') or []):
            connected = True
            break
        time.sleep(0.2)
    if not connected:
        return output(True, 'Connection command accepted; station is not yet confirmed in Connections.',
                      result='pending', target=target, network=network, mode=mode)
    if network == 'ECHO':
        return output(True, 'EchoLink connected to ' + target + '.',
                      result='verified', target=target, network=network, mode=mode)
    # Verify the requested AllStar node in XStat, not a different connection
    # that happens to appear in RPT_LINKS. Do not confuse command acceptance
    # with Asterisk's actual mode confirmation.
    observed_status, observed_label = check_initial_link_mode(local, target, mode, current)
    if observed_status == 'mismatch':
        return output(False, 'Connected to ' + target + ', but its reported mode is ' + observed_label + '.',
                      result='mode_mismatch', target=target, network=network, mode=mode)
    if observed_status == 'verified':
        return output(True, 'Connected to ' + target + ' (' + observed_label + ').',
                      result='verified', target=target, network=network, mode=mode)
    if observed_status == 'consistent':
        return output(True, 'Connected to ' + target + ' (Local Monitor).',
                      result='mode_consistent', target=target, network=network, mode=mode)
    # Same concise response as the proven reference app: a confirmed outbound
    # link is a connection success; do not claim that an absent AMI mode was
    # measured, and do not send the confusing prior warning to the browser.
    return output(True, 'AllStarLink connect command completed.',
                  result='mode_unverified', target=target, network=network, mode=mode)


def main():
    raw = sys.stdin.read(8193)
    if len(raw) > 8192:
        return output(False, 'Request too large.')
    req = json.loads(raw)
    if not isinstance(req, dict):
        return output(False, 'Invalid request.')
    action = req.get('action')
    local = str(req.get('node', ''))
    if not NODE.fullmatch(local) or len(sys.argv) != 2 or local != sys.argv[1]:
        return output(False, 'Node does not match the selected local node.')
    if action not in ('favorites-list', 'capabilities', 'favorite-save', 'favorite-delete', 'connect'):
        return output(False, 'Unsupported Link operation.')
    if action == 'capabilities':
        available=echolink_capability()
        return output(True, echolink_available=available,
                      echolink_reason='' if available else
                      'EchoLink is unavailable: the channel driver is not loaded or running.')
    LOCKS.mkdir(parents=True, exist_ok=True)
    with (LOCKS / (local + '.lock')).open('a+') as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return output(False, 'Another node control is in progress.')
        if action == 'favorites-list':
            return output(True, favorites=favorites_list())
        if action == 'connect':
            return connect(local, req)
        network, target, mode = validate(req)
        items = favorites_list()
        original = len(items)
        items = [x for x in items if not (x.get('network') == network and x.get('target') == target)]
        if action == 'favorite-save':
            name = clean_text(req.get('name', ''), 96)
            description = clean_text(req.get('description', ''), 160)
            if not name:
                raise ValueError('Enter a station name.')
            items.append(dict(network=network, target=target, mode=mode, name=name, description=description))
            if len(items) > 300:
                raise ValueError('Favorite limit reached (300).')
            items.sort(key=lambda x: (x['network'], int(x['target'])))
            favorites_save(items)
            return output(True, 'Favorite saved.', favorites=items)
        if action == 'favorite-delete':
            if len(items) == original:
                return output(False, 'Favorite was not found.')
            favorites_save(items)
            return output(True, 'Favorite deleted.', favorites=items)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        sys.exit(output(False, str(e)))
