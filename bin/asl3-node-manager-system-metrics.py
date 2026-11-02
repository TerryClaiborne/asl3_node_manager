#!/usr/bin/env python3
"""Root-side, read-only, bounded cached system metrics for Node Manager Status."""
import datetime
import fcntl
import ipaddress
import json
import os
import pathlib
import stat
import socket
import tempfile
import time

ROOT=pathlib.Path('/var/www/html/asl3_node_manager/run')
STATE=ROOT/'system_metrics.json'
LOCK=ROOT/'locks/system_metrics.lock'
INTERVAL=5.0

def read_text(path):
    try:return pathlib.Path(path).read_text(encoding='utf-8',errors='replace')
    except (OSError,ValueError):return ''

def cpu_ticks():
    line=read_text('/proc/stat').splitlines()[0].split()
    if not line or line[0]!='cpu':return None
    nums=[int(x) for x in line[1:]]
    total=sum(nums)
    idle=nums[3]+(nums[4] if len(nums)>4 else 0)
    return [total,idle]

def memory():
    values={}
    for line in read_text('/proc/meminfo').splitlines():
        if ':' not in line:continue
        key,val=line.split(':',1)
        try:values[key]=int(val.split()[0])*1024
        except (IndexError,ValueError):pass
    total=values.get('MemTotal',0)
    if not total:return None
    avail=values.get('MemAvailable',values.get('MemFree',0))
    return {'used':max(0,total-avail),'total':total}

def network():
    result={}
    for line in read_text('/proc/net/dev').splitlines()[2:]:
        if ':' not in line:continue
        name,raw=line.split(':',1)
        name=name.strip()
        if name=='lo' or name.startswith(('veth','docker','br-','virbr','tailscale','tun','tap')):continue
        parts=raw.split()
        if len(parts)<16:continue
        try:result[name]=[int(parts[0]),int(parts[8])]
        except ValueError:pass
    return result

def lan_ip():
    # UDP connect assigns local route without sending a packet.
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1',80))
            addr=sock.getsockname()[0]
            if not ipaddress.ip_address(addr).is_loopback:return addr
    except (OSError,ValueError):pass
    return None

def temperature_f():
    base=pathlib.Path('/sys/class/thermal')
    try:paths=sorted(base.glob('thermal_zone*/temp'))
    except OSError:return None
    # CPU thermal zone usually occurs first on Raspberry Pi.
    for path in paths:
        try:
            raw=float(path.read_text().strip())
            c=raw/1000 if abs(raw)>1000 else raw
            if -40<=c<=150:return round(c*9/5+32,1)
        except (OSError,ValueError):pass
    return None

def uptime_seconds():
    try:return int(float(read_text('/proc/uptime').split()[0]))
    except (ValueError,IndexError):return None

def disk(path):
    try:
        st=os.statvfs(path)
        total=st.f_blocks*st.f_frsize
        used=(st.f_blocks-st.f_bfree)*st.f_frsize
        return round(100*used/total,1) if total else None
    except OSError:return None

def get_previous():
    try:
        st=STATE.lstat()
        if not stat.S_ISREG(st.st_mode):return {}
        with STATE.open('r',encoding='utf-8') as fp:
            value=json.load(fp)
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,json.JSONDecodeError):return {}

def write_state(value):
    fd,tmp=tempfile.mkstemp(prefix='.system-metrics-',dir=str(ROOT))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as fp:
            json.dump(value,fp,separators=(',',':'))
            fp.flush();os.fsync(fp.fileno())
        os.replace(tmp,STATE)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def collect():
    now=time.monotonic()
    # Locks prevent overlapping one-second polls from racing cache updates.
    ROOT.joinpath('locks').mkdir(parents=True,exist_ok=True)
    fd=os.open(LOCK,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        prev=get_previous()
        last=prev.get('monotonic',-1)
        if isinstance(last,(float,int)) and 0<=now-last<INTERVAL and isinstance(prev.get('metrics'),dict):
            return prev['metrics']
        ticks=cpu_ticks()
        counters=network()
        delta=now-last if isinstance(last,(float,int)) else 0
        cpu=None
        old_ticks=prev.get('ticks')
        if ticks and isinstance(old_ticks,list) and len(old_ticks)==2:
            total=ticks[0]-old_ticks[0];idle=ticks[1]-old_ticks[1]
            if total>0 and 0<=idle<=total:cpu=round(100*(total-idle)/total,1)
        inbound=outbound=None
        old_net=prev.get('net')
        if delta>0 and isinstance(old_net,dict):
            common=set(counters).intersection(old_net)
            rx=tx=0
            for key in common:
                try:
                    dr=counters[key][0]-old_net[key][0];dt=counters[key][1]-old_net[key][1]
                    if dr>=0 and dt>=0:rx+=dr;tx+=dt
                except (ValueError,TypeError,IndexError):pass
            if common:inbound=round(rx/delta,1);outbound=round(tx/delta,1)
        metrics={
            'lan_ip':lan_ip(),
            'utc_time':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'cpu_percent':cpu,
            'memory':memory(),
            'network_up_bps':outbound,
            'network_down_bps':inbound,
            'temperature_f':temperature_f(),
            'uptime_seconds':uptime_seconds(),
            'root_disk_percent':disk('/'),
            'apache_disk_percent':disk('/var/log/apache2'),
        }
        write_state({'monotonic':now,'ticks':ticks,'net':counters,'metrics':metrics})
        return metrics
    finally:
        os.close(fd)

if __name__=='__main__':print(json.dumps(collect(),separators=(',',':')))
