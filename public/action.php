<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
header('Content-Type: application/json; charset=utf-8'); header('Cache-Control: no-store, max-age=0');
try {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); throw new RuntimeException('POST required.'); }
    manager_require_login(); manager_verify_csrf((string)($_POST['csrf'] ?? ''));
    $action = trim((string)($_POST['action'] ?? ''));
    if ($action === 'appearance') {
        $raw = (string)($_POST['appearance'] ?? ''); if ($raw === '' || strlen($raw) > 16384) throw new RuntimeException('Invalid appearance payload.');
        $decoded = json_decode($raw, true); if (!is_array($decoded)) throw new RuntimeException('Appearance payload is not valid JSON.');
        $profile = manager_appearance_validate($decoded); if ($profile === null) throw new RuntimeException('Appearance settings are invalid.');
        echo json_encode(manager_helper_appearance(manager_node(), $profile), JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE); exit;
    }
    $allowed = ['disconnect','block','restore','disconnect-all','incoming-block','incoming-allow','node-offline','node-restore'];
    if (!in_array($action, $allowed, true)) throw new RuntimeException('Unsupported control action.');
    $target = trim((string)($_POST['target'] ?? '')); $reason = trim((string)($_POST['reason'] ?? ''));
    if (in_array($action, ['disconnect','block','restore'], true) && $target === '') throw new RuntimeException('Target required.');
    echo json_encode(manager_helper_call($action, manager_node(), $target, $reason), JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE);
} catch (Throwable $e) { if (http_response_code() < 400) http_response_code(500); echo json_encode(['ok'=>false,'result'=>'failed','message'=>$e->getMessage()], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE); }
