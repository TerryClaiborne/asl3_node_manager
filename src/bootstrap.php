<?php
declare(strict_types=1);

const ASL3_NODE_MANAGER_APP_DIR = '/var/www/html/asl3_node_manager';
const ASL3_NODE_MANAGER_HELPER = '/usr/local/libexec/asl3-node-manager-helper';
const ASL3_NODE_MANAGER_APPEARANCE = ASL3_NODE_MANAGER_APP_DIR . '/run/appearance.json';

function manager_config(): array
{
    $path = ASL3_NODE_MANAGER_APP_DIR . '/config.ini';
    if (!is_readable($path)) throw new RuntimeException('Configuration is not readable.');
    $cfg = parse_ini_file($path, false, INI_SCANNER_RAW);
    if (!is_array($cfg)) throw new RuntimeException('Configuration could not be parsed.');
    return $cfg;
}

function manager_node(): string
{
    $cfg = manager_config();
    $node = trim((string)($cfg['MYNODE'] ?? ''));
    if (!preg_match('/^\d+$/', $node)) throw new RuntimeException('MYNODE is not configured.');
    return $node;
}

function manager_helper_call(string $action, string $node, string $target = '', string $reason = ''): array
{
    if (!preg_match('/^\d+$/', $node)) throw new RuntimeException('Invalid node.');
    $allowed = [
        'status','disconnect','block','restore','disconnect-all','incoming-block','incoming-allow',
        'node-offline','node-restore'
    ];
    if (!in_array($action, $allowed, true)) throw new RuntimeException('Unsupported helper action.');
    $cmd = ['sudo', '-n', ASL3_NODE_MANAGER_HELPER, $action, $node];
    if ($target !== '') $cmd[] = $target;
    if ($reason !== '') $cmd[] = $reason;
    $spec = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
    $proc = proc_open($cmd, $spec, $pipes, null, ['PATH'=>'/usr/sbin:/usr/bin:/sbin:/bin'], ['bypass_shell'=>true]);
    if (!is_resource($proc)) throw new RuntimeException('Unable to start Node Manager helper.');
    $stdout = stream_get_contents($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]); fclose($pipes[2]);
    $code = proc_close($proc);
    $data = json_decode((string)$stdout, true);
    if (!is_array($data)) throw new RuntimeException(trim((string)$stderr) ?: 'Node Manager helper returned invalid JSON.');
    if ($code !== 0 && empty($data['message'])) throw new RuntimeException(trim((string)$stderr) ?: 'Node Manager helper failed.');
    return $data;
}

function manager_helper_appearance(string $node, array $appearance): array
{
    if (!preg_match('/^\d+$/', $node)) throw new RuntimeException('Invalid node.');
    $cmd = ['sudo', '-n', ASL3_NODE_MANAGER_HELPER, 'appearance', $node];
    $spec = [0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']];
    $proc = proc_open($cmd, $spec, $pipes, null, ['PATH'=>'/usr/sbin:/usr/bin:/sbin:/bin'], ['bypass_shell'=>true]);
    if (!is_resource($proc)) throw new RuntimeException('Unable to start appearance helper.');
    fwrite($pipes[0], json_encode($appearance, JSON_UNESCAPED_SLASHES));
    fclose($pipes[0]);
    $stdout = stream_get_contents($pipes[1]); $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]); fclose($pipes[2]);
    $code = proc_close($proc);
    $data = json_decode((string)$stdout, true);
    if (!is_array($data)) throw new RuntimeException(trim((string)$stderr) ?: 'Appearance helper returned invalid JSON.');
    if ($code !== 0 || empty($data['ok'])) throw new RuntimeException((string)($data['message'] ?? trim((string)$stderr) ?: 'Appearance save failed.'));
    return $data;
}

function manager_helper_status(string $node): array { return manager_helper_call('status', $node); }
function manager_version(): string { return trim((string)@file_get_contents(ASL3_NODE_MANAGER_APP_DIR . '/VERSION')) ?: 'unknown'; }

function manager_appearance_defaults(): array
{
    return [
        'theme' => 'dark',
        'mode' => 'default',
        'audio_alerts' => false,
        'profiles' => [
            'dark' => [
                'background'=>'#080E19','foreground'=>'#121D2F','text'=>'#F2F5FF',
                'secondary'=>'#A9B9D4','headings'=>'#A9B9D4','accent'=>'#7458FF',
            ],
            'light' => [
                'background'=>'#EEF3FA','foreground'=>'#FFFFFF','text'=>'#142038',
                'secondary'=>'#55657F','headings'=>'#55657F','accent'=>'#6550DD',
            ],
        ],
    ];
}

function manager_valid_hex(string $value): bool { return preg_match('/^#[0-9A-Fa-f]{6}$/', $value) === 1; }

function manager_appearance_validate(array $input): ?array
{
    $defaults = manager_appearance_defaults();
    $theme = (string)($input['theme'] ?? $defaults['theme']);
    $mode = (string)($input['mode'] ?? $defaults['mode']);
    if (!in_array($theme, ['dark','light'], true)) return null;
    if (!in_array($mode, ['default','advanced'], true)) return null;
    $profiles = $input['profiles'] ?? null;
    if (!is_array($profiles)) $profiles = $defaults['profiles'];
    // A small persisted preference alongside the existing server-side theme.
    // Older appearance files without this field remain valid and default off.
    $audioAlerts = $input['audio_alerts'] ?? $defaults['audio_alerts'];
    if (!is_bool($audioAlerts)) return null;
    $out = ['theme'=>$theme,'mode'=>$mode,'audio_alerts'=>$audioAlerts,'profiles'=>[]];
    foreach (['dark','light'] as $which) {
        $src = is_array($profiles[$which] ?? null) ? $profiles[$which] : $defaults['profiles'][$which];
        $profile = [];
        foreach (['background','foreground','text','secondary','headings','accent'] as $key) {
            $value = strtoupper(trim((string)($src[$key] ?? $defaults['profiles'][$which][$key])));
            if (!manager_valid_hex($value)) return null;
            $profile[$key] = $value;
        }
        $out['profiles'][$which] = $profile;
    }
    return $out;
}

function manager_appearance(): array
{
    $defaults = manager_appearance_defaults();
    $raw = @file_get_contents(ASL3_NODE_MANAGER_APPEARANCE);
    if (!is_string($raw) || trim($raw) === '') return $defaults;
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) return $defaults;
    return manager_appearance_validate($decoded) ?? $defaults;
}

function manager_appearance_style(array $appearance): string
{
    if (($appearance['mode'] ?? 'default') !== 'advanced') return '';
    $theme = (string)($appearance['theme'] ?? 'dark');
    $p = $appearance['profiles'][$theme] ?? [];
    if (!is_array($p)) return '';
    $map = [
        '--bg'=>'background','--panel'=>'foreground','--text'=>'text','--page-text'=>'text',
        '--muted'=>'secondary','--secondary-text'=>'secondary','--table-heading'=>'headings',
        '--table-label'=>'headings','--primary'=>'accent','--focus'=>'accent',
    ];
    $parts = [];
    foreach ($map as $css=>$key) {
        $v = strtoupper((string)($p[$key] ?? ''));
        if (manager_valid_hex($v)) $parts[] = $css . ':' . $v;
    }
    return implode(';', $parts);
}

require_once __DIR__ . '/auth.php';
