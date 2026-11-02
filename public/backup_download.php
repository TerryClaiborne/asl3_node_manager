<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
try {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') throw new RuntimeException('POST required.');
    manager_require_login();
    // Download is read-only, but token prevents inadvertent cross-site requests.
    manager_verify_csrf((string)($_POST['csrf'] ?? ''));
    $name=(string)($_POST['name'] ?? '');
    $source=(string)($_POST['source'] ?? 'manager');
    if ($source === 'manager') {
        if (preg_match('/^ASL3-config-[0-9]{4}-[0-9]{2}-[0-9]{2}-T[0-9]{6}Z\.tar\.gz$/D',$name)!==1) throw new RuntimeException('Invalid backup name.');
        $action='backup-download';
    } elseif ($source === 'official') {
        if (preg_match('/^ASL_[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4}\.tgz$/D',$name)!==1) throw new RuntimeException('Invalid official backup name.');
        $action='official-backup-download';
    } else {
        throw new RuntimeException('Invalid backup source.');
    }
    $cmd=['sudo','-n',ASL3_NODE_MANAGER_HELPER,$action,manager_node(),$name];
    $proc=proc_open($cmd,[1=>['pipe','w'],2=>['pipe','w']],$pipes,null,['PATH'=>'/usr/sbin:/usr/bin:/sbin:/bin'],['bypass_shell'=>true]);
    if (!is_resource($proc)) throw new RuntimeException('Backup download unavailable.');
    $tmp=tmpfile();if (!$tmp) throw new RuntimeException('Temporary storage unavailable.');
    stream_copy_to_stream($pipes[1],$tmp);$err=stream_get_contents($pipes[2]);fclose($pipes[1]);fclose($pipes[2]);$exit=proc_close($proc);
    if ($exit!==0) throw new RuntimeException(trim((string)$err) ?: 'Backup read failed.');
    $size=ftell($tmp);rewind($tmp);
    header('Content-Type: application/gzip');header('Content-Disposition: attachment; filename="'.$name.'"');header('Content-Length: '.$size);header('Cache-Control: no-store');
    fpassthru($tmp);fclose($tmp);
} catch(Throwable $e) {http_response_code(403);header('Content-Type: text/plain');echo 'Download unavailable: '.$e->getMessage();}
