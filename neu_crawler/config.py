"""All crawler settings live here. Edit this file to change scope, limits, categories and chunking."""
from pathlib import Path

# Put a real contact email in the User-Agent so the site admins can reach you.
USER_AGENT = "NEU-RAG-Crawler/1.0 (student capstone project; contact: YOUR_EMAIL@example.com)"

START_URLS = ["https://neu.edu.ph/main/"]
ALLOWED_DOMAINS = {"neu.edu.ph"}          # subdomains (x.neu.edu.ph) are allowed automatically

MAX_PAGES = 300                           # overridden by --limit
REQUEST_DELAY_SECONDS = 1.5               # pause between requests (one request at a time)
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 15 * 1024 * 1024
MIN_CONTENT_CHARS = 120                   # pages with less text than this are skipped

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "neu"
INGEST_DIR_NAME = "_ingest"               # front-matter-free copies for the admin-panel upload

# Chunking (for chunks.jsonl). Cohere embed v3 truncates at ~512 tokens, so keep the
# target below that unless you switch embedding models.
CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 60
CHARS_PER_TOKEN = 4                       # rough estimate; Filipino/Taglish text may be nearer 3.5

SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".mp3", ".mp4", ".avi", ".mov",
    ".zip", ".rar", ".7z", ".exe", ".css", ".js", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}
SKIP_URL_PARTS = (
    "wp-login", "wp-admin", "/wp-json", "xmlrpc", "logout", "/login", "replytocom=",
    "/feed", "?s=", "&s=", "/cart", "/checkout",
)

# Keyword matching is by word PREFIX ("enroll" matches "enrollment").
# Scoring: URL match = 3, title match = 2, first 600 chars of content = 1.
# On a tie, the category listed first wins, so keep specific categories above generic ones.
CATEGORIES = {
    "news_announcements": ["news", "announcement", "advisory", "suspension", "memorandum", "press release"],
    "events_activities": ["event", "seminar", "webinar", "convocation", "activities", "festival"],
    "admissions_enrollment": ["admission", "enroll", "apply", "application", "freshmen", "transferee", "requirements"],
    "registrar_services": ["registrar", "transcript of records", "academic record", "credential", "diploma", "registration"],
    "finance_scholarships": ["tuition", "scholarship", "payment", "finance", "cashier", "fees", "financial aid", "grant"],
    "academic_programs": ["program", "course", "college", "graduate", "undergraduate", "juris doctor",
                          "medicine", "curriculum", "degree", "bachelor", "master", "integrated school"],
    "library_resources": ["library", "learning resource", "e-resource", "opac"],
    "research_centers": ["research", "center", "centre", "institute"],
    "policies_guidelines": ["policy", "policies", "privacy", "disclaimer", "guideline", "code of conduct", "ai usage", "terms"],
    "campus_information": ["campus", "pampanga", "lipa", "general santos", "rizal", "quezon city"],
    "facilities_resources": ["facilit", "laborator", "gym", "dormitor", "chapel", "auditorium"],
    "university_offices": ["office", "directory", "department", "bureau"],
    "student_services": ["student", "guidance", "counsel", "clinic", "organization", "alumni", "services"],
    "university_overview": ["history", "mission", "vision", "about", "overview", "profile", "core values", "hymn", "trustees"],
    "faqs_contact": ["faq", "contact", "inquir", "question", "hotline", "location"],
}
DEFAULT_CATEGORY = "uncategorized"        # pages that match nothing land here; check the report