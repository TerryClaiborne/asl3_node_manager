<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
try {
    $raw = stream_get_contents(STDIN);
    if (!is_string($raw) || $raw === '' || strlen($raw) > 16384) throw new RuntimeException('Invalid appearance payload.');
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) throw new RuntimeException('Appearance payload is not valid JSON.');
    $profile = manager_appearance_validate($decoded);
    if ($profile === null) throw new RuntimeException('Appearance settings are invalid.');
    $dir = dirname(ASL3_NODE_MANAGER_APPEARANCE);
    if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) throw new RuntimeException('Unable to create runtime directory.');
    $tmp = tempnam($dir, '.appearance.');
    if ($tmp === false) throw new RuntimeException('Unable to create temporary appearance file.');
    try {
        $json = json_encode($profile, JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES) . "\n";
        if (file_put_contents($tmp, $json, LOCK_EX) === false) throw new RuntimeException('Unable to write appearance file.');
        chmod($tmp, 0644);
        if (!rename($tmp, ASL3_NODE_MANAGER_APPEARANCE)) throw new RuntimeException('Unable to install appearance file.');
        chmod(ASL3_NODE_MANAGER_APPEARANCE, 0644);
    } finally {
        if (is_file($tmp)) @unlink($tmp);
    }
    echo json_encode(['ok'=>true,'result'=>'verified','message'=>'Appearance saved.','appearance'=>$profile], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    fwrite(STDERR, $e->getMessage() . "\n");
    echo json_encode(['ok'=>false,'result'=>'failed','message'=>$e->getMessage()], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
    exit(1);
}
