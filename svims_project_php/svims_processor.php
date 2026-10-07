<?php
/**
 * SVIMS CampusBot — Knowledge Base Processor (PHP port of svims_processor.py)
 * Logic bilkul same — sirf language Python se PHP badli hai.
 */

require_once __DIR__ . '/svims_lib.php';

define('SVIMS_BASE_DIR', __DIR__);
define('SVIMS_FAISS_PATH', __DIR__ . '/faiss_index');
define('SVIMS_PDF_FOLDER', __DIR__ . '/college_docs');

// Backup scraping — SIRF wo pages jo regularly UPDATE hote hain.
// PDF mein static info (courses, fees, faculty names, policies, clubs, etc.)
// already hai — unko dobara scrape NAHI karna, taaki duplicate/conflicting
// data na bane aur AI confuse na ho.
$GLOBALS['BACKUP_PAGES'] = [
    "https://www.svimi.org/Notification.php" => "Latest Notifications",
    "https://www.svimi.org/Time-Table-Main.php" => "Exam Time Table Main",
    "https://www.svimi.org/Time-Table-ATKT.php" => "Exam Time Table ATKT",
    "https://www.svimi.org/Results.php" => "Exam Results",
    "https://www.svimi.org/placement/prominent-selections.php" => "Latest Placed Students",
    "https://www.svimi.org/placement/recruiters.php" => "Current Recruiters List",
    "https://www.svimi.org/event-gallery.php?q=events" => "Upcoming/Recent Events",
];

/**
 * PDF se Q&A pairs extract karo.
 * Har Q+A+Link ek saath rakho — context nahi tootega.
 */
function extract_qa_chunks_from_pdf(string $pdf_path): array {
    $chunks = [];

    try {
        $full_text = svims_pdf_extract_text($pdf_path);
        if ($full_text === '') {
            throw new RuntimeException('PDF text extraction failed');
        }
        $total = max(1, substr_count($full_text, "\f") + 1);
        svims_log("  📄 Pages: {$total}");

        $lines = explode("\n", $full_text);
        $block = [];

        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            if (strpos($line, 'Q:') === 0 && $block) {
                $chunk_text = implode("\n", $block);
                if (sv_strlen($chunk_text) > 30) {
                    $chunks[] = $chunk_text;
                }
                $block = [$line];
            } else {
                $block[] = $line;
            }
        }

        if ($block) {
            $chunk_text = implode("\n", $block);
            if (sv_strlen($chunk_text) > 30) {
                $chunks[] = $chunk_text;
            }
        }

        svims_log("  ✅ Q&A chunks extracted: " . count($chunks));

        $link_count = 0;
        foreach ($chunks as $c) {
            if (strpos(sv_strtolower($c), 'http') !== false) $link_count++;
        }
        svims_log("  🔗 Chunks with links: {$link_count}");

    } catch (Throwable $e) {
        svims_log("  ❌ PDF error: " . $e->getMessage());
    }

    return $chunks;
}

/** college_docs folder se PDFs padho */
function read_all_pdfs(): array {
    $all_chunks = [];

    if (!is_dir(SVIMS_PDF_FOLDER)) {
        @mkdir(SVIMS_PDF_FOLDER, 0777, true);
        return [];
    }

    $pdf_files = [];
    foreach (scandir(SVIMS_PDF_FOLDER) ?: [] as $f) {
        if (substr(sv_strtolower($f), -4) === '.pdf') $pdf_files[] = $f;
    }

    if (!$pdf_files) {
        svims_log("  ⚠️ Koi PDF nahi mili!");
        return [];
    }

    svims_log("  📄 " . count($pdf_files) . " PDF(s) mili!");

    foreach ($pdf_files as $pdf_file) {
        svims_log("\n  Reading: {$pdf_file}");
        $chunks = extract_qa_chunks_from_pdf(SVIMS_PDF_FOLDER . '/' . $pdf_file);
        foreach ($chunks as $c) $all_chunks[] = $c;
    }

    return $all_chunks;
}

/** Backup scraping — sirf tab jab PDF mein nahi ho */
function scrape_page(string $url, string $topic = ''): string {
    try {
        $headers = ['User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)'];
        $response = svims_http_request('GET', $url, $headers, null, 8);
        if ($response['error'] !== null || $response['status'] !== 200) {
            throw new RuntimeException($response['error'] ?? ('HTTP ' . $response['status']));
        }
        $text = svims_html_to_text($response['body']);
        if (sv_strlen($text) > 100) {
            svims_log("  ✅ {$topic}");
            return "TOPIC: {$topic}\nSOURCE: {$url}\n" . sv_substr($text, 0, 4000);
        }
        return "";
    } catch (Throwable $e) {
        svims_log("  ⏭️ Skipped: {$topic}");
        return "";
    }
}

function create_knowledge_base(?string $college_url = null): SVIMSVectorStore {
    svims_log("\n" . str_repeat("=", 60));
    svims_log("🔄 SVIMS KNOWLEDGE BASE BAN RAHI HAI");
    svims_log(str_repeat("=", 60));

    $all_chunks = [];

    // ─────────────────────────────────────────
    // SOURCE 1: PDF Q&A (PRIMARY — sabse pehle priority)
    // ─────────────────────────────────────────
    svims_log("\n📄 SOURCE 1: PDF Q&A Database (Primary)...");
    svims_log(str_repeat("-", 40));
    $pdf_chunks = read_all_pdfs();

    if ($pdf_chunks) {
        // PDF chunks 2x weight — duplicate karke add karo
        foreach ($pdf_chunks as $c) $all_chunks[] = $c;
        foreach ($pdf_chunks as $c) $all_chunks[] = $c;
        svims_log("  ✅ PDF chunks: " . count($pdf_chunks) . " (added 2x weight)");
    } else {
        svims_log("  ⚠️ No PDF found! Sirf website se chalega.");
    }

    // ─────────────────────────────────────────
    // SOURCE 2: Website Scraping (BACKUP ONLY)
    // ─────────────────────────────────────────
    svims_log("\n🌐 SOURCE 2: Backup Website Scraping (" . count($GLOBALS['BACKUP_PAGES']) . " pages)...");
    svims_log(str_repeat("-", 40));

    $splitter = new RecursiveCharacterTextSplitter(900, 150, ["\n\n", "\n", ".", " "]);

    $scraped = 0;
    foreach ($GLOBALS['BACKUP_PAGES'] as $url => $topic) {
        $result = scrape_page($url, $topic);
        if ($result !== '') {
            $web_chunks = $splitter->split_text($result);
            foreach ($web_chunks as $wc) $all_chunks[] = $wc;
            $scraped++;
        }
    }

    svims_log("  ✅ Scraped: {$scraped}/" . count($GLOBALS['BACKUP_PAGES']));

    // ─────────────────────────────────────────
    // FAISS INDEX
    // ─────────────────────────────────────────
    svims_log("\n📊 Total chunks: " . count($all_chunks));
    svims_log("🧠 FAISS index ban raha hai... (2-5 min wait karo)");

    $embeddings = SVIMSEmbeddings::instance();

    $vector_store = SVIMSVectorStore::from_texts($all_chunks, $embeddings);
    if (!is_dir(SVIMS_FAISS_PATH)) @mkdir(SVIMS_FAISS_PATH, 0777, true);
    $vector_store->save_local(SVIMS_FAISS_PATH);

    svims_log("\n" . str_repeat("=", 60));
    svims_log("✅ KNOWLEDGE BASE READY!");
    svims_log("   📄 PDF Q&A chunks: " . ($pdf_chunks ? count($pdf_chunks) : 0));
    svims_log("   🌐 Web scraped (backup): {$scraped} pages");
    svims_log("   🧩 Total: " . count($all_chunks));
    svims_log(str_repeat("=", 60) . "\n");

    return $vector_store;
}

function load_knowledge_base(): ?SVIMSVectorStore {
    $index_file = SVIMS_FAISS_PATH . '/index.faiss.json';
    if (is_dir(SVIMS_FAISS_PATH) && is_file($index_file)) {
        svims_log("📂 Loading: " . SVIMS_FAISS_PATH);
        $embeddings = SVIMSEmbeddings::instance();
        return SVIMSVectorStore::load_local(SVIMS_FAISS_PATH, $embeddings);
    }
    return null;
}
