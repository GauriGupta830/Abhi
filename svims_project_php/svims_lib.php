<?php
/**
 * SVIMS CampusBot — PHP Support Library
 * ======================================
 * Ye file Python ke pip-packages ke PHP equivalents deti hai. Logic bilkul
 * same hai — sirf language badli hai:
 *
 *   python-dotenv        -> svims_load_dotenv()
 *   requests             -> svims_http_request() (cURL / stream fallback)
 *   BeautifulSoup        -> svims_html_to_text() (DOMDocument / strip_tags)
 *   RecursiveCharacterTextSplitter (langchain) -> class RecursiveCharacterTextSplitter
 *   pypdf / pdfplumber   -> svims_pdf_extract_text()
 *   sentence-transformers (all-MiniLM-L6-v2) -> class SVIMSEmbeddings
 *   FAISS vector store   -> class SVIMSVectorStore (cosine similarity)
 *   difflib (get_close_matches / SequenceMatcher) -> svims_get_close_matches()
 *   in-memory dicts      -> file-backed stores (PHP har request pe fresh
 *                           start hota hai, isliye state files mein rakhte
 *                           hain — behaviour same rehta hai)
 */

if (!defined('SVIMS_LIB_LOADED')) {
define('SVIMS_LIB_LOADED', 1);

/* ══════════════════════════════════════════════════════
   LOGGING — Python print() ka equivalent: server console
   (stderr) pe jaata hai, KABHI bhi HTTP response mein
   nahi aata.
   ══════════════════════════════════════════════════════ */

function svims_log(string $msg): void {
    if (PHP_SAPI === 'cli' && defined('STDERR')) {
        fwrite(STDERR, $msg . "\n");
    } else {
        error_log($msg);
    }
}

/* ══════════════════════════════════════════════════════
   TEXT HELPERS — Python str semantics (character-based,
   UTF-8 aware) jab mbstring available ho.
   ══════════════════════════════════════════════════════ */

function sv_strlen(string $s): int {
    if (function_exists('mb_strlen')) {
        $n = @mb_strlen($s, 'UTF-8');
        if ($n !== false) return $n;
    }
    return strlen($s);
}

function sv_substr(string $s, int $start, ?int $length = null): string {
    if (function_exists('mb_substr')) {
        $r = $length === null
            ? @mb_substr($s, $start, null, 'UTF-8')
            : @mb_substr($s, $start, $length, 'UTF-8');
        if ($r !== false) return $r;
    }
    return $length === null ? substr($s, $start) : substr($s, $start, $length);
}

function sv_strtolower(string $s): string {
    if (function_exists('mb_strtolower')) {
        $r = @mb_strtolower($s, 'UTF-8');
        if ($r !== false) return $r;
    }
    return strtolower($s);
}

function sv_chars(string $s): array {
    // list(text) equivalent — UTF-8 characters ka array
    if ($s === '') return [];
    $parts = preg_split('//u', $s, -1, PREG_SPLIT_NO_EMPTY);
    return $parts === false ? str_split($s) : $parts;
}

/* ══════════════════════════════════════════════════════
   DOTENV — python-dotenv equivalent
   (existing env vars overwrite NAHI hote — same as dotenv)
   ══════════════════════════════════════════════════════ */

function svims_load_dotenv(?string $path = null): void {
    if ($path === null) $path = getcwd() . '/.env';
    if (!is_file($path) || !is_readable($path)) return;
    $lines = @file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    if ($lines === false) return;
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        if (strpos($line, 'export ') === 0) $line = substr($line, 7);
        $eq = strpos($line, '=');
        if ($eq === false) continue;
        $key = trim(substr($line, 0, $eq));
        $val = trim(substr($line, $eq + 1));
        if ($key === '') continue;
        // quotes strip karo
        $len = strlen($val);
        if ($len >= 2 &&
            (($val[0] === '"' && $val[$len - 1] === '"') ||
             ($val[0] === "'" && $val[$len - 1] === "'"))) {
            $val = substr($val, 1, -1);
        }
        if (getenv($key) === false && !isset($_ENV[$key])) {
            putenv($key . '=' . $val);
            $_ENV[$key] = $val;
        }
    }
}

function svims_env(string $name, string $default = ''): string {
    $v = getenv($name);
    if ($v !== false && $v !== '') return $v;
    if (isset($_ENV[$name]) && $_ENV[$name] !== '') return $_ENV[$name];
    return $default;
}

/* ══════════════════════════════════════════════════════
   HTTP CLIENT — requests equivalent (cURL ya stream)
   return: ['status' => int|null, 'body' => string, 'error' => string|null]
   ══════════════════════════════════════════════════════ */

function svims_http_request(string $method, string $url, array $headers = [], ?string $body = null, float $timeout = 30.0): array {
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        if ($ch === false) {
            return ['status' => null, 'body' => '', 'error' => 'curl_init failed'];
        }
        curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, (int)max(1, ceil($timeout)));
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, (int)max(1, ceil(min($timeout, 15))));
        if (!empty($headers)) curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        if ($body !== null) curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        $resp = curl_exec($ch);
        if ($resp === false) {
            $err = curl_error($ch);
            curl_close($ch);
            return ['status' => null, 'body' => '', 'error' => $err ?: 'request failed'];
        }
        $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        return ['status' => (int)$status, 'body' => (string)$resp, 'error' => null];
    }

    // Fallback: PHP stream context (agar cURL extension nahi hai)
    $hdr = implode("\r\n", $headers);
    $ctx = @stream_context_create([
        'http' => [
            'method' => $method,
            'header' => $hdr,
            'content' => $body ?? '',
            'timeout' => $timeout,
            'ignore_errors' => true,
        ],
        'ssl' => ['verify_peer' => true, 'verify_peer_name' => true],
    ]);
    $resp = @file_get_contents($url, false, $ctx);
    if ($resp === false) {
        return ['status' => null, 'body' => '', 'error' => 'stream request failed'];
    }
    $status = null;
    if (isset($http_response_header) && is_array($http_response_header)) {
        foreach ($http_response_header as $h) {
            if (preg_match('/^HTTP\/\S+\s+(\d+)/', $h, $m)) $status = (int)$m[1];
        }
    }
    return ['status' => $status, 'body' => $resp, 'error' => null];
}

/* ══════════════════════════════════════════════════════
   HTTP SERVER HELPERS — Flask (jsonify / CORS) equivalent
   ══════════════════════════════════════════════════════ */

function svims_json_response($data, int $code = 200): void {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}

function svims_read_json_body(): array {
    // Flask request.json / request.get_json(force=True) equivalent
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        // Non-web SAPI fallback (e.g. CLI-server emulation/tests)
        $raw = isset($GLOBALS['HTTP_RAW_POST_DATA']) ? $GLOBALS['HTTP_RAW_POST_DATA'] : '';
    }
    if ($raw === '') return [];
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function svims_cors_headers(): void {
    // flask_cors(app) default — allow all origins
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization');
    header('Access-Control-Max-Age: 600');
}

/* ══════════════════════════════════════════════════════
   FILE-BACKED RUNTIME STATE — Python ke process-level
   globals/dicts ka equivalent (PHP har request fresh
   start hota hai, isliye state disk pe persist hoti hai)
   ══════════════════════════════════════════════════════ */

function svims_runtime_dir(): string {
    $dir = __DIR__ . '/svims_runtime';
    if (!is_dir($dir)) @mkdir($dir, 0777, true);
    return $dir;
}

function svims_state_read(string $name, $default = null) {
    $f = svims_runtime_dir() . '/' . $name . '.json';
    if (!is_file($f)) return $default;
    $raw = @file_get_contents($f);
    if ($raw === false || $raw === '') return $default;
    $data = json_decode($raw, true);
    return $data === null ? $default : $data;
}

function svims_state_write(string $name, $value): void {
    $f = svims_runtime_dir() . '/' . $name . '.json';
    @file_put_contents($f, json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), LOCK_EX);
}

/* ══════════════════════════════════════════════════════
   SESSION STORE — Flask ke in-memory session dict ka
   equivalent. Server start pe wipe hota hai (Python mein
   restart pe dict fresh hota tha — same behaviour).
   ══════════════════════════════════════════════════════ */

class SVIMSSessionStore {
    private $dir;

    public function __construct(string $dir) {
        $this->dir = $dir;
        if (!is_dir($dir)) @mkdir($dir, 0777, true);
    }

    private function file(string $session_id): string {
        $safe = preg_replace('/[^A-Za-z0-9_\-]/', '_', $session_id);
        if ($safe === '') $safe = 'default';
        return $this->dir . '/' . $safe . '.json';
    }

    public function get(string $session_id): array {
        $f = $this->file($session_id);
        if (!is_file($f)) return [];
        $data = json_decode((string)@file_get_contents($f), true);
        return is_array($data) ? $data : [];
    }

    public function set(string $session_id, array $history): void {
        @file_put_contents($this->file($session_id), json_encode($history, JSON_UNESCAPED_UNICODE), LOCK_EX);
    }

    public function delete(string $session_id): void {
        $f = $this->file($session_id);
        if (is_file($f)) @unlink($f);
    }

    public static function clearAll(string $dir): void {
        if (!is_dir($dir)) return;
        foreach ((array)glob($dir . '/*.json') as $f) @unlink($f);
    }
}

/* ══════════════════════════════════════════════════════
   RecursiveCharacterTextSplitter — langchain_text_splitters
   ka 1:1 port (chunk_size, chunk_overlap, separators,
   keep_separator=True, strip_whitespace=True defaults)
   ══════════════════════════════════════════════════════ */

class RecursiveCharacterTextSplitter {
    private $chunkSize;
    private $chunkOverlap;
    private $separators;

    public function __construct(int $chunk_size = 4000, int $chunk_overlap = 200, array $separators = ["\n\n", "\n", " ", ""]) {
        $this->chunkSize = $chunk_size;
        $this->chunkOverlap = $chunk_overlap;
        $this->separators = $separators;
    }

    public function split_text(string $text): array {
        return $this->splitText($text);
    }

    public function splitText(string $text): array {
        return $this->_splitText($text, $this->separators);
    }

    private function _splitText(string $text, array $separators): array {
        $final_chunks = [];
        $separator = $separators[count($separators) - 1];
        $new_separators = [];
        foreach ($separators as $i => $_s) {
            if ($_s === '') {
                $separator = $_s;
                break;
            }
            if (@preg_match('/' . $_s . '/u', $text) === 1) {
                $separator = $_s;
                $new_separators = array_slice($separators, $i + 1);
                break;
            }
        }

        $splits = $this->splitTextWithRegex($text, $separator, true);

        $_separator = '';  // keep_separator=True -> merge ke waqt separator already chunks mein hai
        $good_splits = [];
        foreach ($splits as $s) {
            if (sv_strlen($s) < $this->chunkSize) {
                $good_splits[] = $s;
            } else {
                if ($good_splits) {
                    $merged = $this->mergeSplits($good_splits, $_separator);
                    foreach ($merged as $mc) $final_chunks[] = $mc;
                    $good_splits = [];
                }
                if (!$new_separators) {
                    $final_chunks[] = $s;
                } else {
                    $other = $this->_splitText($s, $new_separators);
                    foreach ($other as $oc) $final_chunks[] = $oc;
                }
            }
        }
        if ($good_splits) {
            $merged = $this->mergeSplits($good_splits, $_separator);
            foreach ($merged as $mc) $final_chunks[] = $mc;
        }
        return $final_chunks;
    }

    private function splitTextWithRegex(string $text, string $separator, bool $keep_separator): array {
        if ($separator !== '') {
            if ($keep_separator) {
                $parts = preg_split('/(' . $separator . ')/u', $text, -1, PREG_SPLIT_DELIM_CAPTURE);
                if ($parts === false) $parts = [$text];
                $n = count($parts);
                $splits = [];
                for ($i = 1; $i < $n; $i += 2) {
                    $splits[] = $parts[$i] . (isset($parts[$i + 1]) ? $parts[$i + 1] : '');
                }
                if ($n % 2 === 0) {
                    $splits[] = $parts[$n - 1];
                }
                array_unshift($splits, isset($parts[0]) ? $parts[0] : '');
            } else {
                $splits = preg_split('/' . $separator . '/u', $text);
                if ($splits === false) $splits = [$text];
            }
        } else {
            $splits = sv_chars($text);
        }
        return array_values(array_filter($splits, function ($s) { return $s !== ''; }));
    }

    private function mergeSplits(array $splits, string $separator): array {
        $separator_len = sv_strlen($separator);
        $docs = [];
        $current_doc = [];
        $total = 0;
        foreach ($splits as $d) {
            $_len = sv_strlen($d);
            if ($total + $_len + (count($current_doc) > 0 ? $separator_len : 0) > $this->chunkSize) {
                if (count($current_doc) > 0) {
                    $doc = $this->joinDocs($current_doc, $separator);
                    if ($doc !== null) $docs[] = $doc;
                    while ($total > $this->chunkOverlap
                        || ($total + $_len + (count($current_doc) > 0 ? $separator_len : 0) > $this->chunkSize && $total > 0)) {
                        $total -= sv_strlen($current_doc[0]) + (count($current_doc) > 1 ? $separator_len : 0);
                        array_shift($current_doc);
                        if (!$current_doc) break;
                    }
                }
            }
            $current_doc[] = $d;
            $total += $_len + (count($current_doc) > 1 ? $separator_len : 0);
        }
        if ($current_doc) {
            $doc = $this->joinDocs($current_doc, $separator);
            if ($doc !== null) $docs[] = $doc;
        }
        return $docs;
    }

    private function joinDocs(array $docs, string $separator): ?string {
        $text = implode($separator, $docs);
        $text = trim($text);
        if ($text === '') return null;
        return $text;
    }
}

/* ══════════════════════════════════════════════════════
   PDF TEXT EXTRACTION — pypdf/pdfplumber equivalent
   (pure PHP: FlateDecode streams, Tj/TJ/Td/Tm text ops,
   literal + hex strings, ToUnicode CMap support)
   ══════════════════════════════════════════════════════ */

function svims_pdf_maybe_inflate(string $data): ?string {
    // FlateDecode (zlib) try karo, warna raw
    if (strlen($data) > 2) {
        $out = @gzuncompress($data);
        if ($out !== false) return $out;
        $out = @gzinflate($data);
        if ($out !== false) return $out;
    }
    return $data;
}

function svims_pdf_decode_literal(string $s): string {
    // PDF literal string escapes: \n \r \t \b \f \\ \( \) \ddd
    $out = '';
    $len = strlen($s);
    for ($i = 0; $i < $len; $i++) {
        $c = $s[$i];
        if ($c === '\\' && $i + 1 < $len) {
            $n = $s[$i + 1];
            if ($n === 'n') { $out .= "\n"; $i++; continue; }
            if ($n === 'r') { $out .= "\r"; $i++; continue; }
            if ($n === 't') { $out .= "\t"; $i++; continue; }
            if ($n === 'b') { $out .= "\x08"; $i++; continue; }
            if ($n === 'f') { $out .= "\x0C"; $i++; continue; }
            if ($n === '(' || $n === ')' || $n === '\\') { $out .= $n; $i++; continue; }
            if ($n >= '0' && $n <= '7') {
                $oct = $n;
                $j = $i + 2;
                while ($j < $len && strlen($oct) < 3 && $s[$j] >= '0' && $s[$j] <= '7') { $oct .= $s[$j]; $j++; }
                $out .= chr((int)octdec($oct) & 0xFF);
                $i = $j - 1;
                continue;
            }
            $out .= $n; $i++;
            continue;
        }
        $out .= $c;
    }
    return $out;
}

function svims_pdf_decode_hex(string $hex, array $cmap): string {
    $hex = preg_replace('/\s+/', '', $hex);
    if ($hex === '' || $hex === null) return '';
    if (strlen($hex) % 2 === 1) $hex .= '0';
    $bytes = @hex2bin($hex);
    if ($bytes === false) return '';

    if ($cmap) {
        // 2-byte codes ko ToUnicode CMap se decode karo
        $out = '';
        $ok = 0; $total = 0;
        for ($i = 0; $i + 1 < strlen($bytes); $i += 2) {
            $code = strtoupper(bin2hex(substr($bytes, $i, 2)));
            $total++;
            if (isset($cmap[$code])) {
                $out .= $cmap[$code];
                $ok++;
            }
        }
        if ($total > 0 && $ok / $total >= 0.5) return $out;
    }

    // UTF-16BE ASCII-range check (0x00XX pattern)
    $looks_utf16 = true;
    $has_nonzero_high = false;
    for ($i = 0; $i + 1 < strlen($bytes); $i += 2) {
        if (ord($bytes[$i]) !== 0) { $has_nonzero_high = true; break; }
    }
    if (!$has_nonzero_high && strlen($bytes) >= 2) {
        $out = '';
        for ($i = 1; $i < strlen($bytes); $i += 2) {
            $b = ord($bytes[$i]);
            if ($b === 0) continue;
            $out .= chr($b);
        }
        if ($looks_utf16 && $out !== '') return $out;
    }
    return '';
}

function svims_pdf_parse_cmaps(string $raw): array {
    // ToUnicode CMaps (beginbfchar / beginbfrange) se hex-code -> unicode map
    $cmap = [];
    if (preg_match_all('/stream\r?\n(.*?)endstream/s', $raw, $m)) {
        foreach ($m[1] as $stream) {
            if (strpos($stream, 'beginbfchar') === false && strpos($stream, 'beginbfrange') === false) {
                $inflated = svims_pdf_maybe_inflate($stream);
                if ($inflated === null) continue;
                if (strpos($inflated, 'beginbfchar') === false && strpos($inflated, 'beginbfrange') === false) continue;
                $stream = $inflated;
            }

            // beginbfchar ... endbfchar :  <SRC> <DST>
            if (preg_match_all('/beginbfchar(.*?)endbfchar/s', $stream, $bc)) {
                foreach ($bc[1] as $block) {
                    if (preg_match_all('/<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/', $block, $pairs, PREG_SET_ORDER)) {
                        foreach ($pairs as $p) {
                            $cmap[strtoupper($p[1])] = svims_pdf_cmap_dst_to_utf8($p[2]);
                        }
                    }
                }
            }
            // beginbfrange ... endbfrange :  <LO> <HI> <DST>
            if (preg_match_all('/beginbfrange(.*?)endbfrange/s', $stream, $br)) {
                foreach ($br[1] as $block) {
                    if (preg_match_all('/<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/', $block, $ranges, PREG_SET_ORDER)) {
                        foreach ($ranges as $r) {
                            $lo = hexdec($r[1]);
                            $hi = hexdec($r[2]);
                            $dst = hexdec($r[3]);
                            $width = strlen($r[1]);
                            for ($code = $lo; $code <= $hi && $code < $lo + 65536; $code++) {
                                $cmap[strtoupper(str_pad(strtoupper(dechex($code)), $width, '0', STR_PAD_LEFT))] =
                                    svims_codepoint_to_utf8($dst + ($code - $lo));
                            }
                        }
                    }
                }
            }
        }
    }
    return $cmap;
}

function svims_pdf_cmap_dst_to_utf8(string $hex): string {
    // <DST> = UTF-16BE code units
    $out = '';
    $bytes = @hex2bin(preg_replace('/\s+/', '', $hex));
    if ($bytes === false) return '';
    for ($i = 0; $i + 1 < strlen($bytes); $i += 2) {
        $cp = (ord($bytes[$i]) << 8) | ord($bytes[$i + 1]);
        // surrogate pair handling
        if ($cp >= 0xD800 && $cp <= 0xDBFF && $i + 3 < strlen($bytes)) {
            $lo = (ord($bytes[$i + 2]) << 8) | ord($bytes[$i + 3]);
            if ($lo >= 0xDC00 && $lo <= 0xDFFF) {
                $cp = 0x10000 + (($cp - 0xD800) << 10) + ($lo - 0xDC00);
                $i += 2;
            }
        }
        $out .= svims_codepoint_to_utf8($cp);
    }
    return $out;
}

function svims_codepoint_to_utf8(int $cp): string {
    if (function_exists('mb_chr')) {
        $c = @mb_chr($cp, 'UTF-8');
        if ($c !== false) return $c;
    }
    if ($cp < 0x80) return chr($cp);
    if ($cp < 0x800) return chr(0xC0 | ($cp >> 6)) . chr(0x80 | ($cp & 0x3F));
    if ($cp < 0x10000) return chr(0xE0 | ($cp >> 12)) . chr(0x80 | (($cp >> 6) & 0x3F)) . chr(0x80 | ($cp & 0x3F));
    return chr(0xF0 | ($cp >> 18)) . chr(0x80 | (($cp >> 12) & 0x3F)) . chr(0x80 | (($cp >> 6) & 0x3F)) . chr(0x80 | ($cp & 0x3F));
}

function svims_pdf_text_from_content(string $content, array $cmap): string {
    // Content stream parser: BT/ET, Tj, TJ, Td, TD, Tm, T*, ', "
    $out = '';
    $stack = [];
    $len = strlen($content);
    $i = 0;
    $in_bt = false;

    while ($i < $len) {
        $c = $content[$i];

        // Whitespace / separators
        if ($c === ' ' || $c === "\t" || $c === "\r" || $c === "\n" || $c === "\x00") { $i++; continue; }

        // Comment
        if ($c === '%') { while ($i < $len && $content[$i] !== "\n") $i++; continue; }

        // Literal string (...)
        if ($c === '(') {
            $depth = 1; $buf = ''; $i++;
            while ($i < $len && $depth > 0) {
                $ch = $content[$i];
                if ($ch === '\\' && $i + 1 < $len) { $buf .= $ch . $content[$i + 1]; $i += 2; continue; }
                if ($ch === '(') $depth++;
                elseif ($ch === ')') { $depth--; if ($depth === 0) { $i++; break; } }
                $buf .= $ch; $i++;
            }
            $stack[] = ['str', svims_pdf_decode_literal($buf)];
            continue;
        }

        // Hex string <...> (na ki dict <<)
        if ($c === '<') {
            if ($i + 1 < $len && $content[$i + 1] === '<') { $i += 2; continue; }
            $end = strpos($content, '>', $i);
            if ($end === false) break;
            $hex = substr($content, $i + 1, $end - $i - 1);
            $stack[] = ['str', svims_pdf_decode_hex($hex, $cmap)];
            $i = $end + 1;
            continue;
        }
        if ($c === '>') { $i++; continue; }

        // Array [...] (TJ ke liye)
        if ($c === '[') {
            $items = [];
            $i++;
            while ($i < $len) {
                $cc = $content[$i];
                if ($cc === ']') { $i++; break; }
                if ($cc === ' ' || $cc === "\t" || $cc === "\r" || $cc === "\n") { $i++; continue; }
                if ($cc === '(') {
                    $depth = 1; $buf = ''; $i++;
                    while ($i < $len && $depth > 0) {
                        $ch = $content[$i];
                        if ($ch === '\\' && $i + 1 < $len) { $buf .= $ch . $content[$i + 1]; $i += 2; continue; }
                        if ($ch === '(') $depth++;
                        elseif ($ch === ')') { $depth--; if ($depth === 0) { $i++; break; } }
                        $buf .= $ch; $i++;
                    }
                    $items[] = ['str', svims_pdf_decode_literal($buf)];
                    continue;
                }
                if ($cc === '<') {
                    $end = strpos($content, '>', $i);
                    if ($end === false) { $i = $len; break; }
                    $items[] = ['str', svims_pdf_decode_hex(substr($content, $i + 1, $end - $i - 1), $cmap)];
                    $i = $end + 1;
                    continue;
                }
                // number
                if (preg_match('/\G[-+]?\d*\.?\d+/', $content, $nm, 0, $i)) {
                    $items[] = ['num', (float)$nm[0]];
                    $i += strlen($nm[0]);
                    continue;
                }
                $i++;
            }
            $stack[] = ['arr', $items];
            continue;
        }

        // Number
        if (preg_match('/\G[-+]?\d*\.?\d+/', $content, $nm, 0, $i)) {
            $stack[] = ['num', (float)$nm[0]];
            $i += strlen($nm[0]);
            continue;
        }

        // Name object /XYZ — skip
        if ($c === '/') {
            $i++;
            while ($i < $len && !preg_match('/[\s\/<>\[\](){}%]/', $content[$i])) $i++;
            continue;
        }

        // Keyword
        if (preg_match('/\G[A-Za-z\*\']{1,3}/', $content, $kw, 0, $i)) {
            $op = $kw[0];
            $i += strlen($op);

            if ($op === 'BT') { $in_bt = true; $stack = []; continue; }
            if ($op === 'ET') { $in_bt = false; $stack = []; continue; }
            if (!$in_bt) { $stack = []; continue; }

            if ($op === 'Tj') {
                for ($k = count($stack) - 1; $k >= 0; $k--) {
                    if ($stack[$k][0] === 'str') { $out .= $stack[$k][1]; break; }
                }
                $stack = [];
                continue;
            }
            if ($op === 'TJ') {
                for ($k = count($stack) - 1; $k >= 0; $k--) {
                    if ($stack[$k][0] === 'arr') {
                        foreach ($stack[$k][1] as $item) {
                            if ($item[0] === 'str') $out .= $item[1];
                            elseif ($item[0] === 'num' && $item[1] <= -200) $out .= ' ';
                        }
                        break;
                    }
                }
                $stack = [];
                continue;
            }
            if ($op === "'" || $op === '"') {
                for ($k = count($stack) - 1; $k >= 0; $k--) {
                    if ($stack[$k][0] === 'str') { $out .= "\n" . $stack[$k][1]; break; }
                }
                $stack = [];
                continue;
            }
            if ($op === 'Td' || $op === 'TD') {
                $nums = [];
                foreach ($stack as $it) if ($it[0] === 'num') $nums[] = $it[1];
                $ty = count($nums) >= 2 ? $nums[count($nums) - 1] : 0.0;
                if (abs($ty) > 0.001) $out .= "\n";
                $stack = [];
                continue;
            }
            if ($op === 'Tm') { $out .= "\n"; $stack = []; continue; }
            if ($op === 'T*') { $out .= "\n"; $stack = []; continue; }
            $stack = [];
            continue;
        }

        $i++;
    }

    // Latin-1 bytes -> UTF-8
    $out = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F]/', '', $out);
    if (function_exists('mb_convert_encoding')) {
        $conv = @mb_convert_encoding($out, 'UTF-8', 'ISO-8859-1');
        if (is_string($conv)) $out = $conv;
    }
    return $out;
}

function svims_pdf_extract_text(string $path): string {
    if (!is_file($path)) return '';
    $raw = @file_get_contents($path);
    if ($raw === false || strlen($raw) < 4 || substr($raw, 0, 5) !== '%PDF-') return '';

    $cmap = svims_pdf_parse_cmaps($raw);

    $text = '';
    if (preg_match_all('/stream\r?\n(.*?)\s*endstream/s', $raw, $m)) {
        foreach ($m[1] as $stream) {
            $data = svims_pdf_maybe_inflate($stream);
            if ($data === null) continue;
            if (strpos($data, 'BT') === false) continue;
            $text .= svims_pdf_text_from_content($data, $cmap);
        }
    }
    return $text;
}

/* ══════════════════════════════════════════════════════
   HTML -> TEXT — BeautifulSoup equivalent
   (script/style/nav/footer/header remove + whitespace collapse)
   ══════════════════════════════════════════════════════ */

function svims_html_to_text(string $html): string {
    if (class_exists('DOMDocument')) {
        $prev = libxml_use_internal_errors(true);
        $doc = new DOMDocument();
        $ok = false;
        if (function_exists('mb_convert_encoding')) {
            $safe = @mb_convert_encoding($html, 'HTML-ENTITIES', 'UTF-8');
            if (is_string($safe)) $ok = $doc->loadHTML($safe, LIBXML_NOERROR | LIBXML_NOWARNING);
        }
        if (!$ok) $ok = $doc->loadHTML('<?xml encoding="utf-8"?>' . $html, LIBXML_NOERROR | LIBXML_NOWARNING);
        libxml_clear_errors();
        libxml_use_internal_errors($prev);
        if ($ok) {
            foreach (['script', 'style', 'nav', 'footer', 'header'] as $tag) {
                $nodes = [];
                foreach ($doc->getElementsByTagName($tag) as $node) $nodes[] = $node;
                foreach ($nodes as $node) {
                    if ($node->parentNode) $node->parentNode->removeChild($node);
                }
            }
            $text = $doc->textContent;
            $parts = preg_split('/\s+/u', $text);
            return $parts === false ? '' : trim(implode(' ', $parts));
        }
    }
    // Fallback: strip_tags
    $html = (string)preg_replace('/<(script|style|nav|footer|header)\b.*?<\/\1>/is', ' ', $html);
    $text = strip_tags($html);
    $parts = preg_split('/\s+/u', $text);
    return $parts === false ? '' : trim(implode(' ', $parts));
}

/* ══════════════════════════════════════════════════════
   EMBEDDINGS — sentence-transformers/all-MiniLM-L6-v2
   (HuggingFace Inference API / koi bhi compatible
   embedding server — .env se configurable)
   ══════════════════════════════════════════════════════ */

class SVIMSEmbeddings {
    public $model_name = 'sentence-transformers/all-MiniLM-L6-v2';
    // Public — taaki tests/mock subclass inject ho sake (default: real instance)
    public static $instance = null;

    public static function instance(): SVIMSEmbeddings {
        if (self::$instance === null) self::$instance = new SVIMSEmbeddings();
        return self::$instance;
    }

    private function endpoint(): string {
        $url = svims_env('EMBEDDINGS_API_URL');
        if ($url !== '') return rtrim($url, '/');
        return 'https://api-inference.huggingface.co/models/' . $this->model_name;
    }

    private function token(): string {
        foreach (['HF_API_TOKEN', 'HF_API_KEY', 'HUGGINGFACE_API_KEY'] as $k) {
            $v = svims_env($k);
            if ($v !== '') return $v;
        }
        return '';
    }

    /**
     * SentenceTransformer.encode(texts, convert_to_numpy=True) equivalent.
     * @param string[] $texts
     * @return array[] vectors (har ek float[])
     */
    public function encode(array $texts): array {
        if (!$texts) return [];

        $url = $this->endpoint();
        $token = $this->token();
        $vectors = [];

        foreach (array_chunk($texts, 16) as $batch) {
            $headers = ['Content-Type: application/json', 'x-wait-for-model: true'];
            if ($token !== '') $headers[] = 'Authorization: Bearer ' . $token;

            $payload = json_encode(['inputs' => array_values($batch)], JSON_UNESCAPED_UNICODE);

            $res = null;
            $last_err = 'unknown error';
            for ($attempt = 0; $attempt < 3; $attempt++) {
                $res = svims_http_request('POST', $url, $headers, $payload, 120);
                if ($res['error'] !== null) {
                    $last_err = $res['error'];
                    break; // network-level error — retry bekar hai
                }
                if ($res['status'] === 200) break;
                if ($res['status'] === 503 || $res['status'] === 429 || $res['status'] === 502) {
                    $last_err = 'HTTP ' . $res['status'] . ' — ' . sv_substr($res['body'], 0, 200);
                    sleep(2);
                    continue;
                }
                $last_err = 'HTTP ' . $res['status'] . ' — ' . sv_substr($res['body'], 0, 300);
                break;
            }

            if ($res === null || $res['error'] !== null || $res['status'] !== 200) {
                throw new RuntimeException(
                    "Embeddings API failed: {$last_err}\n" .
                    "Model: {$this->model_name} | Endpoint: {$url}\n" .
                    "Fix: .env mein HF_API_TOKEN set karo (free: huggingface.co/settings/tokens) " .
                    "ya EMBEDDINGS_API_URL se apna embedding server point karo."
                );
            }

            $j = json_decode($res['body'], true);
            if (!is_array($j)) {
                throw new RuntimeException('Embeddings API returned invalid JSON');
            }
            // formats: [[...]] ya {"data": [[...]]} ya {"embeddings": [[...]]}
            if (isset($j['data']) && is_array($j['data'])) $j = $j['data'];
            elseif (isset($j['embeddings']) && is_array($j['embeddings'])) $j = $j['embeddings'];
            if (!isset($j[0]) || !is_array($j[0])) {
                $msg = isset($j['error']) ? (is_string($j['error']) ? $j['error'] : json_encode($j['error'])) : 'unexpected response shape';
                throw new RuntimeException('Embeddings API error: ' . $msg);
            }
            foreach ($j as $vec) $vectors[] = array_map('floatval', $vec);
        }

        if (count($vectors) !== count($texts)) {
            throw new RuntimeException('Embeddings API returned ' . count($vectors) . ' vectors for ' . count($texts) . ' texts');
        }
        return $vectors;
    }
}

/* ══════════════════════════════════════════════════════
   VECTOR STORE + RETRIEVER — FAISS equivalent
   (cosine similarity, save/load local, k-retriever)
   ══════════════════════════════════════════════════════ */

function svims_cosine(array $a, array $b): float {
    $dot = 0.0; $na = 0.0; $nb = 0.0;
    $n = min(count($a), count($b));
    for ($i = 0; $i < $n; $i++) {
        $dot += $a[$i] * $b[$i];
        $na += $a[$i] * $a[$i];
        $nb += $b[$i] * $b[$i];
    }
    $denom = sqrt($na) * sqrt($nb);
    if ($denom == 0.0) $denom = 1e-10;
    return $dot / $denom;
}

class SVIMSVectorStore {
    public $chunks = [];
    public $vectors = [];
    /** @var SVIMSEmbeddings */
    public $embeddings;

    public function __construct(array $chunks = [], array $vectors = [], ?SVIMSEmbeddings $embeddings = null) {
        $this->chunks = $chunks;
        $this->vectors = $vectors;
        $this->embeddings = $embeddings ?: SVIMSEmbeddings::instance();
    }

    /** FAISS.from_texts(texts, embedding=embeddings) equivalent */
    public static function from_texts(array $texts, SVIMSEmbeddings $embeddings): SVIMSVectorStore {
        if (!$texts) throw new RuntimeException('No texts to embed');
        $vectors = $embeddings->encode(array_values($texts));
        return new SVIMSVectorStore(array_values($texts), $vectors, $embeddings);
    }

    /** vector_store.save_local(path) equivalent */
    public function save_local(string $dir): void {
        if (!is_dir($dir)) @mkdir($dir, 0777, true);
        $rounded = [];
        foreach ($this->vectors as $v) {
            $rv = [];
            foreach ($v as $x) $rv[] = round($x, 6);
            $rounded[] = $rv;
        }
        $payload = json_encode(
            ['chunks' => $this->chunks, 'vectors' => $rounded],
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
        );
        @file_put_contents($dir . '/index.faiss.json', $payload, LOCK_EX);
    }

    /** FAISS.load_local(path, embeddings) equivalent */
    public static function load_local(string $dir, SVIMSEmbeddings $embeddings): SVIMSVectorStore {
        $f = $dir . '/index.faiss.json';
        $data = json_decode((string)@file_get_contents($f), true);
        if (!is_array($data)) throw new RuntimeException('Vector index load failed: ' . $f);
        return new SVIMSVectorStore(
            isset($data['chunks']) ? $data['chunks'] : [],
            isset($data['vectors']) ? $data['vectors'] : [],
            $embeddings
        );
    }

    /** vector_store.as_retriever(search_kwargs={"k": 8}) equivalent */
    public function as_retriever(int $k = 8): SVIMSRetriever {
        return new SVIMSRetriever($this, $k);
    }
}

class SVIMSRetriever {
    private $store;
    private $k;

    public function __construct(SVIMSVectorStore $store, int $k = 8) {
        $this->store = $store;
        $this->k = $k;
    }

    /** retriever.invoke(query) equivalent — top-k docs (page_content) */
    public function invoke(string $query): array {
        if (!$this->store->vectors) return [];
        $qv = $this->store->embeddings->encode([$query]);
        if (!$qv) return [];
        $q = $qv[0];

        $scored = [];
        foreach ($this->store->vectors as $idx => $vec) {
            $scored[] = [svims_cosine($q, $vec), $idx];
        }
        usort($scored, function ($a, $b) { return $b[0] <=> $a[0]; });

        $docs = [];
        foreach (array_slice($scored, 0, $this->k) as $pair) {
            $docs[] = ['page_content' => $this->store->chunks[$pair[1]] ?? ''];
        }
        return $docs;
    }
}

/* ══════════════════════════════════════════════════════
   DIFFLIB — get_close_matches / SequenceMatcher port
   (Ratcliff/Obershelp similarity — Python difflib jaisa)
   ══════════════════════════════════════════════════════ */

function svims_find_longest_match(string $a, int $alo, int $ahi, string $b, int $blo, int $bhi, array $b2j): array {
    $besti = $alo; $bestj = $blo; $bestsize = 0;
    $j2len = [];
    for ($i = $alo; $i < $ahi; $i++) {
        $newj2len = [];
        $ch = sv_substr($a, $i, 1);
        foreach (($b2j[$ch] ?? []) as $j) {
            if ($j < $blo) continue;
            if ($j >= $bhi) break;
            $k = (isset($j2len[$j - 1]) ? $j2len[$j - 1] : 0) + 1;
            $newj2len[$j] = $k;
            if ($k > $bestsize) {
                $besti = $i - $k + 1;
                $bestj = $j - $k + 1;
                $bestsize = $k;
            }
        }
        $j2len = $newj2len;
    }
    // matching block ko aage-peeche extend karo (difflib same karta hai)
    while ($besti > $alo && $bestj > $blo
        && sv_substr($a, $besti - 1, 1) === sv_substr($b, $bestj - 1, 1)) {
        $besti--; $bestj--; $bestsize++;
    }
    while ($besti + $bestsize < $ahi && $bestj + $bestsize < $bhi
        && sv_substr($a, $besti + $bestsize, 1) === sv_substr($b, $bestj + $bestsize, 1)) {
        $bestsize++;
    }
    return [$besti, $bestj, $bestsize];
}

function svims_matching_blocks_sum(string $a, int $alo, int $ahi, string $b, int $blo, int $bhi, array $b2j): int {
    if ($alo >= $ahi || $blo >= $bhi) return 0;
    list($i, $j, $n) = svims_find_longest_match($a, $alo, $ahi, $b, $blo, $bhi, $b2j);
    if ($n === 0) return 0;
    return svims_matching_blocks_sum($a, $alo, $i, $b, $blo, $j, $b2j)
         + $n
         + svims_matching_blocks_sum($a, $i + $n, $ahi, $b, $j + $n, $bhi, $b2j);
}

/** SequenceMatcher(None, a, b).ratio() equivalent */
function svims_sequence_ratio(string $a, string $b): float {
    $la = sv_strlen($a);
    $lb = sv_strlen($b);
    if ($la + $lb === 0) return 1.0;

    $b2j = [];
    foreach (sv_chars($b) as $j => $ch) $b2j[$ch][] = $j;

    $matches = svims_matching_blocks_sum($a, 0, $la, $b, 0, $lb, $b2j);
    return 2.0 * $matches / ($la + $lb);
}

/** get_close_matches(word, possibilities, n, cutoff) equivalent */
function svims_get_close_matches(string $word, array $possibilities, int $n = 3, float $cutoff = 0.6): array {
    if ($cutoff > 1.0 || $cutoff < 0.0) return [];
    $result = [];
    $len_w = sv_strlen($word);
    $cnt_w = array_count_values(sv_chars($word));

    foreach ($possibilities as $x) {
        $len_x = sv_strlen($x);
        if ($len_w + $len_x === 0) continue;
        // real_quick_ratio
        if (2.0 * min($len_w, $len_x) / ($len_w + $len_x) < $cutoff) continue;
        // quick_ratio
        $cnt_x = array_count_values(sv_chars($x));
        $inter = 0;
        foreach ($cnt_w as $ch => $cw) {
            if (isset($cnt_x[$ch])) $inter += min($cw, $cnt_x[$ch]);
        }
        if (2.0 * $inter / ($len_w + $len_x) < $cutoff) continue;
        // full ratio
        $r = svims_sequence_ratio($word, $x);
        if ($r >= $cutoff) $result[] = [$r, $x];
    }

    usort($result, function ($p, $q) {
        if ($q[0] !== $p[0]) return $q[0] <=> $p[0];
        return strcmp($p[1], $q[1]);
    });
    $out = [];
    foreach (array_slice($result, 0, max(0, $n)) as $pair) $out[] = $pair[1];
    return $out;
}

} // SVIMS_LIB_LOADED
// ─────────────────────────────────────────────────────────
// End of svims_lib.php
// ─────────────────────────────────────────────────────────
