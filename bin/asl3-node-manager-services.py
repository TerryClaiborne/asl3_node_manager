#!/usr/bin/env python3
"""Restricted root-side ASL3 services interface. Never accepts paths or shell commands from HTTP."""
import datetime,fcntl,json,os,pathlib,re,subprocess,sys,tempfile,tarfile,stat,shutil,time
BASE=pathlib.Path('/var/www/html/asl3_node_manager')
DATA=BASE/'run/dtmf_favorites.txt'
BACKUPS=pathlib.Path('/var/backups/asl3-node-manager/asl3-config')
OFFICIAL=pathlib.Path('/var/asl-backups')
MAX_FAVORITES=200
RESTORE_STAGING=pathlib.Path('/var/backups/asl3-node-manager/restore-staging')
RESTORE_LIMIT=512*1024*1024
RESTORE_SAFETY=pathlib.Path('/var/backups/asl3-node-manager/restore-safety')

def validate_node(req):
    """Require an exact match to the locally configured node for every action."""
    node=req.get('node')
    if not isinstance(node,str) or not re.fullmatch(r'[0-9]{1,7}',node):
        raise ValueError('Invalid configured-node request.')
    config=BASE/'config.ini'
    if not config.is_file() or config.is_symlink():
        raise ValueError('Node Manager configuration unavailable.')
    configured=None
    for line in config.read_text(encoding='utf-8').splitlines():
        match=re.fullmatch(r'\s*MYNODE\s*=\s*["\']?([0-9]{1,7})["\']?\s*(?:[;#].*)?',line)
        if match:
            if configured is not None: raise ValueError('Duplicate MYNODE configuration.')
            configured=match.group(1)
    if configured is None or node!=configured:
        raise ValueError('Requested node does not match MYNODE.')
    return node

def execute(args,timeout=30):
    try:
        r=subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)
    except subprocess.TimeoutExpired:
        raise ValueError('Operation timed out; check the service status before retrying.')
    if r.returncode: raise ValueError((r.stderr or r.stdout or 'Command failed').strip()[:500])
    return r.stdout.strip()

def fav_load():
    if not DATA.is_file(): return []
    if DATA.is_symlink(): raise ValueError('Favorites file is not safe.')
    result=[]
    for ln in DATA.read_text(encoding='utf-8').splitlines():
        code,sep,name=ln.partition('|')
        if re.fullmatch(r'[0-9*#]{1,14}',code):result.append({'code':code,'name':name[:64] or code})
    return sorted(result,key=lambda x:(x['name'].casefold(),x['code']))[:MAX_FAVORITES]

def fav_write(items):
    DATA.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.dtmf-',dir=str(DATA.parent),text=True)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(''.join(f"{i['code']}|{i['name']}\n" for i in items));out.flush();os.fsync(out.fileno())
        os.replace(name,DATA)
    finally:
        if os.path.exists(name):os.unlink(name)

def backups():
    if not BACKUPS.is_dir():return []
    items=[]
    for f in sorted(BACKUPS.iterdir(),reverse=True):
        if re.fullmatch(r'ASL3-config-\d{4}-\d{2}-\d{2}-T\d{6}Z\.tar\.gz',f.name) and f.is_file() and not f.is_symlink():
            items.append({'name':f.name,'bytes':f.stat().st_size,'created':datetime.datetime.fromtimestamp(f.stat().st_mtime,datetime.timezone.utc).isoformat()})
    return items[:100]

def official_backups():
    if not OFFICIAL.is_dir(): return []
    result=[]
    for f in sorted(OFFICIAL.iterdir(),reverse=True):
        if not re.fullmatch(r'ASL_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.tgz',f.name): continue
        if not f.is_file() or f.is_symlink(): continue
        st=f.stat()
        result.append({'name':f.name,'bytes':st.st_size,'created':datetime.datetime.fromtimestamp(st.st_mtime,datetime.timezone.utc).isoformat()})
    return result[:100]

def backup_create():
    BACKUPS.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(BACKUPS,0o700)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-T%H%M%SZ')
    final=BACKUPS/f'ASL3-config-{stamp}.tar.gz'
    if final.exists():raise ValueError('A backup was already created this second; try again.')
    sources=[x for x in ['/etc/asterisk','/etc/allstarlink','/var/lib/asterisk'] if pathlib.Path(x).is_dir()]
    if '/etc/asterisk' not in sources:raise ValueError('Asterisk configuration directory is missing.')
    fd,tmp=tempfile.mkstemp(prefix='.creating-',suffix='.tar.gz',dir=str(BACKUPS))
    os.close(fd);os.chmod(tmp,0o600)
    try:
        # tar -C / stores relative names without unsafe absolute paths.
        execute(['/usr/bin/tar','--create','--gzip','--acls','--xattrs','--xattrs-include=*','--numeric-owner','--file',tmp,'--directory=/','--']+[s.lstrip('/') for s in sources],timeout=180)
        execute(['/usr/bin/tar','--list','--gzip','--file',tmp],timeout=120)
        execute(['/usr/bin/gzip','--test',tmp],timeout=120)
        os.replace(tmp,final);os.chmod(final,0o600)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {'name':final.name,'backups':backups(),'message':'Backup created and archive listing verified. Live databases may change during capture.'}

def restore_archive(source,name):
    if source=='manager':
        if not re.fullmatch(r'ASL3-config-\d{4}-\d{2}-\d{2}-T\d{6}Z\.tar\.gz',name): raise ValueError('Invalid Node Manager archive name.')
        base=BACKUPS
    elif source=='official':
        if not re.fullmatch(r'ASL_\d{4}-\d{2}-\d{2}_\d{4}\.tgz',name): raise ValueError('Invalid official archive name.')
        base=OFFICIAL
    else: raise ValueError('Invalid archive source.')
    path=base/name
    if not path.is_file() or path.is_symlink(): raise ValueError('Archive is unavailable.')
    return path

def allowed_restore_path(path,source):
    # This tool restores Asterisk only; other official ASL3 menu selections remain untouched.
    groups=('etc/asterisk/','var/lib/asterisk/','etc/allstarlink/')
    if source=='manager':return any(path==g[:-1] or path.startswith(g) for g in groups)
    return (path=='etc/asterisk' or path.startswith('etc/asterisk/') or
            path=='var/lib/asterisk/astdb.sqlite3' or path=='etc/sa818.conf' or
            path=='var/asl-backups/asl-backup-files' or
            path=='etc/allmon3' or path.startswith('etc/allmon3/'))

def preflight_restore(source,name):
    path=restore_archive(source,name)
    execute(['/usr/bin/gzip','--test',str(path)],timeout=120)
    included=[];excluded=[];size=0;types={'files':0,'dirs':0}; seen=set()
    with tarfile.open(path,'r:gz') as tf:
        for member in tf:
            n=member.name
            # Never extract absolute/traversal paths or links/devices from untrusted archives.
            parts=n.rstrip('/').split('/')
            if not n or n.startswith('/') or '\\' in n or any(x in ('','.','..') for x in parts):
                raise ValueError('Archive contains an unsafe path: '+n[:120])
            if not (member.isfile() or member.isdir()):
                raise ValueError('Restore archive contains a link or special entry; live restore is blocked: '+n[:120])
            if n in seen:raise ValueError('Archive contains duplicate names: '+n[:120])
            seen.add(n)
            if allowed_restore_path(n,source):
                included.append(n)
                size+=member.size
                if size>RESTORE_LIMIT:raise ValueError('Restore exceeds 512 MB safety limit.')
                types['files' if member.isfile() else 'dirs']+=1
            else: excluded.append(n)
    if not included or not any(x.startswith('etc/asterisk/') for x in included):
        raise ValueError('No supported Asterisk configuration files in archive.')
    if source=='manager' and excluded:raise ValueError('Unexpected files in Node Manager archive.')
    return path,included,excluded,types

def guard_existing_paths(names):
    for n in names:
        current=pathlib.Path('/')
        for part in n.split('/'):
            current=current/part
            if current.is_symlink():raise ValueError('Existing restore path contains a symlink: '+str(current))

def stage_restore(source,name):
    archive,included,excluded,types=preflight_restore(source,name)
    guard_existing_paths(included)
    RESTORE_STAGING.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(RESTORE_STAGING,0o700)
    stage=pathlib.Path(tempfile.mkdtemp(prefix='preview-',dir=RESTORE_STAGING))
    os.chmod(stage,0o700)
    try:
        # Extract validated members to an isolated directory, never to the live filesystem.
        execute(['/usr/bin/tar','--extract','--gzip','--no-same-owner','--no-recursion','--file',str(archive),'--directory',str(stage),'--']+included,timeout=180)
        for n in included:
            candidate=stage/n
            if not candidate.exists() or candidate.is_symlink():raise ValueError('Restore preview did not materialize safely: '+n)
        return {'message':f'Preflight passed: {len(included)} entries extracted safely to isolated staging; {len(excluded)} unsupported official entries excluded. Live files unchanged.',
                'included':len(included),'excluded':len(excluded),'files':types['files'],'directories':types['dirs'],
                'warning':'This is a preview only. No active configuration was overwritten or restarted.'}
    finally:
        shutil.rmtree(stage)

def live_restore(source,name):
    """Restore selected entries under a preserved, verified rollback snapshot.

    Never replace Asterisk's database while the service is running.
    """
    import hashlib
    archive,included,excluded,types=preflight_restore(source,name)
    if excluded:
        raise ValueError('Archive contains unsupported files; live restore refused.')
    guard_existing_paths(included)
    RESTORE_SAFETY.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(RESTORE_SAFETY,0o700)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    safety=RESTORE_SAFETY/f'BEFORE-RESTORE-{stamp}-{os.getpid()}.tar.gz'
    # Include the full contents of any existing directory we might modify.
    # Never use --no-recursion for the safety archive: it would save empty
    # directory entries and make rollback appear successful while losing files.
    selected_roots=['etc/asterisk','var/lib/asterisk','etc/allstarlink'] if source=='manager' else [
        'etc/asterisk','var/lib/asterisk/astdb.sqlite3','etc/sa818.conf',
        'var/asl-backups/asl-backup-files','etc/allmon3']
    existing_roots=[x for x in selected_roots if pathlib.Path('/'+x).exists()]
    if 'etc/asterisk' not in existing_roots:
        raise ValueError('Existing Asterisk configuration unavailable.')
    guard_existing_paths(existing_roots)
    preexisting={n for n in included if pathlib.Path('/'+n).exists()}
    newly_created=[n for n in included if n not in preexisting]
    def fingerprint():
        result={}
        for n in included:
            f=pathlib.Path('/'+n)
            if n not in preexisting:
                result[n]=None
            elif f.is_file():
                st=f.stat()
                with f.open('rb') as inp:
                    h=hashlib.file_digest(inp,'sha256').hexdigest()
                result[n]=('file',h,st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode),st.st_mtime_ns)
            elif f.is_dir():
                st=f.stat()
                result[n]=('dir',st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode))
            else:
                raise ValueError('Unexpected existing file type: '+n)
        return result
    def active():
        return subprocess.run(['/usr/bin/systemctl','is-active','--quiet','asterisk'],timeout=15).returncode==0
    if not active():
        raise ValueError('Asterisk is not active; restore refused until service health is checked.')
    # User-controlled content in names remains constrained to the archive allowlist.
    stopped=False; safety_ready=False
    try:
        execute(['/usr/bin/systemctl','stop','asterisk'],timeout=90)
        stopped=True
        if active():raise ValueError('Asterisk did not stop; refusing to overwrite configuration.')
        guard_existing_paths(included)
        before=fingerprint()
        execute(['/usr/bin/tar','--create','--gzip','--acls','--xattrs','--xattrs-include=*',
                 '--numeric-owner','--directory=/','--file',str(safety),'--']+existing_roots,timeout=180)
        os.chmod(safety,0o600)
        execute(['/usr/bin/gzip','--test',str(safety)],timeout=120)
        execute(['/usr/bin/tar','--list','--gzip','--file',str(safety)],timeout=120)
        # Ensure the safety backup really includes each pre-existing target.
        with tarfile.open(safety,'r:gz') as tf:
            backed=set(tf.getnames())
        missing=[n for n in preexisting if n not in backed]
        if missing:raise ValueError('Safety backup incomplete: '+', '.join(missing[:3]))
        safety_ready=True
        execute(['/usr/bin/tar','--extract','--gzip','--same-owner','--same-permissions',
                 '--acls','--xattrs','--xattrs-include=*','--no-recursion',
                 '--directory=/','--file',str(archive),'--']+included,timeout=180)
        execute(['/usr/bin/systemctl','start','asterisk'],timeout=90)
        if not active():raise ValueError('Asterisk did not return to active state.')
        return {'message':f'Restored {len(included)} entries from {name}; Asterisk is active. Safety backup: {safety.name}.',
                'safety_backup':str(safety),'restored_entries':len(included),'excluded_entries':len(excluded)}
    except Exception as exc:
        if stopped:
            try:
                # Always stop again: systemctl start may have succeeded even
                # if a later service health check failed.
                execute(['/usr/bin/systemctl','stop','asterisk'],timeout=90)
                if active():raise ValueError('Asterisk still active; rollback files not touched.')
                if safety_ready:
                    for n in sorted(newly_created,key=lambda x:(-x.count('/'),x)):
                        f=pathlib.Path('/'+n)
                        if f.is_symlink():raise ValueError('New restore path became a symlink: '+n)
                        if f.is_file():f.unlink()
                        elif f.is_dir():
                            try:f.rmdir()
                            except OSError:pass
                    execute(['/usr/bin/tar','--extract','--gzip','--same-owner',
                             '--same-permissions','--acls','--xattrs','--xattrs-include=*',
                             '--directory=/','--file',str(safety)],timeout=180)
                    after=fingerprint()
                    if before!=after:
                        raise ValueError('Rollback file verification mismatch; manual recovery required.')
                execute(['/usr/bin/systemctl','start','asterisk'],timeout=90)
                if not active():raise ValueError('Asterisk not active after recovery.')
            except Exception as rollback_error:
                # Do not claim recovery. Make a best-effort service start but
                # clearly report that the configuration may require manual repair.
                service_note=''
                try:
                    if not active():
                        execute(['/usr/bin/systemctl','start','asterisk'],timeout=90)
                    service_note=' Asterisk ACTIVE.' if active() else ' Asterisk NOT ACTIVE.'
                except Exception as restart_error:
                    service_note=f' Asterisk restart also failed: {restart_error}'
                raise ValueError(f'URGENT: restore/recovery failed. Safety archive: {safety}. Details: {rollback_error}.{service_note}') from exc
            if safety_ready:
                raise ValueError(f'Restore failed; safety rollback VERIFIED and Asterisk ACTIVE. Reason: {exc}') from exc
            raise ValueError(f'Restore not performed; Asterisk restarted. Safety backup preparation failed: {exc}') from exc
        raise

def handle(r):
    validate_node(r)
    action=r.get('action','')
    if action=='list':return {'favorites':fav_load(),'backups':backups(),'official_backups':official_backups(),'services':{x:execute(['/usr/bin/systemctl','is-active',x]) if subprocess.run(['/usr/bin/systemctl','is-active','--quiet',x]).returncode==0 else 'inactive' for x in ['asterisk','apache2']}}
    if action=='favorite-save':
        code=r.get('code','');original=r.get('original_code','');name=r.get('name','')
        if not isinstance(code,str) or not re.fullmatch(r'[0-9*#]{1,14}',code):raise ValueError('Invalid DTMF code (1–14 digits, * or #).')
        if not isinstance(original,str) or (original and not re.fullmatch(r'[0-9*#]{1,14}',original)):raise ValueError('Invalid original code.')
        if not isinstance(name,str):raise ValueError('Invalid name.')
        name=' '.join(name.replace('|',' ').split())[:64] or code
        items=fav_load();items=[x for x in items if x['code']!=original] if original else items
        items=[x for x in items if x['code']!=code];items.append({'code':code,'name':name})
        if len(items)>MAX_FAVORITES:raise ValueError('Favorites limit reached.')
        fav_write(sorted(items,key=lambda x:(x['name'].casefold(),x['code'])))
        return {'favorites':fav_load(),'message':'Favorite saved.'}
    if action=='favorite-delete':
        code=r.get('code','');
        if not isinstance(code,str) or not re.fullmatch(r'[0-9*#]{1,14}',code):raise ValueError('Invalid code.')
        fav_write([x for x in fav_load() if x['code']!=code]);return {'favorites':fav_load(),'message':'Favorite removed.'}
    if action=='dtmf-send':
        code=r.get('code','');node=r['node']
        if not isinstance(code,str) or not re.fullmatch(r'[0-9*#]{1,14}',code) or not re.fullmatch(r'[0-9]{1,7}',node):raise ValueError('Invalid DTMF request.')
        execute(['/usr/sbin/asterisk','-rx',f'rpt fun {node} {code}'],timeout=15)
        return {'message':'DTMF command sent to Asterisk.'}
    if action=='official-backup-verify':
        name=r.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'ASL_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.tgz',name):raise ValueError('Invalid official backup name.')
        f=OFFICIAL/name
        if not f.is_file() or f.is_symlink():raise ValueError('Official ASL3 backup unavailable.')
        execute(['/usr/bin/tar','--list','--gzip','--file',str(f)],timeout=120)
        execute(['/usr/bin/gzip','--test',str(f)],timeout=120)
        return {'message':'Official ASL3 backup integrity checked. Restore remains disabled.'}
    if action=='official-backup-delete':
        name=r.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'ASL_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.tgz',name):
            raise ValueError('Invalid official ASL3 backup name.')
        # This action only removes the named archive; never an asl-menu manifest,
        # a directory, a symlink or a Node Manager safety backup.
        f=OFFICIAL/name
        if not f.is_file() or f.is_symlink():raise ValueError('Official ASL3 backup unavailable or unsafe.')
        f.unlink()
        return {'official_backups':official_backups(),'message':'Official ASL3 backup deleted: '+name}
    if action=='backup-create':return backup_create()
    if action=='backup-delete':
        name=r.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'ASL3-config-\d{4}-\d{2}-\d{2}-T\d{6}Z\.tar\.gz',name):
            raise ValueError('Invalid Node Manager backup name.')
        # The directory is root-owned; no arbitrary paths, official backups or safety snapshots.
        f=BACKUPS/name
        if f.is_symlink() or not f.is_file():raise ValueError('Backup unavailable or unsafe.')
        f.unlink()
        return {'backups':backups(),'message':'Node Manager backup deleted: '+name}

    if action=='restore-live':
        source=r.get('source','');name=r.get('name','')
        if not isinstance(source,str) or not isinstance(name,str) or r.get('confirmation')!='RESTORE':
            raise ValueError('Restore confirmation missing.')
        return live_restore(source,name)
    if action=='restore-preview':
        source=r.get('source','');name=r.get('name','')
        if not isinstance(source,str) or not isinstance(name,str):raise ValueError('Invalid restore request.')
        return stage_restore(source,name)
    if action=='backup-verify':
        name=r.get('name','')
        if not isinstance(name,str) or not re.fullmatch(r'ASL3-config-\d{4}-\d{2}-\d{2}-T\d{6}Z\.tar\.gz',name):raise ValueError('Invalid backup name.')
        f=BACKUPS/name
        if not f.is_file() or f.is_symlink():raise ValueError('Backup unavailable.')
        execute(['/usr/bin/tar','--list','--gzip','--file',str(f)],timeout=120)
        execute(['/usr/bin/gzip','--test',str(f)],timeout=120)
        return {'message':'Archive verified: tar listing and gzip integrity passed.'}
    commands={'asterisk-reload':['/usr/sbin/asterisk','-rx','core reload'], 'app-rpt-reload':['/usr/sbin/asterisk','-rx','module reload app_rpt.so'], 'asterisk-restart':['/usr/bin/systemctl','restart','asterisk'], 'apache-reload':['/usr/bin/systemctl','reload','apache2']}
    if action in commands:
        execute(commands[action],timeout=90);return {'message':f'{action.replace("-"," ").title()} command completed.'}
    if action=='apache-restart':
        # systemd-run schedules outside the Apache/PHP request lifetime.
        execute(['/usr/bin/systemd-run','--quiet','--unit=asl3-manager-apache-restart-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'--on-active=3s','/usr/bin/systemctl','restart','apache2'],timeout=10)
        return {'message':'Apache restart queued; the dashboard may briefly disconnect.'}
    raise ValueError('Unsupported Services action.')

def main():
    try:
        req=json.load(sys.stdin)
        if not isinstance(req,dict):raise ValueError('Request must be an object.')
        lock=BASE/'run/services.lock';lock.parent.mkdir(exist_ok=True)
        with open(lock,'a+') as lf:
            fcntl.flock(lf,fcntl.LOCK_EX)
            result=handle(req)
        print(json.dumps({'ok':True,**result}))
    except (ValueError,OSError,TypeError) as e:
        print(json.dumps({'ok':False,'message':str(e)[:500]}));sys.exit(1)
if __name__=='__main__':main()
