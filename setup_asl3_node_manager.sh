#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="ASL3 Node Manager"
APP_DIR="/var/www/html/asl3_node_manager"
CONFIG="$APP_DIR/config.ini"
HELPER_DST="/usr/local/libexec/asl3-node-manager-helper"
SUDOERS="/etc/sudoers.d/asl3-node-manager"
APACHE_NAME="asl3-node-manager"
APACHE_CONF="/etc/apache2/conf-available/${APACHE_NAME}.conf"
APACHE_ENABLED="/etc/apache2/conf-enabled/${APACHE_NAME}.conf"
POLLING_NAME="asl3-node-manager-polling"
POLLING_CONF="/etc/apache2/conf-available/${POLLING_NAME}.conf"
POLLING_ENABLED="/etc/apache2/conf-enabled/${POLLING_NAME}.conf"
BACKUP_ROOT="/var/backups/asl3-node-manager"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_OVERRIDE=""
SET_PASSWORD=0
DISABLE_AUTH=0
ENABLE_AUTH=0
UNINSTALL=0
PASSWORD_HASH=""
COMMITTED=0
BACKUP_DIR=""
APACHE_GUARD_BEFORE=""
APACHE_GUARD_AFTER=""

usage(){ cat <<EOF2
Usage: sudo $0 [--node NODE] [--set-admin-password] [--disable-auth] [--enable-auth] [--uninstall]

Installs/updates ASL3 Node Manager without modifying rpt.conf or restarting Asterisk.
--uninstall creates a protected backup, removes only Node Manager integration, and
leaves unrelated Apache filters/configuration untouched.
EOF2
}

die(){ echo "ERROR: $*" >&2; return 1; }

while (($#)); do
  case "$1" in
    --node) shift; [[ $# -gt 0 ]] || die "--node requires a value"; NODE_OVERRIDE="$1" ;;
    --set-admin-password) SET_PASSWORD=1 ;;
    --disable-auth) DISABLE_AUTH=1 ;;
    --enable-auth) ENABLE_AUTH=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "run with sudo/root"
[[ -z "$NODE_OVERRIDE" || "$NODE_OVERRIDE" =~ ^[0-9]+$ ]] || die "--node must be numeric"
(( DISABLE_AUTH + ENABLE_AUTH <= 1 )) || die "--disable-auth and --enable-auth are mutually exclusive"
(( SET_PASSWORD + DISABLE_AUTH <= 1 )) || die "--set-admin-password and --disable-auth cannot be used together"
if (( UNINSTALL == 1 )) && (( SET_PASSWORD + DISABLE_AUTH + ENABLE_AUTH > 0 )) ; then
  die "--uninstall cannot be combined with authentication options"
fi

for cmd in php python3 apache2ctl visudo sha256sum tar awk sed grep find install timeout cmp a2enconf a2disconf systemctl sort xargs; do
  command -v "$cmd" >/dev/null || die "required command missing: $cmd"
done

apache_guard_snapshot(){
  local out="$1"
  {
    find /etc/apache2/conf-available -maxdepth 1 -type f -name '*polling.conf' ! -name "${POLLING_NAME}.conf" -print0 2>/dev/null |
      sort -z | xargs -0 -r sha256sum
    find /etc/apache2/sites-available -maxdepth 1 -type f -name '*.conf' -print0 2>/dev/null |
      sort -z | xargs -0 -r sha256sum
  } | sort > "$out"
}

verify_apache_guard(){
  APACHE_GUARD_AFTER="$(mktemp)"
  apache_guard_snapshot "$APACHE_GUARD_AFTER"
  if ! cmp -s "$APACHE_GUARD_BEFORE" "$APACHE_GUARD_AFTER"; then
    echo "[ERROR] An unrelated Apache polling/site configuration changed during setup." >&2
    diff -u "$APACHE_GUARD_BEFORE" "$APACHE_GUARD_AFTER" >&2 || true
    return 1
  fi
}

# Fast password-only path when invoked from the installed application.
# This changes only config.ini, creates a focused backup, and avoids rerunning the installer.
if (( SET_PASSWORD == 1 )) && [[ "$SOURCE_DIR" == "$APP_DIR" ]] && [[ -f "$CONFIG" ]] && [[ -z "$NODE_OVERRIDE" ]] && (( DISABLE_AUTH == 0 && ENABLE_AUTH == 0 && UNINSTALL == 0 )); then
  read -r -s -p "New admin password: " P1; echo
  read -r -s -p "Confirm admin password: " P2; echo
  [[ -n "$P1" ]] || die "password cannot be empty"
  [[ "$P1" == "$P2" ]] || die "passwords do not match"
  PASSWORD_HASH="$(php -r 'echo password_hash($argv[1], PASSWORD_DEFAULT);' "$P1")"
  unset P1 P2
  [[ -n "$PASSWORD_HASH" ]] || die "password hash creation failed"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  PASS_BACKUP="$BACKUP_ROOT/password-$STAMP"
  mkdir -p "$PASS_BACKUP"
  cp -a "$CONFIG" "$PASS_BACKUP/config.ini"
  python3 - "$CONFIG" "$PASSWORD_HASH" <<'PY2'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); h=sys.argv[2]; s=p.read_text(encoding='utf-8')
def setv(name,value):
    global s
    pat=rf'^{re.escape(name)}=.*$'; line=f'{name}={value}'
    s=re.sub(pat,line,s,count=1,flags=re.M) if re.search(pat,s,flags=re.M) else s.rstrip()+"\n"+line+"\n"
setv('ASL3_NODE_MANAGER_ADMIN_USER','"admin"')
setv('ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH',f'"{h}"')
setv('ASL3_NODE_MANAGER_AUTH_ENABLED','1')
p.write_text(s,encoding='utf-8')
PY2
  chown root:www-data "$CONFIG"; chmod 0640 "$CONFIG"
  php -r '$c=parse_ini_file($argv[1],false,INI_SCANNER_RAW); if(!is_array($c)||trim((string)($c["ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH"]??""))===""||((string)($c["ASL3_NODE_MANAGER_AUTH_ENABLED"]??"0"))!=="1")exit(1);' "$CONFIG" || die "updated login configuration could not be verified"
  echo
  echo "[OK] ASL3 Node Manager administrator password set."
  echo "Application login: ENABLED (user: admin)"
  echo "Protected config backup: $PASS_BACKUP/config.ini"
  exit 0
fi

APACHE_GUARD_BEFORE="$(mktemp)"
apache_guard_snapshot "$APACHE_GUARD_BEFORE"

cleanup_temps(){
  [[ -n "$APACHE_GUARD_BEFORE" ]] && rm -f "$APACHE_GUARD_BEFORE" || true
  [[ -n "$APACHE_GUARD_AFTER" ]] && rm -f "$APACHE_GUARD_AFTER" || true
}

if (( UNINSTALL == 1 )); then
  if [[ ! -d "$APP_DIR" && ! -e "$HELPER_DST" && ! -e "$SUDOERS" && ! -e "$APACHE_CONF" && ! -e "$POLLING_CONF" ]]; then
    cleanup_temps
    echo "[OK] ASL3 Node Manager is not installed."
    exit 0
  fi
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_DIR="$BACKUP_ROOT/uninstall-$STAMP"
  mkdir -p "$BACKUP_DIR/system"
  [[ -d "$APP_DIR" ]] && tar -C "$(dirname "$APP_DIR")" -czf "$BACKUP_DIR/app.tar.gz" "$(basename "$APP_DIR")"
  [[ -e "$HELPER_DST" ]] && cp -a "$HELPER_DST" "$BACKUP_DIR/system/helper"
  [[ -e "$SUDOERS" ]] && cp -a "$SUDOERS" "$BACKUP_DIR/system/sudoers"
  [[ -e "$APACHE_CONF" ]] && cp -a "$APACHE_CONF" "$BACKUP_DIR/system/apache.conf"
  [[ -e "$POLLING_CONF" ]] && cp -a "$POLLING_CONF" "$BACKUP_DIR/system/polling.conf"
  [[ -L "$APACHE_ENABLED" || -e "$APACHE_ENABLED" ]] && echo 1 > "$BACKUP_DIR/system/apache-enabled" || echo 0 > "$BACKUP_DIR/system/apache-enabled"
  [[ -L "$POLLING_ENABLED" || -e "$POLLING_ENABLED" ]] && echo 1 > "$BACKUP_DIR/system/polling-enabled" || echo 0 > "$BACKUP_DIR/system/polling-enabled"

  # Uninstall rollback: restore only Node Manager's own integration.
  uninstall_rollback(){
    local rc=$?
    trap - ERR
    set +e
    echo "[ERROR] Uninstall failed; restoring protected installation." >&2
    local failed=0

    if [[ -f "$BACKUP_DIR/app.tar.gz" ]]; then
      rm -rf "$APP_DIR" || failed=1
      tar -C "$(dirname "$APP_DIR")" -xzf "$BACKUP_DIR/app.tar.gz" || failed=1
    fi

    local entry target
    for entry in helper sudoers apache.conf polling.conf; do
      case "$entry" in
        helper) target="$HELPER_DST" ;;
        sudoers) target="$SUDOERS" ;;
        apache.conf) target="$APACHE_CONF" ;;
        polling.conf) target="$POLLING_CONF" ;;
      esac
      if [[ -f "$BACKUP_DIR/system/$entry" ]]; then
        cp -a "$BACKUP_DIR/system/$entry" "$target" || failed=1
      else
        rm -f "$target" || failed=1
      fi
    done

    if [[ "$(cat "$BACKUP_DIR/system/apache-enabled")" == 1 ]]; then
      a2enconf "$APACHE_NAME" >/dev/null 2>&1 || failed=1
    else
      a2disconf "$APACHE_NAME" >/dev/null 2>&1 || failed=1
    fi

    if [[ "$(cat "$BACKUP_DIR/system/polling-enabled")" == 1 ]]; then
      a2enconf "$POLLING_NAME" >/dev/null 2>&1 || failed=1
    else
      a2disconf "$POLLING_NAME" >/dev/null 2>&1 || failed=1
    fi

    apache2ctl configtest || failed=1
    if (( failed == 0 )); then
      systemctl reload apache2 || failed=1
    fi

    cleanup_temps
    if (( failed != 0 )); then
      echo "[ERROR] Automatic recovery incomplete; manual recovery required." >&2
    else
      echo "[OK] Previous Node Manager installation restored." >&2
    fi
    echo "Protected backup: $BACKUP_DIR" >&2
    exit "$rc"
  }
  trap uninstall_rollback ERR

  a2disconf "$POLLING_NAME" >/dev/null 2>&1 || true
  a2disconf "$APACHE_NAME" >/dev/null 2>&1 || true
  apache2ctl configtest >/dev/null
  systemctl reload apache2

  rm -f "$POLLING_CONF" "$POLLING_ENABLED" "$APACHE_CONF" "$APACHE_ENABLED" "$SUDOERS" "$HELPER_DST"
  rm -rf "$APP_DIR"
  apache2ctl configtest >/dev/null
  systemctl reload apache2
  verify_apache_guard
  trap - ERR
  cleanup_temps
  cat <<EOF2

[OK] ASL3 Node Manager uninstalled.
Protected uninstall backup: $BACKUP_DIR
EOF2
  exit 0
fi

command -v asterisk >/dev/null || die "Asterisk executable not found"
[[ -r /etc/asterisk/rpt.conf ]] || die "/etc/asterisk/rpt.conf not readable"
apache2ctl -M 2>/dev/null | grep -q 'setenvif_module' || die "Apache setenvif_module must already be enabled"

required=(
  VERSION README.md config.ini.example .gitignore tree.txt
  bin/asl3-node-manager-status.py bin/asl3-node-manager-control.py bin/asl3-node-manager-echolink.php
  bin/asl3-node-manager-appearance.php bin/asl3-node-manager-helper bin/asl3-node-manager
  bin/asl3-node-manager-services.py bin/asl3-node-manager-system-metrics.py public/services.php public/backup_download.php
  public/index.php public/status.php public/action.php public/login.php public/logout.php
  public/assets/app.js public/assets/style.css src/bootstrap.php src/auth.php
  src/NodeIdentity.php src/EchoLink.php src/CacheMaintenance.php
)
for file in "${required[@]}"; do [[ -f "$SOURCE_DIR/$file" ]] || die "source missing: $file"; done

for file in public/index.php public/status.php public/action.php public/login.php public/logout.php src/bootstrap.php src/auth.php src/NodeIdentity.php src/EchoLink.php src/CacheMaintenance.php bin/asl3-node-manager-echolink.php bin/asl3-node-manager-appearance.php public/services.php public/backup_download.php; do
  php -l "$SOURCE_DIR/$file" >/dev/null || die "PHP syntax failed: $file"
done
python3 -m py_compile "$SOURCE_DIR/bin/asl3-node-manager-status.py" "$SOURCE_DIR/bin/asl3-node-manager-control.py" "$SOURCE_DIR/bin/asl3-node-manager-services.py" "$SOURCE_DIR/bin/asl3-node-manager-system-metrics.py" || die "Python syntax failed"
rm -rf "$SOURCE_DIR/bin/__pycache__"
bash -n "$SOURCE_DIR/bin/asl3-node-manager-helper"
bash -n "$SOURCE_DIR/bin/asl3-node-manager"
bash -n "$SOURCE_DIR/setup_asl3_node_manager.sh"
if command -v node >/dev/null; then node --check "$SOURCE_DIR/public/assets/app.js" >/dev/null || die "JavaScript syntax failed"; fi

NODE="$NODE_OVERRIDE"
if [[ -z "$NODE" && -f "$CONFIG" ]]; then
  current="$(php -r '$c=@parse_ini_file($argv[1],false,INI_SCANNER_RAW); echo is_array($c)?trim((string)($c["MYNODE"]??"")):"";' "$CONFIG")"
  [[ "$current" =~ ^[0-9]+$ ]] && NODE="$current"
fi
if [[ -z "$NODE" ]]; then
  mapfile -t CANDIDATES < <(
    grep -RhoE '^\[[0-9]+\]' /etc/asterisk/rpt.conf /etc/asterisk/rpt.d /etc/asterisk/*.conf.d 2>/dev/null |
      tr -d '[]' | sort -un || true
  )
  VALID=()
  for candidate in "${CANDIDATES[@]}"; do
    if timeout 4 asterisk -rx "rpt show variables $candidate" 2>/dev/null | grep -q '^ *RPT_'; then VALID+=("$candidate"); fi
  done
  # ASL private nodes are numbered below 2000.
  PUBLIC=()
  for candidate in "${VALID[@]}"; do
    if (( 10#$candidate >= 2000 )); then
      PUBLIC+=("$candidate")
    fi
  done

  if (( ${#PUBLIC[@]} == 1 )); then
    NODE="${PUBLIC[0]}"
    echo "[INFO] Automatically selected public ASL node $NODE"
  elif (( ${#PUBLIC[@]} == 0 )); then
    die "No public app_rpt node detected; use --node NODE"
  else
    echo "Multiple public app_rpt nodes detected:"
    for i in "${!PUBLIC[@]}"; do
      printf '  %d) %s\n' "$((i+1))" "${PUBLIC[i]}"
    done
    [[ -t 0 ]] || die "Use --node NODE for unattended installation"
    while true; do
      read -r -p "Select public node [1-${#PUBLIC[@]}]: " choice || die "Node selection cancelled"
      if [[ "$choice" =~ ^[1-9][0-9]*$ ]] &&
         (( choice <= ${#PUBLIC[@]} )); then
        NODE="${PUBLIC[choice-1]}"
        break
      fi
      echo "Invalid selection."
    done
  fi
fi
if ! timeout 5 asterisk -rx "rpt show variables $NODE" 2>/dev/null | grep -q '^ *RPT_'; then
  die "Asterisk/app_rpt did not return runtime variables for node $NODE"
fi

# Node Manager is self-contained: the exact proven EchoLink resolver is bundled
# in this source tree and must validate before any live installation begins.
for file in NodeIdentity.php EchoLink.php CacheMaintenance.php; do
  php -l "$SOURCE_DIR/src/$file" >/dev/null || die "EchoLink resolver syntax failed: $file"
done
[[ "$(sha256sum "$SOURCE_DIR/src/NodeIdentity.php" | awk '{print $1}')" == "0f5b061e07c413c5aba7acd146ebbdc48b2a357b77594b40280b74af050409be" ]] || die "NodeIdentity.php is not the accepted resolver revision"
[[ "$(sha256sum "$SOURCE_DIR/src/EchoLink.php" | awk '{print $1}')" == "0f703613ed9a1dbcb0cd174ae1cdb1f1f2ef0e356ad6d2d2a280a65d45faaeca" ]] || die "EchoLink.php is not the accepted resolver revision"
[[ "$(sha256sum "$SOURCE_DIR/src/CacheMaintenance.php" | awk '{print $1}')" == "7c3f72f894dc161e0ff83d6cfccd6eaf0121a891175740a6e48779b7513964bc" ]] || die "CacheMaintenance.php is not the accepted resolver revision"

if (( SET_PASSWORD == 1 )); then
  read -r -s -p "New admin password: " P1; echo
  read -r -s -p "Confirm admin password: " P2; echo
  [[ -n "$P1" ]] || die "password cannot be empty"
  [[ "$P1" == "$P2" ]] || die "passwords do not match"
  PASSWORD_HASH="$(php -r 'echo password_hash($argv[1], PASSWORD_DEFAULT);' "$P1")"
  unset P1 P2
  [[ -n "$PASSWORD_HASH" ]] || die "password hash creation failed"
fi

if [[ -f "$CONFIG" ]]; then
  php -r '$c=parse_ini_file($argv[1],false,INI_SCANNER_RAW); if(!is_array($c))exit(1); $n=trim((string)($c["MYNODE"]??"")); if($n!==""&&!preg_match("/^\\d+$/",$n))exit(2);' "$CONFIG" || die "existing config.ini is invalid"
fi
if (( ENABLE_AUTH == 1 )) && [[ -z "$PASSWORD_HASH" ]]; then
  existing_hash=""
  [[ -f "$CONFIG" ]] && existing_hash="$(php -r '$c=@parse_ini_file($argv[1],false,INI_SCANNER_RAW); echo is_array($c)?trim((string)($c["ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH"]??"")):"";' "$CONFIG")"
  [[ -n "$existing_hash" ]] || die "--enable-auth requires a saved password; use --set-admin-password first"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$BACKUP_ROOT/setup-$STAMP"
mkdir -p "$BACKUP_DIR/system"
EXISTED_APP=0; EXISTED_HELPER=0; EXISTED_SUDOERS=0; EXISTED_APACHE=0; EXISTED_POLLING=0; WAS_APACHE_ENABLED=0; WAS_POLLING_ENABLED=0
[[ -d "$APP_DIR" ]] && EXISTED_APP=1
[[ -e "$HELPER_DST" ]] && EXISTED_HELPER=1
[[ -e "$SUDOERS" ]] && EXISTED_SUDOERS=1
[[ -e "$APACHE_CONF" ]] && EXISTED_APACHE=1
[[ -e "$POLLING_CONF" ]] && EXISTED_POLLING=1
[[ -L "$APACHE_ENABLED" || -e "$APACHE_ENABLED" ]] && WAS_APACHE_ENABLED=1
[[ -L "$POLLING_ENABLED" || -e "$POLLING_ENABLED" ]] && WAS_POLLING_ENABLED=1
(( EXISTED_APP == 1 )) && tar -C "$(dirname "$APP_DIR")" -czf "$BACKUP_DIR/app.tar.gz" "$(basename "$APP_DIR")"
(( EXISTED_HELPER == 1 )) && cp -a "$HELPER_DST" "$BACKUP_DIR/system/helper"
(( EXISTED_SUDOERS == 1 )) && cp -a "$SUDOERS" "$BACKUP_DIR/system/sudoers"
(( EXISTED_APACHE == 1 )) && cp -a "$APACHE_CONF" "$BACKUP_DIR/system/apache.conf"
(( EXISTED_POLLING == 1 )) && cp -a "$POLLING_CONF" "$BACKUP_DIR/system/polling.conf"
printf '%s\n' "$WAS_APACHE_ENABLED" > "$BACKUP_DIR/system/apache-enabled"
printf '%s\n' "$WAS_POLLING_ENABLED" > "$BACKUP_DIR/system/polling-enabled"
echo "[INFO] Protected previous installation: $BACKUP_DIR"

rollback(){
  local rc=$?
  if (( COMMITTED == 1 )); then return "$rc"; fi
  trap - ERR
  echo "[WARN] Installation failed; restoring protected pre-install state." >&2
  if (( EXISTED_APP == 1 )) && [[ -f "$BACKUP_DIR/app.tar.gz" ]]; then rm -rf "$APP_DIR"; tar -C "$(dirname "$APP_DIR")" -xzf "$BACKUP_DIR/app.tar.gz"; else rm -rf "$APP_DIR"; fi
  if (( EXISTED_HELPER == 1 )); then cp -a "$BACKUP_DIR/system/helper" "$HELPER_DST"; else rm -f "$HELPER_DST"; fi
  if (( EXISTED_SUDOERS == 1 )); then cp -a "$BACKUP_DIR/system/sudoers" "$SUDOERS"; else rm -f "$SUDOERS"; fi
  if (( EXISTED_APACHE == 1 )); then cp -a "$BACKUP_DIR/system/apache.conf" "$APACHE_CONF"; else rm -f "$APACHE_CONF"; fi
  if (( EXISTED_POLLING == 1 )); then cp -a "$BACKUP_DIR/system/polling.conf" "$POLLING_CONF"; else rm -f "$POLLING_CONF"; fi
  if (( WAS_APACHE_ENABLED == 1 )); then a2enconf "$APACHE_NAME" >/dev/null 2>&1 || true; else a2disconf "$APACHE_NAME" >/dev/null 2>&1 || true; fi
  if (( WAS_POLLING_ENABLED == 1 )); then a2enconf "$POLLING_NAME" >/dev/null 2>&1 || true; else a2disconf "$POLLING_NAME" >/dev/null 2>&1 || true; fi
  apache2ctl configtest >/dev/null 2>&1 && systemctl reload apache2 >/dev/null 2>&1 || true
  cleanup_temps
  exit "$rc"
}
trap rollback ERR

TMP_LOCAL="$(mktemp -d)"
[[ -f "$CONFIG" ]] && cp -a "$CONFIG" "$TMP_LOCAL/config.ini"
[[ -d "$APP_DIR/run" ]] && cp -a "$APP_DIR/run" "$TMP_LOCAL/run"
[[ -d "$APP_DIR/cache" ]] && cp -a "$APP_DIR/cache" "$TMP_LOCAL/cache"
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
  mkdir -p "$APP_DIR"
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name config.ini ! -name run ! -name cache ! -name .git -exec rm -rf {} +
  tar -C "$SOURCE_DIR" --exclude='./config.ini' --exclude='./run' --exclude='./cache' --exclude='./.git' -cf - . | tar -C "$APP_DIR" -xf -
else
  echo "[INFO] Running installer from installed application directory; current source tree kept in place."
fi
mkdir -p -m 0700 "$BACKUP_ROOT/asl3-config"
chmod 0700 "$BACKUP_ROOT/asl3-config"
mkdir -p "$APP_DIR/src" "$APP_DIR/run/locks" "$APP_DIR/run/snapshots" "$APP_DIR/cache/echolink" /usr/local/libexec
[[ -f "$TMP_LOCAL/config.ini" ]] && cp -a "$TMP_LOCAL/config.ini" "$CONFIG"
[[ -d "$TMP_LOCAL/run" ]] && cp -a "$TMP_LOCAL/run/." "$APP_DIR/run/"
[[ -d "$TMP_LOCAL/cache" ]] && cp -a "$TMP_LOCAL/cache/." "$APP_DIR/cache/"
rm -rf "$TMP_LOCAL"
[[ -f "$CONFIG" ]] || cp "$APP_DIR/config.ini.example" "$CONFIG"

python3 - "$CONFIG" "$NODE" "$DISABLE_AUTH" "$ENABLE_AUTH" "$PASSWORD_HASH" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); node=sys.argv[2]; disable=sys.argv[3]=='1'; enable=sys.argv[4]=='1'; password_hash=sys.argv[5]
s=p.read_text(encoding='utf-8')
def setv(name,value):
    global s
    pat=rf'^{re.escape(name)}=.*$'; line=f'{name}={value}'
    s=re.sub(pat,line,s,count=1,flags=re.M) if re.search(pat,s,flags=re.M) else s.rstrip()+"\n"+line+"\n"
setv('MYNODE',f'"{node}"')
if disable:setv('ASL3_NODE_MANAGER_AUTH_ENABLED','0')
if enable:setv('ASL3_NODE_MANAGER_AUTH_ENABLED','1')
if password_hash:
    setv('ASL3_NODE_MANAGER_ADMIN_USER','"admin"')
    setv('ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH',f'"{password_hash}"')
    setv('ASL3_NODE_MANAGER_AUTH_ENABLED','1')
p.write_text(s,encoding='utf-8')
PY

# Preserve Git repository metadata permissions.
find "$APP_DIR" -path "$APP_DIR/.git" -prune -o -exec chown root:root {} +
find "$APP_DIR" -path "$APP_DIR/.git" -prune -o -type d -exec chmod 0755 {} +
find "$APP_DIR" \( -path "$APP_DIR/.git" -o -path "$APP_DIR/run" -o -path "$APP_DIR/cache" \) -prune -o -type f -exec chmod 0644 {} +
find "$APP_DIR/run" -type f -exec chmod 0644 {} +
# DTMF Favorites contain local user data and must remain root-only.
if [[ -f "$APP_DIR/run/dtmf_favorites.txt" ]]; then
  chmod 0600 "$APP_DIR/run/dtmf_favorites.txt"
fi
find "$APP_DIR/cache" -type f -exec chmod 0644 {} +
chmod 0755 "$APP_DIR/bin/asl3-node-manager-status.py" "$APP_DIR/bin/asl3-node-manager-control.py" "$APP_DIR/bin/asl3-node-manager-helper" "$APP_DIR/bin/asl3-node-manager" "$APP_DIR/bin/asl3-node-manager-services.py" "$APP_DIR/bin/asl3-node-manager-system-metrics.py" "$APP_DIR/setup_asl3_node_manager.sh"
chown root:www-data "$CONFIG"; chmod 0640 "$CONFIG"
chown -R root:root "$APP_DIR/run" "$APP_DIR/cache"
find "$APP_DIR/run" "$APP_DIR/cache" -type d -exec chmod 0755 {} +
touch "$APP_DIR/run/control.log"; chown root:root "$APP_DIR/run/control.log"; chmod 0644 "$APP_DIR/run/control.log"

install -o root -g root -m 0755 "$APP_DIR/bin/asl3-node-manager-helper" "$HELPER_DST"
cat > "$SUDOERS" <<EOF2
www-data ALL=(root) NOPASSWD: $HELPER_DST
EOF2
chmod 0440 "$SUDOERS"; visudo -cf "$SUDOERS" >/dev/null

cat > "$APACHE_CONF" <<EOF2
Alias /node-manager/ $APP_DIR/public/
RedirectMatch 301 ^/node-manager$ /node-manager/
<Directory $APP_DIR>
  Require all denied
</Directory>
<Directory $APP_DIR/public>
  Options -Indexes
  AllowOverride None
  Require all granted
  DirectoryIndex index.php
</Directory>
EOF2
cat > "$POLLING_CONF" <<'EOF2'
# ASL3 Node Manager: suppress only successful high-frequency status polling.
# Failed status requests, login/logout, and control actions remain in access.log.
SetEnvIf Request_URI "^/node-manager/status\.php$" dontlog_app_polling_200=1
EOF2

a2enconf "$APACHE_NAME" >/dev/null
a2enconf "$POLLING_NAME" >/dev/null

for file in public/index.php public/status.php public/action.php public/login.php public/logout.php src/bootstrap.php src/auth.php src/NodeIdentity.php src/EchoLink.php src/CacheMaintenance.php bin/asl3-node-manager-echolink.php bin/asl3-node-manager-appearance.php public/services.php public/backup_download.php; do php -l "$APP_DIR/$file" >/dev/null; done
python3 -m py_compile "$APP_DIR/bin/asl3-node-manager-status.py" "$APP_DIR/bin/asl3-node-manager-control.py" "$APP_DIR/bin/asl3-node-manager-services.py" "$APP_DIR/bin/asl3-node-manager-system-metrics.py"; rm -rf "$APP_DIR/bin/__pycache__"
bash -n "$APP_DIR/bin/asl3-node-manager-helper"; bash -n "$APP_DIR/bin/asl3-node-manager"; bash -n "$APP_DIR/setup_asl3_node_manager.sh"
if command -v node >/dev/null; then node --check "$APP_DIR/public/assets/app.js" >/dev/null; fi
apache2ctl configtest >/dev/null
systemctl reload apache2
for file in NodeIdentity.php EchoLink.php CacheMaintenance.php; do cmp -s "$SOURCE_DIR/src/$file" "$APP_DIR/src/$file" || die "installed EchoLink resolver differs from bundled source: $file"; done

if command -v runuser >/dev/null; then
  STATUS_TMP="$(mktemp)"
  runuser -u www-data -- sudo -n "$HELPER_DST" status "$NODE" > "$STATUS_TMP"
  python3 - "$STATUS_TMP" "$NODE" <<'PY'
import json,sys
with open(sys.argv[1],encoding='utf-8') as fh:data=json.load(fh)
if str(data.get('node'))!=sys.argv[2] or not data.get('node_online'):raise SystemExit('installed helper returned invalid node status')
PY
  rm -f "$STATUS_TMP"
fi
verify_apache_guard

COMMITTED=1
trap - ERR
POLLING_SHARED="NOT DETECTED"
grep -Rqs "dontlog_app_polling_200" /etc/apache2/sites-enabled/*.conf 2>/dev/null && POLLING_SHARED="ACTIVE"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
VERSION="$(cat "$APP_DIR/VERSION")"
AUTH="$(php -r '$c=parse_ini_file($argv[1],false,INI_SCANNER_RAW); echo ((string)($c["ASL3_NODE_MANAGER_AUTH_ENABLED"]??"0")==="1" && trim((string)($c["ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH"]??""))!=="")?"ENABLED (user: admin)":"DISABLED";' "$CONFIG")"
cleanup_temps
cat <<EOF2

[OK] $APP_NAME setup complete.
Version: $VERSION
ASL3 node: $NODE
Dashboard: http://${IP:-NODE-IP}/node-manager/
Application login: $AUTH
Successful status-poll access-log suppression: $POLLING_SHARED
Unrelated Apache polling filters/site configs: UNCHANGED
Bundled EchoLink resolver: VERIFIED
Protected setup backup: $BACKUP_DIR

Set/change administrator password and enable login:
sudo $APP_DIR/setup_asl3_node_manager.sh --set-admin-password

EOF2
