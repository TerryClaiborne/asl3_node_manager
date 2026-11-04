<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
try {
    $method=(string)($_SERVER['REQUEST_METHOD']??'GET');
    if($method==='GET') {
        $action=(string)($_GET['action']??'');
        if(!in_array($action,['favorites-list','capabilities'],true)) {http_response_code(405);throw new RuntimeException('Invalid request.');}
        $payload=['action'=>$action,'node'=>manager_node()];
    } elseif($method==='POST') {
        manager_require_login();manager_verify_csrf((string)($_POST['csrf']??''));
        $action=(string)($_POST['action']??'');
        if(!in_array($action,['lookup','connect','favorite-save','favorite-delete'],true)) {http_response_code(422);throw new RuntimeException('Unsupported Link action.');}
        $payload=['action'=>$action,'node'=>manager_node()];
        foreach(['network'=>8,'target'=>40,'mode'=>20,'name'=>96,'description'=>160] as $k=>$lim) {
            if(isset($_POST[$k])) {
                $v=trim((string)$_POST[$k]);if(strlen($v)>$lim*4) throw new RuntimeException('Input too long.');
                $payload[$k]=$v;
            }
        }
    } else {http_response_code(405);throw new RuntimeException('Unsupported method.');}
    // Root helper validates configured MYNODE; all sensitive operations are fixed-whitelist.
    $sub=($payload['action']==='lookup')?'link-lookup':'link';
    $cmd=['sudo','-n',ASL3_NODE_MANAGER_HELPER,$sub,manager_node()];
    $proc=proc_open($cmd,[0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']],$pipes,null,
        ['PATH'=>'/usr/sbin:/usr/bin:/sbin:/bin'],['bypass_shell'=>true]);
    if(!is_resource($proc))throw new RuntimeException('Cannot start Link helper.');
    fwrite($pipes[0],json_encode($payload,JSON_UNESCAPED_SLASHES));fclose($pipes[0]);
    $out=stream_get_contents($pipes[1]);$err=stream_get_contents($pipes[2]);fclose($pipes[1]);fclose($pipes[2]);
    $code=proc_close($proc);
    $data=json_decode((string)$out,true);
    if(!is_array($data)) throw new RuntimeException(trim((string)$err)?:'Link helper returned invalid JSON.');
    if($code!==0||empty($data['ok']))http_response_code(422);
    echo json_encode($data,JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);exit;
} catch(Throwable $e) {
    if(http_response_code()<400)http_response_code(500);
    echo json_encode(['ok'=>false,'message'=>$e->getMessage()],JSON_UNESCAPED_SLASHES);
}
