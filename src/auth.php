<?php
declare(strict_types=1);

function manager_auth_enabled(): bool
{
    $cfg = manager_config();
    return ((string)($cfg['ASL3_NODE_MANAGER_AUTH_ENABLED'] ?? '0')) === '1'
        && trim((string)($cfg['ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH'] ?? '')) !== '';
}

function manager_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) return;
    session_name('asl3_manager_session');
    ini_set('session.use_strict_mode', '1');
    $secure = !empty($_SERVER['HTTPS']) && strtolower((string)$_SERVER['HTTPS']) !== 'off';
    session_set_cookie_params([
        'lifetime' => 0,
        'path' => '/',
        'secure' => $secure,
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    session_start();
}

function manager_is_logged_in(): bool
{
    if (!manager_auth_enabled()) return true;
    manager_session_start();
    return !empty($_SESSION['asl3_manager_admin']);
}

function manager_require_login(): void
{
    if (manager_is_logged_in()) return;
    http_response_code(403);
    throw new RuntimeException('Administrator login required.');
}

function manager_login(string $password): bool
{
    $cfg = manager_config();
    $hash = (string)($cfg['ASL3_NODE_MANAGER_ADMIN_PASSWORD_HASH'] ?? '');
    if ($hash === '' || !password_verify($password, $hash)) return false;
    manager_session_start();
    session_regenerate_id(true);
    $_SESSION['asl3_manager_admin'] = true;
    return true;
}

function manager_logout(): void
{
    manager_session_start();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p = session_get_cookie_params();
        setcookie(session_name(), '', [
            'expires' => time() - 42000,
            'path' => $p['path'] ?: '/',
            'domain' => $p['domain'] ?? '',
            'secure' => !empty($p['secure']),
            'httponly' => !empty($p['httponly']),
            'samesite' => $p['samesite'] ?? 'Lax',
        ]);
    }
    session_destroy();
}

function manager_csrf_token(): string
{
    manager_session_start();
    $token = (string)($_SESSION['asl3_manager_csrf'] ?? '');
    if ($token === '') {
        $token = bin2hex(random_bytes(24));
        $_SESSION['asl3_manager_csrf'] = $token;
    }
    return $token;
}

function manager_verify_csrf(string $token): void
{
    manager_session_start();
    $expected = (string)($_SESSION['asl3_manager_csrf'] ?? '');
    if ($expected === '' || $token === '' || !hash_equals($expected, $token)) {
        http_response_code(403);
        throw new RuntimeException('Invalid control request token. Refresh the page and try again.');
    }
}
