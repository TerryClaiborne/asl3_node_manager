#!/usr/bin/env python3
import argparse
import configparser
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ASTERISK_CANDIDATES = ("/usr/sbin/asterisk", "/usr/bin/asterisk", "asterisk")
ASTDB = Path(os.environ.get("ASL3_NODE_MANAGER_ASTDB", "/var/lib/asterisk/astdb.txt"))
APP_ROOT = Path(__file__).resolve().parent.parent
ECHOLINK_RESOLVER = APP_ROOT / "bin" / "asl3-node-manager-echolink.php"


def app_version():
    try:
        value = (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return value or "unknown"
    except Exception:
        return "unknown"


def asterisk_bin():
    override = os.environ.get("ASL3_NODE_MANAGER_ASTERISK_BIN")
    if override:
        return override
    for item in ASTERISK_CANDIDATES:
        if item == "asterisk" or Path(item).exists():
            return item
    return "asterisk"


def run_asterisk(command, timeout=3.0):
    try:
        cp = subprocess.run(
            [asterisk_bin(), "-rx", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": cp.returncode == 0,
            "returncode": cp.returncode,
            "stdout": cp.stdout.strip(),
            "stderr": cp.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": 124, "stdout": "", "stderr": "Asterisk command timed out"}
    except Exception as exc:
        return {"ok": False, "returncode": 125, "stdout": "", "stderr": str(exc)}




def manager_config():
    path = Path(os.environ.get("ASL3_NODE_MANAGER_MANAGER_CONF", "/etc/asterisk/manager.conf"))
    if not path.is_file():
        return None
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str.lower
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return None
    host = "127.0.0.1"
    port = 5038
    if parser.has_section("general"):
        bind = parser.get("general", "bindaddr", fallback="").strip()
        if bind and bind not in ("0.0.0.0", "::"):
            host = bind
        raw_port = parser.get("general", "port", fallback="").strip()
        if raw_port.isdigit():
            port = int(raw_port)
    user = secret = ""
    for section in parser.sections():
        if section.lower() == "general":
            continue
        candidate = parser.get(section, "secret", fallback="").strip()
        if candidate:
            user, secret = section.strip(), candidate
            break
    if not user or not secret:
        return None
    return host, port, user, secret


def ami_read_response(stream, action_id, deadline_seconds=1.8):
    wanted = f"ActionID: {action_id}"
    deadline = time.monotonic() + deadline_seconds
    block = []
    while time.monotonic() < deadline:
        try:
            raw = stream.readline()
        except (socket.timeout, OSError):
            break
        if raw == b"":
            break
        line = raw.decode("utf-8", "replace").strip("\r\n")
        if line == "":
            if block and wanted in block:
                return block
            block = []
            continue
        block.append(line)
    if block and wanted in block:
        return block
    return []


def ami_action(sock, stream, fields, action_id):
    payload = "".join(f"{k}: {v}\r\n" for k, v in fields.items())
    payload += f"ActionID: {action_id}\r\n\r\n"
    sock.sendall(payload.encode("utf-8"))
    return ami_read_response(stream, action_id)


def fetch_sawstat(node):
    cfg = manager_config()
    if cfg is None:
        return {}
    host, port, user, secret = cfg
    sock = None
    stream = None
    try:
        sock = socket.create_connection((host, port), timeout=2.0)
        sock.settimeout(2.0)
        stream = sock.makefile("rb")
        # Consume the AMI greeting block before the first action.
        while True:
            line = stream.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
        login_id = f"node_manager_login_{os.getpid()}"
        login = ami_action(sock, stream, {
            "Action": "Login", "Username": user, "Secret": secret, "Events": "0"
        }, login_id)
        if not any("Authentication accepted" in line for line in login):
            return {}
        saw_id = f"node_manager_saw_{os.getpid()}"
        saw = ami_action(sock, stream, {
            "Action": "RptStatus", "Command": "SawStat", "Node": str(node)
        }, saw_id)
        try:
            ami_action(sock, stream, {"Action": "Logoff"}, f"node_manager_logoff_{os.getpid()}")
        except Exception:
            pass
    except Exception:
        return {}
    finally:
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass
    return parse_sawstat_lines(saw)


def parse_sawstat_lines(lines):
    keyed = {}
    for line in lines:
        m = re.search(r"(?:^|\s)Conn:\s+(.*)$", str(line))
        if not m:
            continue
        parts = re.split(r"\s+", m.group(1).strip())
        if len(parts) < 2:
            continue
        ident = parts[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,64}", ident):
            continue
        active = parts[1].strip().lower() in ("1", "true", "yes", "keyed")
        try:
            last = int(parts[2]) if len(parts) > 2 else -1
        except Exception:
            last = -1
        keyed[ident] = {"active": active, "last": last}
    return keyed


def parse_variables(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("RPT_"):
            out[k] = v.strip()
    return out


def parse_xnode(text):
    directions = {}
    controller = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(
            r"^([A-Za-z0-9_.:@-]+)\s+(?:(\S+)\s+)?(\d+)\s+(IN|OUT)\s+(\S+)\s+(\S.*)$",
            line,
            re.I,
        )
        if m:
            ident, peer, _zero, direction, elapsed, state = m.groups()
            directions[ident] = {
                "direction": direction.upper(),
                "peer": peer,
                "elapsed": elapsed,
                "state": state.strip(),
            }
            continue
        m = re.match(r"^([a-z_]+)=(-?\d+)$", line, re.I)
        if m:
            controller[m.group(1).lower()] = int(m.group(2))
    return directions, controller


def intish(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def boolish(value):
    return str(value).strip() == "1"


def mode_name(code):
    return {"T": "Transceive", "R": "Monitor", "C": "Command"}.get(code, f"Mode {code}")


def astdb_records():
    records = {}
    try:
        with ASTDB.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\r\n").split("|")
                node = (parts[0] if parts else "").strip()
                if not node:
                    continue
                records[node] = {
                    "callsign": (parts[1] if len(parts) > 1 else "").strip(),
                    "description": (parts[2] if len(parts) > 2 else "").strip(),
                    "location": (parts[3] if len(parts) > 3 else "").strip(),
                }
    except OSError:
        pass
    return records


def split_alink(raw):
    raw = raw.strip()
    if len(raw) >= 3 and raw[-2] in "TRC" and raw[-1] in "KU":
        ident = raw[:-2]
        if ident and re.fullmatch(r"[A-Za-z0-9_.:@-]{1,64}", ident):
            return ident, raw[-2], raw[-1]
    return raw, "?", "U"


def parse_adjacent_raw(value):
    if not value or value == "0":
        return []
    parts = [p.strip() for p in value.split(",") if p.strip()]
    entries = parts[1:] if parts and parts[0].isdigit() else parts
    out = []
    for raw in entries:
        ident, mode, keyed = split_alink(raw)
        out.append(
            {
                "node": ident,
                "mode_code": mode,
                "mode": mode_name(mode) if mode != "?" else "Unknown",
                "keyed": keyed == "K",
                "raw": raw,
            }
        )
    return out


def parse_all_links(value):
    if not value or value == "0":
        return []
    parts = [p.strip() for p in value.split(",") if p.strip()]
    entries = parts[1:] if parts and parts[0].isdigit() else parts
    result = []
    for raw in entries:
        m = re.fullmatch(r"([A-Z])(.+)", raw)
        if m:
            mode, node = m.groups()
            result.append({"node": node, "mode": mode_name(mode), "mode_code": mode, "raw": raw})
        else:
            result.append({"node": raw, "mode": "Unknown", "mode_code": "?", "raw": raw})
    return result


def parse_channels(text):
    out = {"raw_lines": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        out["raw_lines"].append(line)
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.+)$", line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    out["raw_lines"] = out["raw_lines"][:16]
    rx = out.get("rxchannel", "")
    out["driver"] = rx.split("/", 1)[0] if "/" in rx else (rx or "Unknown")
    return out


def parse_echolink_show_nodes(text):
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^Output:\s*", "", line, flags=re.I)
        m = re.match(r"^(\d{1,6})\s+([A-Za-z0-9*_.\/-]{1,32})(?:\s+|$)", line)
        if not m:
            continue
        node = m.group(1).lstrip("0") or "0"
        call = m.group(2).upper()
        result[node] = {"node": node, "callsign": call}
    return result


def exact_echolink_resolve(identifier):
    identifier = str(identifier or "").strip()
    if not identifier or not ECHOLINK_RESOLVER.exists():
        return None
    try:
        cp = subprocess.run(
            ["/usr/bin/php", str(ECHOLINK_RESOLVER)],
            input=json.dumps([identifier]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3.5,
            check=False,
        )
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return None
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return None
    for entry in entries.values():
        if not isinstance(entry, dict) or not entry.get("found"):
            continue
        node = str(entry.get("node") or "").strip()
        callsign = str(entry.get("callsign") or "").strip().upper()
        if node and callsign:
            return {"node": node, "callsign": callsign}
    return None


def map_echolink_controls(entries, live):
    remaining = set(live.keys())
    mapped = {}
    unmatched = []
    for entry in entries:
        control = entry["node"]
        if not re.fullmatch(r"3\d{6}", control):
            continue
        candidate = control[1:].lstrip("0") or "0"
        if candidate in remaining:
            mapped[control] = candidate
            remaining.remove(candidate)
        else:
            unmatched.append(control)
    if len(unmatched) == 1 and len(remaining) == 1:
        mapped[unmatched[0]] = next(iter(remaining))
    return mapped


def wt_callsign(ident):
    value = str(ident or "").strip().upper()
    value = value[:-2] if value.endswith("-P") else value
    return value if re.fullmatch(r"[A-Z]{1,3}[0-9][A-Z0-9]{1,4}", value) else ""


def classify_adjacent(entries, directions):
    records = astdb_records()
    echo_cmd = run_asterisk("echolink show nodes", timeout=2.0)
    live_echo = parse_echolink_show_nodes(echo_cmd["stdout"] if echo_cmd["ok"] else "")
    echo_map = map_echolink_controls(entries, live_echo)
    classified = []

    for entry in entries:
        ident = entry["node"]
        x = directions.get(ident, {})
        direction = str(x.get("direction") or "").upper()
        is_echo = bool(re.fullmatch(r"3\d{6}", ident))
        is_numeric = ident.isdigit() and 1 <= len(ident) <= 7 and not is_echo
        item = dict(entry)
        item.update(
            {
                "control_target": ident,
                "display_node": ident,
                "callsign": "",
                "connection_type": "client",
                "direction": direction or "UNKNOWN",
                "peer": x.get("peer", ""),
                "elapsed": x.get("elapsed", ""),
                "restore_eligible": False,
                "restore_policy": "Disconnect only",
                "mode_label": "Web Transceiver",
            }
        )

        if is_echo:
            official = echo_map.get(ident, "")
            live = live_echo.get(official, {}) if official else {}
            callsign = str(live.get("callsign") or "").upper()
            resolved = None
            if callsign:
                resolved = exact_echolink_resolve(callsign)
            elif official:
                resolved = exact_echolink_resolve(official)
            if resolved:
                official = resolved.get("node") or official
                callsign = resolved.get("callsign") or callsign
            item.update(
                {
                    "connection_type": "echolink",
                    "display_node": official or "EchoLink ID unavailable",
                    "echolink_node": official,
                    "callsign": callsign,
                    "mode_label": "EchoLink",
                    "restore_eligible": False,
                    "restore_policy": "Disconnect only",
                    "identity_verified": bool(official and callsign),
                }
            )
        elif is_numeric:
            rec = records.get(ident) or {}
            # Critical safety rule: an inbound link does not expose the far-end
            # user's original connection intent. A Local Monitor connection
            # initiated remotely is reported here as T/TU, so never infer its
            # original mode from the local node side.
            if direction == "OUT" and entry.get("mode_code") in ("T", "R"):
                label = "Node Transceiver" if entry.get("mode_code") == "T" else "Node Monitor"
                eligible = True
                policy = "Eligible"
            elif direction == "IN":
                label = "Inbound AllStar"
                eligible = False
                policy = "Remote reconnect"
            elif direction == "OUT":
                label = "Outbound AllStar"
                eligible = False
                policy = "Mode unknown"
            else:
                label = "AllStar Node"
                eligible = False
                policy = "Mode unknown"
            item.update(
                {
                    "connection_type": "node",
                    "callsign": rec.get("callsign", ""),
                    "description": rec.get("description", ""),
                    "location": rec.get("location", ""),
                    "mode_label": label,
                    "restore_eligible": eligible,
                    "restore_policy": policy,
                }
            )
        else:
            call = wt_callsign(ident)
            item.update(
                {
                    "connection_type": "client",
                    "callsign": call,
                    "mode_label": "Web Transceiver",
                    "restore_eligible": False,
                    "restore_policy": "Disconnect only",
                }
            )

        classified.append(item)

    return classified


def merge_xnode_only(entries, directions):
    """Include established direct sessions that app_rpt omits from RPT_ALINKS.

    Local-monitor style sessions can appear in rpt xnode while being absent from
    RPT_ALINKS/RPT_LINKS.  We show them, but do not invent a mode or mark them
    restore-eligible.
    """
    seen = {str(e.get("node") or "") for e in entries}
    out = list(entries)
    for ident, info in directions.items():
        if ident in seen:
            continue
        state = str(info.get("state") or "").upper()
        if state and state != "ESTABLISHED":
            continue
        out.append({
            "node": ident,
            "mode_code": "?",
            "mode": "Unknown",
            "keyed": False,
            "raw": ident,
            "xnode_only": True,
        })
    return out



def parse_blocked_nodes(node):
    records = astdb_records()
    cmd = run_asterisk(f"database show denylist/{node}", timeout=2.5)
    blocked = []
    if not cmd["ok"]:
        return blocked
    pat = re.compile(rf"^/denylist/{re.escape(str(node))}/(\d{{4,7}})\s*:\s*(.*)$")
    for raw in cmd["stdout"].splitlines():
        line = raw.strip()
        m = pat.match(line)
        if not m:
            continue
        remote, reason = m.groups()
        rec = records.get(remote) or {}
        blocked.append({
            "node": remote,
            "callsign": rec.get("callsign", ""),
            "reason": reason.strip(),
        })
    blocked.sort(key=lambda x: int(x["node"]))
    return blocked

def get_system_metrics():
    """Read optional system metrics without affecting existing node status."""
    try:
        import importlib.util
        path=APP_ROOT/'bin/asl3-node-manager-system-metrics.py'
        spec=importlib.util.spec_from_file_location('node_manager_system_metrics',path)
        if spec is None or spec.loader is None:return {}
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.collect()
    except Exception:
        return {}


def get_status(node):
    checked = datetime.now(timezone.utc).isoformat()
    vc = run_asterisk(f"rpt show variables {node}")
    cc = run_asterisk(f"rpt show channels {node}")
    xc = run_asterisk(f"rpt xnode {node}")
    variables = parse_variables(vc["stdout"])
    directions, controller = parse_xnode(xc["stdout"] if xc["ok"] else "")
    online = vc["ok"] and bool(variables)
    raw_adjacent = parse_adjacent_raw(variables.get("RPT_ALINKS", "0"))
    raw_adjacent = merge_xnode_only(raw_adjacent, directions)
    sawstat = fetch_sawstat(node)
    for entry in raw_adjacent:
        ident = str(entry.get("node") or "")
        if ident in sawstat:
            entry["keyed"] = bool(sawstat[ident].get("active"))
            entry["keyed_seconds"] = int(sawstat[ident].get("last", -1))
    adjacent = classify_adjacent(raw_adjacent, directions)
    adjacent.sort(key=lambda item: (0 if item.get("keyed") else 1, str(item.get("display_node") or item.get("node") or "").lower()))
    all_links = parse_all_links(variables.get("RPT_LINKS", "0"))
    channels = parse_channels(cc["stdout"])
    blocked_nodes = parse_blocked_nodes(node)
    errors = []
    if not vc["ok"]:
        errors.append(vc["stderr"] or vc["stdout"] or "Unable to read app_rpt variables")
    if not cc["ok"]:
        errors.append(cc["stderr"] or cc["stdout"] or "Unable to read app_rpt channels")
    if not xc["ok"]:
        errors.append(xc["stderr"] or xc["stdout"] or "Unable to read app_rpt xnode state")
    return {
        "ok": online,
        "read_only": False,
        "node": str(node),
        "checked_at": checked,
        "system_metrics": get_system_metrics(),
        "asterisk_online": vc["returncode"] != 125 and (vc["ok"] or cc["ok"]),
        "node_online": online,
        "rx_keyed": boolish(variables.get("RPT_RXKEYED", "0")),
        "tx_keyed": boolish(variables.get("RPT_TXKEYED", "0")),
        "external_tx_keyed": boolish(variables.get("RPT_ETXKEYED", "0")),
        "autopatch_up": boolish(variables.get("RPT_AUTOPATCHUP", "0")),
        "adjacent_link_count": len(adjacent),
        "reported_adjacent_link_count": intish(variables.get("RPT_NUMALINKS", len(adjacent)), len(adjacent)),
        "all_link_count": intish(variables.get("RPT_NUMLINKS", len(all_links)), len(all_links)),
        "adjacent_links": adjacent,
        "all_links": all_links,
        "blocked_nodes": blocked_nodes,
        "blocked_count": len(blocked_nodes),
        "channels": channels,
        "controller": controller,
        "variables": {
            k: variables.get(k)
            for k in (
                "RPT_RXKEYED",
                "RPT_TXKEYED",
                "RPT_ETXKEYED",
                "RPT_NUMLINKS",
                "RPT_LINKS",
                "RPT_NUMALINKS",
                "RPT_ALINKS",
                "RPT_AUTOPATCHUP",
            )
            if k in variables
        },
        "errors": errors,
    }


def state_word(value, yes="ENABLED", no="DISABLED"):
    if value is None:
        return "UNKNOWN"
    return yes if intish(value) == 1 else no


def pretty(status):
    controller = status.get("controller") or {}
    print(f"ASL3 Node Manager {app_version()}")
    print(f"Node: {status['node']}")
    print(f"Asterisk: {'ONLINE' if status['asterisk_online'] else 'OFFLINE'}")
    print(f"app_rpt node: {'ONLINE' if status['node_online'] else 'UNAVAILABLE'}")
    print(f"ASL3 system: {state_word(controller.get('sys_ena'))}")
    print(f"Linking: {state_word(controller.get('link_ena'))}")
    print(f"RX: {'KEYED' if status['rx_keyed'] else 'IDLE'}")
    print(f"TX: {'KEYED' if status['tx_keyed'] else 'IDLE'}")
    print(f"Direct links: {status['adjacent_link_count']}")
    print(f"All linked nodes: {status['all_link_count']}")
    print(f"Autopatch: {'UP' if status['autopatch_up'] else 'DOWN'}")
    print(f"Interface: {status['channels'].get('driver', 'Unknown')}")
    if status["adjacent_links"]:
        print("Connected direct links:")
        for link in status["adjacent_links"]:
            label = link.get("callsign") or link.get("display_node") or link.get("node") or "?"
            suffix = " KEYED" if link.get("keyed") else ""
            direction = link.get("direction", "UNKNOWN")
            print(
                f"  {label}  {link.get('mode_label', 'Unknown')}  {direction}  "
                f"[{link.get('restore_policy', '')}]{suffix}"
            )
    else:
        print("Connected direct links: none")
    if status["errors"]:
        print("Warnings:")
        for error in status["errors"]:
            print(f"  {error}")


def main():
    parser = argparse.ArgumentParser(description="ASL3 node status")
    parser.add_argument("--node", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+", args.node):
        print("ERROR: node must be numeric", file=sys.stderr)
        return 2
    status = get_status(args.node)
    if args.json:
        print(json.dumps(status, separators=(",", ":"), sort_keys=True), end="")
    else:
        pretty(status)
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
