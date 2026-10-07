<?php
/**
 * SVIMS CampusBot — Engine (PHP port of svims_engine.py)
 * =======================================================
 * Har function/class Python version ka 1:1 port hai — same logic, same
 * order, same messages. Sirf coding language Python -> PHP badli hai.
 *
 * Python ke module-level globals yahan SVIMSEngine class ke static members
 * hain. Python ka process-level state (blacklist, response cache, key
 * rotation index) PHP mein file-backed store mein persist hota hai kyunki
 * PHP har request pe fresh start hota hai — behaviour same rehta hai.
 */

require_once __DIR__ . '/svims_lib.php';
require_once __DIR__ . '/svims_qa_loader.php';

class SVIMSEngine {

    /* ── Groq keys (GROQ_API_KEY_1, GROQ_API_KEY_2, ... + legacy GROQ_API_KEY) ── */
    public static $GROQ_API_KEYS = [];
    public static $groq_clients = [];   // clients ≙ API keys (round-robin rotation)
    public static $key_index = 0;

    /* ── Config ── */
    public static $CFG = [];
    public static $SHOW_STAFF_PHONES = false;
    public static $ACADEMIC_CALENDAR = [];
    public static $ACHIEVEMENT_CFG = [];
    public static $FEES_CFG = [];
    public static $MODELS_TO_TRY = [];
    public static $SYLLABUS_CFG = null;
    public static $SYLLABUS_ANSWERS = null;
    public static $ALL_SYLLABUS_ANSWER = null;

    /* ── Smart model manager ── */
    public static $BLACKLISTED_MODELS = [];
    public static $LIVE_MODELS_CACHE = [];
    public static $LIVE_MODELS_FETCHED_AT = 0;
    const LIVE_MODELS_TTL = 3600;
    const NON_CHAT_KEYWORDS = ["whisper", "tts", "vision", "distil", "guard", "embed", "moderation"];

    /* ── Hardcoded answers ── */
    public static $FACULTY_LIST_ANSWER = '';
    public static $CS_FACULTY_ANSWER = '';
    public static $UG_FACULTY_ANSWER = '';
    public static $PG_FACULTY_ANSWER = '';
    public static $ACADEMIC_CALENDAR_ANSWER = '';

    /* ── Topic links snapshot (module-level build — see init) ── */
    public static $TOPIC_LINKS = [];

    private static $initialized = false;

    /* ══════════════════════════════════════════════════════
       INIT — Python module import-time code ka equivalent
       ══════════════════════════════════════════════════════ */
    public static function init(): void {
        if (self::$initialized) return;
        self::$initialized = true;

        // load_dotenv(dotenv_path=.../.env) — Python module-level call ka equivalent
        svims_load_dotenv(__DIR__ . '/.env');

        // ── Groq keys load karo (.env se) ──
        self::$GROQ_API_KEYS = [];
        $i = 1;
        while (true) {
            $v = trim(svims_env("GROQ_API_KEY_{$i}"));
            if ($v === '') break;
            self::$GROQ_API_KEYS[] = $v;
            $i++;
        }

        $_legacy = trim(svims_env("GROQ_API_KEY"));
        if ($_legacy !== '' && !in_array($_legacy, self::$GROQ_API_KEYS, true)) {
            self::$GROQ_API_KEYS[] = $_legacy;
        }

        if (!self::$GROQ_API_KEYS) {
            throw new RuntimeException("No Groq API key found! Set GROQ_API_KEY_1 in .env");
        }

        $previews = [];
        foreach (self::$GROQ_API_KEYS as $k) $previews[] = "'" . substr($k, 0, 10) . "...'";
        svims_log("✅ Engine loaded with " . count(self::$GROQ_API_KEYS) . " Groq key(s): ["
            . implode(", ", $previews) . "]");

        self::$groq_clients = self::$GROQ_API_KEYS;

        // ── Persisted process-state load karo (fresh server start pe empty hota hai —
        //    launcher svims_runtime/ wipe karta hai, same as Python fresh process) ──
        $ms = svims_state_read('model_state', []);
        self::$BLACKLISTED_MODELS = isset($ms['blacklist']) ? $ms['blacklist'] : [];
        self::$LIVE_MODELS_CACHE = isset($ms['live_cache']) ? $ms['live_cache'] : [];
        self::$LIVE_MODELS_FETCHED_AT = isset($ms['fetched_at']) ? (int)$ms['fetched_at'] : 0;
        self::$key_index = (int)svims_state_read('key_index', 0);

        // ══════════════════════════════════════════════════════
        // CONFIG LOADER — svims_config.json se sab updatable data
        // ══════════════════════════════════════════════════════
        self::$CFG = self::_load_config();

        self::$SHOW_STAFF_PHONES = isset(self::$CFG['show_staff_phones']) ? (bool)self::$CFG['show_staff_phones'] : false;
        self::$ACADEMIC_CALENDAR = isset(self::$CFG['academic_calendar']) ? self::$CFG['academic_calendar'] : [
            "year" => "2025-26",
            "link" => "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf",
        ];
        self::$ACHIEVEMENT_CFG = isset(self::$CFG['achievement_links']) ? self::$CFG['achievement_links'] : [];
        self::$FEES_CFG = isset(self::$CFG['fees']) ? self::$CFG['fees'] : [];
        self::$MODELS_TO_TRY = isset(self::$CFG['groq_models']) ? self::$CFG['groq_models'] : [
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-20b",
        ];

        self::_build_faculty_answers();
        self::buildModuleLevelAnswers();
    }

    /**
     * Python mein TOPIC_LINKS aur ACADEMIC_CALENDAR_ANSWER module import
     * ke waqt EK BAAR bante the (aur reload-config ke baad bhi stale rehte
     * the jab tak server restart na ho). Wahi semantics yahan snapshot
     * file se maintain hote hain.
     */
    private static function buildModuleLevelAnswers(): void {
        $snap = svims_state_read('engine_snapshot', null);
        if (is_array($snap) && isset($snap['topic_links']) && isset($snap['calendar_answer'])) {
            self::$TOPIC_LINKS = $snap['topic_links'];
            self::$ACADEMIC_CALENDAR_ANSWER = $snap['calendar_answer'];
            return;
        }

        self::$ACADEMIC_CALENDAR_ANSWER = self::buildAcademicCalendarAnswer(
            isset(self::$ACADEMIC_CALENDAR['year']) ? self::$ACADEMIC_CALENDAR['year'] : '2025-26',
            isset(self::$ACADEMIC_CALENDAR['link']) ? self::$ACADEMIC_CALENDAR['link']
                : 'https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf'
        );
        self::$TOPIC_LINKS = self::buildTopicLinks();

        svims_state_write('engine_snapshot', [
            'topic_links' => self::$TOPIC_LINKS,
            'calendar_answer' => self::$ACADEMIC_CALENDAR_ANSWER,
        ]);
    }

    private static function buildAcademicCalendarAnswer(string $year, string $link): string {
        return <<<EOT
Academic Calendar {$year} — SVIMS

Download the full Academic Calendar PDF here:
{$link}

For semester dates, exam schedules, and holidays — refer to this PDF or visit www.svimi.org/Notification.php for latest updates.
EOT;
    }

    private static function saveModelState(): void {
        svims_state_write('model_state', [
            'blacklist' => array_values(self::$BLACKLISTED_MODELS),
            'live_cache' => self::$LIVE_MODELS_CACHE,
            'fetched_at' => self::$LIVE_MODELS_FETCHED_AT,
        ]);
    }

    /* ══════════════════════════════════════════════════════
       KEY ROTATION — _get_client()
       ══════════════════════════════════════════════════════ */
    public static function _get_client(): string {
        $idx = self::$key_index;
        $client = self::$groq_clients[$idx % count(self::$groq_clients)];
        $key_preview = substr(self::$GROQ_API_KEYS[$idx % count(self::$GROQ_API_KEYS)], 0, 10);
        svims_log("🔑 Using Key #" . (($idx % count(self::$groq_clients)) + 1) . " ({$key_preview}...) for this request");
        self::$key_index = (self::$key_index + 1) % count(self::$groq_clients);
        svims_state_write('key_index', self::$key_index);
        return $client;
    }

    /* ══════════════════════════════════════════════════════
       CONFIG LOADER
       ══════════════════════════════════════════════════════ */
    public static function _load_config(): array {
        $path = __DIR__ . '/svims_config.json';
        try {
            $raw = file_get_contents($path);
            if ($raw === false) throw new RuntimeException('config file missing');
            $data = json_decode($raw, true);
            if (!is_array($data)) throw new RuntimeException('invalid json');
            return $data;
        } catch (Throwable $e) {
            svims_log("⚠️ Config load failed ({$e->getMessage()}) — using defaults");
            return [];
        }
    }

    /* ══════════════════════════════════════════════════════
       SMART MODEL MANAGER
       ══════════════════════════════════════════════════════ */
    public static function _fetch_live_groq_models(): array {
        $now = time();
        if (self::$LIVE_MODELS_CACHE && ($now - self::$LIVE_MODELS_FETCHED_AT) < self::LIVE_MODELS_TTL) {
            return self::$LIVE_MODELS_CACHE;
        }
        if (!self::$GROQ_API_KEYS) {
            // Python mein yahan tak aane se pehle hi "No Groq API key" raise ho jaata hai
            return self::$LIVE_MODELS_CACHE;
        }
        try {
            $r = svims_http_request(
                'GET',
                'https://api.groq.com/openai/v1/models',
                ['Authorization: Bearer ' . self::$GROQ_API_KEYS[0]],
                null,
                6
            );
            if ($r['error'] === null && $r['status'] === 200) {
                $j = json_decode($r['body'], true);
                $all_models = is_array($j) && isset($j['data']) ? $j['data'] : [];
                $chat_models = [];
                foreach ($all_models as $m) {
                    if (!isset($m['id'])) continue;
                    $id_lower = sv_strtolower($m['id']);
                    $skip = false;
                    foreach (self::NON_CHAT_KEYWORDS as $kw) {
                        if (strpos($id_lower, $kw) !== false) { $skip = true; break; }
                    }
                    if (!$skip) $chat_models[] = $m['id'];
                }
                if ($chat_models) {
                    self::$LIVE_MODELS_CACHE = $chat_models;
                    self::$LIVE_MODELS_FETCHED_AT = $now;
                    self::saveModelState();
                    svims_log("  🔄 Live Groq models: [" . implode(", ", $chat_models) . "]");
                    return $chat_models;
                }
            }
        } catch (Throwable $e) {
            svims_log("  ⚠️ Live model fetch failed: " . $e->getMessage());
        }
        return self::$LIVE_MODELS_CACHE;
    }

    public static function _get_active_models(): array {
        $active = [];
        foreach (self::$MODELS_TO_TRY as $m) {
            if (!in_array($m, self::$BLACKLISTED_MODELS, true)) $active[] = $m;
        }
        if ($active) {
            return $active;
        }
        svims_log("  ⚠️ All configured models failed — fetching live list...");
        $live = self::_fetch_live_groq_models();
        if ($live) {
            self::$BLACKLISTED_MODELS = [];
            self::saveModelState();
            return $live;
        }
        self::$BLACKLISTED_MODELS = [];
        self::saveModelState();
        return self::$MODELS_TO_TRY;
    }

    /* ══════════════════════════════════════════════════════
       RESPONSE CACHE — same question dobara → no API call
       TTL: 1800 sec (30 min). Server busy errors 30-40% kam.
       ══════════════════════════════════════════════════════ */
    const CACHE_TTL = 1800; // seconds

    public static function _cache_get(string $key): ?string {
        $cache = svims_state_read('response_cache', []);
        if (isset($cache[$key]) && (time() - $cache[$key][1]) < self::CACHE_TTL) {
            return $cache[$key][0];
        }
        return null;
    }

    public static function _cache_set(string $key, string $value): void {
        $cache = svims_state_read('response_cache', []);
        $cache[$key] = [$value, time()];
        // Memory guard — 500 entries se zyada hone par purane hata do
        if (count($cache) > 500) {
            uasort($cache, function ($a, $b) { return $a[1] <=> $b[1]; });
            $i = 0;
            foreach (array_keys($cache) as $k) {
                if ($i >= 100) break;
                unset($cache[$k]);
                $i++;
            }
        }
        svims_state_write('response_cache', $cache);
    }

    /* ══════════════════════════════════════════════════════
       QUERY EXPANSION — short queries + typos
       ══════════════════════════════════════════════════════ */
    public static function query_expansion_map(): array {
        return [
            "faculties" => "list all faculty members professors of svims departments cs management",
            "faculty" => "list all faculty members professors of svims",
            "list all faculty members of svims" => "list all faculty members professors cs bioscience management ug pg svims",
            "list all faculty" => "list all faculty members professors cs bioscience management ug pg svims",
            "list faculty" => "list all faculty members professors cs bioscience management ug pg svims",
            "all faculty members" => "list all faculty members professors cs bioscience management ug pg svims",
            "policies" => "attendance policy code of conduct fee refund policy svims",
            "policy" => "attendance policy rules svims",
            "admission" => "admission process eligibility how to apply svims",
            "fees" => "fee structure all courses bca bba bsc mba mca svims",
            "fee" => "fee structure courses svims",
            "syllabus" => "syllabus curriculum all courses svims",
            "courses" => "all courses offered ug pg svims",
            "clubs" => "clubs activities edc nss it hr marketing finance svims",
            "cells" => "cells edc nss iic rdc cdc iiic svims",
            "cels" => "cells edc nss iic rdc cdc iiic svims",
            "events" => "events prabandhotsav srijan khelotsav nav udyami abhisanskaran confluence svims",
            "placement" => "placement cell training jobs recruiters svims",
            "hostel" => "hostel facilities accommodation boys girls svims",
            "library" => "library books timings resources svims",
            "scholarship" => "scholarships schemes eligibility svims",
            "contact" => "contact phone email address svims",
            "result" => "how to check exam results svims",
            "results" => "how to check exam results svims",
            "timetable" => "exam time table schedule main atkt svims",
            "attendance" => "attendance policy 75 percent mandatory all courses svims",
            "director" => "director svims dr george thomas",
            "chairman" => "chairman svims leadership trust",
            "patron" => "patron svims leadership trust",
            "facilities" => "facilities labs library hostel sports canteen svims",
            "about" => "about svims history overview accreditation naac",
            "faq" => "frequently asked questions svims",
            "faqs" => "frequently asked questions svims",
            "labs" => "laboratories computer microbiology biotechnology chemistry physics svims",
            "sports" => "sports facilities ground playground svims",
            "canteen" => "canteen food svims",
            "address" => "address location svims gumasta nagar indore",
            "naac" => "naac accreditation grade a svims",
            "ranking" => "ranking business today svims",
            "achievement" => "faculty achievements student achievements awards phd research paper patent svims",
            "achievements" => "faculty achievements student achievements awards phd research paper patent svims",
            "student achievements" => "student achievements awards topper university rank svims",
            "teacher achievements" => "faculty achievements awards research paper phd patent conference svims",
            "faculty achievements" => "faculty achievements awards phd research paper patent intellectual property svims",
            "faculties achivments" => "faculty achievements awards phd research paper patent intellectual property svims",
            "dress code" => "dress code uniform svims",
            "iqac" => "iqac quality assurance svims",
            "alumni" => "alumni association svims",
            "alumini" => "alumni association svims",
            "alumnii" => "alumni association svims",
            // Typos
            "slyabus" => "syllabus svims", "sylabus" => "syllabus svims",
            "palcements" => "placement cell svims", "placments" => "placement svims",
            "schoalrship" => "scholarship svims", "scholrship" => "scholarship svims",
            "addmission" => "admission process svims", "admision" => "admission svims",
            "libary" => "library svims", "libraray" => "library svims",
            "hostle" => "hostel svims",
            "faculity" => "faculty members svims", "faculy" => "faculty svims",
            "driector" => "director svims", "dierctor" => "director svims",
            "attendence" => "attendance policy svims", "atendance" => "attendance svims",
            "fess" => "fee structure svims", "feees" => "fee structure svims",
            "pg faculties" => "pg management faculty list svims",
            "ug faculties" => "ug management faculty list svims",
            "cs faculties" => "cs bioscience faculty list svims",
            "achivments" => "achievements awards svims",
            "achivment" => "achievement awards svims",
            "placement officiers" => "training placement officer tpo name designation svims",
            "placement officer" => "training placement officer tpo name designation svims",
            "mca syllabus" => "mca syllabus curriculum master computer applications svims",
            "biotechnology syllabus" => "bsc biotechnology bt syllabus i year svims",
            "bioinformatics syllabus" => "bsc bioinformatics bi syllabus i year svims",
            "microbiology syllabus" => "bsc microbiology mb syllabus i year svims",
        ];
    }

    public static function expand_query(string $question): string {
        $map = self::query_expansion_map();
        $q_lower = sv_strtolower(trim($question));
        if (isset($map[$q_lower])) {
            return $map[$q_lower];
        }
        $close = svims_get_close_matches($q_lower, array_keys($map), 1, 0.82);
        if ($close) {
            return $map[$close[0]];
        }
        return $question;
    }

    /* ══════════════════════════════════════════════════════
       OUT OF SCOPE — only block CLEARLY unrelated topics
       Default = SVIMS related (safer)
       ══════════════════════════════════════════════════════ */
    public static function non_svims_topics(): array {
        return [
            "prime minister", "president of india", "weather today",
            "write code", "write a program", "python code", "java code",
            "recipe", "movie review", "cricket score", "stock price",
            "who is elon musk", "who is modi", "who is ambani", "who is mukesh",
            "who is bill gates", "who is sachin", "capital of", "population of",
            "translate", "joke", "poem about", "story about",
            "what is ai", "what is machine learning", "chatgpt",
            "taj mahal", "where is taj", "pythagoras", "pythagorean",
            "explain theorem", "newton", "einstein", "who is virat",
            "who is dhoni", "bollywood", "hollywood", "cricket team",
        ];
    }

    // Math-only patterns — answer directly without SVIMS context
    const MATH_PATTERN = '/^[\d\s\+\-\*\/\(\)\=\?\.]+$/';

    public static function is_out_of_scope(string $question): bool {
        $q = sv_strtolower(trim($question));
        if (in_array($q, ["hi", "hello", "hey", "ok", "okay", "thanks", "thank you"], true)) {
            return false;
        }
        foreach (self::non_svims_topics() as $topic) {
            if (strpos($q, $topic) !== false) return true;
        }
        return false;
    }

    /** Simple arithmetic like 2+5=? — answer directly */
    public static function is_pure_math(string $question): bool {
        $q = trim($question);
        return (preg_match(self::MATH_PATTERN, $q) === 1) && sv_strlen($q) < 30;
    }

    /* ══════════════════════════════════════════════════════════════
       FULLY HARDCODED ANSWERS — zero AI involvement, always identical
       ══════════════════════════════════════════════════════════════
       In sawalon ke jawab kabhi AI se nahi banaye jaate — yeh static text
       hai jo direct return hota hai. Isse "Server busy" jaisa error kabhi
       nahi aata in queries pe, aur jawab hamesha 100% same rehta hai.

       PHONE NUMBERS: show_staff_phones = false (config.json) hone par
       HOD/Director ke numbers chatbot answer mein nahi dikhenge. Sirf
       official email aur faculty directory link milega.
       ══════════════════════════════════════════════════════════════ */

    /** Faculty hardcoded answers — sirf naam, designation, email, aur directory link (no phone numbers). */
    public static function _build_faculty_answers(): void {
        self::$FACULTY_LIST_ANSWER = <<<EOT
SVIMS Faculty — Department Overview

**Director:** Dr. George Thomas | svimi@svimi.org

**Computer & BioScience:**
HOD: Dr. Kshama Paithankar (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_cs

**Management (UG):**
HOD: Dr. Deepa Katiyal (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_UG

**Management (PG):**
HOD: Dr. Mandip Gill (Professor & HOD)
Full List → https://www.svimi.org/departments/faculties.php?q=faculty_PG

**Training & Placement:**
T&P Officer: Mr. Hemant Pathak
Asst. T&P Officer: Mr. Sourabh Upadhyay
For queries: svimi@svimi.org
EOT;

        self::$CS_FACULTY_ANSWER = <<<EOT
**Computer & BioScience Department**

HOD: Dr. Kshama Paithankar (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_cs
EOT;

        self::$UG_FACULTY_ANSWER = <<<EOT
**Management (UG) Department**

HOD: Dr. Deepa Katiyal (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_UG
EOT;

        self::$PG_FACULTY_ANSWER = <<<EOT
**Management (PG) Department**

HOD: Dr. Mandip Gill (Professor & HOD) | svimi@svimi.org

For complete faculty list with profiles and qualifications, visit:
https://www.svimi.org/departments/faculties.php?q=faculty_PG
EOT;
    }

    // ══ SYLLABUS ANSWERS — config.json se build hote hain ══
    // ══ SCHOLARSHIP HARDCODED ANSWER ══
    public static function scholarship_answer(): string {
        return <<<EOT
Scholarships Available at SVIMS

— Post Metric Scholarship (SC/ST/OBC — based on family income)
— Minority Scholarship (minority community students)
— Central Sector Scheme (80%+ marks in 10+2)
— Awas Scholarship (SC/ST students)
— PG Indira Gandhi Scholarship (Single Girl Child pursuing PG)
— AICTE PG Scholarship / GATE Fellowship
— SVIMS Meritorious Scholarship (for students with 75%+ attendance and good academic performance)

For eligibility details and application process, visit:
https://www.svimi.org/scholarship.php
Or email: svimi@svimi.org
EOT;
    }

    public static function faqs_answer(): string {
        return <<<EOT
Frequently Asked Questions (FAQs) — SVIMS

For the complete list of FAQs covering admissions, courses, fees, attendance, facilities and more, visit the official FAQ pages:

— **General FAQs:** https://www.svimi.org/FAQs.php
— **Academic FAQs:** https://www.svimi.org/academic-faqs.php

If your question is not answered there, email svimi@svimi.org or call Toll Free: 18002332601
EOT;
    }

    /**
     * Faculty list aur syllabus jaise FIXED-answer queries ke liye hamesha
     * same, static jawab return karta hai — AI ko bilkul call nahi kiya jaata.
     * Match nahi mila toh null return karta hai (normal flow continue hoga).
     *
     * @return array|null [answer, link]
     */
    public static function get_hardcoded_answer(string $question): ?array {
        $q = sv_strtolower(trim($question));
        $q_clean = preg_replace('/[^a-z0-9 ]/', ' ', $q);
        $q_clean = trim((string)preg_replace('/\s+/', ' ', $q_clean));

        // ── Faculty list queries (check specific department FIRST) ──
        if (strpos($q_clean, "pg faculty") !== false || strpos($q_clean, "pg faculties") !== false ||
            strpos($q_clean, "management pg faculty") !== false || strpos($q_clean, "faculty list of pg") !== false ||
            strpos($q_clean, "pg faculty list") !== false || strpos($q_clean, "faculty of pg") !== false ||
            strpos($q_clean, "mba faculty") !== false) {
            return [self::$PG_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_PG"];
        }

        if (strpos($q_clean, "ug faculty") !== false || strpos($q_clean, "ug faculties") !== false ||
            strpos($q_clean, "management ug faculty") !== false || strpos($q_clean, "faculty list of ug") !== false ||
            strpos($q_clean, "ug faculty list") !== false || strpos($q_clean, "faculty of ug") !== false ||
            strpos($q_clean, "bba faculty") !== false) {
            return [self::$UG_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_UG"];
        }

        if (strpos($q_clean, "cs faculty") !== false || strpos($q_clean, "computer science faculty") !== false ||
            strpos($q_clean, "bioscience faculty") !== false || strpos($q_clean, "computer faculty") !== false ||
            strpos($q_clean, "cs faculties") !== false || strpos($q_clean, "faculty list of cs") !== false ||
            strpos($q_clean, "faculty of cs") !== false || strpos($q_clean, "faculty of computer") !== false ||
            strpos($q_clean, "bca faculty") !== false) {
            return [self::$CS_FACULTY_ANSWER, "https://www.svimi.org/departments/faculties.php?q=faculty_cs"];
        }

        $faculty_all_triggers = [
            "list all faculty", "all faculty member", "faculty members of svims",
            "list faculty", "all faculties", "faculty list", "faculties list",
            "complete faculty", "show all faculty", "total faculty",
        ];
        $is_faculty_all = in_array($q_clean, ["faculty", "faculties", "faculty members"], true);
        if (!$is_faculty_all) {
            foreach ($faculty_all_triggers as $t) {
                if (strpos($q_clean, $t) !== false) { $is_faculty_all = true; break; }
            }
        }
        if ($is_faculty_all) {
            return [self::$FACULTY_LIST_ANSWER, "https://www.svimi.org/departments/faculties.php"];
        }

        // ── Syllabus queries ──────────────────────────────────────
        $syllabus_words = ["syllabus", "sylabus", "slyabus", "slybus", "sllyabus",
                           "sllybus", "syllabuss", "curriculum", "sillabus", "sllaybus"];
        $has_syllabus = false;
        foreach ($syllabus_words as $w) {
            if (strpos($q_clean, $w) !== false) { $has_syllabus = true; break; }
        }
        if ($has_syllabus) {
            // "all syllabus", "give me all syllabus", "all syllabus link" etc
            $all_triggers = ["all syllabus", "all syla", "give me all", "give all", "sabhi syllabus",
                             "sare syllabus", "saare syllabus", "complete syllabus", "every syllabus",
                             "all course syllabus", "list syllabus", "show syllabus"];
            $course_kws = [
                "bca" => ["bca"], "bba" => ["bba"],
                "mba" => ["mba"], "mca" => ["mca"],
                "msc cs" => ["msc cs", "m sc cs", "msc computer", "m.sc"],
                "bsc cs" => ["bsc cs", "b sc cs", "bsc computer", "computer science"],
                "biotechnology" => ["biotechnology", "biotech"],
                "bioinformatics" => ["bioinformatics"],
                "microbiology" => ["microbiology"],
            ];
            $matched = [];
            foreach ($course_kws as $c => $kws) {
                foreach ($kws as $kw) {
                    if (strpos($q_clean, $kw) !== false) { $matched[] = $c; break; }
                }
            }

            $all_asked = false;
            foreach ($all_triggers as $t) {
                if (strpos($q_clean, $t) !== false) { $all_asked = true; break; }
            }

            if ($all_asked || ($has_syllabus && !$matched)) {
                // No specific course mentioned OR "all syllabus" asked → full list
                $all_text =
                    "Here are all available syllabus PDFs at SVIMS:\n\n" .
                    "**UG Programmes:**\n" .
                    "— BCA I Year: https://www.svimi.org/assets/images/BCA_I_Year_Syllabus.pdf\n" .
                    "— BBA II Sem: https://www.svimi.org/assets/images/BBA_II_Sem_Syllabus.pdf\n" .
                    "— BBA (Foreign Trade) II Sem: https://www.svimi.org/assets/images/BBA_(FT)_II_Sem_Syllabus.pdf\n" .
                    "— BBA (Hospital Admin) II Sem: https://www.svimi.org/assets/images/BBA_(HA)_II_Sem_Syllabus.pdf\n" .
                    "— B.Sc. Computer Science I Year: https://www.svimi.org/assets/images/B.%20Sc._(CS)_I_Year_Syllabus.pdf\n" .
                    "— B.Sc. Biotechnology I Year: https://www.svimi.org/assets/images/B.%20Sc._(BT)_I_Year_Syllabus.pdf\n" .
                    "— B.Sc. Bioinformatics I Year: https://www.svimi.org/assets/images/B.%20Sc._(BI)_I_Year_Syllabus.pdf\n" .
                    "— B.Sc. Microbiology I Year: https://www.svimi.org/assets/images/B.%20Sc._(MB)_I_Year_Syllabus.pdf\n\n" .
                    "**PG Programmes:**\n" .
                    "— MBA Full Time: https://www.svimi.org/assets/images/MBA_FT_Syllabus.pdf\n" .
                    "— MBA Financial Administration: https://www.svimi.org/assets/images/MBA_FA_Syllabus.pdf\n" .
                    "— MBA Marketing Management: https://www.svimi.org/assets/images/MBA_MM_Syllabus.pdf\n" .
                    "— MCA: https://www.svimi.org/assets/images/MCA_Syllabus.pdf\n" .
                    "— M.Sc. CS: https://www.svimi.org/assets/images/M.Sc.CS_Syllabus.pdf";
                return [$all_text, "https://www.svimi.org/under-graduate.php"];
            }
        }

        // ── Academic Calendar ─────────────────────────────────────
        $calendar_triggers = ["academic calendar", "calender", "calendar", "semester dates",
                              "academic schedule", "holiday list", "exam calendar"];
        foreach ($calendar_triggers as $t) {
            if (strpos($q_clean, $t) !== false) {
                $link = isset(self::$ACADEMIC_CALENDAR['link']) ? self::$ACADEMIC_CALENDAR['link']
                    : "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf";
                return [self::$ACADEMIC_CALENDAR_ANSWER, $link];
            }
        }

        // ── FAQs ─────────────────────────────────────────────────
        $faq_triggers = ["faq", "faqs", "frequently asked", "show me all faq",
                         "all faqs", "common questions", "academic faq"];
        foreach ($faq_triggers as $t) {
            if (strpos($q_clean, $t) !== false) {
                return [self::faqs_answer(), "https://www.svimi.org/FAQs.php"];
            }
        }

        // ── Anti-Ragging ──────────────────────────────────────────
        $ragging_triggers = ["anti ragging", "anti-ragging", "ragging", "ragging committee",
                             "anti ragging committee"];
        foreach ($ragging_triggers as $t) {
            if (strpos($q_clean, $t) !== false) {
                $ragging_answer =
                    "**Anti-Ragging Committee — SVIMS**\n\n" .
                    "SVIMS has constituted an Anti-Ragging Committee as per UGC Anti-Ragging Regulations, 2009.\n\n" .
                    "**Key Officials:**\n" .
                    "— Director: Dr. George Thomas\n" .
                    "— Nodal Officer: Dr. Sandeep Malu\n" .
                    "— Monitoring Cell: Dr. Kshama Paithankar, Dr. Deepa Katiyal, Dr. Mandip Gill\n\n" .
                    "**Committee includes representatives from:**\n" .
                    "— Institute Administration, Police (ACP + Station), Media, Parents, Students, Hostel Wardens, Canteen\n\n" .
                    "**If you experience ragging:** Contact any committee member, faculty, hostel warden, or email svimi@svimi.org immediately.\n\n" .
                    "Full committee details: https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf";
                return [$ragging_answer, "https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf"];
            }
        }

        // ── Scholarship queries ──────────────────────────────────
        $scholarship_triggers = [
            "scholarship", "schoalrship", "scholrship", "merit scholarship",
            "meritorious", "svims scholarship", "fee waiver", "financial aid",
            "post metric", "minority scholarship", "central sector",
        ];
        foreach ($scholarship_triggers as $t) {
            if (strpos($q_clean, $t) !== false) {
                return [self::scholarship_answer(), "https://www.svimi.org/scholarship.php"];
            }
        }

        return null;
    }

    /* ══════════════════════════════════════════════════════
       VERIFIED LINKS (from PDF + official site — 75+ real URLs)
       ══════════════════════════════════════════════════════ */
    public static function buildTopicLinks(): array {
        $ACH = self::$ACHIEVEMENT_CFG;
        $CAL = self::$ACADEMIC_CALENDAR;
        $faculty_ach_link = isset($ACH['faculty']) ? $ACH['faculty']
            : "https://www.svimi.org/assets/images/achievements/Faculty_Other_Achievement_2024-25.pdf";
        $faculty_ach_year = isset($ACH['faculty_year']) ? $ACH['faculty_year'] : '2024-25';
        $student_ach_link = isset($ACH['student']) ? $ACH['student']
            : "https://www.svimi.org/assets/images/achievements/Student_Achievements_2024-25.pdf";
        $student_ach_year = isset($ACH['student_year']) ? $ACH['student_year'] : '2024-25';
        $cal_link = isset($CAL['link']) ? $CAL['link']
            : "https://www.svimi.org/assets/images/Academic_Calender_2025-26.pdf";
        $cal_year = isset($CAL['year']) ? $CAL['year'] : '2025-26';

        return [
            [["admission", "apply", "eligibility", "counselling", "addmission", "admision"],
             "https://www.svimi.org/admission-process.php", "Admission Process"],
            [["pg admission", "mba admission", "mca admission"],
             "https://www.svimi.org/admission-process.php#pg_admission_process", "PG Admission"],
            [["fee payment", "pay fee", "online payment", "pay online"],
             "https://accsoft.svimi.org/Accsoft_SVG/AdmissionRegPayment.aspx", "Online Fee Payment"],
            [["fee refund", "refund policy", "cancel admission"],
             "https://www.svimi.org/assets/images/Fee_Refund_Policy.pdf", "Fee Refund Policy"],
            [["fee", "fees", "fess", "feees", "tuition", "cost"],
             "https://www.svimi.org/scholarship.php", "Fee & Scholarship Info"],
            [["scholarship", "schoalrship", "scholrship", "merit"],
             "https://www.svimi.org/scholarship.php", "Scholarships"],
            [["placement officer", "placement officiers", "tpo", "training placement officer"],
             "https://www.svimi.org/placement/about-placement.php", "Placement Cell - T&P Team"],
            [["highest package", "average package", "placement rate", "placement percentage",
              "placement 2025", "placement 2024", "placement stats", "placement record",
              "kitne students place", "placement details", "package kitna", "salary package",
              "prominent", "placed students"],
             "https://www.svimi.org/placement/prominent-selections.php", "Placement Details & Glimpses"],
            [["placement cell", "placement", "palcements", "placments", "job", "recruiter"],
             "https://www.svimi.org/placement/about-placement.php", "Placement Cell"],
            [["library", "books", "libary", "libraray", "journal"],
             "https://www.svimi.org/infrastructure/library.php", "Library"],
            [["computer lab", "lab", "laboratory", "labs"],
             "https://www.svimi.org/infrastructure/computer.php", "Computer Lab"],
            [["bio lab", "biotech lab", "microbiology lab", "mi-bt"],
             "https://www.svimi.org/infrastructure/MI-BT.php", "Bio Lab"],
            [["auditorium", "abhay prashal"],
             "https://www.svimi.org/infrastructure/auditorium.php", "Auditorium"],
            [["about bca", "bca program", "bca course"],
             "https://www.svimi.org/under-graduate.php#aboutBCASec", "About BCA"],
            [["about bba", "bba program", "bba course"],
             "https://www.svimi.org/under-graduate.php#aboutBBASec", "About BBA"],
            [["about bsc", "b.sc program", "bsc course", "b.sc. computer science",
              "bsc computer science", "b.sc computer science", "career after b.sc",
              "career opportunities after b.sc", "career opportunities for b.sc"],
             "https://www.svimi.org/under-graduate.php#aboutBscSec", "About B.Sc"],
            [["about mba", "mba program", "mba course"],
             "https://www.svimi.org/post-graduate.php#aboutMBASec", "About MBA"],
            [["about mca", "mca program", "mca course"],
             "https://www.svimi.org/post-graduate.php", "About MCA"],
            [["pg faculty", "mba faculty", "faculity", "faculy", "pg faculties"],
             "https://www.svimi.org/departments/faculties.php?q=faculty_PG", "PG Faculty"],
            [["ug faculty", "bba faculty", "ug faculties"],
             "https://www.svimi.org/departments/faculties.php?q=faculty_UG", "UG Faculty"],
            [["cs faculty", "computer faculty", "bioscience faculty", "cs faculties", "faculty", "faculties"],
             "https://www.svimi.org/departments/faculties.php?q=faculty_cs", "CS Faculty"],
            [["faculty achievement", "faculty achievements", "research paper", "patent", "phd award"],
             $faculty_ach_link, "Faculty Achievements {$faculty_ach_year}"],
            [["student achievement", "topper", "university rank"],
             $student_ach_link, "Student Achievements {$student_ach_year}"],
            [["edc", "entrepreneurship", "nav udyami", "incubation"],
             "https://www.svimi.org/cells/edc.php", "EDC Cell"],
            [["nss"], "https://www.svimi.org/cells/nss.php", "NSS Cell"],
            [["iic", "innovation"], "https://www.svimi.org/cells/iic.php", "IIC"],
            [["rdc", "research development"], "https://www.svimi.org/cells/rdc.php", "RDC"],
            [["cdc", "case development"], "https://www.svimi.org/cells/cdc.php", "CDC"],
            [["iiic", "industry institute"], "https://www.svimi.org/cells/iiic.php", "IIIC"],
            [["iqac", "quality assurance"], "https://www.svimi.org/iqac.php", "IQAC"],
            [["nirf", "ranking"], "https://www.svimi.org/ranking-nirf.php", "NIRF Ranking"],
            [["naac", "accreditation"], "https://www.svimi.org/recongnition-description.php", "Recognition & Accreditation"],
            [["academic faq"], "https://www.svimi.org/FAQs.php", "FAQs"],
            [["faq", "faqs", "frequently asked"], "https://www.svimi.org/FAQs.php", "FAQs"],
            [["erp", "student portal", "login"],
             "https://accsoft.svimi.org/accsoft_SVG/studentlogin.aspx", "Student ERP"],
            [["atkt"], "https://www.svimi.org/Time-Table-ATKT.php", "ATKT Time Table"],
            [["timetable", "time table", "exam schedule"],
             "https://www.svimi.org/Time-Table-Main.php", "Exam Time Table"],
            [["result", "marks", "results"], "https://www.svimi.org/Results.php", "Results"],
            [["notification", "notice", "announcement"],
             "https://www.svimi.org/Notification.php", "Notifications"],
            [["anti ragging", "ragging"],
             "https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf", "Anti-Ragging Committee"],
            [["contact", "phone", "email", "address"],
             "https://www.svimi.org/contact-us.php", "Contact Us"],
            [["governing body", "trust", "board"],
             "https://www.svimi.org/governing-body.php", "Governing Body"],
            [["chairman", "patron", "director", "leadership", "driector", "dierctor"],
             "https://www.svimi.org/leadership.php?q=director", "Leadership"],
            [["alumni", "alumini", "alumnii"], "https://www.svimi.org/alumni-speak.php", "Alumni Speaks"],
            [["alumni association", "alumni meet", "confluence"],
             "https://www.svimi.org/alumni_association.php", "Alumni Association"],
            [["journal", "management effigy"], "https://www.managementeffigy.in/archives.php", "Management Effigy Journal"],
            [["vision", "mission"], "https://www.svimi.org/vision.php", "Vision & Mission"],
            [["calendar", "academic calendar"],
             $cal_link, "Academic Calendar {$cal_year}"],
            [["virtual tour", "campus tour", "360"],
             "https://www.svimi.org/", "Virtual Campus Tour"],
            [["about svims", "history of svims", "svims history"],
             "https://www.svimi.org/about-institute-description.php", "About SVIMS"],
            [["hostel", "hostle"], "https://www.svimi.org/infrastructure/hostel.php", "Hostel"],
            [["canteen"], "https://www.svimi.org/infrastructure/canteen.php", "Canteen"],
            [["sports"], "https://www.svimi.org/infrastructure/sports.php", "Sports"],
            [["it club"], "https://www.svimi.org/activity-clubs/it-club.php", "IT Club"],
            [["finance club"], "https://www.svimi.org/activity-clubs/finance-club.php", "Finance Club"],
            [["hr club"], "https://www.svimi.org/activity-clubs/hr-club.php", "HR Club"],
            [["marketing club"], "https://www.svimi.org/activity-clubs/marketing-club.php", "Marketing Club"],
            [["literary club"], "https://www.svimi.org/activity-clubs/literary-club.php", "Literary Club"],
            [["science club"], "https://www.svimi.org/activity-clubs/science-club.php", "Science Club"],
            [["photography club"], "https://www.svimi.org/activity-clubs/photography-club.php", "Photography Club"],
            [["what clubs", "clubs available", "clubs at svims", "list of clubs", "all clubs", "club"],
             "https://www.svimi.org/activity-clubs/it-club.php", "Activity Clubs"],
            [["events", "major events", "event calendar", "prabandhotsav", "srijan", "khelotsav",
              "nav udyami", "abhisanskaran", "confluence"],
             "https://www.svimi.org/event-gallery.php", "Events"],
            [["faculites", "faculty overview", "all faculty"],
             "https://www.svimi.org/departments/faculties.php?q=faculty_cs", "Faculty Directory"],
            [["slybus", "sylabus", "syllabus", "curriculum"],
             "https://www.svimi.org/under-graduate.php", "Syllabus Info"],
        ];
    }

    /**
     * Sirf EK relevant link return karo.
     * Pehle question ke keyword se TOPIC_LINKS mein best match dhundo.
     * Agar match ka URL None hai (e.g. MCA syllabus), koi link mat do.
     * Agar koi match nahi mila, tabhi context se URL nikalo (fallback).
     *
     * @return array[] list of [url, label]
     */
    public static function get_links(string $question, string $context = ""): array {
        $q = sv_strtolower($question);

        $best_match = null;
        $best_score = 0;
        foreach (self::$TOPIC_LINKS as $entry) {
            list($keywords, $url, $label) = $entry;
            foreach ($keywords as $kw) {
                if (strpos($q, $kw) !== false && sv_strlen($kw) > $best_score) {
                    $best_score = sv_strlen($kw);
                    $best_match = [$url, $label];
                }
            }
        }

        if ($best_match) {
            list($url, $label) = $best_match;
            if ($url === null) {
                // Explicitly "no link exists" — don't show any link
                return [];
            }
            return [[$url, $label]];
        }

        if ($context !== '') {
            $urls = [];
            if (preg_match_all('/https?:\/\/[^\s\)\]\>",]+/', $context, $m)) {
                $urls = $m[0];
            }
            $specific_urls = [];
            foreach ($urls as $u) {
                if (rtrim($u, '/') !== "https://www.svimi.org") $specific_urls[] = $u;
            }
            $target = $specific_urls ? $specific_urls[0] : ($urls ? $urls[0] : null);
            if ($target !== null) {
                $url = rtrim($target, '.,;)');
                return [[$url, "More Info"]];
            }
        }

        return [];
    }

    /* ══════════════════════════════════════════════════════
       CHATBOT FACTORY
       ══════════════════════════════════════════════════════ */

    /**
     * pdf_path: agar diya jaaye, toh PDF se direct Q&A matcher bhi banta hai —
     * isse exact PDF questions ka jawab 100% accurate (hallucination-free) milta hai.
     */
    public static function create_chatbot(SVIMSVectorStore $vector_store, ?string $api_key = null, ?string $pdf_path = null): array {
        $qa_matcher = null;
        if ($pdf_path === null) {
            // college_docs/ folder mein PDF dhundo automatically
            $docs_folder = __DIR__ . '/college_docs';
            if (is_dir($docs_folder)) {
                $pdfs = [];
                foreach (scandir($docs_folder) ?: [] as $f) {
                    if (substr(sv_strtolower($f), -4) === '.pdf') $pdfs[] = $f;
                }
                if ($pdfs) {
                    $pdf_path = $docs_folder . '/' . $pdfs[0];
                }
            }
        }

        if ($pdf_path !== null && is_file($pdf_path)) {
            try {
                $qa_matcher = new SVIMSQAMatcher($pdf_path, __DIR__ . '/svims_qa_cache.pkl');
            } catch (Throwable $e) {
                svims_log("  ⚠️ Q&A direct matcher could not be built: " . $e->getMessage());
                $qa_matcher = null;
            }
        }

        return [
            "client" => isset(self::$groq_clients[0]) ? self::$groq_clients[0] : null,
            "retriever" => $vector_store->as_retriever(8),
            "qa_matcher" => $qa_matcher,
        ];
    }

    /* ══════════════════════════════════════════════════════
       GROQ API CALL
       ══════════════════════════════════════════════════════ */

    /** Single chat completion — Groq OpenAI-compatible REST API pe */
    private static function groqChatCompletion(string $api_key, string $model, array $messages): string {
        $payload = json_encode([
            'model' => $model,
            'messages' => $messages,
            'max_tokens' => 600,
            'temperature' => 0.0,
        ], JSON_UNESCAPED_UNICODE);

        $res = svims_http_request('POST', 'https://api.groq.com/openai/v1/chat/completions', [
            'Authorization: Bearer ' . $api_key,
            'Content-Type: application/json',
        ], $payload, 60);

        if ($res['error'] !== null) {
            throw new RuntimeException('Connection error: ' . $res['error']);
        }
        if ($res['status'] !== 200) {
            // SDK-style error message — taaki keyword checks (401/429/model_not_found/...) same kaam karein
            throw new RuntimeException("Error code: {$res['status']} - {$res['body']}");
        }
        $j = json_decode($res['body'], true);
        if (!is_array($j) || !isset($j['choices'][0]['message']['content'])) {
            throw new RuntimeException('Invalid response from Groq API: ' . sv_substr($res['body'], 0, 200));
        }
        return (string)$j['choices'][0]['message']['content'];
    }

    /**
     * $client param backward-compat ke liye rakha hai (ignore hota hai) —
     * ab yeh function khud groq_clients list mein se key rotate karta hai:
     *   1. Round-robin: har naya request agli key try karta hai (load balance)
     *   2. Fallback: agar current key rate-limited/invalid ho, to next key
     *      automatically try hoti hai — user ko error nahi dikhta.
     */
    public static function _call_groq($client, array $messages): string {
        $last_error = null;
        $num_keys = count(self::$groq_clients);

        for ($key_attempt = 0; $key_attempt < $num_keys; $key_attempt++) {
            $active_client = self::_get_client();

            foreach (self::_get_active_models() as $model) {
                for ($attempt = 0; $attempt < 3; $attempt++) {
                    try {
                        return self::groqChatCompletion($active_client, $model, $messages);
                    } catch (Throwable $e) {
                        $last_error = $e;
                        $err = sv_strtolower($e->getMessage());
                        if (strpos($err, "invalid_api_key") !== false || strpos($err, "401") !== false) {
                            svims_log("  ❌ This key invalid — trying next key...");
                            break; // is key ko chhodo, agli key try karo
                        }
                        if (strpos($err, "model_not_found") !== false || strpos($err, "does not exist") !== false ||
                            strpos($err, "model not found") !== false || strpos($err, "deprecated") !== false) {
                            svims_log("  ❌ '{$model}' expired/not found — blacklisting, switching...");
                            if (!in_array($model, self::$BLACKLISTED_MODELS, true)) {
                                self::$BLACKLISTED_MODELS[] = $model;
                            }
                            self::saveModelState();
                            break;
                        }
                        if (strpos($err, "413") !== false || strpos($err, "request too large") !== false ||
                            strpos($err, "tokens_per_minute") !== false) {
                            break;
                        }
                        if (strpos($err, "429") !== false || strpos($err, "rate_limit") !== false) {
                            if ($attempt < 2) {
                                sleep((int)pow(2, $attempt));
                                continue;
                            }
                            svims_log("  ⏳ Key rate-limited — trying next key...");
                            break;
                        }
                        break;
                    }
                }
            }
            // is key se sab models fail ho gaye — agli key try karo (agar hai)
            if ($key_attempt < $num_keys - 1) {
                continue;
            }
        }

        // Sab keys/models fail — live API se fresh models try karo (pehli key se)
        foreach ((self::_fetch_live_groq_models() ?: []) as $model) {
            if (in_array($model, self::$MODELS_TO_TRY, true)) {
                continue;
            }
            foreach (self::$groq_clients as $gclient) {
                try {
                    $response = self::groqChatCompletion($gclient, $model, $messages);
                    svims_log("  ✅ Live fallback '{$model}' worked!");
                    return $response;
                } catch (Throwable $e) {
                    $last_error = $e;
                }
            }
        }
        if ($last_error !== null) throw $last_error;
        throw new RuntimeException("No working Groq model found");
    }

    /* ══════════════════════════════════════════════════════
       SYSTEM PROMPT TEMPLATE (verbatim — {context} fill hota hai)
       ══════════════════════════════════════════════════════ */
    private static function system_prompt_template(): string {
        return <<<'SVIMSPROMPT'
You are CampusBot — official AI assistant for SVIMS Indore (Shri Vaishnav Institute of Management & Science).

══════════════════════════════════════
LANGUAGE: Always reply in English only. Understand Hindi/Hinglish but reply in English.

FORMATTING RULES:
- NEVER use markdown tables (no | column | format |). Use clean lines instead.
- For lists, use simple dashes (—) or bullet points, not numbered lists.
- Keep answers short and clean — no unnecessary padding or repetition.
- For faculty: mention only HOD name + email. For full list, give the link.
- Example of GOOD format:
  HOD: Dr. Kshama Paithankar | svimi@svimi.org
  Full list: https://www.svimi.org/departments/faculties.php?q=faculty_cs
- Example of BAD format (avoid):
  | Name | Phone | Designation |
  |------|-------|-------------|
══════════════════════════════════════

══════════════════════════════════════
STRICT RULES — NO EXCEPTIONS
══════════════════════════════════════
1. Answer using ONLY the CONTEXT below and the KNOWN FACTS section.
2. CRITICAL — If a topic is NOT clearly and explicitly present in CONTEXT or
   KNOWN FACTS, say: "I don't have this specific information. Please visit
   www.svimi.org or contact svimi@svimi.org | Toll Free: 18002332601"
   Do NOT guess. Do NOT build a plausible-sounding structure from general
   knowledge of what such things "usually" look like.
2a. CRITICAL — CELL/COMMITTEE MEMBERSHIP: Never invent who manages, heads,
    coordinates, or is a member of any cell or committee (EDC, NSS, IIC, RDC,
    IIIC, CDC, etc.) unless their EXACT name and role is explicitly stated in
    CONTEXT. Do NOT assume the T&P team runs the EDC cell, or that a Dept HOD
    is automatically an "Advisor" to a cell. Each cell may have its own
    separate committee with different people — never reuse names from one
    cell/department and assign them roles in a different cell without
    explicit evidence in CONTEXT. If exact committee members are not in
    CONTEXT, say "I don't have the exact list of committee members for this
    cell. Please visit www.svimi.org or contact svimi@svimi.org."
3. NEVER repeat the same name for multiple different people/roles.
4. NEVER invent: phone extensions, emails, fake URLs, fake event names,
   fake statistics, fake committee members, fake office bearers.
4a. CRITICAL — PHONE NUMBERS: Each person has at most ONE phone number listed
    in KNOWN FACTS. If a person's phone number is NOT explicitly given in
    KNOWN FACTS or CONTEXT, do NOT attach any other person's number to them.
    Say "contact via svimi@svimi.org" instead. NEVER reuse the Admin Officer's
    number (9301527178) for T&P Officer, faculty, or anyone else — that
    number belongs ONLY to the Administrative Officer.
4b. NEVER invent specific FACTUAL numbers: placement percentage, salary
    packages, company-wise placement percentages, batch years, student
    counts, or any SVIMS-specific statistic not VERBATIM present in CONTEXT.
    This includes "estimated", "approximate", or "anumaniya" (अनुमानित)
    numbers — giving a number with a disclaimer like "this is an estimate"
    is STILL forbidden and STILL hallucination. If exact placement
    percentage/data is not in CONTEXT, say EXACTLY: "I don't have the exact
    placement details. For verified placement data and latest glimpses,
    please visit: https://www.svimi.org/placement/prominent-selections.php"
    Do NOT soften this into a guessed number under any framing.
    EXCEPTION — this rule does NOT apply to simple logic/math questions that
    don't require any SVIMS-specific fact, e.g. "if a course is 4 years,
    how many semesters is that?" (answer: 8, using standard 2 semesters/year
    — this is basic arithmetic, not a fact lookup, so answer it normally).
    The restriction is only on SVIMS-specific data points (placement %,
    fees amounts, student counts, dates) that we don't actually have.
4b2. NEVER rank, compare, or recommend one course as "better" than another
    for placement, career prospects, or any other reason UNLESS CONTEXT
    explicitly states such a comparison. Do NOT say things like "B.Sc. CS
    has stronger placement results than BCA" or "X is more popular" unless
    this exact comparison is in CONTEXT. If asked "which course is best for
    placement", say: "I don't have comparative placement data between
    courses. Please visit the Prominent Selections page on www.svimi.org or
    contact the Placement Cell for guidance." All UG/PG courses share the
    same recruiter list (TCS, Deloitte, Wipro, etc.) — do not imply one
    course has better outcomes than another.
4c. Do NOT invent generic clubs that sound plausible unless explicitly named
    in CONTEXT. SVIMS's real clubs are listed in KNOWN FACTS — use ONLY those.
5. The ONLY official email is svimi@svimi.org (or admission@svimi.org for admissions).
6. The ONLY official phone numbers are listed in KNOWN FACTS — never invent extensions
   or reassign one person's number to another person.
7. Do NOT add URLs or "Source:" labels in answer text — the system adds ONE
   link separately after your answer. Just give the factual answer in prose.
   NEVER write the literal word "Source" as a placeholder (e.g. never write
   "Source: Source" or "🔗 Source:" with nothing useful after it). If you are
   tempted to cite a source, simply omit it — the system handles all links.
8. Attendance is ALWAYS 75% for ALL courses.
9. SVIMS has ONLY ONE campus in Gumasta Nagar, Indore. Never mention Khandwa Road.
10. When unsure whether something is real or plausible-sounding, ALWAYS choose
    to say "I don't have this information" rather than answer with invented details.
11. For syllabus PDF links: ONLY mention links that are explicitly present in
    CONTEXT. MCA does NOT have a direct syllabus PDF link in our data — if asked,
    say "I don't have a direct syllabus PDF link for MCA. Please contact
    svimi@svimi.org or visit www.svimi.org/post-graduate.php"
12. CRITICAL — NEVER invent individual named examples (student names, specific
    years, specific competitions, specific universities like "IIM Ahmedabad",
    specific startup names, specific awards with names attached) UNLESS that
    exact name/detail is explicitly present in CONTEXT. This applies even when
    using a placeholder like "[Name]" — using a placeholder to invent a fake
    structured example is STILL hallucination and is forbidden. If CONTEXT only
    has a GENERAL statement (e.g. "students have won awards"), give ONLY that
    general statement and point to the relevant PDF/webpage — do NOT elaborate
    with invented specifics to make the answer sound more complete.
13. CRITICAL — NEVER invent specific numbers/timings/schedules that are not
    explicitly in CONTEXT or KNOWN FACTS. Examples of forbidden invention:
    college class timings (e.g. "9 AM to 4 PM" — we do NOT have this data),
    labeling a general contact number as "Reception" when no such label
    exists in our data, number of buses, holiday schedules, semester counts.
    If asked for any specific number/timing/schedule not explicitly given
    below, say "I don't have this specific information. Please visit
    www.svimi.org or contact svimi@svimi.org | Toll Free: 18002332601" —
    do NOT guess a "reasonable-sounding" answer.

══════════════════════════════════════
KNOWN FACTS — ALWAYS USE THESE EXACTLY
══════════════════════════════════════

--- BASIC INFO ---
Full Name: Shri Vaishnav Institute of Management & Science (SVIMS / SVIMI)
Established: 1987 | Autonomous Institute | Campus: 7 acres, Central Indore
Address: Scheme No. 71, Gumasta Nagar, Indore - 452009, Madhya Pradesh, India
NAAC: A Grade — 3 consecutive cycles (2012, 2017, 2024)
Approved: AICTE, New Delhi | Affiliated: DAVV Indore (UG/PG/PhD) + RGPV Bhopal (MBA)
ISO 9001:2015 Certified | Ranking: Business Today 2024 — 266 (Management category)

--- CONTACTS (ONLY THESE ARE REAL — each number belongs to exactly ONE person/purpose) ---
Main Email: svimi@svimi.org
Admission Email: admission@svimi.org
Phone: +91-731-2789925, +91-731-2780011, +91-731-2382962 (Alternate)
Toll Free: 18002332601
Admission UG: 9329912587, 9630451445 | Admission MBA: 9329912582
WhatsApp: +91-9329912587
Student Welfare: 7312580137 | Exam Controller: 7312518030 | Enquiry: 7312580157
PRIVATE (never share in answers): Administrative Officer (internal only): 9301527178
NEVER share Director, HOD, or any faculty phone numbers. These are not published.
NOTE: Exam Controller (7312518030) has NO published email address — there is
NO examcontroller@svimi.org. For exam queries direct to svimi@svimi.org or
the phone number only. Do NOT invent department-specific email addresses.
NOTE: T&P Officer Mr. Hemant Pathak and Assistant T&P Mr. Sourabh Upadhyay do
NOT have published phone numbers in our data — direct queries about them to
svimi@svimi.org, do NOT attach the Admin Officer's number (9301527178) to them.
NOTE: There is NO healthcentre@svimi.org, sports@svimi.org, hostel@svimi.org,
placement@svimi.org — these emails DO NOT EXIST. Use only svimi@svimi.org.

--- GOVERNING BODY (exact names — verified from PDF) ---
Chairman: Shri Vishnu Pasari (also Chairman of Shri Vaishnav Institute of Management Shikshan Samiti)
Member Secretary: Dr. George Thomas (Director, SVIMS)
Vice Chairman (of Shikshan Samiti): Shri Rajkumar Bhatia
Secretary (of Shikshan Samiti): Shri Manish Baheti
Joint Secretary (of Shikshan Samiti): Shri Shashank Gupta
Treasurer (of Shikshan Samiti): Shri Puneet Soni
Special Invitees:
  - Shri Purushottamdas Pasari (Chairman, Shri Vaishnav Group of Trusts, Indore)
  - Shri Devendrakumar Muchhal (Secretary, Shri Vaishnav Sahayak Kapda Market Committee)
  - Shri Girdhargopal Nagar (Secretary, Shri Vaishnav Shaikshanik Avam Parmarthik Nyas)
Parent Trust: Shri Vaishnav Shaikshanik Avam Parmarthik Nyas, Indore (established 1987)

--- LEADERSHIP ---
Director: Dr. George Thomas (contact via svimi@svimi.org)
HOD CS & BioScience: Dr. Kshama Paithankar (contact via svimi@svimi.org)
HOD Management UG: Dr. Deepa Katiyal (contact via svimi@svimi.org)
HOD Management PG: Dr. Mandip Gill (contact via svimi@svimi.org)
Chairman and Patron details: see Leadership page on website.

--- FACULTY ---
IMPORTANT: The complete faculty list IS available below. If asked "list all
faculty members", "all faculty", or similar, ALWAYS answer using this list.
For ANY faculty question — give only HOD names and link. NEVER list all
individual teacher names in the answer text.
Director: Dr. George Thomas | svimi@svimi.org
HOD CS & BioScience: Dr. Kshama Paithankar
  Full CS list: https://www.svimi.org/departments/faculties.php?q=faculty_cs
HOD Management UG: Dr. Deepa Katiyal
  Full UG list: https://www.svimi.org/departments/faculties.php?q=faculty_UG
HOD Management PG: Dr. Mandip Gill
  Full PG list: https://www.svimi.org/departments/faculties.php?q=faculty_PG
T&P Team: Mr. Hemant Pathak (T&P Officer), Mr. Sourabh Upadhyay (Asst T&P)
IMPORTANT: The URL for faculty is ONLY one of these three — never use
"svimi.org/faculties.php" (does not exist). Always use the exact URLs above.

--- COURSES ---
UG: BCA, BBA (General/Foreign Trade/Hospital Admin), B.Sc. (CS/Biotechnology/Microbiology/Bioinformatics)
PG: MBA (Dual Specialization/Financial Administration/Marketing Management), MCA, M.Sc. Computer Science
Research: PhD in Management (DAVV recognized)
NOT OFFERED: B.Com, B.A., B.Tech, BE, B.Ed, Law, Medical

--- EXACT FEES ---
BBA (all variants): Rs. 80,000/year | BCA: Rs. 60,000/year | B.Sc. (all): Rs. 40,000/year
MBA Dual Specialization: Rs. 43,000/semester | MBA FA: Rs. 40,500/semester | MBA MM: Rs. 30,000/semester
MCA: Rs. 27,500/semester | M.Sc. CS: Rs. 40,000/year
Caution Money (BBA/BCA/MBA/MCA/MSc): Rs. 1,500 refundable | B.Sc.: Rs. 2,000 refundable
Installments: 1st - July 1-15 | 2nd - January 1-15

--- ATTENDANCE ---
Minimum 75% in EACH subject — ALL courses. Required for exams, placements, scholarship.
Medical leave: max 10% weightage, certificate within 7 days of rejoining.

--- LIBRARY ---
Books: 52,785+ | E-Books: 17,000+ | Online Journals: 10,000+
Print Journals: 88 | CDs: 2,907 | Video Cassettes: 41 | Encyclopedias: 18
Timings: 9:00 AM to 9:00 PM (Working Days)
UG: 3 books for 15 days | PG: 4 books for 15 days | Late fine: Rs. 2/day/book
Special Collections: Indian Philosophy, Value Management, Harvard Business Publishing,
ICFAI Publishing, IGNOU Study Materials, Project Reports, Case Studies, Biographies
Databases: IEEE Xplore, Emerald Insight, National Digital Library, EBSCO

--- HOSTEL ---
Separate hostels for boys and girls. Facilities: room sharing, lockable almirah,
attached toilet, study table, 24hr water, hot water (solar), common dining hall
with mess, internet, indoor games, security guards, CCTV, warden supervision.
Girls hostel has additional lift facility and sanitary napkin vending machine.
For booking/charges: contact svimi@svimi.org

--- LABS ---
Computer Laboratories (7 labs), Microbiology & Biotechnology Lab, Chemistry Lab,
Physics Lab, Language Lab, Business Analytics Lab — all support practical sessions,
research, and project work.

--- SPORTS ---
Outdoor playgrounds and indoor courts for various sports — part of curriculum to
promote fitness and competitive spirit. For details contact svimi@svimi.org

--- CANTEEN ---
On-campus canteen provides quality food at student-friendly prices — popular
gathering spot for students and staff.

--- PLACEMENT ---
T&P Officer: Mr. Hemant Pathak | Asst: Mr. Sourabh Upadhyay (no individual phone
numbers published — use svimi@svimi.org for queries)
Recruiters: TCS, Deloitte, Wipro, ICICI Bank, Cognizant, Tech Mahindra, Infosys,
Capgemini, HCL, Accenture | PEP Model: Project Based + Value Based + Personality Development Training
For exact placement numbers/statistics, direct to Prominent Selections page.

--- DRESS CODE ---
MBA: Unicode Shirting (Real B-4970), Trouser (P-Power Shade 017), Blazer
UG: Sarafarosh Pc Shirting, Siyaram Unicode Black Trouser, Blazer
All: Formal black leather shoes/bellies, plain white socks
Bioscience: White Lab Apron compulsory

--- ONLINE PORTALS ---
Online Fee Payment: accsoft.svimi.org/Accsoft_SVG/AdmissionRegPayment.aspx
  (students log in to the ERP portal and pay fees through this payment gateway)
Student ERP Login: accsoft.svimi.org/accsoft_SVG/studentlogin.aspx
Results: www.svimi.org/Results.php
Notifications: www.svimi.org/Notification.php
IMPORTANT: If asked "how to pay fees online", answer that students can pay
via the Online Fee Payment portal (link above) after logging into the
Student ERP — do NOT say "I don't have this information".

--- CELLS ---
EDC (Entrepreneurship Development Cell): Coordinator — Mr. Devendra Jain.
  Members: Dr. Poonam Nagar, Ms. Deepika Raikwar, Dr. Chandni Keswani,
  Mr. Ashish Sinhal, Mr. Hemant Pathak (Member only, not Incharge).
  Activities: Nav Udyami, Business Plan Competitions, Entrepreneurship
  Workshops, Startup Awareness Sessions, MSME Programs, IPR Workshops.

NSS (National Service Scheme): Program Officer — Mr. Ritesh Kushwah.
  Members: Ms. Pooja Parmar, Ms. Harsha Yadav, Mr. Ravi Chouhan,
  Mr. Varun Agrawal, Mr. Harish Sharma.
  Source: https://www.svimi.org/cells/nss.php

IIIC (Industry Institute Interface Cell): Coordinator — Dr. Digamber Negi.
  Members: Mr. Gaurav Porwal, Mr. Ravi Chouhan, Ms. Nidhi Dubey,
  Mr. Hemant Pathak (Member).
  Source: https://www.svimi.org/cells/iiic.php

IIC (Institution's Innovation Council), RDC (Research & Development Cell),
CDC (Case Development Cell), Monitoring Cell (supervises anti-ragging policy)
— for committee member details of these cells, say "I don't have the exact
list, please visit www.svimi.org"

--- ACTIVITY CLUBS (these are the ONLY real clubs — do not invent others) ---
IT Club, Finance Club, HR Club, Marketing Club, Literary Club,
Science Club, Photography Club

--- EVENTS ---
Abhisanskaran: Induction — August | Nav Udyami: Entrepreneurship by EDC — February
Srijan: Cultural fest — November | Khelotsav: Sports week — January
Prabandhotsav: Annual fest — March (past performers: Asees Kaur, Shirley Setia,
Sayli Kamble, Shanmukha Priya, Rupali Jagga, Ankush Bhardwaj — these are PERFORMERS not founders)
Confluence: Alumni Meet — March

--- SCHOLARSHIPS ---
SVIMS Meritorious Scholarship: for students with 75%+ attendance and strong academic performance — SVIMS's OWN scholarship, mention this prominently when asked about SVIMS scholarships.
Post Metric (SC/ST/OBC based on income), Minority Scholarship, Central Sector Scheme
(80%+ marks), Awas Scholarship (SC/ST), PG Indira Gandhi Scholarship (Single Girl
Child PG), AICTE Fellowship / GATE Fellowship.
For details: www.svimi.org/scholarship.php

--- FACULTY & STUDENT ACHIEVEMENTS ---
CRITICAL: We do NOT have any individual student/faculty names, specific years,
specific competition names, specific universities (IIM/IIT etc.), or specific
startup names for achievements. NEVER invent any of these — not even as
examples or placeholders like "[Name]". This is a common hallucination
mistake — avoid it completely.
PDF states ONLY these general facts (use ONLY this, nothing more specific):
- "SVIMS students regularly secure top positions in university merit lists.
  Students from BCA, BBA, B.Sc. Computer Science, Biotechnology, and
  Bioinformatics programmes have achieved University Topper and DAVV Merit
  positions with excellent CGPA and AGPA scores."
- "Students actively participate in national conferences, paper presentations,
  poster presentations, and research activities. Many students have received
  Best Paper Awards, Best Poster Awards, and recognition for their research
  contributions in Computer Science, Biotechnology, Bioinformatics, and Management."
- Faculty achievements include PhD awards, Best Research Paper Awards, Patents,
  publications, conference presentations (general categories only, no names/years).
For specific names, years, or detailed lists, ALWAYS direct the user to:
Student Achievement Report 2024-25: www.svimi.org/assets/images/achievements/Student_Achievements_2024-25.pdf
Faculty Achievement Report 2024-25: www.svimi.org/assets/images/achievements/Faculty_Other_Achievement_2024-25.pdf

--- SYLLABUS LINKS AVAILABLE (only these PDFs exist — copy URLs EXACTLY, do not simplify or rewrite them) ---
BCA I Year: https://www.svimi.org/assets/images/BCA_I_Year_Syllabus.pdf
BBA II Sem: https://www.svimi.org/assets/images/BBA_II_Sem_Syllabus.pdf
BBA (Foreign Trade) II Sem: https://www.svimi.org/assets/images/BBA_(FT)_II_Sem_Syllabus.pdf
BBA (Hospital Admin) II Sem: https://www.svimi.org/assets/images/BBA_(HA)_II_Sem_Syllabus.pdf
MBA Full Time: https://www.svimi.org/assets/images/MBA_FT_Syllabus.pdf
MBA Financial Administration: https://www.svimi.org/assets/images/MBA_FA_Syllabus.pdf
MBA Marketing Management: https://www.svimi.org/assets/images/MBA_MM_Syllabus.pdf
MCA: https://www.svimi.org/assets/images/MCA_Syllabus.pdf
M.Sc. CS: https://www.svimi.org/assets/images/M.Sc.CS_Syllabus.pdf
B.Sc. Computer Science I Year: https://www.svimi.org/assets/images/B.%20Sc._(CS)_I_Year_Syllabus.pdf
B.Sc. Biotechnology I Year: https://www.svimi.org/assets/images/B.%20Sc._(BT)_I_Year_Syllabus.pdf
B.Sc. Bioinformatics I Year: https://www.svimi.org/assets/images/B.%20Sc._(BI)_I_Year_Syllabus.pdf
B.Sc. Microbiology I Year: https://www.svimi.org/assets/images/B.%20Sc._(MB)_I_Year_Syllabus.pdf
CRITICAL: These B.Sc. URLs contain "B.%20Sc._(CS)_" with a literal "%20" and parentheses —
copy them EXACTLY character-for-character. Do NOT rewrite as "BSc_CS_" or any simplified form.
NOTE: College is newly autonomous (2025) — more semester syllabi will be added as they are uploaded.
When asked for 3rd/4th/5th/6th sem syllabus and it's not in the list above, say:
"Syllabi for higher semesters are being updated — please check www.svimi.org or contact svimi@svimi.org"

══════════════════════════════════════
CONTEXT FROM PDF & KNOWLEDGE BASE
══════════════════════════════════════
{context}
SVIMSPROMPT;
    }

    /* ══════════════════════════════════════════════════════
       GET ANSWER — main chat flow (Python get_answer ka 1:1 port)
       ══════════════════════════════════════════════════════ */
    public static function get_answer(array $chain, string $question, ?array $external_history = null): string {
        try {
            $client = $chain["client"];
            $retriever = $chain["retriever"];
            $qa_matcher = isset($chain["qa_matcher"]) ? $chain["qa_matcher"] : null;

            $q_clean = sv_strtolower(trim($question));
            if (in_array($q_clean, ["hi", "hello", "hey", "hii", "helo"], true)) {
                return ("👋 Hello! I'm SVIMS CampusBot — your official guide for "
                      . "Shri Vaishnav Institute of Management & Science, Indore. "
                      . "Ask me about courses, fees, admissions, faculty, placements, "
                      . "hostel, or any other campus information!");
            }

            if (self::is_out_of_scope($question)) {
                return ("I'm here to help with information about SVIMS Indore only. "
                      . "Please ask about courses, fees, admissions, faculty, "
                      . "placements, or facilities.\n\n"
                      . "📧 svimi@svimi.org | 📞 0731-2789925 | 🆓 18002332601");
            }

            // ═══════════════════════════════════════════════════════
            // SEMESTER COUNT — pure logic, no PDF needed
            // ═══════════════════════════════════════════════════════
            $semester_map = [
                "bca" => ["BCA is a 3-year programme with 6 semesters (2 semesters per year).\n"
                        . "NEP-based 4-year Honours option has 8 semesters.",
                        "https://www.svimi.org/under-graduate.php#aboutBCASec"],
                "bba" => ["BBA is a 3-year programme with 6 semesters (2 semesters per year).\n"
                        . "NEP-based 4-year Honours option has 8 semesters.",
                        "https://www.svimi.org/under-graduate.php#aboutBBASec"],
                "b.sc" => ["B.Sc. is a 3-year programme with 6 semesters (2 semesters per year).\n"
                         . "NEP-based 4-year Honours option has 8 semesters.",
                         "https://www.svimi.org/under-graduate.php#aboutBscSec"],
                "bsc" => ["B.Sc. is a 3-year programme with 6 semesters (2 semesters per year).\n"
                        . "NEP-based 4-year Honours option has 8 semesters.",
                        "https://www.svimi.org/under-graduate.php#aboutBscSec"],
                "mba" => ["MBA is a 2-year programme with 4 semesters.",
                        "https://www.svimi.org/post-graduate.php#aboutMBASec"],
                "mca" => ["MCA is a 2-year programme with 4 semesters.",
                        "https://www.svimi.org/post-graduate.php"],
                "m.sc" => ["M.Sc. CS is a 2-year programme with 4 semesters.",
                         "https://www.svimi.org/post-graduate.php"],
                "msc" => ["M.Sc. CS is a 2-year programme with 4 semesters.",
                        "https://www.svimi.org/post-graduate.php"],
            ];
            $sem_asked = false;
            foreach (["semester", "semesters", "sem", "semster"] as $w) {
                if (strpos($q_clean, $w) !== false) { $sem_asked = true; break; }
            }
            if ($sem_asked) {
                foreach ($semester_map as $course => $pair) {
                    if (strpos($q_clean, $course) !== false) {
                        return $pair[0] . "\n\n🔗 **More Info:** " . $pair[1];
                    }
                }
                foreach (["each course", "all course", "total semester", "kitne semester"] as $w) {
                    if (strpos($q_clean, $w) !== false) {
                        return ("Semester count at SVIMS:\n"
                              . "— BCA: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                              . "— BBA: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                              . "— B.Sc.: 6 semesters (3 years) | 8 with 4-year Honours (NEP)\n"
                              . "— MBA: 4 semesters (2 years)\n"
                              . "— MCA: 4 semesters (2 years)\n"
                              . "— M.Sc. CS: 4 semesters (2 years)\n\n"
                              . "🔗 **More Info:** https://www.svimi.org/under-graduate.php");
                    }
                }
            }

            // ═══════════════════════════════════════════════════════
            // PRIORITY 0 — FULLY HARDCODED ANSWERS (faculty list, syllabus, scholarship)
            // ═══════════════════════════════════════════════════════
            $hardcoded = self::get_hardcoded_answer($question);
            if ($hardcoded) {
                list($answer, $link) = $hardcoded;
                if ($link) {
                    $answer .= "\n\n🔗 **More Info:** " . $link;
                }
                return $answer;
            }

            // ═══════════════════════════════════════════════════════
            // RESPONSE CACHE — same question (case-insensitive, trimmed) dobara
            // puchha gaya to cached answer return karo (no API call).
            // TTL: 30 min. History-based follow-up questions skip karo (unhe cache nahi karo).
            // ═══════════════════════════════════════════════════════
            $has_history = (bool)$external_history;
            $cache_key = $has_history ? null : $q_clean;
            if ($cache_key !== null) {
                $cached = self::_cache_get($cache_key);
                if ($cached !== null) {
                    return $cached;
                }
            }

            // ═══════════════════════════════════════════════════════
            // PRIORITY 1 — DIRECT PDF MATCH (most reliable, zero hallucination)
            // Agar user ka question PDF ke kisi exact Q&A se closely match
            // karta hai, toh PDF ka EXACT answer + EXACT link directly do.
            // AI ko bilkul call nahi kiya jaata — content seedha PDF se aata hai.
            // ═══════════════════════════════════════════════════════
            if ($qa_matcher) {
                $direct = $qa_matcher->get_direct_answer($question);
                if ($direct) {
                    // PDF answer clean karo — raw Q:/A:/Source:/More Information: lines
                    // hata do taaki chatbot response mein raw PDF formatting na aaye
                    $raw_ans = $direct["answer"];
                    $clean_lines = [];
                    foreach (explode("\n", $raw_ans) as $line) {
                        $ls = trim($line);
                        if ($ls === '') continue;
                        // Skip: Q: lines, Source:, More Information:, Link: lines
                        if (strpos($ls, "Q:") === 0 || strpos($ls, "Source:") === 0 ||
                            strpos($ls, "More Information") === 0 || strpos($ls, "Link:") === 0) {
                            continue;
                        }
                        // "A: " prefix hata do agar ho
                        if (strpos($ls, "A:") === 0) {
                            $ls = trim(substr($ls, 2));
                        }
                        $clean_lines[] = $ls;
                    }
                    $joined = trim(implode("\n", $clean_lines));
                    $answer = ($joined !== '') ? $joined : $raw_ans;

                    $pdf_link = $direct["link"];
                    $topic_match = self::get_links($question, "");
                    $final_link = $pdf_link;
                    if ($topic_match && $topic_match[0][0]) {
                        $final_link = $topic_match[0][0];
                    }
                    if ($final_link && $final_link !== "https://www.svimi.org/") {
                        $answer .= "\n\n🔗 **More Info:** " . $final_link;
                    }
                    return $answer;
                }
            }

            $expanded = self::expand_query($question);

            $docs1 = $retriever->invoke(sv_strtolower($expanded));
            $docs2 = $retriever->invoke(sv_strtolower($question));
            $seen_keys = [];
            $all_docs = [];
            foreach (array_merge($docs1, $docs2) as $d) {
                $key = sv_substr($d['page_content'], 0, 80);
                if (!isset($seen_keys[$key])) {
                    $seen_keys[$key] = true;
                    $all_docs[] = $d;
                }
            }
            $context_parts = [];
            foreach (array_slice($all_docs, 0, 6) as $d) $context_parts[] = $d['page_content'];
            $context = implode("\n\n---\n\n", $context_parts);

            // ═══════════════════════════════════════════════════════
            // PRIORITY 2 — If no single direct match, but qa_matcher exists,
            // pull the most relevant PDF Q&A pairs as STRONGER context
            // (these are more reliable than generic FAISS chunks since they
            // preserve the exact Q&A + Link structure from the PDF).
            // ═══════════════════════════════════════════════════════
            if ($qa_matcher) {
                list($qa_context, $_relevant) = $qa_matcher->get_relevant_context($question, 6);
                if ($qa_context !== '') {
                    $context = $qa_context . "\n\n---\n\n" . $context;
                }
            }

            $system_prompt = str_replace('{context}', $context, self::system_prompt_template());

            $messages = [["role" => "system", "content" => $system_prompt]];

            if ($external_history) {
                foreach (array_slice($external_history, -4) as $msg) {
                    $role = isset($msg["role"]) ? $msg["role"] : "";
                    $content = isset($msg["content"]) ? $msg["content"] : "";
                    if ($role === "user") {
                        $messages[] = ["role" => "user", "content" => $content];
                    } elseif ($role === "bot" || $role === "assistant") {
                        $messages[] = ["role" => "assistant", "content" => $content];
                    }
                }
            }

            $messages[] = ["role" => "user", "content" => $question];

            $answer = self::_call_groq($client, $messages);

            // Defensive check — agar AI ne khali ya bahut chhota jawab diya,
            // generic fallback do instead of returning just a link with no text
            if (!$answer || sv_strlen(trim($answer)) < 3) {
                $answer = ("I'm not sure about the exact details for this. "
                         . "Please visit www.svimi.org or contact svimi@svimi.org | "
                         . "Toll Free: 18002332601");
            }

            $links = self::get_links($question, $context);
            if ($links && $links[0]) {
                list($url, $label) = $links[0];
                $answer .= "\n\n🔗 **More Info:** [{$label}]({$url})";
            }

            // Cache karo — future mein same question ke liye no API call
            if ($cache_key !== null) {
                self::_cache_set($cache_key, $answer);
            }

            return $answer;

        } catch (Throwable $e) {
            $error = sv_strtolower($e->getMessage());
            svims_log("🚨 ERROR: " . $e->getMessage());
            if (strpos($error, "quota") !== false || strpos($error, "429") !== false || strpos($error, "rate_limit") !== false) {
                return "⏳ Server busy. Please try again!\n\n📧 svimi@svimi.org | 📞 0731-2789925 | 🆓 18002332601";
            } elseif (strpos($error, "invalid_api_key") !== false || strpos($error, "401") !== false) {
                return "❌ API Key error. Check .env file.";
            } else {
                return "😊 Please rephrase and try again!\n\n📧 svimi@svimi.org | 📞 0731-2789925";
            }
        }
    }
}

/* ══════════════════════════════════════════════════════
   Convenience wrappers — Python function names se direct
   call karne ke liye (create_chatbot, get_answer, ...)
   ══════════════════════════════════════════════════════ */

function create_chatbot(SVIMSVectorStore $vector_store, ?string $api_key = null, ?string $pdf_path = null): array {
    return SVIMSEngine::create_chatbot($vector_store, $api_key, $pdf_path);
}

function get_answer(array $chain, string $question, ?array $external_history = null): string {
    return SVIMSEngine::get_answer($chain, $question, $external_history);
}
