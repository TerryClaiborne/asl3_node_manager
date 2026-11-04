<?php
declare(strict_types=1);
require_once __DIR__ . '/../src/bootstrap.php';
$version = manager_version();
$repoUrl = 'https://github.com/TerryClaiborne/asl3_node_manager';
$remoteVersionUrl = 'https://raw.githubusercontent.com/TerryClaiborne/asl3_node_manager/main/VERSION';
try { $node = manager_node(); } catch (Throwable $e) { $node = 'Not configured'; }
$authEnabled = manager_auth_enabled();
$loggedIn = manager_is_logged_in();
$canControl = !$authEnabled || $loggedIn;
$csrf = manager_csrf_token();
$appearance = manager_appearance();
$appearanceStyle = manager_appearance_style($appearance);
?>
<!doctype html>
<html lang="en" data-theme="<?=htmlspecialchars($appearance['theme'], ENT_QUOTES, 'UTF-8')?>" data-palette="<?=htmlspecialchars($appearance['mode'], ENT_QUOTES, 'UTF-8')?>"<?= $appearanceStyle !== '' ? ' style="'.htmlspecialchars($appearanceStyle, ENT_QUOTES, 'UTF-8').'"' : '' ?>>
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark">
  <title>ASL3 Node Manager</title>
  <link rel="stylesheet" href="assets/style.css?v=<?=rawurlencode($version)?>-<?=filemtime(__DIR__ . "/assets/style.css")?>">
  <script>window.ASL3_NODE_MANAGER_APPEARANCE=<?=json_encode($appearance, JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE)?>;</script>
</head>
<body data-can-control="<?=$canControl ? '1' : '0'?>" data-csrf="<?=htmlspecialchars($csrf, ENT_QUOTES, 'UTF-8')?>">
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <a class="brand-repo" id="brandingStar" href="<?=htmlspecialchars($repoUrl, ENT_QUOTES, 'UTF-8')?>" target="_blank" rel="noopener noreferrer" aria-label="Open the ASL3 Node Manager repository" data-local-version="<?=htmlspecialchars($version, ENT_QUOTES, 'UTF-8')?>" data-version-url="<?=htmlspecialchars($remoteVersionUrl, ENT_QUOTES, 'UTF-8')?>" title="ASL3 Node Manager <?=htmlspecialchars($version, ENT_QUOTES, 'UTF-8')?>">
        <span class="brand-mark" aria-hidden="true"><svg class="brand-star-svg" viewBox="0 0 72 72" aria-hidden="true" focusable="false"><path class="star-outline" d="M36 4 44 25 67 26 49 40 55 64 36 51 17 64 23 40 5 26 28 25Z"/><path class="star-wave wave-one" d="M19 31c5-6 10-6 15 0s10 6 15 0"/><path class="star-wave wave-two" d="M16 39c7-8 14-8 21 0s14 8 21 0"/><circle class="star-center" cx="36" cy="35" r="3.5"/></svg></span>
      </a>
      <div class="brand-copy"><h1>ASL3 Node Manager</h1><div class="subtitle">Node <?=htmlspecialchars($node, ENT_QUOTES, 'UTF-8')?> · ASL3 node management</div></div>
    </div>
    <div class="header-actions">
      <button class="top-btn" id="themeToggle" type="button" title="Switch between Light and Dark themes. Your choice is saved on this node." <?=$canControl ? '' : 'disabled'?>>Light / Dark</button>
      <?php if ($canControl): ?>
      <details class="color-menu" id="colorMenu">
        <summary class="top-btn color-button" title="Color settings"><span class="color-wide">Colors</span><span class="color-compact">🎨</span></summary>
        <div class="color-popover">
          <div id="colorMainPanel">
            <label class="color-field"><span>Mode</span><select id="colorMode"><option value="default">Default</option><option value="advanced">Advanced…</option></select></label>
            <div id="advancedColorFields" class="advanced-fields" hidden>
              <?php foreach ([
                'background'=>['Background','Page background behind cards and panels.'],
                'foreground'=>['Foreground / Cards','Cards, panels, and major foreground surfaces.'],
                'text'=>['Text','Primary text.'],
                'secondary'=>['Secondary Text','Muted labels, notes, and secondary text.'],
                'headings'=>['Table Headings','Table headers and compact labels.'],
                'accent'=>['Accent','Active tabs, focus, borders, and accent elements.'],
              ] as $key=>$meta): ?>
              <button class="advanced-color-button" data-color-target="<?=$key?>" type="button" title="<?=htmlspecialchars($meta[1],ENT_QUOTES,'UTF-8')?>"><span><?=$meta[0]?></span><span class="color-value"><span class="color-swatch" id="swatch-<?=$key?>"></span><code id="value-<?=$key?>">—</code></span></button>
              <?php endforeach; ?>
            </div>
            <div class="color-message" id="colorMessage"></div>
            <div class="color-actions"><button class="small-btn" id="resetColors" type="button" title="Reset the current color selections to defaults. Click Apply to save.">Reset</button><button class="small-btn primary" id="applyColors" type="button" title="Save the selected appearance settings for this node.">Apply</button></div>
          </div>
          <div id="colorEditor" class="color-editor" hidden>
            <div class="color-editor-title" id="colorEditorTitle">Choose Color</div><div class="color-editor-preview" id="colorEditorPreview"></div>
            <div class="quick-color-palette" aria-label="Quick colors">
              <?php foreach (['#000000','#FFFFFF','#808080','#D64545','#E67E22','#F1C40F','#27AE60','#16A085','#18A8C9','#3478D4','#7C3AED','#D946EF'] as $c): ?><button type="button" class="quick-color-swatch" data-color="<?=$c?>" style="background:<?=$c?>" aria-label="<?=$c?>"></button><?php endforeach; ?>
            </div>
            <label class="slider-field"><span>Hue</span><input id="colorHue" type="range" min="0" max="360" step="1"></label>
            <label class="slider-field"><span>Saturation</span><input id="colorSaturation" type="range" min="0" max="100" step="1"></label>
            <label class="slider-field"><span>Brightness</span><input id="colorBrightness" type="range" min="0" max="100" step="1"></label>
            <label class="color-field"><span>Hex</span><input id="colorHex" type="text" maxlength="7" inputmode="text" autocomplete="off"></label>
            <div class="color-actions"><button class="small-btn" id="cancelColor" type="button">Cancel</button><button class="small-btn primary" id="useColor" type="button">Use Color</button></div>
          </div>
        </div>
      </details>
      <?php endif; ?>
      <?php if ($authEnabled): ?><?php if ($loggedIn): ?><a class="top-btn link-btn" href="logout.php">Logout</a><?php else: ?><a class="top-btn link-btn" href="login.php">Login</a><?php endif; ?><?php endif; ?>
    </div>
  </header>

  <section class="status-tabs" aria-label="Node summary"><div class="status-tab"><span>ASL3</span><b id="systemTop">—</b></div><div class="status-tab"><span>RX</span><b id="rxTop">—</b></div><div class="status-tab"><span>TX</span><b id="txTop">—</b></div><div class="status-tab"><span>CONNECTIONS</span><b id="linksTop">0</b></div></section>
  <nav class="section-switcher" aria-label="Node Manager sections"><button type="button" class="section-tab active" data-mobile-panel="statusPanel" title="Node status, system information, and live activity">Status</button><button type="button" class="section-tab" data-mobile-panel="linkPanel" title="Connect to AllStarLink or EchoLink and manage Link Favorites">Link</button><button type="button" class="section-tab" data-mobile-panel="linksPanel" title="Monitor live connections, disconnect stations, and manage blocked nodes">Connections</button><button type="button" class="section-tab" data-mobile-panel="controlsPanel" title="Manage node operating controls and settings">Controls</button><button type="button" class="section-tab" data-mobile-panel="servicesPanel" title="Manage system services, DTMF commands, and configuration backups">Services</button></nav>

  <main class="dashboard">
    <section class="panel mobile-panel active" id="statusPanel">
      <div class="panel-head compact-head"><div><div class="eyebrow">NODE STATUS</div><h2><?=htmlspecialchars('Node ' . $node, ENT_QUOTES, 'UTF-8')?></h2></div><div class="panel-meta status-last-check" aria-live="polite"><span class="dot ok" id="updateDot"></span><span id="lastUpdate">Checking…</span></div></div>
      <div class="summary-grid system-summary-grid" aria-label="System information">
        <div class="summary"><span>LAN IP</span><strong id="sysLanIp">—</strong></div>
        <div class="summary"><span>DATE / TIME</span><strong id="sysDateTime">—</strong></div>
        <div class="summary"><span>CPU USAGE</span><strong id="sysCpu">—</strong></div>
        <div class="summary"><span>RAM USAGE</span><strong id="sysRam">—</strong></div>
        <div class="summary"><span>NETWORK UP</span><strong id="sysNetUp">—</strong></div>
        <div class="summary"><span>NETWORK DOWN</span><strong id="sysNetDown">—</strong></div>
        <div class="summary"><span>TEMPERATURE</span><strong id="sysTemp">—</strong></div>
        <div class="summary"><span>UPTIME</span><strong id="sysUptime">—</strong></div>
        <div class="summary"><span>ROOT DISK</span><strong id="sysRootDisk">—</strong></div>
        <div class="summary"><span>APACHE DISK</span><strong id="sysApacheDisk">—</strong></div>
      </div>
      <div class="summary-grid"><div class="summary"><span>NODE</span><strong id="nodeValue"><?=htmlspecialchars($node, ENT_QUOTES, 'UTF-8')?></strong></div><div class="summary"><span>ASTERISK</span><strong id="asteriskState">—</strong></div><div class="summary"><span>APP_RPT</span><strong id="appRptState">—</strong></div><div class="summary"><span>INTERFACE</span><strong id="driverState">—</strong></div><div class="summary"><span>SYSTEM</span><strong id="systemState">—</strong></div><div class="summary"><span>LINK COMMANDS</span><strong id="linkingState">—</strong></div><div class="summary"><span>TIMEOUT</span><strong id="timeoutState">—</strong></div><div class="summary"><span>TELEMETRY</span><strong id="telemetryState">—</strong></div><div class="summary"><span>AUTOPATCH</span><strong id="autopatchState">—</strong></div><div class="summary"><span>ALL LINKS</span><strong id="allLinksState">0</strong></div></div>
      <div class="channel-line"><span>RX</span><code id="rxChannel">—</code><span>TX</span><code id="txChannel">—</code></div>
    </section>

    <section class="panel mobile-panel" id="linksPanel">
      <div class="panel-head compact-head"><div><div class="eyebrow">LIVE CONNECTIONS</div><h2>Current Connections</h2></div><span class="connections-head-actions"><span class="count-badge" id="directCount">0</span><button type="button" id="mobileConnectionsToggle" class="mobile-connections-toggle" aria-expanded="true" aria-controls="mobileConnectionsContent" hidden>Hide</button></span></div>
      <div id="mobileConnectionsContent">
      <div id="connectionActionResult" class="action-result" hidden></div>
      <div class="connection-filter-row"><label class="sr-only" for="connectionSearch">Find connected node or callsign</label><div class="clear-input-wrap"><input id="connectionSearch" type="text" placeholder="Search Connections" autocomplete="off" aria-label="Search current Connections"><button type="button" class="input-clear" data-clear-for="connectionSearch" aria-label="Clear Connections search" title="Clear search" hidden>×</button></div></div>
      <div class="links-table"><div class="link-row link-head"><span>STATUS</span><span>DIRECTION</span><span>NODE / STATION</span><span>MODE</span><span class="desktop-connection-detail">TIME</span><span class="desktop-connection-detail">LINK</span><span class="desktop-connection-detail" title="Save an active station to Link Favorites">FAVORITE</span><span>ACTIONS</span></div><div id="linksBody"><div class="empty">Waiting for status…</div></div></div>
      <div class="compact-note">Node Restore automatically reconnects only proven outbound numeric AllStar links. WT and EchoLink are disconnect-only.</div>
      </div>
      <div class="blocked-section"><div class="panel-head compact-head blocked-head"><div><div class="eyebrow">DENYLIST</div><div class="blocked-title-line"><h2>Blocked Nodes</h2><span id="blockedCount" class="blocked-count-inline">0</span></div></div><div class="manual-block-head-actions"><button type="button" id="openManualBlock" class="manual-block-launch" title="Manually block an AllStar node by number; disconnects it if active and denies future incoming access. EchoLink and Web Transceiver cannot be blocked." <?=$canControl?'':'disabled'?>>Manual Block Node</button></div></div><div class="blocked-table"><div class="blocked-row blocked-head-row"><span>NODE</span><span>REASON</span><span>ACTION</span></div><div id="blockedBody"><div class="empty">No blocked nodes.</div></div></div></div>
    </section>
      <div id="manualBlockDialog" class="manual-block-dialog" role="dialog" aria-modal="true" aria-labelledby="manualBlockTitle" hidden>
        <div class="manual-block-box">
          <div class="manual-block-heading"><h3 id="manualBlockTitle">Manually Block AllStar Node</h3><button type="button" id="manualBlockClose" title="Close without blocking" aria-label="Close Manual Block">×</button></div>
          <p>Blocks future incoming access from this AllStar node. If currently connected, it will be disconnected. EchoLink and WT are disconnect-only.</p>
          <form id="manualBlockForm">
            <label for="manualBlockTarget">Node Number</label>
            <input id="manualBlockTarget" type="text" inputmode="numeric" pattern="[0-9]{4,7}" maxlength="7" autocomplete="off" placeholder="4–7 digit AllStar node" required>
            <label for="manualBlockReason">Reason (optional)</label>
            <input id="manualBlockReason" type="text" maxlength="80" autocomplete="off" placeholder="Blocked with ASL3 Node Manager">
            <p id="manualBlockFeedback" class="manual-block-feedback" role="status" hidden></p>
            <div class="manual-block-footer"><button type="button" id="manualBlockCancel">Cancel</button><button type="submit" id="manualBlockSubmit" class="manual-block-danger">Block Node</button></div>
          </form>
        </div>
      </div>

    <section class="panel mobile-panel" id="linkPanel" aria-labelledby="linkPanelTitle">
      <div class="panel-head compact-head"><div><div class="eyebrow">OUTBOUND CONNECTIONS</div><h2 id="linkPanelTitle">Link &amp; Favorites</h2></div><span class="control-lock <?=$canControl ? 'ready' : ''?>"><?=$canControl ? 'Ready' : 'Login required'?></span></div>
      <div class="link-workspace">
        <section class="link-card" aria-labelledby="linkConnectHeading">
          <div class="link-card-title"><h3 id="linkConnectHeading" title="Enter an AllStarLink or EchoLink target, search by callsign, or load a Favorite to connect.">Connect</h3></div>
          <div class="link-network-options" role="radiogroup" aria-label="Network">
            <label class="link-network-choice" title="Connect to an AllStarLink node"><input type="radio" name="linkNetwork" value="ASL" checked><span>AllStarLink</span></label>
            <label class="link-network-choice" title="EchoLink allows multiple incoming callers, but only one outgoing link; outbound requests are blocked while incoming callers are active"><input type="radio" name="linkNetwork" value="ECHO" disabled><span>EchoLink</span></label>
          </div>
          <label class="link-field" for="linkTarget" title="Enter a node number or search an exact callsign"><span>Node Number or Callsign</span></label>
          <div class="link-target-row">
            <div class="clear-input-wrap"><input id="linkTarget" title="AllStarLink or EchoLink node number, or callsign to look up" type="text" maxlength="40" autocomplete="off" spellcheck="false" placeholder="AllStar node or callsign" aria-label="Node number or callsign"><button type="button" class="input-clear" data-clear-for="linkTarget" aria-label="Clear node or callsign" title="Clear input" hidden>×</button></div>
            <button type="button" id="linkLookup" title="Search for this station" aria-label="Search station" class="link-icon-button" <?=$canControl?'':'disabled'?>><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6"/><path d="m16 16 5 5"/></svg></button>
            <button type="button" id="linkSaveFavorite" title="Save or edit Link Favorite" aria-label="Save Favorite" class="link-icon-button link-star" <?=$canControl?'':'disabled'?>>★</button>
          </div>
          <button type="button" id="linkConnect" title="Connect the selected station in the chosen Transceive or Local Monitor mode. Existing connections are not changed." class="link-connect-btn" <?=$canControl?'':'disabled'?>>CONNECT</button>
          <fieldset class="link-modes"><legend title="Choose Transceive or Local Monitor before connecting. Changing this selection does not alter any active connection; disconnect first to reconnect in a different mode.">Link Mode</legend><div class="link-mode-options">
            <label title="Two-way audio: Transceive"><input type="radio" name="linkMode" value="transceive" checked><span>Transceive</span></label>
            <label title="Receive the remote audio locally without retransmitting it"><input type="radio" name="linkMode" value="local_monitor"><span>Local Monitor</span></label>
          </div></fieldset>
          <label class="link-audio-option" title="Announce actual connected and disconnected stations through this device when the page is open. Turn off any time."><input id="linkAudioAlerts" type="checkbox"><span>Audio alerts</span></label>
          <div id="linkResult" class="action-result link-result" role="status" aria-live="polite" hidden></div>
        </section>
        <section class="link-card link-fav-card" aria-labelledby="linkFavoritesHeading">
          <div class="link-card-title"><h3 id="linkFavoritesHeading" title="Saved Link Favorites. Load a station to use its saved network and mode. Edit and Delete are visible alongside Load on all screens.">Favorites</h3><span class="link-subtitle" id="linkFavoriteCount"></span></div>
          <div class="clear-input-wrap"><input id="linkFavoriteSearch" title="Filter saved Link Favorites by number, name, description or network" type="text" maxlength="60" placeholder="Search Favorites" aria-label="Search Link Favorites"><button type="button" class="input-clear" data-clear-for="linkFavoriteSearch" aria-label="Clear Favorites search" title="Clear search" hidden>×</button></div>
          <div class="link-fav-head"><button type="button" data-link-sort="node" title="Sort Favorites by node number">NODE <span class="sort-arrow" aria-hidden="true"></span></button><button type="button" data-link-sort="station" title="Sort Favorites by station name">STATION <span class="sort-arrow" aria-hidden="true"></span></button><button type="button" data-link-sort="network" title="Sort Favorites by network">NETWORK <span class="sort-arrow" aria-hidden="true"></span></button><span>ACTIONS</span></div>
          <div id="linkFavorites" class="link-favorites"><div class="empty">Loading Favorites…</div></div>
        </section>
      </div>
      <div class="link-modal" id="linkLookupDialog" hidden role="dialog" aria-modal="true" aria-labelledby="linkLookupDialogTitle">
        <div class="link-modal-inner"><div class="link-modal-head"><h3 id="linkLookupDialogTitle">Select Station</h3><button type="button" data-link-close="linkLookupDialog" aria-label="Close lookup">Close ×</button></div><div id="linkLookupMatches"></div></div>
      </div>
      <div class="link-modal" id="linkFavoriteDialog" hidden role="dialog" aria-modal="true" aria-labelledby="linkFavoriteDialogTitle">
        <div class="link-modal-inner"><div class="link-modal-head"><h3 id="linkFavoriteDialogTitle">Save Favorite</h3><button type="button" data-link-close="linkFavoriteDialog" aria-label="Close Favorite">Close ×</button></div>
          <form id="linkFavoriteForm"><label>Node <input id="linkFavTarget" readonly></label><label>Station Name <input id="linkFavName" maxlength="96" required></label><label>Description <input id="linkFavDescription" maxlength="160"></label><div class="link-modal-actions"><button type="button" data-link-close="linkFavoriteDialog">Cancel</button><button type="submit" class="link-connect-btn" <?=$canControl?'':'disabled'?>>Save Favorite</button></div></form>
        </div>
      </div>
    </section>

    <section class="panel mobile-panel" id="controlsPanel">
      <div class="panel-head compact-head"><div><div class="eyebrow">ASL3 NODE CONTROL</div><h2>Controls</h2></div><span class="control-lock <?=$canControl ? 'ready' : ''?>"><?=$canControl ? 'Available' : 'Login required'?></span></div>
      <div id="actionResult" class="action-result" hidden></div>
      <div class="control-state-grid"><div><span>System</span><b id="systemControlState">—</b></div><div><span>Incoming</span><b id="incomingControlState">—</b></div><div><span>Link Commands</span><b id="linkControlState">—</b></div><div><span>Connections</span><b id="connectionsControlState">—</b></div></div>
      <div class="control-layout refined-controls">
        <div class="control-column">
          <section class="control-group">
            <div class="control-group-head"><div><div class="eyebrow">CONNECTION ACCESS</div><h3>Incoming Connections</h3></div><p>Choose whether new stations may connect. Existing sessions stay up unless disconnected separately.</p></div>
            <div class="control-actions two-up">
              <div class="control-item"><button class="control-btn warning" data-action="incoming-block" data-confirm="Block new incoming connections? Existing connections will stay connected." <?=$canControl ? '' : 'disabled'?>>Block New Incoming</button><button type="button" class="control-help" aria-label="About Block New Incoming" data-help="Prevent new incoming connections. Existing sessions stay connected until separately disconnected.">i</button></div>
              <div class="control-item"><button class="control-btn success" data-action="incoming-allow" <?=$canControl ? '' : 'disabled'?>>Allow New Incoming</button><button type="button" class="control-help" aria-label="About Allow New Incoming" data-help="Allow new incoming connections again. This does not create a connection by itself.">i</button></div>
            </div>
          </section>
          <section class="control-group">
            <div class="control-group-head"><div><div class="eyebrow">ACTIVE CONNECTIONS</div><h3>Disconnect Current Sessions</h3></div><p>Disconnect current NODE, WT, and EchoLink sessions without blocking later reconnects.</p></div>
            <div class="control-actions one-up">
              <div class="control-item"><button class="control-btn danger" data-action="disconnect-all" data-confirm="Disconnect every current AllStar, Web Transceiver, and EchoLink connection from this ASL3 node?" <?=$canControl ? '' : 'disabled'?>>Disconnect All Connections</button><button type="button" class="control-help" aria-label="About Disconnect All Connections" data-help="Disconnect every current supported session. This does not block a later reconnect by itself.">i</button></div>
            </div>
          </section>
        </div>
        <section class="control-group node-state-group">
          <div class="control-group-head"><div><div class="eyebrow">NODE STATE</div><h3>Isolation / Restore</h3></div><p>Take the ASL3 node offline, or restore the saved operating state and eligible outbound numeric links.</p></div>
          <div class="control-actions node-state-actions">
            <div class="control-item"><button class="control-btn danger" data-action="node-offline" data-confirm="Take this ASL3 node offline?" <?=$canControl ? '' : 'disabled'?>>Take ASL3 Node Offline</button><button type="button" class="control-help" aria-label="About Take ASL3 Node Offline" data-help="Save state, block new incoming connections, disconnect AllStar/WT/EchoLink, disable link commands, then disable the ASL3 system.">i</button></div>
            <div class="control-item"><button class="control-btn success" data-action="node-restore" data-confirm="Restore the saved ASL3 operating state and reconnect only proven-safe outbound numeric links?" <?=$canControl ? '' : 'disabled'?>>Restore ASL3 Node + Eligible Links</button><button type="button" class="control-help" aria-label="About Restore ASL3 Node" data-help="Restore saved System, link-command, and incoming state. Only proven outbound numeric AllStar links are auto-restored. Reconnection may take about 10 seconds. Unknown or unverified modes are skipped and reported.">i</button></div>
          </div>
          <div class="compact-note">Restore never guesses: inbound AllStar, WT, EchoLink, and unknown-mode sessions reconnect separately.</div>
        </section>
      </div>
    </section>

    <section class="panel mobile-panel" id="servicesPanel">
      <div class="panel-head compact-head"><div><div class="eyebrow">ASL3 NODE SERVICES</div><h2>Services</h2></div><span class="control-lock <?=$canControl ? 'ready' : ''?>"><?=$canControl ? 'Available' : 'Login required'?></span></div>
      <div class="services-grid">
        <section class="services-card"><h3>ASL3 Maintenance</h3><p>Service status and controlled reload / restart.</p>
          <div class="services-status"><span>Asterisk <b id="svcAsterisk">—</b></span><span>Apache <b id="svcApache">—</b></span></div>
          <div class="services-actions">
          <button data-service="asterisk-reload" title="Reload Asterisk configuration; active calls can be affected.">Reload Asterisk</button>
          <button data-service="app-rpt-reload" title="Reload app_rpt module configuration; may affect radio linking and active sessions.">Reload app_rpt</button>
          <button data-service="apache-reload" title="Reload Apache configuration; normally brief, but web requests may be affected.">Reload Apache</button>
          <button data-service="asterisk-restart" class="danger" title="Restart Asterisk. Disconnects all active calls and links.">Restart Asterisk</button>
          <button data-service="apache-restart" class="danger" title="Restart Apache; the browser session may be interrupted.">Restart Apache</button>
          </div>
        </section>
        <section class="services-card"><h3>DTMF Commands</h3>
          <p>Enter the complete command, including * or # when required. Example: <strong>*921</strong> (Parrot On).</p>
          <div class="dtmf-input-row"><div class="clear-input-wrap"><input id="svcDtmfCode" maxlength="14" placeholder="Example: *921" aria-label="Complete DTMF command"><button type="button" class="input-clear" data-clear-for="svcDtmfCode" aria-label="Clear DTMF command" title="Clear DTMF without sending" hidden>×</button></div><button id="svcDtmfSend" class="primary" type="button" title="Submit the entered command to Asterisk. This does not confirm the function executed.">Send</button></div>
          <div class="svc-launch-row"><span><strong>Saved Favorites</strong><small id="svcFavoriteCount">0 saved</small></span><button id="svcOpenFavorites" type="button" title="Manage Favorites. Loading a Favorite fills the command box; press Send separately.">Open Favorites</button></div>
        </section>
        <section class="services-card services-backup-card"><h3>Configuration Backups</h3>
          <p>Create a protected local backup, or browse your existing archives when needed.</p>
          <div class="svc-backup-primary">
            <button id="svcBackupCreate" class="primary" type="button" title="Create a configuration backup in /var/backups/asl3-node-manager/asl3-config/. The archive can be verified, downloaded, restored, or deleted.">Create New Backup</button>
            <div class="svc-backup-location">Saved privately on this node · Restore with safety backup and Asterisk restart</div>
          </div>
          <div class="svc-backup-launches">
            <button type="button" id="svcOpenManagerBackups" title="Browse backups in /var/backups/asl3-node-manager/asl3-config/. Verify, download, restore, or delete archives.">Node Manager Backups <span id="svcBackupCount">—</span></button>
            <button type="button" id="svcOpenOfficialBackups" title="Browse official asl-menu backups in /var/asl-backups/. Verify, download, restore, or delete archives.">Official ASL3 Backups <span id="svcOfficialBackupCount">—</span></button>
          </div>
        </section>
      </div>
      <div class="action-result" id="svcResult" role="status" aria-live="polite" hidden></div>
      <div class="svc-activity" id="svcActivity"><div class="svc-activity-head"><strong>Recent Services activity</strong><button type="button" id="svcActivityClear" class="svc-activity-clear" title="Clear recent activity messages">Clear</button></div><div id="svcActivityLog" class="svc-activity-log" role="status" aria-live="polite">No operations in this session.</div></div>
      <div class="svc-modal" id="svcRestoreConfirm" role="alertdialog" aria-modal="true" aria-labelledby="svcRestoreConfirmTitle" hidden>
        <div class="svc-modal-box svc-restore-confirm-box"><div class="svc-modal-head"><h3 id="svcRestoreConfirmTitle">Confirm Configuration Restore</h3></div>
          <p id="svcRestoreDescription" class="svc-modal-note"></p>
          <div id="svcRestoreArchive" class="svc-restore-archive"></div>
          <p class="svc-modal-note">WARNING: Restoring replaces current supported configuration and data with files from the selected backup. Changes made after the backup may be permanently lost. Node Manager will stop Asterisk, create a protected safety backup, restore the archived files, and restart Asterisk. All active calls and links will disconnect. If restoration fails, a rollback will be attempted.</p>
          <input type="hidden" id="svcRestoreSource"><input type="hidden" id="svcRestoreName">
          <div class="svc-confirm-buttons"><button type="button" id="svcRestoreCancel" title="Cancel restoration without changing the node.">Cancel</button><button type="button" id="svcRestoreProceed" class="svc-restore-danger" title="Overwrite supported current files with this backup, create a safety backup, and restart Asterisk. Newer changes may be lost.">Restore & Restart Asterisk</button></div>
        </div>
      </div>
      <div class="svc-modal" id="svcFavoritesDialog" role="dialog" aria-modal="true" aria-labelledby="svcFavoritesTitle" hidden>
        <div class="svc-modal-box"><div class="svc-modal-head"><h3 id="svcFavoritesTitle">DTMF Favorites</h3><button type="button" data-svc-close title="Close Favorites">Close ×</button></div>
          <p class="svc-modal-note">Load puts the command in the DTMF field. Press Send separately.</p>
          <label class="svc-sort-label" for="svcFavoriteSort">Sort <select id="svcFavoriteSort"><option value="alpha">Name A–Z</option><option value="code">Command 0–9</option><option value="code-alpha">Command, then name</option></select></label>
          <div id="svcFavorites" class="svc-favorites svc-modal-list">Loading…</div>
          <div class="svc-editor"><input id="svcFavName" maxlength="64" placeholder="Favorite description" aria-label="Favorite description"><input id="svcFavCode" maxlength="14" placeholder="Example: *921" aria-label="Favorite DTMF code"><button id="svcFavSave" type="button" title="Save without sending the DTMF command">Add Favorite</button><button id="svcFavCancel" type="button" hidden>Cancel Edit</button></div>
        </div>
      </div>
      <div class="svc-modal" id="svcManagerDialog" role="dialog" aria-modal="true" aria-labelledby="svcManagerTitle" hidden>
        <div class="svc-modal-box"><div class="svc-modal-head"><h3 id="svcManagerTitle">Node Manager Backups</h3><button type="button" data-svc-close title="Close this backup list">Close ×</button></div>
          <p class="svc-modal-note">Node Manager backups: /var/backups/asl3-node-manager/asl3-config/. Verify, download, restore, or delete archives.</p><div id="svcManagerResult" class="svc-inline-result" role="status" aria-live="polite" hidden></div><div id="svcBackups" class="svc-backups svc-modal-list">Loading…</div>
        </div>
      </div>
      <div class="svc-modal" id="svcOfficialDialog" role="dialog" aria-modal="true" aria-labelledby="svcOfficialTitle" hidden>
        <div class="svc-modal-box"><div class="svc-modal-head"><h3 id="svcOfficialTitle">Official ASL3 Backups</h3><button type="button" data-svc-close title="Close this backup list">Close ×</button></div>
          <p class="svc-modal-note">Official asl-menu backups: /var/asl-backups/. Verify, download, restore, or delete archives.</p><div id="svcOfficialResult" class="svc-inline-result" role="status" aria-live="polite" hidden></div><div id="svcOfficialBackups" class="svc-backups svc-modal-list">Loading…</div>
        </div>
      </div>

    </section>
  </main>
  <div id="controlHelpTip" class="control-help-tip" role="tooltip" aria-hidden="true" hidden></div>
  <footer><span>ASL3 Node Manager <?=htmlspecialchars($version, ENT_QUOTES, 'UTF-8')?> · Node <?=htmlspecialchars($node, ENT_QUOTES, 'UTF-8')?></span><span>Status refresh · 1 sec</span></footer>
</div>
<script src="assets/app.js?v=<?=rawurlencode($version)?>-<?=filemtime(__DIR__ . "/assets/app.js")?>"></script>
</body></html>
