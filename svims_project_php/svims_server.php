<?php
/**
 * SVIMS CampusBot Server (PHP port of svims_server.py)
 * =====================================================
 * Run:  php svims_server.php      (port 5000 — index.html wahi URL use karta hai)
 * Ya:   php -S 127.0.0.1:5000 svims_server.php
 *
 * Routes bilkul same hain:
 *   GET  /                    -> index.html
 *   POST /api/chat            -> { response }
 *   GET  /api/status          -> { status, bot, version }
 *   POST /api/reload-config   -> config hot-reload
 *   GET  /api/model-status    -> model blacklist/active status
 *   POST /api/rebuild         -> knowledge base rebuild (admin)
 */

require_once __DIR__ . '/svims_lib.php';
require_once __DIR__ . '/svims_processor.php';
require_once __DIR__ . '/svims_engine.php';

// load_dotenv(dotenv_path=...); load_dotenv()
svims_load_dotenv(__DIR__ . '/.env');
svims_load_dotenv();

/* ══════════════════════════════════════════════════════════
   CLI MODE — Python module-level startup ka exact equivalent:
   KB load/build + chatbot init, phir built-in server start.
   ══════════════════════════════════════════════════════════ */
if (PHP_SAPI === 'cli' && !defined('SVIMS_ROUTER_TEST')) {
    echo "⚙️  SVIMS CampusBot Server starting...\n";

    // Fresh process state — Python mein har run pe dicts empty hote the
    SVIMSSessionStore::clearAll(__DIR__ . '/svims_sessions');
    foreach ((array)glob(__DIR__ . '/svims_runtime/*.json') as $f) @unlink($f);

    $startup_error = null;
    try {
        SVIMSEngine::init();
        $v_store = load_knowledge_base();
        if ($v_store === null) {
            echo "🔄 Building fresh knowledge base...\n";
            $v_store = create_knowledge_base();
        }
        $bot_chain = create_chatbot($v_store);
        echo "✅ Server ready!\n";
    } catch (Throwable $e) {
        $startup_error = $e->getMessage();
        echo "🚨 Startup Error: {$startup_error}\n";
        echo "   (Server phir bhi start ho raha hai — /api/chat error message dikhayega)\n";
    }

    echo "🚀 Server: http://127.0.0.1:5000\n";
    $php_bin = PHP_BINARY ?: 'php';
    passthru(escapeshellarg($php_bin) . ' -S 127.0.0.1:5000 ' . escapeshellarg(__FILE__));
    exit;
}

/* ══════════════════════════════════════════════════════════
   ROUTER MODE — php -S har request pe ye script chalata hai.
   (Flask app ke route handlers ka equivalent)
   ══════════════════════════════════════════════════════════ */

svims_cors_headers(); // CORS(app)
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
    http_response_code(200);
    exit;
}

try {
    SVIMSEngine::init();
} catch (Throwable $e) {
    // Python mein engine import fail hone par server start hi nahi hota tha.
    // API routes pe error dete hain; static page serve hoti rahti hai.
    if (!isset($_SERVER['REQUEST_URI']) || strpos($_SERVER['REQUEST_URI'], '/api/') === false) {
        header('Content-Type: text/html; charset=utf-8');
        readfile(__DIR__ . '/index.html');
        exit;
    }
    svims_json_response(['error' => $e->getMessage()], 500);
    exit;
}

function svims_server_get_chain(): array {
    static $chain = null;
    if ($chain !== null) return $chain;
    $v_store = load_knowledge_base();
    if ($v_store === null) {
        svims_log("🔄 Building fresh knowledge base...");
        $v_store = create_knowledge_base();
    }
    $chain = create_chatbot($v_store);
    return $chain;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if (!is_string($path) || $path === '') $path = '/';

/* ── @app.route("/") ── */
if ($path === '/' && $method === 'GET') {
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/index.html');
    exit;
}

/* ── @app.route("/api/chat", methods=["POST"]) ── */
if ($path === '/api/chat' && $method === 'POST') {
    $data = svims_read_json_body();
    $user_msg = trim((string)(isset($data['message']) ? $data['message'] : ''));
    $session_id = (string)(isset($data['session_id']) ? $data['session_id'] : 'default');

    if ($user_msg === '') {
        svims_json_response(['error' => 'Empty message'], 400);
        exit;
    }

    $store = new SVIMSSessionStore(__DIR__ . '/svims_sessions');
    $history = $store->get($session_id);

    try {
        $chain = svims_server_get_chain();
        // ✅ History pass karo — context maintain hoga
        $answer = get_answer($chain, $user_msg, $history);
    } catch (Throwable $e) {
        svims_json_response(['error' => $e->getMessage()], 500);
        exit;
    }

    $history[] = ['role' => 'user', 'content' => $user_msg];
    $history[] = ['role' => 'assistant', 'content' => $answer];

    if (count($history) > 10) {
        $history = array_slice($history, -10);
    }
    $store->set($session_id, $history);

    svims_json_response(['response' => $answer]);
    exit;
}

/* ── @app.route("/api/status", methods=["GET"]) ── */
if ($path === '/api/status' && $method === 'GET') {
    svims_json_response(['status' => 'online', 'bot' => 'SVIMS CampusBot', 'version' => '2.0']);
    exit;
}

/* ── @app.route("/api/reload-config", methods=["POST"]) ──
   Config hot-reload — bina server restart ke svims_config.json ke changes
   apply ho jaate hain. Fees, calendar link, achievement links, syllabus links,
   show_staff_phones — sab reload ho jaata hai.

   Use: browser ya terminal se POST request bhejo:
     curl -X POST http://127.0.0.1:5000/api/reload-config
   Ya index.html mein ek hidden admin button bana sakte ho.
   ────────────────────────────────────────────────────────────
   NOTE: Python version _build_syllabus_answers()/_build_all_syllabus_text()
   call karta hai jo engine mein defined NAHI hain — isliye Python mein ye
   endpoint config update karke bhi 500 error return karta tha. Wahi exact
   behaviour yahan bhi maintain kiya hai (logic change nahi kiya). */
if ($path === '/api/reload-config' && $method === 'POST') {
    try {
        // Config file dobara padhte hain
        $new_cfg = SVIMSEngine::_load_config();
        SVIMSEngine::$CFG = $new_cfg;
        SVIMSEngine::$SHOW_STAFF_PHONES   = isset($new_cfg['show_staff_phones']) ? (bool)$new_cfg['show_staff_phones'] : false;
        SVIMSEngine::$ACADEMIC_CALENDAR   = isset($new_cfg['academic_calendar']) ? $new_cfg['academic_calendar'] : SVIMSEngine::$ACADEMIC_CALENDAR;
        SVIMSEngine::$SYLLABUS_CFG        = isset($new_cfg['syllabus_links']) ? $new_cfg['syllabus_links'] : [];
        SVIMSEngine::$ACHIEVEMENT_CFG     = isset($new_cfg['achievement_links']) ? $new_cfg['achievement_links'] : [];
        SVIMSEngine::$FEES_CFG            = isset($new_cfg['fees']) ? $new_cfg['fees'] : [];
        SVIMSEngine::$MODELS_TO_TRY       = isset($new_cfg['groq_models']) ? $new_cfg['groq_models'] : SVIMSEngine::$MODELS_TO_TRY;
        // Blacklist reset karo — naye models tryable ho jaayein
        SVIMSEngine::$BLACKLISTED_MODELS = [];
        SVIMSEngine::$LIVE_MODELS_CACHE = [];
        svims_state_write('model_state', [
            'blacklist' => [], 'live_cache' => [], 'fetched_at' => 0,
        ]);
        // Dependent data rebuild karo
        SVIMSEngine::$SYLLABUS_ANSWERS    = SVIMSEngine::_build_syllabus_answers();
        SVIMSEngine::$ALL_SYLLABUS_ANSWER = SVIMSEngine::_build_all_syllabus_text();
        SVIMSEngine::_build_faculty_answers();
        // Response cache clear karo taaki purane answers serve na hon
        svims_state_write('response_cache', []);
        svims_json_response([
            'status' => 'reloaded',
            'show_staff_phones' => SVIMSEngine::$SHOW_STAFF_PHONES,
            'calendar_year' => isset(SVIMSEngine::$ACADEMIC_CALENDAR['year']) ? SVIMSEngine::$ACADEMIC_CALENDAR['year'] : null,
            'student_achievement_year' => isset(SVIMSEngine::$ACHIEVEMENT_CFG['student_year']) ? SVIMSEngine::$ACHIEVEMENT_CFG['student_year'] : null,
            'models' => SVIMSEngine::$MODELS_TO_TRY,
            'message' => '✅ Config reloaded — changes active immediately (no restart needed)',
        ]);
    } catch (Throwable $e) {
        svims_json_response(['status' => 'error', 'message' => $e->getMessage()], 500);
    }
    exit;
}

/* ── @app.route("/api/model-status", methods=["GET"]) ──
   Kaunse models active hain, kaunse blacklist mein hain — status check. */
if ($path === '/api/model-status' && $method === 'GET') {
    try {
        svims_json_response([
            'configured_models' => SVIMSEngine::$MODELS_TO_TRY,
            'blacklisted' => array_values(SVIMSEngine::$BLACKLISTED_MODELS),
            'active_models' => SVIMSEngine::_get_active_models(),
            'live_models_cached' => SVIMSEngine::$LIVE_MODELS_CACHE,
        ]);
    } catch (Throwable $e) {
        svims_json_response(['error' => $e->getMessage()], 500);
    }
    exit;
}

/* ── @app.route("/api/rebuild", methods=["POST"]) ──
   Knowledge base rebuild karo (admin use) */
if ($path === '/api/rebuild' && $method === 'POST') {
    try {
        $v_store = create_knowledge_base();
        $bot_chain = create_chatbot($v_store);
        svims_json_response(['status' => 'rebuilt', 'message' => 'Knowledge base rebuilt successfully']);
    } catch (Throwable $e) {
        svims_json_response(['status' => 'error', 'message' => $e->getMessage()], 500);
    }
    exit;
}

// Flask 404 equivalent
svims_json_response(['error' => 'Not Found'], 404);
