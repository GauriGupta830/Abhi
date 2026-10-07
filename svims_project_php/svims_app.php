<?php
/**
 * SVIMS CampusBot — PHP Backend (PHP port of svims_app.py)
 * =========================================================
 * Frontend (index.html) already tumhari di hui file hai — usko
 * bilkul touch nahi kiya. Ye backend usi ke API format se match karta hai:
 *
 *   POST /api/chat   { message, session_id }  ->  { response }
 *   GET  /api/status                           ->  { ready }
 *   POST /api/clear  { session_id }            ->  { ok }
 *
 * Backend logic (Groq calls, PDF matching, RAG) svims_engine.php /
 * svims_qa_loader.php / svims_processor.php se hi aata hai — unhe touch
 * nahi kiya.
 *
 * Run:  php svims_app.php        (0.0.0.0:5000 — same as Python version)
 * Ya:   php -S 0.0.0.0:5000 svims_app.php
 */

require_once __DIR__ . '/svims_lib.php';
require_once __DIR__ . '/svims_processor.php';
require_once __DIR__ . '/svims_engine.php';

// .env load
svims_load_dotenv(__DIR__ . '/.env');
svims_load_dotenv();

// ─────────────────────────────────────────────
// PER-SESSION CHAT HISTORY
// Frontend sirf current message bhejta hai + session_id, poori history
// nahi bhejta — isliye history yahan server pe track karte hain.
// NOTE: server restart hone pe history khatam ho jaati hai (launcher
// sessions wipe karta hai — Python ke in-memory dict jaisa behaviour).
// ─────────────────────────────────────────────
define('SVIMS_APP_SESSIONS_DIR', __DIR__ . '/svims_sessions_app');
define('SVIMS_MAX_HISTORY_TURNS', 12); // per session kitne purane messages yaad rakhein

function svims_app_get_history(SVIMSSessionStore $store, string $session_id): array {
    return $store->get($session_id);
}

function svims_app_trim_history(array $history): array {
    // Zyada purani history hatate jao taaki memory na badhe
    if (count($history) > SVIMS_MAX_HISTORY_TURNS * 2) {
        $history = array_slice($history, count($history) - SVIMS_MAX_HISTORY_TURNS * 2);
    }
    return $history;
}

/* ══════════════════════════════════════════════════════════
   CLI MODE — KNOWLEDGE BASE + CHATBOT — ek baar app start
   hone pe load hota hai (Python module-level code equivalent)
   ══════════════════════════════════════════════════════════ */
if (PHP_SAPI === 'cli' && !defined('SVIMS_ROUTER_TEST')) {
    echo "🎓 SVIMS CampusBot loading knowledge base...\n";

    // Fresh process state
    SVIMSSessionStore::clearAll(SVIMS_APP_SESSIONS_DIR);
    foreach ((array)glob(__DIR__ . '/svims_runtime/*.json') as $f) @unlink($f);

    $_load_error = null;
    try {
        SVIMSEngine::init();
        $vector_store = load_knowledge_base();
        if ($vector_store === null) {
            echo "🔄 Knowledge base not found — building fresh (1-2 mins)...\n";
            $vector_store = create_knowledge_base();
        }
        $_chain = create_chatbot($vector_store);
        echo "✅ CampusBot ready!\n";
    } catch (Throwable $e) {
        $_load_error = $e->getMessage();
        echo "🚨 Startup Error: {$_load_error}\n";
    }

    // Local development ke liye. Production/deploy ke liye PHP-FPM/Apache use karo.
    $php_bin = PHP_BINARY ?: 'php';
    passthru(escapeshellarg($php_bin) . ' -S 0.0.0.0:5000 ' . escapeshellarg(__FILE__));
    exit;
}

/* ══════════════════════════════════════════════════════════
   ROUTER MODE — per-request handlers
   ══════════════════════════════════════════════════════════ */

svims_cors_headers();
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// Engine init (per-request)
$_load_error = null;
try {
    SVIMSEngine::init();
} catch (Throwable $e) {
    $_load_error = $e->getMessage();
}

// ─────────────────────────────────────────────
// ROUTES
// ─────────────────────────────────────────────
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if (!is_string($path) || $path === '') $path = '/';

/** @return array|null chain, ya null jab KB na mile */
function svims_app_load_chain(): ?array {
    global $_load_error;
    try {
        $vector_store = load_knowledge_base();
        if ($vector_store === null) {
            $_load_error = 'Knowledge base not found — run: php svims_app.php';
            return null;
        }
        return create_chatbot($vector_store);
    } catch (Throwable $e) {
        $_load_error = $e->getMessage();
        return null;
    }
}

/* ── @app.route("/") ── */
if ($path === '/' && $method === 'GET') {
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/index.html');
    exit;
}

/* ── @app.route("/api/status") ── */
if ($path === '/api/status' && $method === 'GET') {
    $chain_ok = (svims_app_load_chain() !== null) && $_load_error === null;
    svims_json_response(['ready' => $chain_ok, 'error' => $_load_error]);
    exit;
}

/* ── @app.route("/api/chat", methods=["POST"]) ── */
if ($path === '/api/chat' && $method === 'POST') {
    $_chain = svims_app_load_chain();
    if ($_chain === null || $_load_error !== null) {
        svims_json_response(['response' => "⚠️ Bot not ready: {$_load_error}"], 500);
        exit;
    }

    $data = svims_read_json_body();
    $message = trim((string)(isset($data['message']) ? $data['message'] : ''));
    $session_id = (string)(isset($data['session_id']) && $data['session_id'] ? $data['session_id'] : 'default');

    if ($message === '') {
        svims_json_response(['response' => 'Please type a question.'], 400);
        exit;
    }

    $store = new SVIMSSessionStore(SVIMS_APP_SESSIONS_DIR);
    $history = svims_app_get_history($store, $session_id);

    try {
        $answer = get_answer($_chain, $message, $history);
    } catch (Throwable $e) {
        svims_log("Chat error: " . $e->getMessage());
        $answer = "Something went wrong: " . $e->getMessage() . "\n\nPlease contact svimi@svimi.org";
    }

    $history[] = ['role' => 'user', 'content' => $message];
    $history[] = ['role' => 'bot', 'content' => $answer];
    $history = svims_app_trim_history($history);
    $store->set($session_id, $history);

    svims_json_response(['response' => $answer]);
    exit;
}

/* ── @app.route("/api/clear", methods=["POST"]) ── */
if ($path === '/api/clear' && $method === 'POST') {
    $data = svims_read_json_body();
    $session_id = (string)(isset($data['session_id']) && $data['session_id'] ? $data['session_id'] : 'default');
    $store = new SVIMSSessionStore(SVIMS_APP_SESSIONS_DIR);
    $store->delete($session_id);
    svims_json_response(['ok' => true]);
    exit;
}

svims_json_response(['error' => 'Not Found'], 404);
