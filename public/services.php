<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
try {
    $method = (string)($_SERVER['REQUEST_METHOD'] ?? 'GET');
    if ($method !== 'POST') { http_response_code(405); throw new RuntimeException('POST required.'); }
    manager_require_login(); manager_verify_csrf((string)($_POST['csrf'] ?? ''));
    $action = (string)($_POST['action'] ?? '');
    $allowed=['list','favorite-save','favorite-delete','dtmf-send','backup-create','backup-delete','official-backup-delete','backup-verify','official-backup-verify','restore-preview','restore-live','asterisk-reload','app-rpt-reload','asterisk-restart','apache-reload','apache-restart'];
    if (!in_array($action,$allowed,true)) { http_response_code(422); throw new RuntimeException('Unsupported action.'); }
    $payload=['action'=>$action,'node'=>manager_node()];
    foreach (['code','original_code','name'] as $key) {
        if (isset($_POST[$key])) { $value=(string)$_POST[$key]; if (strlen($value)>256) throw new RuntimeException('Input too long.'); $payload[$key]=$value; }
    }
    if ($action==='restore-preview' || $action==='restore-live') { $payload['source']=(string)($_POST['source'] ?? ''); $payload['name']=(string)($_POST['backup_name'] ?? ''); }
    if ($action==='restore-live') $payload['confirmation']=(string)($_POST['confirmation'] ?? '');
    if ($action==='backup-delete' || $action==='official-backup-delete' || $action==='backup-verify' || $action==='official-backup-verify') $payload['name']=(string)($_POST['backup_name'] ?? '');
    $cmd=['sudo','-n',ASL3_NODE_MANAGER_HELPER,'services',manager_node()];
    $proc=proc_open($cmd,[0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']],$pipes,null,['PATH'=>'/usr/sbin:/usr/bin:/sbin:/bin'],['bypass_shell'=>true]);
    if (!is_resource($proc)) throw new RuntimeException('Cannot start Services helper.');
    fwrite($pipes[0],json_encode($payload,JSON_UNESCAPED_SLASHES)); fclose($pipes[0]);
    $out=stream_get_contents($pipes[1]);$err=stream_get_contents($pipes[2]);fclose($pipes[1]);fclose($pipes[2]);
    $code=proc_close($proc);$data=json_decode((string)$out,true);
    if (!is_array($data)) throw new RuntimeException(trim((string)$err) ?: 'Services helper returned invalid JSON.');
    if ($code!==0 || empty($data['ok'])) http_response_code(422);
    echo json_encode($data,JSON_UNESCAPED_SLASHES);exit;
} catch(Throwable $e) {
    if (http_response_code()<400) http_response_code(500);
    echo json_encode(['ok'=>false,'message'=>$e->getMessage()],JSON_UNESCAPED_SLASHES);
}
