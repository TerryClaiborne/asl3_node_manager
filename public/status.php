<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
try {
    $data = manager_helper_status(manager_node());
    // Reuse the existing 1-second status poll to synchronize the saved
    // node appearance across open browsers/devices without another endpoint.
    $data['appearance'] = manager_appearance();
    echo json_encode($data, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok'=>false,'read_only'=>true,'error'=>$e->getMessage()]);
}
