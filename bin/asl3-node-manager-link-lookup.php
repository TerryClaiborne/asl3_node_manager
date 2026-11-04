<?php
declare(strict_types=1);
require_once dirname(__DIR__) . '/src/NodeIdentity.php';
require_once dirname(__DIR__) . '/src/EchoLink.php';
use AllStarConnect\NodeIdentity;
use AllStarConnect\EchoLink;
function finish(bool $ok, string $message='', array $matches=[]): never {
    echo json_encode(['ok'=>$ok,'message'=>$message,'matches'=>$matches], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE), "\n";
    exit($ok ? 0 : 1);
}
try {
    $request=json_decode((string)stream_get_contents(STDIN, 8193), true);
    if(!is_array($request)) finish(false,'Invalid lookup request.');
    $network=(string)($request['network']??'');
    $q=strtoupper(trim((string)($request['target']??'')));
    if(!in_array($network,['ASL','ECHO'],true) || strlen($q)>32 || $q==='') finish(false,'Enter a valid node or callsign.');
    $matches=[];
    if($network==='ASL') {
        if(preg_match('/^[0-9]{1,7}$/',$q)) {
            $record=NodeIdentity::astdbLookup($q);
            $matches[]=['network'=>'ASL','target'=>$q,'callsign'=>trim((string)($record['call']??'')),
                'description'=>trim((string)($record['description']??'')),'location'=>trim((string)($record['location']??''))];
        } elseif(preg_match('/^[A-Z0-9_.\/-]{2,32}$/',$q) && preg_match('/[A-Z]/',$q)) {
            foreach(array_slice(NodeIdentity::astdbCallsignLookup($q),0,40) as $r) {
                $matches[]=['network'=>'ASL','target'=>(string)$r['target'],
                    'callsign'=>(string)$r['callsign'],'description'=>(string)$r['description'],
                    'location'=>(string)$r['location']];
            }
        } else finish(false,'Enter a valid AllStar node number or callsign.');
    } else {
        if(preg_match('/^3\d{6}$/',$q)) $number=NodeIdentity::echoLinkNodeNumber($q,true);
        elseif(preg_match('/^\d{1,6}$/',$q)) $number=NodeIdentity::echoLinkNodeNumber($q);
        else $number='';
        if($number!=='') {
            $ids=[$number];
        } elseif(preg_match('/^[A-Z0-9_.\/-]{2,32}$/',$q) && preg_match('/[A-Z]/',$q)) {
            $base=preg_replace('/-(?:L|R)$/','',$q);
            $ids=array_values(array_unique([$q,$base,$base.'-R',$base.'-L']));
        } else finish(false,'Enter a valid EchoLink node number or callsign.');
        $resolver=new EchoLink();
        $snapshot=[];
        // Resolver intentionally refreshes at most one uncached identity per call.
        // Three bounded calls also resolve -R and -L where available.
        for($attempt=0;$attempt<count($ids);$attempt++) {
            $snapshot=$resolver->snapshot([], $ids);
            if(empty($snapshot['pending'])) break;
        }
        $used=[];
        foreach($ids as $id) {
            $e=$snapshot['entries']['call:'.$id]??$snapshot['entries'][$id]??null;
            if(!is_array($e)) continue;
            $n=NodeIdentity::echoLinkNodeNumber((string)($e['node']??''));
            if($n===''||$n==='0') continue;
            $target='3'.str_pad($n,6,'0',STR_PAD_LEFT);
            if(isset($used[$target])) continue;
            $used[$target]=true;
            $call=strtoupper(trim((string)($e['callsign']??'')));
            $kind=str_ends_with($call,'-R')?'EchoLink Repeater':(str_ends_with($call,'-L')?'EchoLink Link':'EchoLink User');
            $matches[]=['network'=>'ECHO','target'=>$target,'callsign'=>$call,
                'description'=>$kind,'location'=>'','official_node'=>$n];
        }
    }
    if(!$matches) finish(false,'No matching station was found.');
    finish(true,'',array_slice($matches,0,40));
} catch(Throwable $e) {finish(false,'Station lookup is temporarily unavailable.');}
