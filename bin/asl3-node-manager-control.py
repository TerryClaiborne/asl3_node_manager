#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from echolink_guard import reset_when_idle

APP_ROOT = Path(__file__).resolve().parent.parent
STATUS = Path(os.environ.get('ASL3_NODE_MANAGER_STATUS_SCRIPT', str(APP_ROOT / 'bin' / 'asl3-node-manager-status.py')))
RUN_DIR = APP_ROOT / 'run'
LOCK_DIR = RUN_DIR / 'locks'
SNAP_DIR = RUN_DIR / 'snapshots'
AUDIT_LOG = RUN_DIR / 'control.log'
ASTERISK = os.environ.get('ASL3_NODE_MANAGER_ASTERISK_BIN') or ('/usr/sbin/asterisk' if Path('/usr/sbin/asterisk').exists() else 'asterisk')

ACTIONS = {
    'disconnect', 'block', 'restore',
    'disconnect-all', 'incoming-block', 'incoming-allow',
    'node-offline', 'node-restore',
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_runtime():
    for p in (RUN_DIR, LOCK_DIR, SNAP_DIR):
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p, 0o755)
        except OSError:
            pass


def audit(node, action, result, detail=''):
    ensure_runtime()
    clean = str(detail).replace('\n', ' ').replace('\r', ' ')[:1000]
    with AUDIT_LOG.open('a', encoding='utf-8') as fh:
        fh.write(f'{now_iso()} node={node} action={action} result={result} detail={clean}\n')
    try:
        os.chmod(AUDIT_LOG, 0o644)
    except OSError:
        pass


def run_cmd(args, timeout=5.0):
    try:
        cp = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
        return {'ok': cp.returncode == 0, 'code': cp.returncode,
                'stdout': cp.stdout.strip(), 'stderr': cp.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'code': 124, 'stdout': '', 'stderr': 'command timed out'}
    except Exception as exc:
        return {'ok': False, 'code': 125, 'stdout': '', 'stderr': str(exc)}


def asterisk(command):
    return run_cmd([ASTERISK, '-rx', command], 5.0)


def read_status(node):
    cp = run_cmd(['/usr/bin/python3', str(STATUS), '--node', str(node), '--json'], 8.0)
    if not cp['ok'] and not cp['stdout']:
        raise RuntimeError(cp['stderr'] or 'status command failed')
    try:
        data = json.loads(cp['stdout'])
    except Exception as exc:
        raise RuntimeError(f'invalid status JSON: {exc}')
    if not isinstance(data, dict) or str(data.get('node')) != str(node):
        raise RuntimeError('status returned the wrong node')
    return data


def wait_for(node, predicate, timeout=5.0, interval=0.25):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = read_status(node)
        if predicate(last):
            return last, True
        time.sleep(interval)
    return last or read_status(node), False


def wait_for_stable(node, predicate, timeout=6.0, interval=0.25, consecutive=3):
    """Require the requested controller state to survive multiple polls.

    app_rpt controller changes can settle asynchronously.  A single matching
    sample is not enough when restoring the node from an offline transition.
    """
    end = time.monotonic() + timeout
    last = None
    matches = 0
    while time.monotonic() < end:
        last = read_status(node)
        if predicate(last):
            matches += 1
            if matches >= max(1, int(consecutive)):
                return last, True
        else:
            matches = 0
        time.sleep(interval)
    return last or read_status(node), False


def apply_state_command(node, command, label, predicate, *, timeout=6.0,
                        interval=0.25, consecutive=3, settle_hold=0.5, attempts=2):
    """Apply a controller command and require the result to remain settled.

    The command may return before app_rpt has completed a larger state
    transition.  Re-apply the requested state once if that transition later
    overwrites it.
    """
    last = None
    for _attempt in range(max(1, int(attempts))):
        command_or_raise(node, command, label)
        last, ok = wait_for_stable(
            node, predicate, timeout=timeout, interval=interval,
            consecutive=consecutive
        )
        if ok:
            if settle_hold > 0:
                time.sleep(settle_hold)
                last = read_status(node)
            if predicate(last):
                return last, True
        time.sleep(0.35)
    return last or read_status(node), False


def controller_value(status, key):
    try:
        return int((status.get('controller') or {}).get(key))
    except Exception:
        return None


def command_or_raise(node, command, label):
    r = asterisk(f'rpt cmd {node} {command}')
    if not r['ok']:
        raise RuntimeError(f'{label} failed: {r["stderr"] or r["stdout"] or "Asterisk returned an error"}')
    return r


def snapshot_path(node):
    return SNAP_DIR / f'{node}.json'


def classify_snapshot_links(status):
    """Capture observed links and conservatively select safe reconnections.

    T is a reported outgoing transceive mode. R says receive-only, NOT
    whether ilink 2 or ilink 8 established it. An xnode-only ? provides
    even less information. We MUST NOT manufacture provenance from a
    previously issued command because an external client may have replaced
    the active connection in the meantime.
    """
    eligible = []
    observed = []
    skipped = []
    for link in status.get('adjacent_links') or []:
        remote = str(link.get('node') or '')
        mode = str(link.get('mode_code') or '').upper()
        kind = str(link.get('connection_type') or '')
        direction = str(link.get('direction') or '').upper()
        observed.append({
            'node': remote,
            'display_node': str(link.get('display_node') or ''),
            'callsign': str(link.get('callsign') or ''),
            'connection_type': kind,
            'direction': direction,
            'mode_code': mode,
            'mode_label': str(link.get('mode_label') or ''),
            'restore_policy': str(link.get('restore_policy') or ''),
        })
        if kind != 'node' or not remote.isdigit():
            continue
        if direction not in ('OUT', 'IN'):
            skipped.append({
                'node': remote, 'mode_code': mode or '?',
                'reason': 'Numeric link direction is unclassified; cannot determine whether it requires outgoing restoration.',
            })
            continue
        if direction != 'OUT':
            continue
        if mode == 'T':
            eligible.append({
                'node': remote, 'mode_code': 'T', 'ilink_command': '3',
                'mode_evidence': 'current_outgoing_status_T',
                'mode_label': 'Transceive',
                'callsign': str(link.get('callsign') or ''),
            })
        else:
            skipped.append({
                'node': remote, 'mode_code': mode or '?',
                'reason': ('Receive-only status does not identify ilink 2 versus ilink 8.'
                           if mode == 'R' else
                           'Current outgoing connection mode is not verifiable.'),
            })
    return eligible, observed, skipped


def snapshot_restore_plan(snap):
    """Revalidate restore intentions, including legacy version-1 snapshots.

    Historical R entries cannot prove their original monitor command.
    All unknown-mode outgoing links remain explicitly skipped.
    """
    eligible = []
    skipped = []
    seen = set()
    for link in snap.get('eligible_links') or []:
        remote = str(link.get('node') or '')
        mode = str(link.get('mode_code') or '').upper()
        command = str(link.get('ilink_command') or '')
        evidence = str(link.get('mode_evidence') or '')
        if remote in seen:
            skipped.append({'node': remote, 'mode_code': mode or '?',
                            'reason': 'Duplicate restore target in snapshot; repeated command suppressed.'})
            continue
        if not remote.isdigit() or remote == str(snap.get('node') or ''):
            skipped.append({'node': remote, 'mode_code': mode, 'reason': 'Invalid restore target.'})
            continue
        seen.add(remote)
        # T is unambiguous in both v1 and v2. Never trust an unverified
        # command claim for R or ?. Future explicit provenance requires a
        # separate audited session-lifetime implementation.
        if mode == 'T' and (not command or command == '3') and (not evidence or evidence == 'current_outgoing_status_T'):
            eligible.append({'node': remote, 'mode_code': 'T', 'ilink_command': '3',
                             'mode_label': str(link.get('mode_label') or 'Transceive')})
        else:
            skipped.append({'node': remote, 'mode_code': mode or '?',
                            'reason': 'Saved mode lacks verified command provenance; no automatic reconnect.'})
    for link in snap.get('observed_links') or []:
        remote = str(link.get('node') or '')
        if remote in seen or not remote.isdigit():
            continue
        if str(link.get('connection_type') or '') != 'node':
            continue
        direction = str(link.get('direction') or '').upper()
        if direction == 'IN':
            continue
        seen.add(remote)
        skipped.append({'node': remote, 'mode_code': str(link.get('mode_code') or '?'),
                        'reason': ('Outgoing link was observed but its saved mode is not safe to restore.'
                                   if direction == 'OUT' else
                                   'Numeric link direction unclassified; manual review required.')})
    # Snapshot v2 also records skipped connections separately; preserve them
    # even if an old/imported snapshot lacks an observed_links entry.
    for link in snap.get('skipped_links') or []:
        remote = str(link.get('node') or '')
        if remote not in seen:
            seen.add(remote)
            skipped.append({'node': remote, 'mode_code': str(link.get('mode_code') or '?'),
                            'reason': str(link.get('reason') or 'Mode unverified.')})
    return eligible, skipped


def save_snapshot(node, status):
    ensure_runtime()
    eligible, observed, skipped = classify_snapshot_links(status)
    data = {
        'version': 2,
        'node': str(node),
        'created_at': now_iso(),
        'system_was_enabled': controller_value(status, 'sys_ena') == 1,
        'linking_was_enabled': controller_value(status, 'link_ena') == 1,
        'incoming_was_enabled': controller_value(status, 'iconns') != 0,
        'incoming_state_observed': controller_value(status, 'iconns'),
        'eligible_links': eligible,
        'observed_links': observed,
        'skipped_links': skipped,
    }
    path = snapshot_path(node)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    os.chmod(path, 0o644)
    return data


def load_snapshot(node):
    path = snapshot_path(node)
    if not path.is_file():
        raise RuntimeError('No saved ASL3 offline snapshot exists for this node.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise RuntimeError(f'Unable to read saved snapshot: {exc}')
    if str(data.get('node')) != str(node):
        raise RuntimeError('Saved snapshot belongs to a different node.')
    return data


CLIENT_RE = re.compile(r'^[A-Za-z0-9_.:@-]{1,64}$')


def disconnect_one(node, link):
    """Disconnect one live session using the proven path for its type."""
    ctype = str(link.get('connection_type') or '').lower()
    target = str(link.get('control_target') or link.get('node') or '').strip()
    display = str(link.get('display_node') or link.get('callsign') or target).strip()
    if ctype == 'client':
        if not CLIENT_RE.fullmatch(target):
            return {'ok': False, 'target': target, 'display': display, 'type': ctype,
                    'detail': 'unsafe or invalid named-client target'}
        r = asterisk(f'rpt cmd {node} ilink 11 {target}')
        return {'ok': r['ok'], 'target': target, 'display': display, 'type': ctype,
                'detail': r['stderr'] or r['stdout']}
    if ctype in ('node', 'echolink'):
        if not re.fullmatch(r'\d{1,7}', target):
            return {'ok': False, 'target': target, 'display': display, 'type': ctype,
                    'detail': 'invalid numeric app_rpt control target'}
        # Same *1 target disconnect path proven by ASL3 Node Blocker & Restore.
        # EchoLink uses the hidden 3xxxxxx app_rpt target, never the public ID.
        r = asterisk(f'rpt fun {node} *1{target}')
        return {'ok': r['ok'], 'target': target, 'display': display, 'type': ctype,
                'detail': r['stderr'] or r['stdout']}
    return {'ok': False, 'target': target, 'display': display, 'type': ctype or 'unknown',
            'detail': 'unsupported live connection type'}


def disconnect_all_connections(node, initial=None):
    """Disconnect active sessions; never rapidly retry an EchoLink disconnect.

    Follow AllStar Connect's direct ilink-1 / immediate 1-second settling
    sequence for EchoLink. Uncertain EchoLink state is a partial failure, not
    an invitation to issue another disconnect or unload a busy driver.
    """
    attempts = []
    status = initial or read_status(node)
    echo_attempted = set()
    for _round in range(3):
        links = list(status.get('adjacent_links') or [])
        if not links:
            return status, not any(not a.get('ok') for a in attempts), attempts
        for link in links:
            ctype = str(link.get('connection_type') or '').lower()
            target = str(link.get('control_target') or link.get('node') or '').strip()
            if ctype != 'echolink':
                attempts.append(disconnect_one(node, link))
                continue
            if target in echo_attempted:
                continue
            echo_attempted.add(target)
            display = str(link.get('display_node') or link.get('callsign') or target)
            if not re.fullmatch(r'3\d{6}', target):
                attempts.append({'ok': False, 'target': target, 'display': display,
                                 'type': 'echolink', 'detail': 'Invalid EchoLink control target'})
                continue
            # Asterisk may accept the command before the channel has settled.
            # This is the direct command and immediate delay proven in AllStar Connect.
            command = asterisk(f'rpt cmd {node} ilink 1 {target}')
            time.sleep(1.0)
            after, gone = wait_for(node, lambda st: live_link_by_target(st, target) is None,
                                   timeout=5.0, interval=0.3)
            ok = bool(command['ok'] and gone)
            detail = command['stderr'] or command['stdout'] or ''
            if not gone:
                detail = (detail + ' Connection still observed; automatic retry suppressed.').strip()
            # Only outgoing cleanup may reset the driver. The shared guard
            # refuses a reset if *any* incoming/outgoing caller or use remains.
            if ok and str(link.get('direction') or '').upper() == 'OUT':
                try:
                    reset_when_idle(node, read_status, require_idle=False)
                except Exception as exc:
                    ok = False
                    detail = (detail + ' Driver cleanup requires operator attention: ' + str(exc)).strip()
            attempts.append({'ok': ok, 'target': target, 'display': display,
                             'type': 'echolink', 'detail': detail})
            status = after
        time.sleep(0.35)
        status = read_status(node)
    status, clear = wait_for(node,
                            lambda st: int(st.get('adjacent_link_count') or 0) == 0,
                            timeout=4.0, interval=0.35)
    return status, bool(clear and all(a.get('ok') for a in attempts)), attempts


def incoming_state(status):
    return controller_value(status, 'iconns')


def set_incoming(node, allow):
    # app_rpt cop 49 = disable incoming connections; cop 50 = enable them.
    command_or_raise(node, 'cop 50' if allow else 'cop 49',
                     'Allow incoming connections' if allow else 'Block incoming connections')
    expected = 1 if allow else 0
    first = read_status(node)
    if incoming_state(first) is None:
        return first, None
    return wait_for(node, lambda st: incoming_state(st) == expected, timeout=5.0)



def live_link_by_target(status, target):
    target = str(target or '').strip()
    for link in status.get('adjacent_links') or []:
        if str(link.get('control_target') or link.get('node') or '').strip() == target:
            return link
    return None


def disconnect_target(node, target, before):
    link = live_link_by_target(before, target)
    if not link:
        # The browser may display a stale row after another client or remote
        # node has already disconnected. A disconnect of an absent target is
        # complete; never present this harmless race as a failed operation.
        return result_payload(node, 'disconnect', 'verified',
                              'Connection already disconnected.', before, before,
                              target=target, echolink_cleanup='not-applicable')
    result = disconnect_one(node, link)
    if not result.get('ok'):
        # Asterisk can report a missing target if it went away between status
        # and command. Verify absence before deciding if this is a failure.
        after_error = read_status(node)
        if live_link_by_target(after_error, target) is None:
            return result_payload(node, 'disconnect', 'verified',
                                  'Connection already disconnected.', before, after_error,
                                  target=target, disconnect_attempt=result,
                                  echolink_cleanup='skipped-already-gone')
        raise RuntimeError(result.get('detail') or 'Disconnect command failed.')
    after, gone = wait_for(
        node,
        lambda st: live_link_by_target(st, target) is None,
        timeout=5.0,
        interval=0.3,
    )
    ctype = str(link.get('connection_type') or '')
    display = str(link.get('display_node') or link.get('callsign') or target)
    message = f'{display} disconnected.' if gone else f'Disconnect command sent for {display}, but the connection is still observed.'
    cleanup = 'not-applicable'
    # Match the accepted AllStar Connect outgoing EchoLink cleanup sequence.
    # Never reset the channel driver while another station or a module user
    # remains active. Incoming EchoLink callers continue to be disconnect-only.
    if gone and ctype.lower() == 'echolink' and str(link.get('direction') or '').upper() == 'OUT':
        time.sleep(1.0)  # Reference disconnect settling time.
        try:
            cleanup = 'reset' if reset_when_idle(node, read_status, require_idle=False) else 'skipped-busy'
        except Exception as error:
            cleanup = 'failed'
            message += ' EchoLink driver cleanup needs attention: ' + str(error)[:140]
    return result_payload(node, 'disconnect', 'partial' if cleanup == 'failed' else ('verified' if gone else 'partial'), message, before, after,
                          target=target, connection_type=ctype, disconnect_attempt=result, echolink_cleanup=cleanup)


def clean_reason(reason):
    reason = re.sub(r'[^A-Za-z0-9 .,_:;()/#@+\-]', '', str(reason or '').replace('\r', ' ').replace('\n', ' ')).strip()
    return (reason[:80] or 'Blocked with ASL3 Node Manager')


def block_target(node, target, reason, before):
    if not re.fullmatch(r'\d{4,7}', str(target or '')):
        raise RuntimeError('Only numeric 4-7 digit AllStar nodes can be blocked.')
    if re.fullmatch(r'3\d{6}', str(target)):
        raise RuntimeError('EchoLink connections are disconnect-only and cannot be blocked.')
    if str(target) == str(node):
        raise RuntimeError('The local node cannot block itself.')
    link = live_link_by_target(before, target)
    if link and str(link.get('connection_type') or '') != 'node':
        raise RuntimeError('Only numeric AllStar node connections can be blocked.')
    disconnect_result = None
    if link:
        disconnect_result = disconnect_one(node, link)
        if not disconnect_result.get('ok'):
            raise RuntimeError(disconnect_result.get('detail') or 'Unable to disconnect the node before blocking it.')
        wait_for(node, lambda st: live_link_by_target(st, target) is None, timeout=5.0, interval=0.3)
    reason = clean_reason(reason)
    r = asterisk(f'database put denylist/{node} {target} "{reason}"')
    if not r['ok']:
        raise RuntimeError(r['stderr'] or r['stdout'] or 'Unable to add the denylist entry.')
    check = asterisk(f'database show denylist/{node}')
    pat = re.compile(rf'^/denylist/{re.escape(str(node))}/{re.escape(str(target))}\s*:', re.M)
    verified = check['ok'] and bool(pat.search(check['stdout']))
    after = read_status(node)
    message = f'Node {target} disconnected and blocked.' if verified else f'Block command sent for node {target}, but the denylist entry was not verified.'
    return result_payload(node, 'block', 'verified' if verified else 'partial', message, before, after,
                          target=str(target), reason=reason, disconnect_attempt=disconnect_result)


def restore_target(node, target, before):
    if not re.fullmatch(r'\d{4,7}', str(target or '')):
        raise RuntimeError('Restore target must be a numeric 4-7 digit AllStar node.')
    if str(target) == str(node):
        raise RuntimeError('The local node cannot restore itself.')
    asterisk(f'database del denylist/{node} {target}')
    check = asterisk(f'database show denylist/{node}')
    pat = re.compile(rf'^/denylist/{re.escape(str(node))}/{re.escape(str(target))}\s*:', re.M)
    verified = check['ok'] and not bool(pat.search(check['stdout']))
    after = read_status(node)
    message = f'Node {target} access restored; it may connect again.' if verified else f'Restore command sent for node {target}, but the denylist entry is still present.'
    return result_payload(node, 'restore', 'verified' if verified else 'partial', message, before, after, target=str(target))

def result_payload(node, action, result, message, before=None, after=None, **extra):
    out = {
        'ok': result in ('verified', 'accepted'),
        'result': result,
        'node': str(node),
        'action': action,
        'message': message,
        'checked_at': now_iso(),
    }
    if before is not None:
        out['before'] = before
    if after is not None:
        out['after'] = after
    out.update(extra)
    return out


def perform(node, action, target="", reason=""):
    before = read_status(node)
    if not before.get('node_online'):
        raise RuntimeError('app_rpt node is not online.')

    if action == 'disconnect':
        if not target:
            raise RuntimeError('Missing disconnect target.')
        return disconnect_target(node, target, before)

    if action == 'block':
        if not target:
            raise RuntimeError('Missing block target.')
        return block_target(node, target, reason, before)

    if action == 'restore':
        if not target:
            raise RuntimeError('Missing restore target.')
        return restore_target(node, target, before)

    if action == 'disconnect-all':
        after, ok, attempts = disconnect_all_connections(node, before)
        remain = int(after.get('adjacent_link_count') or 0)
        failures = [a for a in attempts if not a.get('ok')]
        verified = ok and not failures
        if verified:
            message = 'All current AllStar, Web Transceiver, and EchoLink connections disconnected.'
        elif ok:
            message = 'All currently observed connections are gone, but one or more disconnect commands reported an error.'
        else:
            message = f'Disconnect operation completed; {remain} connection(s) still observed.'
        return result_payload(node, action, 'verified' if verified else 'partial', message,
                              before, after, remaining_links=remain,
                              disconnect_attempts=attempts, disconnect_failures=failures)

    if action == 'incoming-block':
        after, verified = set_incoming(node, False)
        result = 'verified' if verified is True else ('accepted' if verified is None else 'partial')
        message = ('New incoming connections are blocked.' if verified is True else
                   'Block-new-incoming command accepted by app_rpt.' if verified is None else
                   'Command sent, but the blocked state was not verified.')
        return result_payload(node, action, result, message, before, after,
                              verification='cop 49; existing connections are not disconnected by this action.')

    if action == 'incoming-allow':
        after, verified = set_incoming(node, True)
        result = 'verified' if verified is True else ('accepted' if verified is None else 'partial')
        message = ('New incoming connections are allowed.' if verified is True else
                   'Allow-new-incoming command accepted by app_rpt.' if verified is None else
                   'Command sent, but the allowed state was not verified.')
        return result_payload(node, action, result, message, before, after,
                              verification='cop 50; this does not create a connection by itself.')

    if action == 'node-offline':
        snap = save_snapshot(node, before)
        # Prevent a new inbound session racing the isolation sequence.
        incoming_after, _incoming_verified = set_incoming(node, False)
        after_disconnect, disconnected, attempts = disconnect_all_connections(node, incoming_after)
        # Disable user link commands and then disable the ASL3/app_rpt system.
        command_or_raise(node, 'cop 12', 'Disable user link commands')
        command_or_raise(node, 'cop 3', 'Disable ASL3 system')
        after, state_ok = wait_for(
            node,
            lambda st: controller_value(st, 'sys_ena') == 0
                       and controller_value(st, 'link_ena') == 0
                       and int(st.get('adjacent_link_count') or 0) == 0,
            timeout=6.0,
        )
        incoming_ok = incoming_state(after) in (None, 0)
        failures = [a for a in attempts if not a.get('ok')]
        ok = state_ok and disconnected and incoming_ok and not failures
        skipped_links = snap.get('skipped_links') or []
        message = ('ASL3 node taken offline; some links were skipped or could not be classified for automatic restoration.'
                   if ok and skipped_links else
                   'ASL3 node taken offline: new incoming connections blocked, current connections disconnected, link commands disabled, and ASL3 system disabled.'
                   if ok else
                   'Offline sequence completed, but one or more requested states need attention.')
        return result_payload(node, action, 'verified' if ok and not skipped_links else 'partial', message, before, after,
                              snapshot=snap, skipped_links=skipped_links, disconnect_attempts=attempts,
                              disconnect_failures=failures,
                              note='Physical repeater/radio power is not changed.')

    if action == 'node-restore':
        snap = load_snapshot(node)
        want_system = bool(snap.get('system_was_enabled', True))
        want_linking = bool(snap.get('linking_was_enabled', True))
        want_incoming = bool(snap.get('incoming_was_enabled', True))
        expected_system = 1 if want_system else 0
        expected_linking = 1 if want_linking else 0
        expected_incoming = 1 if want_incoming else 0

        # Restore controller state in stages.  app_rpt can finish a system
        # enable/disable transition after the CLI command returns; sending the
        # link/incoming commands immediately can therefore be overwritten by
        # that later transition.  Each stage must remain correct across
        # repeated polls, and the writable stages are retried once if app_rpt
        # changes them while settling.
        _system_after, system_ok = apply_state_command(
            node,
            'cop 2' if want_system else 'cop 3',
            'Restore ASL3 system state',
            lambda st: controller_value(st, 'sys_ena') == expected_system,
            timeout=7.0, interval=0.25, consecutive=4, settle_hold=1.0, attempts=2,
        )

        _link_after, linking_ok = apply_state_command(
            node,
            'cop 11' if want_linking else 'cop 12',
            'Restore link-command state',
            lambda st: (controller_value(st, 'sys_ena') == expected_system
                        and controller_value(st, 'link_ena') == expected_linking),
            timeout=7.0, interval=0.25, consecutive=4, settle_hold=0.7, attempts=2,
        )

        # iconns is exposed on current ASL3/app_rpt builds.  If it is not
        # observable on a future/older build, still send the command and mark
        # this stage accepted rather than fabricating verification.
        observed_incoming_before = incoming_state(read_status(node))
        if observed_incoming_before is None:
            command_or_raise(
                node, 'cop 50' if want_incoming else 'cop 49',
                'Restore incoming-connection state'
            )
            incoming_verified = None
        else:
            _incoming_after, incoming_verified = apply_state_command(
                node,
                'cop 50' if want_incoming else 'cop 49',
                'Restore incoming-connection state',
                lambda st: (controller_value(st, 'sys_ena') == expected_system
                            and controller_value(st, 'link_ena') == expected_linking
                            and incoming_state(st) == expected_incoming),
                timeout=7.0, interval=0.25, consecutive=4,
                settle_hold=0.7, attempts=2,
            )

        def restored_base_state(st):
            observed_incoming = incoming_state(st)
            incoming_matches = (observed_incoming is None
                                or observed_incoming == expected_incoming)
            return (controller_value(st, 'sys_ena') == expected_system
                    and controller_value(st, 'link_ena') == expected_linking
                    and incoming_matches)

        _base_after, base_stable = wait_for_stable(
            node, restored_base_state, timeout=8.0, interval=0.3, consecutive=5
        )
        if base_stable:
            time.sleep(0.8)
            base_stable = restored_base_state(read_status(node))

        restored = []
        failed = []
        plan, skipped = snapshot_restore_plan(snap)
        base_ready = system_ok and linking_ok and base_stable and incoming_verified is not False
        if not want_system or not want_linking:
            for link in plan:
                skipped.append({'node': link['node'], 'mode_code': link['mode_code'],
                                'reason': 'Saved node or link commands were disabled.'})
            plan = []
        elif not base_ready:
            for link in plan:
                failed.append({'node': link['node'], 'mode_code': link['mode_code'],
                               'reason': 'ASL3 controller state did not stabilize; connection not attempted.'})
            plan = []
        for link in plan:
            remote = str(link['node'])
            mode = 'T'
            # Another controller (AllStar Connect, CLI, etc.) may already have
            # re-established this target after the snapshot was taken. Never
            # issue a new ilink command against an existing session: even an
            # existing Transceive connection is not evidence we created it.
            try:
                current = read_status(node)
            except Exception as exc:
                failed.append({'node': remote, 'mode_code': mode,
                               'reason': f'Unable to check current links before reconnect: {exc}'})
                continue
            if not isinstance(current.get('adjacent_links'), list):
                failed.append({'node': remote, 'mode_code': mode,
                               'reason': 'Current link list unavailable; automatic reconnect suppressed.'})
                continue
            existing = [cur for cur in current['adjacent_links']
                        if str(cur.get('node') or '') == remote]
            if existing:
                skipped.append({'node': remote, 'mode_code': mode,
                                'reason': 'Target already connected (possibly by another application); existing session left unchanged.'})
                continue
            r = asterisk(f'rpt cmd {node} ilink 3 {remote}')
            if not r['ok']:
                failed.append({'node': remote, 'mode_code': mode,
                               'reason': r['stderr'] or r['stdout'] or 'command failed'})
                continue

            def link_seen(status):
                for cur in status.get('adjacent_links') or []:
                    if (str(cur.get('node') or '') == remote
                            and str(cur.get('direction') or '') == 'OUT'
                            and str(cur.get('mode_code') or '') == 'T'):
                        return True
                return False

            _s, link_ok = wait_for(node, link_seen, timeout=6.0, interval=0.4)
            if link_ok:
                restored.append({'node': remote, 'mode_code': mode,
                                 'mode_label': link.get('mode_label', '')})
            else:
                failed.append({'node': remote, 'mode_code': mode,
                               'reason': 'connection was not verified in the saved mode'})

        after, final_stable = wait_for_stable(
            node, restored_base_state, timeout=6.0, interval=0.3, consecutive=4
        )
        if final_stable:
            time.sleep(0.8)
            after = read_status(node)
            final_stable = restored_base_state(after)

        final_incoming = incoming_state(after)
        incoming_ok = (incoming_verified is not False
                       and (final_incoming is None or final_incoming == expected_incoming))
        base_ok = (system_ok and linking_ok and base_stable and final_stable
                   and controller_value(after, 'sys_ena') == expected_system
                   and controller_value(after, 'link_ena') == expected_linking)
        overall = base_ok and incoming_ok and not failed and not skipped
        msg = ('ASL3 node restored to its saved operating state.' if overall
               else 'ASL3 node restore completed with items requiring attention.')

        # Keep the snapshot for audit/retry; annotate it instead of deleting it.
        snap['last_restore_at'] = now_iso()
        snap['last_restore_restored'] = restored
        snap['last_restore_failed'] = failed
        snap['last_restore_skipped'] = skipped
        path = snapshot_path(node)
        path.write_text(json.dumps(snap, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.chmod(path, 0o644)
        return result_payload(node, action, 'verified' if overall else 'partial', msg, before, after,
                              restored_links=restored, failed_links=failed, skipped_links=skipped,
                              restore_checks={
                                  'system_stable': system_ok,
                                  'linking_stable': linking_ok,
                                  'incoming_verified': incoming_verified,
                                  'base_stable': base_stable,
                                  'final_stable': final_stable,
                              },
                              note='Inbound AllStar, Web Transceiver, EchoLink, and unverified monitor modes are not auto-restored.')

    raise RuntimeError('Unsupported action.')


def main():
    p = argparse.ArgumentParser(description='ASL3 Node Manager control engine')
    p.add_argument('--node', required=True)
    p.add_argument('--action', required=True, choices=sorted(ACTIONS))
    p.add_argument('--target', default='')
    p.add_argument('--reason', default='')
    args = p.parse_args()
    if not re.fullmatch(r'\d+', args.node):
        print(json.dumps({'ok': False, 'result': 'failed', 'message': 'node must be numeric'}))
        return 2
    ensure_runtime()
    lock_path = LOCK_DIR / f'{args.node}.lock'
    with lock_path.open('a+', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            out = result_payload(args.node, args.action, 'failed', 'Another control action is already running for this node.')
            audit(args.node, args.action, 'failed', out['message'])
            print(json.dumps(out, separators=(',', ':')))
            return 3
        try:
            out = perform(args.node, args.action, args.target, args.reason)
            audit(args.node, args.action, out['result'], out['message'])
            print(json.dumps(out, separators=(',', ':'), sort_keys=True))
            return 0 if out.get('ok') else 1
        except Exception as exc:
            out = result_payload(args.node, args.action, 'failed', str(exc))
            audit(args.node, args.action, 'failed', str(exc))
            print(json.dumps(out, separators=(',', ':'), sort_keys=True))
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
