<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
manager_logout();
header('Location: index.php');
