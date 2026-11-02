<?php
declare(strict_types=1);

require_once __DIR__ . '/../src/CacheMaintenance.php';
require_once __DIR__ . '/../src/NodeIdentity.php';
require_once __DIR__ . '/../src/EchoLink.php';

use AllStarConnect\EchoLink;

$raw = stream_get_contents(STDIN);
$ids = json_decode($raw ?: '[]', true);
if (!is_array($ids)) {
    fwrite(STDERR, "Invalid JSON input\n");
    exit(2);
}

$clean = [];
foreach ($ids as $id) {
    $id = trim((string)$id);
    if ($id !== '') {
        $clean[] = $id;
    }
}

try {
    $snapshot = (new EchoLink())->snapshot([], $clean);
    echo json_encode($snapshot, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";
} catch (Throwable $e) {
    fwrite(STDERR, $e->getMessage() . "\n");
    exit(1);
}
