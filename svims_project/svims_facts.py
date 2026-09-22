"""
SVIMS CampusBot — Verified Facts Knowledge Base
================================================
Yahan ka SAARA data official college website https://www.svimi.org/ se
verify karke hardcode kiya gaya hai (Sept 2026 mein checked).

Ye file bot ka "permanent memory" hai — fees, courses, contacts, leadership,
facilities, cells, clubs, events — sab kuch ek hi jagah, ek hi format mein.

UPDATE RULE:
  College website pe kuch change ho (fees, phone number, HOD, calendar)
  to sirf yeh file (ya svims_config.json) update karo — engine ko touch
  nahi karna padta. Server restart karo, bas.

Baaki dynamic cheezein (notifications, results, time tables, events,
placement updates) svims_scraper.py website se live scrape karta hai.
"""

# ══════════════════════════════════════════════════════════════════
# INSTITUTE IDENTITY
# ══════════════════════════════════════════════════════════════════
INSTITUTE = {
    "name": "SVIMS",
    "full_name": "Shri Vaishnav Institute of Management & Science",
    "city": "Indore",
    "established": 1987,
    "description": (
        "Shri Vaishnav Institute of Management & Science (SVIMS), Indore has a "
        "glorious history since 1987 under Shri Vaishnav Shaikshanik Avam "
        "Parmarthik Nyas, Indore. It is an Autonomous institute, conferred with "
        "the award of being the Oldest Self Finance Institute of M.P. by CMAI, "
        "Asia, and approved as an 'A' Category Institute by Govt. of Madhya Pradesh."
    ),
    "naac": "UGC-NAAC Accredited with 'A' Grade in three consecutive cycles (2012, 2017, 2024)",
    "iso": "ISO 9001:2015 Certified",
    "approvals": "Approved by AICTE, New Delhi | Autonomous Institute",
    "affiliations": (
        "Affiliated to Devi Ahilya Vishwavidyalaya (DAVV), Indore and Rajiv "
        "Gandhi Proudyogiki Vishwavidyalaya (RGPV), Bhopal. Recognized research "
        "centre of DAVV for Doctoral Degree (PhD) in Management."
    ),
    "campus": "Lush green campus spread over 7 acres in the heart of Indore city",
    "address": "Scheme No. 71, Gumasta Nagar, Indore - 452009, Madhya Pradesh, India",
    "areas": "Education in Management, Computer Science and BioScience (UG, PG, Research)",
}

# ══════════════════════════════════════════════════════════════════
# CONTACTS  (sab official website / official letters se verified)
# ══════════════════════════════════════════════════════════════════
CONTACTS = {
    "email": "svimi@svimi.org",
    "admission_email": "admission@svimi.org",
    "phone": "+91-731-2780011, +91-731-2789925, +91-731-2382962",
    "toll_free": "1800-233-2601",
    "admission_ug": "9329912587",
    "admission_mba": "9329912582",
    "admission_mca": "9329912586",
    "whatsapp": "9329912587 (WhatsApp on Admission Enquiry number)",
    "website": "www.svimi.org",
}

# ══════════════════════════════════════════════════════════════════
# LEADERSHIP  (leadership.php se verified)
# ══════════════════════════════════════════════════════════════════
LEADERSHIP = [
    {"role": "Patron", "name": "Shri Purushottamdas Pasari",
     "detail": "Chairman, Shri Vaishnav Group of Trusts, Indore"},
    {"role": "Chairman", "name": "Shri Vishnu Pasari",
     "detail": "Chairman, Shri Vaishnav Institute of Management & Science, Indore"},
    {"role": "Secretary", "name": "Shri Manish Baheti",
     "detail": "Secretary, Shri Vaishnav Institute of Management & Science, Indore"},
    {"role": "Director", "name": "Dr. George Thomas",
     "detail": "Director, Shri Vaishnav Institute of Management & Science, Indore"},
]

# ══════════════════════════════════════════════════════════════════
# DEPARTMENTS & HODs  (faculties pages se verified)
# ══════════════════════════════════════════════════════════════════
DEPARTMENTS = {
    "cs": {
        "name": "Computer Science & BioScience",
        "hod": "Dr. Kshama Paithankar",
        "hod_designation": "Professor and Head of the Department",
        "programs": "BCA, B.Sc. (CS / Microbiology / Bioinformatics / Biotechnology), MCA, M.Sc. (CS)",
        "faculty_url": "https://www.svimi.org/departments/faculties.php?q=faculty_cs",
    },
    "ug": {
        "name": "Management (UG)",
        "hod": "Dr. Deepa Katiyal",
        "hod_designation": "Professor and Head of the Department",
        "programs": "BBA, BBA (Foreign Trade), BBA (Hospital Administration)",
        "faculty_url": "https://www.svimi.org/departments/faculties.php?q=faculty_UG",
    },
    "pg": {
        "name": "Management (PG)",
        "hod": "Dr. Mandip Gill",
        "hod_designation": "Professor and Head of the Department",
        "programs": "MBA (Dual Specialization / FA / MM)",
        "faculty_url": "https://www.svimi.org/departments/faculties.php?q=faculty_PG",
    },
}

# ══════════════════════════════════════════════════════════════════
# TRAINING & PLACEMENT  (placement/about-placement.php se verified)
# ══════════════════════════════════════════════════════════════════
PLACEMENT = {
    "team": [
        {"name": "Mr. Hemant Pathak", "role": "Training & Placement Officer"},
        {"name": "Mr. Sourabh Upadhyay", "role": "Assistant Training & Placement Officer"},
        {"name": "Ms. Pratibha Agrawal", "role": "Soft Skills Trainer"},
        {"name": "Mr. Rohan Joshi", "role": "Soft Skills Trainer"},
        {"name": "Ms. Vishakha Wadhwani", "role": "Soft Skills Trainer"},
        {"name": "Ms. Aishwarya Chauhan", "role": "Soft Skills Trainer"},
    ],
    "pep_model": (
        "PEP Model (Personality Enhancement Program) — 3 pillars: "
        "Project Based Training, Value Based Education, and Personality "
        "Development Training (Soft Skills, Domain & Aptitude Training)."
    ),
    "training": (
        "Training programmes run through the entire course duration — "
        "communication skills, personality development, aptitude, logical "
        "reasoning, expert lectures from industry professionals, mock tests, "
        "mock group discussions and mock interviews."
    ),
    "recruiters": [
        "TCS", "Deloitte", "Wipro", "ICICI Bank", "Cognizant",
        "Tech Mahindra", "Infosys", "Capgemini", "HCL", "Accenture",
    ],
    "note": ("Exact placement statistics (packages, percentages) institute ke "
             "Prominent Selections page pe update hote rehte hain — bot numbers "
             "guess nahi karta."),
}

# ══════════════════════════════════════════════════════════════════
# COURSES  (under-graduate.php + post-graduate.php se verified)
#   aliases → deterministic matching ke liye
# ══════════════════════════════════════════════════════════════════
COURSES = [
    # ---------------- UG ----------------
    {
        "key": "bba", "level": "UG", "name": "BBA (Bachelor of Business Administration)",
        "aliases": ["bba", "bba general", "bba plain", "bba (plain)",
                    "bachelor of business administration"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with 50% marks in aggregate",
        "fee": "Rs. 80,000/- per year", "seats": 480,
        "admission": "Through DTE/DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bba_ft", "level": "UG", "name": "BBA (Foreign Trade)",
        "aliases": ["bba ft", "bba foreign trade", "foreign trade", "bba (ft)"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with 50% marks in aggregate",
        "fee": "Rs. 80,000/- per year", "seats": 60,
        "admission": "Through DTE/DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bba_ha", "level": "UG", "name": "BBA (Hospital Administration)",
        "aliases": ["bba ha", "bba hospital administration", "hospital administration",
                    "bba (ha)", "hospital admin"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with 50% marks in aggregate",
        "fee": "Rs. 80,000/- per year", "seats": 60,
        "admission": "Through DTE/DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bca", "level": "UG", "name": "BCA (Bachelor of Computer Application)",
        "aliases": ["bca", "computer application", "b c a"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with 50% marks in aggregate",
        "fee": "Rs. 60,000/- per year", "seats": 180,
        "admission": "Through DTE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bsc_cs", "level": "UG", "name": "B.Sc. (Computer Science)",
        "aliases": ["bsc cs", "b sc cs", "b.sc cs", "bsc computer science",
                    "b.sc computer science", "bsc (cs)"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with Physics, Maths and Chemistry/Biology, or 3-year relevant Diploma",
        "fee": "Rs. 40,000/- per year", "seats": 60,
        "admission": "Through DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bsc_mb", "level": "UG", "name": "B.Sc. (Microbiology)",
        "aliases": ["bsc microbiology", "b sc microbiology", "microbiology",
                    "b.sc microbiology", "bsc mb"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with Physics, Maths and Chemistry/Biology, or 3-year relevant Diploma",
        "fee": "Rs. 40,000/- per year", "seats": 60,
        "admission": "Through DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bsc_bi", "level": "UG", "name": "B.Sc. (Bioinformatics)",
        "aliases": ["bsc bioinformatics", "b sc bioinformatics", "bioinformatics",
                    "b.sc bioinformatics", "bsc bi"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with Physics, Maths and Chemistry/Biology, or 3-year relevant Diploma",
        "fee": "Rs. 40,000/- per year", "seats": 60,
        "admission": "Through DHE M.P. online counselling on 10+2 merit",
    },
    {
        "key": "bsc_bt", "level": "UG", "name": "B.Sc. (Biotechnology)",
        "aliases": ["bsc biotechnology", "b sc biotechnology", "biotechnology",
                    "b.sc biotechnology", "biotech", "bsc bt"],
        "duration": "3 years", "semesters": 6,
        "eligibility": "10+2 with Physics, Maths and Chemistry/Biology, or 3-year relevant Diploma",
        "fee": "Rs. 40,000/- per year", "seats": 60,
        "admission": "Through DHE M.P. online counselling on 10+2 merit",
    },
    # ---------------- PG ----------------
    {
        "key": "mba", "level": "PG", "name": "MBA — Dual Specialization (Full Time)",
        "aliases": ["mba", "mba ft", "mba full time", "mba dual", "mba dual specialization",
                    "master of business administration"],
        "duration": "2 years", "semesters": 4,
        "eligibility": "Graduate with min. 50% (45% for SC/ST/OBC non-creamy layer of M.P.)",
        "fee": "Rs. 43,000/- per semester", "seats": 180,
        "admission": "Through CMAT (AICTE) + DTE M.P. counselling on CMAT merit",
    },
    {
        "key": "mba_fa", "level": "PG", "name": "MBA — Financial Administration (FA)",
        "aliases": ["mba fa", "mba financial administration", "financial administration",
                    "mba (fa)"],
        "duration": "2 years", "semesters": 4,
        "eligibility": "Graduate with min. 50% (45% for SC/ST/OBC non-creamy layer of M.P.)",
        "fee": "Rs. 40,500/- per semester", "seats": 60,
        "admission": "Through CMAT (AICTE) + DTE M.P. counselling on CMAT merit",
    },
    {
        "key": "mba_mm", "level": "PG", "name": "MBA — Marketing Management (MM)",
        "aliases": ["mba mm", "mba marketing management", "mba marketing",
                    "marketing management", "mba (mm)"],
        "duration": "2 years", "semesters": 4,
        "eligibility": "Graduate with min. 50% (45% for SC/ST/OBC non-creamy layer of M.P.)",
        "fee": "Rs. 30,000/- per semester", "seats": 60,
        "admission": "Through CMAT (AICTE) + DTE M.P. counselling on CMAT merit",
    },
    {
        "key": "mca", "level": "PG", "name": "MCA (Master of Computer Applications)",
        "aliases": ["mca", "master of computer application", "m c a"],
        "duration": "2 years", "semesters": 4,
        "eligibility": "Graduate with min. 50% (45% for SC/ST/OBC non-creamy layer of M.P.)",
        "fee": "Rs. 27,500/- per semester", "seats": 120,
        "admission": "Through DTE M.P. counselling on qualifying exam merit",
    },
    {
        "key": "msc_cs", "level": "PG", "name": "M.Sc. (Computer Science)",
        "aliases": ["msc cs", "m sc cs", "m.sc cs", "msc computer science",
                    "m.sc computer science", "msc", "m sc"],
        "duration": "2 years", "semesters": 4,
        "eligibility": "B.Sc./BCA/B.Com/B.A. with Mathematics (10+2 or graduation level), min. 50%",
        "fee": "Rs. 40,000/- per year", "seats": 30,
        "admission": "Through counselling on qualifying exam merit",
    },
]

RESEARCH = ("PhD in Management — SVIMS is a recognized research centre of "
            "Devi Ahilya Vishwavidyalaya (DAVV), Indore.")

NOT_OFFERED = ["B.Com", "B.A.", "B.Tech", "B.E.", "B.Ed", "Law", "Medical", "M.Sc. Bio"]

UG_ELIGIBILITY_COMMON = "10+2 with 50% marks in aggregate"

# ══════════════════════════════════════════════════════════════════
# ADMISSION PROCESS  (admission-process.php se verified)
# ══════════════════════════════════════════════════════════════════
ADMISSION = {
    "ug": (
        "UG admissions (BBA/BCA/B.Sc.) are done through the Regulatory Body — "
        "Department of Higher Education / DTE, Govt. of M.P. via ONLINE COUNSELLING. "
        "First round is on the merit of 10+2 marks. If seats remain vacant, a second "
        "round of counselling and then College Level Counselling is conducted."
    ),
    "pg": (
        "MBA (FT/FA/MM) admission is through CMAT (conducted by AICTE) followed by "
        "DTE M.P. online counselling on the AICTE common merit list. "
        "MCA & M.Sc. admissions are through counselling on qualifying-exam merit."
    ),
    "counselling_site": "https://dte.mponline.gov.in/",
    "admission_url": "https://www.svimi.org/admission-process.php",
}

# ══════════════════════════════════════════════════════════════════
# SCHOLARSHIPS  (scholarship.php se verified)
# ══════════════════════════════════════════════════════════════════
SCHOLARSHIPS = [
    {"name": "Post Metric Scholarship (SC/ST/OBC)",
     "detail": "Parental income limit: SC/ST — up to Rs. 6 lakh/annum, OBC — up to Rs. 3 lakh/annum"},
    {"name": "Post Metric / Merit Cum Means Minority Scholarship",
     "detail": "For Jain/Muslim/Christian/Sikh/Buddhist/Parsi students — income up to Rs. 2.5 lakh/annum"},
    {"name": "Central Sector Scheme",
     "detail": "Above 80% marks in qualifying exam can apply — income up to Rs. 2.5 lakh/annum"},
    {"name": "Awas Scholarship", "detail": "Only for SC/ST students"},
    {"name": "PG Indira Gandhi Scholarship", "detail": "For single girl child pursuing Post Graduation"},
    {"name": "AICTE Scholarship / Fellowship Schemes", "detail": "https://www.aicte.gov.in/schemes/students-development-schemes"},
]

# ══════════════════════════════════════════════════════════════════
# FACILITIES  (infrastructure pages se verified)
# ══════════════════════════════════════════════════════════════════
LIBRARY = {
    "books": "52,785 books",
    "ebooks": "17,000+ e-books",
    "online_journals": "10,000+ online journals",
    "print_journals": "88 print national & international journals",
    "cds": "2,907 CDs", "video_cassettes": "41", "encyclopedias": "18",
    "special_collections": ("Indian Philosophy, Value Management, Harvard Business "
                            "Publishing, ICFAI Publishing, IGNOU study materials, "
                            "Project Reports, Case Studies, Biographies"),
    "databases": ("Capitaline, CRISIL, EBSCO Business Source Elite, EBSCO eBooks, "
                  "J-Gate, Sage Journals, Indiastat, DELNET, NDL India; via SVVV "
                  "subscription: Current Science, Emerald Insight, IEEE, ICT Academy Journals"),
    "services": "Circulation, Reference, Reprography, Current Awareness, Internet services",
    "url": "https://www.svimi.org/infrastructure/library.php",
}

HOSTEL = {
    "summary": ("Separate hostels for Boys and Girls near the campus at pocket-friendly "
                "charges (managed by Vaishnav Hostels)."),
    "girls_url": "https://vaishnavhostels.in/girls/",
    "boys_url": "https://vaishnavhostels.in/boys/",
    "facilities": ("Sharing rooms, individual bed & bedding, lockable steel almirah, "
                   "attached toilet, study table & chair, visitors room, aquaguard "
                   "drinking water, solar hot water, 24-hr running water, common hall "
                   "with TV, newspaper & magazines, internet, primary health care with "
                   "sickroom, dining hall with mess (everyday menu change), tiffin "
                   "facility, pantry, indoor games, open ground, covered parking, "
                   "bus facility between hostel and college, resident warden with "
                   "assistant, security guards 24-hr, CCTV, laundry washing machines"),
    "girls_extra": ("Girls hostel additionally has: Sanitary Napkin Vending Machine & "
                    "Incinerator, Lift facility (3-storied building), birthday "
                    "celebrations by hostel management"),
    "url": "https://www.svimi.org/infrastructure/hostel.php",
}

LABS = ("Computer laboratories, Microbiology & Biotechnology labs, Chemistry lab, "
        "Physics lab, Language lab and Business Analytics lab — supporting practical "
        "sessions, research and project work.")

SPORTS = ("Outdoor playgrounds and indoor courts for various sports — part of the "
          "curriculum to promote fitness and competitive spirit (Khelotsav sports "
          "week is organized every year in January).")

CANTEEN = ("On-campus canteen providing quality food at student-friendly prices — "
           "a popular gathering spot for students and staff.")

AUDITORIUM = "Abhay Prashal — major events like Prabandhotsav concerts are held here."

# ══════════════════════════════════════════════════════════════════
# CELLS  (cells pages + official committee letters se verified)
# ══════════════════════════════════════════════════════════════════
CELLS = {
    "EDC": {
        "name": "Entrepreneurship Development Cell",
        "about": ("Promotes entrepreneurship awareness and skills among students — "
                  "organizes Nav Udyami (Entrepreneur Meet), Business Plan "
                  "Competitions, MSME programmes, workshops and guest lectures."),
        "url": "https://www.svimi.org/cells/edc.php",
    },
    "NSS": {
        "name": "National Service Scheme (NSS) Cell",
        "about": ("Social activities inside and outside the institute as per DAVV "
                  "planning — plantation, NSS Day, blood donation camps, and the "
                  "Special Seven Days residential camp at adopted village Rangwasa."),
        "team": [
            ("Mr. Ritesh Kushwah", "Program Officer"),
            ("Ms. Pooja Parmar", "Member"), ("Ms. Harsha Yadav", "Member"),
            ("Mr. Ravi Chouhan", "Member"), ("Mr. Varun Agrawal", "Member"),
            ("Mr. Harish Sharma", "Member"),
        ],
        "url": "https://www.svimi.org/cells/nss.php",
    },
    "IIC": {"name": "Institution's Innovation Council",
            "url": "https://www.svimi.org/cells/iic.php"},
    "RDC": {"name": "Research & Development Cell",
            "url": "https://www.svimi.org/cells/rdc.php"},
    "CDC": {"name": "Case Development Cell",
            "url": "https://www.svimi.org/cells/cdc.php"},
    "IIIC": {"name": "Industry Institute Interface Cell",
             "url": "https://www.svimi.org/cells/iiic.php"},
}

# ══════════════════════════════════════════════════════════════════
# CLUBS & EVENTS
# ══════════════════════════════════════════════════════════════════
CLUBS = [
    ("IT Club", "https://www.svimi.org/activity-clubs/it-club.php"),
    ("Finance Club", "https://www.svimi.org/activity-clubs/finance-club.php"),
    ("HR Club", "https://www.svimi.org/activity-clubs/hr-club.php"),
    ("Marketing Club", "https://www.svimi.org/activity-clubs/marketing-club.php"),
    ("Literary Club", "https://www.svimi.org/activity-clubs/literary-club.php"),
    ("Science Club", "https://www.svimi.org/activity-clubs/science-club.php"),
    ("Photography Club", "https://www.svimi.org/activity-clubs/photography-club.php"),
]

# Recurring annual events (typical months)
ANNUAL_EVENTS = [
    ("Abhisanskaran", "Induction Ceremony", "August"),
    ("Srijan", "Cultural Fest", "November"),
    ("Khelotsav", "Sports Week", "January"),
    ("Nav Udyami", "Entrepreneur Meet (by EDC)", "February"),
    ("Prabandhotsav", "Annual Fest (with celebrity concerts)", "February/March"),
    ("Confluence", "Alumni Meet", "March"),
]

PRABANDHOTSAV_PERFORMERS = [
    "Ankush Bhardwaj (2k25)", "Sayli Kamble (2k24)", "Shanmukha Priya (2k23)",
    "Rupali Jagga (2k22)", "Asees Kaur (2k19)", "Shirley Setia (2k18)",
]

# ══════════════════════════════════════════════════════════════════
# ANTI-RAGGING  (Anti_Ragging_Committee.pdf — 2026-27 se verified)
# ══════════════════════════════════════════════════════════════════
ANTI_RAGGING = {
    "committee_2026_27": [
        "Dr. Jayesh Tiwari", "Dr. Sandeep Malu", "Dr. Uttam Rao Jagtap",
        "Dr. Kshama Ganjiwale", "Dr. Ekta Agrawal", "Dr. Bhavna Kabra",
        "Dr. Prachi Nikam", "Dr. Prashant Kushwaha", "Dr. Sakshi Yadav",
    ],
    "nodal_officer": "Dr. Sandeep Kumar Malu",
    "monitoring_cell": ["Dr. George Thomas (Director)", "Dr. Kshama Paithankar",
                        "Dr. Deepa Katiyal", "Dr. Mandip Gill", "Dr. Sandeep Malu",
                        "Mr. Kalpesh Bhatt"],
    "url": "https://www.svimi.org/assets/images/Anti_Ragging_Committee.pdf",
    "helpline": "UGC Anti-Ragging Helpline: 1800-180-5522",
}

# ══════════════════════════════════════════════════════════════════
# POLICIES & PORTALS
# ══════════════════════════════════════════════════════════════════
ATTENDANCE_POLICY = (
    "Minimum 75% attendance in each subject is mandatory for appearing in "
    "examinations (as per the institute's Attendance Policy). Medical leave "
    "cases are considered as per policy with valid documentation."
)
ATTENDANCE_POLICY_URL = "https://drive.google.com/file/d/1lYP9e5blMMu1rG0kx7inMBVFR6hutna5/view"

DRESS_CODE = (
    "Formal dress code with blazer is applicable (details in the official Dress "
    "Code document). Bioscience students must wear a white lab apron in "
    "laboratories."
)
DRESS_CODE_URL = "https://drive.google.com/file/d/1JRv_WrvAKbei2f8t_R7SBeUt1IabS37L/view"

PORTALS = {
    "student_erp": "https://accsoft.svimi.org/accsoft_SVG/studentlogin.aspx",
    "fee_payment": "https://accsoft.svimi.org/Accsoft_SVG/AdmissionRegPayment.aspx",
    "results": "https://www.svimi.org/Results.php",
    "notifications": "https://www.svimi.org/Notification.php",
    "time_table_main": "https://www.svimi.org/Time-Table-Main.php",
    "time_table_atkt": "https://www.svimi.org/Time-Table-ATKT.php",
}

BROCHURE_URL = "https://www.svimi.org/assets/images/SVIMS_Brochure_2026.pdf"
VIRTUAL_TOUR_URL = "https://clickeffect.co.in/svim/"
FEE_REFUND_POLICY_URL = "https://www.svimi.org/assets/images/Fee_Refund_Policy.pdf"
IQAC_URL = "https://www.svimi.org/iqac.php"
NIRF_URL = "https://www.svimi.org/ranking-nirf.php"
GOVERNING_BODY_URL = "https://www.svimi.org/governing-body.php"
FAQS_URL = "https://www.svimi.org/FAQs.php"


# ══════════════════════════════════════════════════════════════════
# HELPERS — facts se readable text banane ke liye
# ══════════════════════════════════════════════════════════════════

def find_course(query: str):
    """Query text se course detect karo (aliases match karke). None agar nahi mila."""
    q = " " + query.lower().strip() + " "
    best = None
    best_len = 0
    for c in COURSES:
        for alias in c["aliases"]:
            if f" {alias} " in q and len(alias) > best_len:
                best = c
                best_len = len(alias)
    return best


def fee_table() -> str:
    lines = ["**Fee Structure — SVIMS (as per official website)**", ""]
    lines.append("**Under Graduate (per year):**")
    for c in COURSES:
        if c["level"] == "UG":
            lines.append(f"— {c['name']}: {c['fee']} | Seats: {c['seats']}")
    lines.append("")
    lines.append("**Post Graduate:**")
    for c in COURSES:
        if c["level"] == "PG":
            lines.append(f"— {c['name']}: {c['fee']} | Seats: {c['seats']}")
    lines.append("")
    lines.append("For fee refund rules see the Fee Refund Policy on the website.")
    return "\n".join(lines)


def courses_overview() -> str:
    lines = ["**Courses offered at SVIMS**", ""]
    lines.append("**Under Graduate (3 years):**")
    for c in COURSES:
        if c["level"] == "UG":
            lines.append(f"— {c['name']} ({c['seats']} seats)")
    lines.append("")
    lines.append("**Post Graduate (2 years):**")
    for c in COURSES:
        if c["level"] == "PG":
            lines.append(f"— {c['name']} ({c['seats']} seats)")
    lines.append("")
    lines.append(f"Research: {RESEARCH}")
    return "\n".join(lines)


def course_detail(c: dict) -> str:
    lines = [f"**{c['name']}**", ""]
    lines.append(f"— Level: {c['level']} ({c['duration']}, {c['semesters']} semesters)")
    lines.append(f"— Eligibility: {c['eligibility']}")
    lines.append(f"— Fee: {c['fee']}")
    lines.append(f"— Seats: {c['seats']}")
    lines.append(f"— Admission: {c['admission']}")
    return "\n".join(lines)


def contact_block() -> str:
    return (
        "**SVIMS — Contact Details**\n\n"
        f"— Address: {INSTITUTE['address']}\n"
        f"— Email: {CONTACTS['email']} | Admissions: {CONTACTS['admission_email']}\n"
        f"— Phone: {CONTACTS['phone']}\n"
        f"— Toll Free: {CONTACTS['toll_free']}\n"
        f"— Admission Enquiry: {CONTACTS['admission_ug']} (UG), "
        f"{CONTACTS['admission_mba']} (MBA), {CONTACTS['admission_mca']} (MCA)\n"
        f"— Website: {CONTACTS['website']}"
    )


def build_fact_documents():
    """
    Facts ko FAISS seed ke liye text-documents mein convert karo.
    (Agar website scrape na ho paye, tab bhi bot in facts se answer karega.)
    """
    docs = []

    docs.append(
        f"ABOUT SVIMS: {INSTITUTE['full_name']}, {INSTITUTE['city']} — established "
        f"{INSTITUTE['established']}. {INSTITUTE['description']} {INSTITUTE['naac']}. "
        f"{INSTITUTE['iso']}. {INSTITUTE['approvals']}. {INSTITUTE['affiliations']}. "
        f"{INSTITUTE['campus']}. Address: {INSTITUTE['address']}. "
        f"Contact: {CONTACTS['email']} | {CONTACTS['phone']} | Toll Free {CONTACTS['toll_free']}."
    )

    docs.append(contact_block().replace("**", ""))

    for l in LEADERSHIP:
        docs.append(f"SVIMS LEADERSHIP — {l['role']}: {l['name']}, {l['detail']}")

    for key, d in DEPARTMENTS.items():
        docs.append(
            f"SVIMS DEPARTMENT — {d['name']}: HOD {d['hod']} ({d['hod_designation']}). "
            f"Programs: {d['programs']}. Faculty list: {d['faculty_url']}"
        )

    docs.append(
        "SVIMS TRAINING & PLACEMENT CELL: " +
        "; ".join(f"{m['name']} ({m['role']})" for m in PLACEMENT["team"]) +
        ". " + PLACEMENT["pep_model"] + " " + PLACEMENT["training"] +
        " Prominent recruiters: " + ", ".join(PLACEMENT["recruiters"]) + "."
    )

    for c in COURSES:
        docs.append(
            f"SVIMS COURSE — {c['name']} ({c['level']}): Duration {c['duration']} "
            f"({c['semesters']} semesters). Eligibility: {c['eligibility']}. "
            f"Fee: {c['fee']}. Seats: {c['seats']}. Admission: {c['admission']}."
        )
    docs.append("SVIMS RESEARCH: " + RESEARCH)

    docs.append("SVIMS ADMISSION PROCESS UG: " + ADMISSION["ug"])
    docs.append("SVIMS ADMISSION PROCESS PG (MBA/MCA/M.Sc.): " + ADMISSION["pg"])

    docs.append(
        "SVIMS SCHOLARSHIPS: " +
        "; ".join(f"{s['name']} — {s['detail']}" for s in SCHOLARSHIPS) +
        " Details: https://www.svimi.org/scholarship.php"
    )

    docs.append(
        f"SVIMS LIBRARY: {LIBRARY['books']}, {LIBRARY['ebooks']}, "
        f"{LIBRARY['online_journals']}, {LIBRARY['print_journals']}, {LIBRARY['cds']}, "
        f"{LIBRARY['video_cassettes']} video cassettes, {LIBRARY['encyclopedias']} "
        f"encyclopedias. Special collections: {LIBRARY['special_collections']}. "
        f"Databases: {LIBRARY['databases']}. Services: {LIBRARY['services']}."
    )

    docs.append(
        f"SVIMS HOSTEL: {HOSTEL['summary']} Facilities: {HOSTEL['facilities']}. "
        f"{HOSTEL['girls_extra']}. Boys: {HOSTEL['boys_url']} Girls: {HOSTEL['girls_url']}"
    )

    docs.append("SVIMS LABS: " + LABS)
    docs.append("SVIMS SPORTS: " + SPORTS)
    docs.append("SVIMS CANTEEN: " + CANTEEN)

    for key, cell in CELLS.items():
        team = ""
        if "team" in cell:
            team = " Team: " + ", ".join(f"{n} ({r})" for n, r in cell["team"]) + "."
        about = cell.get("about", cell["name"])
        docs.append(f"SVIMS CELL — {key} ({cell['name']}): {about}{team} Source: {cell['url']}")

    docs.append(
        "SVIMS ACTIVITY CLUBS: " + ", ".join(name for name, _ in CLUBS) +
        ". Club pages: https://www.svimi.org/activity-clubs/it-club.php etc."
    )

    events_txt = "; ".join(f"{n} ({t}) — typically {m}" for n, t, m in ANNUAL_EVENTS)
    docs.append(
        f"SVIMS ANNUAL EVENTS: {events_txt}. Prabandhotsav celebrity performers over "
        f"the years: {', '.join(PRABANDHOTSAV_PERFORMERS)}. Events gallery: "
        f"https://www.svimi.org/event-gallery.php?q=events"
    )

    docs.append(
        f"SVIMS ANTI-RAGGING (2026-27): Committee as per UGC Regulations 2009 — "
        f"{', '.join(ANTI_RAGGING['committee_2026_27'])}. Nodal Officer: "
        f"{ANTI_RAGGING['nodal_officer']}. Monitoring Cell: "
        f"{', '.join(ANTI_RAGGING['monitoring_cell'])}. "
        f"{ANTI_RAGGING['helpline']}. Full list: {ANTI_RAGGING['url']}"
    )

    docs.append("SVIMS ATTENDANCE POLICY: " + ATTENDANCE_POLICY)
    docs.append("SVIMS DRESS CODE: " + DRESS_CODE)

    docs.append(
        "SVIMS ONLINE PORTALS: Student ERP login " + PORTALS["student_erp"] +
        " | Online fee payment " + PORTALS["fee_payment"] +
        " | Results " + PORTALS["results"] +
        " | Notifications " + PORTALS["notifications"] +
        " | Exam time tables " + PORTALS["time_table_main"] + " & " + PORTALS["time_table_atkt"]
    )

    docs.append(
        "SVIMS VISION: To be the center of excellence in multidisciplinary education "
        "by instilling lifelong learning and skill development, transforming individuals "
        "to be globally competent and ethically & socially responsible professionals. "
        "MISSION: (1) Impart quality education leading to advancement of knowledge and "
        "sustainable career (2) Holistic development of students to make them employable "
        "(3) Excellent pedagogy with experiential and process-oriented learning "
        "(4) Develop entrepreneurial orientation with strong moral and ethical values."
    )

    return docs
