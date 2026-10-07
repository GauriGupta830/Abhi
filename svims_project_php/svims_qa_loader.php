<?php
/**
 * SVIMS Direct Q&A Matcher (PHP port of svims_qa_loader.py)
 * =========================================================
 * PDF mein ready-made Q&A pairs hain (Question + Answer + Source Link).
 * Jab user ka question PDF ke kisi exact Q&A se closely match karta hai,
 * toh PDF ka EXACT answer aur EXACT link directly use hota hai — AI ko
 * sirf phrasing/tone ke liye call kiya jaata hai, content invent karne
 * ka koi mauka nahi milta.
 *
 * Wahi sentence-transformers model (all-MiniLM-L6-v2) use hota hai jo
 * svims_processor.php vector store ke liye use karta hai — koi extra
 * dependency/download nahi.
 */

require_once __DIR__ . '/svims_lib.php';

/**
 * PDF se saare Q&A pairs nikalo, poora document ek saath (text extract
 * karte hain) taaki cross-page Q&A split na ho.
 */
function parse_pdf_qa_pairs(string $pdf_path): array {
    try {
        $text = svims_pdf_extract_text($pdf_path);
        if ($text === '') {
            throw new RuntimeException('PDF text extraction failed');
        }
    } catch (Throwable $e) {
        svims_log("  PDF text extraction failed: " . $e->getMessage());
        return [];
    }

    $pattern = '/Q[:.]\s*(.+?)\n+'
             . 'A:\s*(.*?)'
             . '(?:\n+(?:Link|Source):\s*(\S+))?'
             . '(?=\n+Q[:.]|\z)/s';

    $qa_pairs = [];
    if (preg_match_all($pattern, $text, $matches, PREG_SET_ORDER)) {
        foreach ($matches as $m) {
            $q = trim($m[1]);
            $a = preg_replace('/\n{2,}/', "\n", trim($m[2]));
            $link = rtrim(trim(isset($m[3]) ? $m[3] : ''), '.,;)');
            if ($q !== '' && $a !== '' && sv_strlen($a) > 3) {
                $qa_pairs[] = ["question" => $q, "answer" => $a, "link" => $link];
            }
        }
    }

    return $qa_pairs;
}

/**
 * User question ko PDF ke Q&A pairs se semantic similarity se match karta hai.
 * High-confidence match -> PDF ka EXACT answer + link directly return.
 */
class SVIMSQAMatcher {
    public $high_threshold;
    public $low_threshold;
    public $qa_pairs = [];
    public $question_embeddings = null;
    /** @var SVIMSEmbeddings|null */
    public $model = null;
    private $pdf_path;
    private $cache_path;

    public function __construct(string $pdf_path, string $cache_path = null,
                                float $high_threshold = 0.68, float $low_threshold = 0.40) {
        $this->pdf_path = $pdf_path;
        $this->cache_path = $cache_path !== null ? $cache_path : (__DIR__ . '/svims_qa_cache.pkl');
        $this->high_threshold = $high_threshold;
        $this->low_threshold = $low_threshold;
        $this->_load();
    }

    private function _load(): void {
        $pdf_path = $this->pdf_path;
        $cache_path = $this->cache_path;
        $pdf_mtime = is_file($pdf_path) ? filemtime($pdf_path) : 0;

        if (is_file($cache_path)) {
            try {
                $cached = @unserialize((string)@file_get_contents($cache_path));
                if (is_array($cached) && isset($cached['pdf_mtime']) && $cached['pdf_mtime'] == $pdf_mtime) {
                    $this->qa_pairs = $cached['qa_pairs'];
                    $this->question_embeddings = $cached['question_embeddings'];
                    svims_log("✅ Q&A cache loaded: " . count($this->qa_pairs) . " pairs");
                    $this->_load_model();
                    return;
                }
            } catch (Throwable $e) {
                svims_log("  Q&A cache load failed: " . $e->getMessage() . " — rebuilding...");
            }
        }

        svims_log("🔄 Building direct Q&A index from PDF...");
        $this->qa_pairs = parse_pdf_qa_pairs($pdf_path);
        svims_log("  Parsed " . count($this->qa_pairs) . " Q&A pairs from PDF");

        if (!$this->qa_pairs) {
            svims_log("  ⚠️ No Q&A pairs found — direct matching disabled");
            return;
        }

        $this->_load_model();
        $questions = [];
        foreach ($this->qa_pairs as $p) $questions[] = $p['question'];
        $this->question_embeddings = $this->model->encode($questions);

        try {
            @file_put_contents($cache_path, serialize([
                'pdf_mtime' => $pdf_mtime,
                'qa_pairs' => $this->qa_pairs,
                'question_embeddings' => $this->question_embeddings,
            ]), LOCK_EX);
            svims_log("✅ Q&A index built and cached: " . count($this->qa_pairs) . " pairs");
        } catch (Throwable $e) {
            svims_log("  Cache save failed (non-fatal): " . $e->getMessage());
        }
    }

    private function _load_model(): void {
        if ($this->model === null) {
            $this->model = SVIMSEmbeddings::instance();
        }
    }

    public function find_best_matches(string $user_question, int $top_k = 3): array {
        if (!$this->qa_pairs || $this->question_embeddings === null) {
            return [];
        }

        $query_vecs = $this->model->encode([$user_question]);
        if (!$query_vecs) return [];
        $query_emb = $query_vecs[0];

        $similarities = [];
        foreach ($this->question_embeddings as $idx => $vec) {
            $norms = svims_vec_norm($vec) * svims_vec_norm($query_emb);
            if ($norms == 0.0) $norms = 1e-10;
            $dot = 0.0;
            $n = min(count($vec), count($query_emb));
            for ($i = 0; $i < $n; $i++) $dot += $vec[$i] * $query_emb[$i];
            $similarities[$idx] = $dot / $norms;
        }

        arsort($similarities);
        $top_indices = array_slice(array_keys($similarities), 0, $top_k);

        $results = [];
        foreach ($top_indices as $idx) {
            $results[] = [
                'question' => $this->qa_pairs[$idx]['question'],
                'answer' => $this->qa_pairs[$idx]['answer'],
                'link' => $this->qa_pairs[$idx]['link'],
                'score' => (float)$similarities[$idx],
            ];
        }
        return $results;
    }

    /** High-confidence single match -> PDF ka exact answer/link. Warna null. */
    public function get_direct_answer(string $user_question): ?array {
        $matches = $this->find_best_matches($user_question, 1);
        if (!$matches) {
            return null;
        }
        $best = $matches[0];
        if ($best['score'] >= $this->high_threshold) {
            return $best;
        }
        return null;
    }

    /**
     * Top-k relevant Q&A pairs ko context string banakar do — AI ko dene
     * ke liye jab single direct match na mile (multi-part/combined queries).
     */
    public function get_relevant_context(string $user_question, int $top_k = 6): array {
        $matches = $this->find_best_matches($user_question, $top_k);
        $relevant = [];
        foreach ($matches as $m) {
            if ($m['score'] >= $this->low_threshold) $relevant[] = $m;
        }
        if (!$relevant) {
            $relevant = array_slice($matches, 0, 3);
        }

        $context_parts = [];
        foreach ($relevant as $m) {
            $part = "Q: {$m['question']}\nA: {$m['answer']}";
            if ($m['link'] !== '') {
                $part .= "\nLink: {$m['link']}";
            }
            $context_parts[] = $part;
        }
        return [implode("\n\n---\n\n", $context_parts), $relevant];
    }
}

function svims_vec_norm(array $v): float {
    $s = 0.0;
    foreach ($v as $x) $s += $x * $x;
    return sqrt($s);
}
