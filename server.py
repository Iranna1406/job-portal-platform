# -*- coding: utf-8 -*-
"""
Job Link Portal - Python Backend Service
Using Built-in HTTP Server and SQLite3
"""

import os
import sys
import json
import sqlite3
import re
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

PORT = 3000
DB_FILE = os.path.join(os.getcwd(), 'sqlite_db.db')

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT CHECK(role IN ('employer', 'candidate')) NOT NULL
        )
    ''')
    
    # 2. Candidate Profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            education TEXT,
            work_experience TEXT,
            skills TEXT, -- Comma-separated list of skills
            resume_file_name TEXT,
            resume_text TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # 3. Employer Profiles
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employer_profiles (
            user_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            industry TEXT NOT NULL,
            description TEXT,
            contact_info TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # 4. Jobs Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            employer_id TEXT NOT NULL,
            title TEXT NOT NULL,
            company_name TEXT NOT NULL,
            industry TEXT NOT NULL,
            description TEXT,
            salary TEXT NOT NULL,
            role TEXT NOT NULL,
            skills_required TEXT, -- Comma-separated list of skills
            location TEXT DEFAULT 'Remote',
            created_at TEXT NOT NULL,
            FOREIGN KEY(employer_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # 5. Applications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            status TEXT CHECK(status IN ('applied', 'reviewing', 'matched', 'rejected')) DEFAULT 'applied',
            match_score INTEGER DEFAULT 0,
            match_analysis TEXT,
            applied_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(candidate_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(job_id, candidate_id)
        )
    ''')
    
    # 6. Emails Log Table (Simulated Email Outbox)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            to_address TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
    ''')
    
    # Pre-seed default polished jobs if empty
    cursor.execute("SELECT COUNT(*) FROM jobs")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.utcnow().isoformat() + 'Z'
        default_jobs = [
            (
                "job-default-1",
                "emp-default",
                "Senior Full Stack Engineer",
                "Google Cloud Partners",
                "Information Technology",
                "Join our fast-growing engineering team focusing on high-performance serverless systems, real-time analytics dashboards, and state-of-the-art AI-powered applications. You'll build modular React micro-frontends and scalable Express APIs.",
                "$120,000 - $150,000",
                "Full Stack Engineer",
                "React,TypeScript,Node.js,Express,Tailwind CSS,SQL",
                "San Francisco, CA (Hybrid)",
                now_str
            ),
            (
                "job-default-2",
                "emp-default",
                "Data Analyst & AI Specialist",
                "Zenith Insights",
                "Business Consulting",
                "Looking for an analytical mind to extract critical trends from resume data and configure custom recommendation dashboards. You will implement machine learning models, fine-tune Gemini prompts, and craft visually striking D3/Recharts data representations.",
                "$95,000 - $115,000",
                "Data Analyst",
                "Python,SQL,Data Visualization,D3.js,Recharts,Gemini API",
                "Remote",
                now_str
            ),
            (
                "job-default-3",
                "emp-default-2",
                "UI/UX Front-End Developer",
                "PixelPerfect Design",
                "Design & Media",
                "We believe typography and fluid micro-animations make the absolute difference. We need a front-end engineer passionate about React, Tailwind, Framer Motion, and high-fidelity interactive elements.",
                "$80,000 - $105,000",
                "Front-End Developer",
                "React,CSS,Tailwind CSS,Motion,Figma,UI Design",
                "New York, NY",
                now_str
            )
        ]
        cursor.executemany('''
            INSERT INTO jobs (id, employer_id, title, company_name, industry, description, salary, role, skills_required, location, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', default_jobs)
        
    conn.commit()
    conn.close()
    print("SQLite database successfully initialized and pre-seeded.")

# --- HELPERS ---
def send_email_notification(to_address, subject, body):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    email_id = f"email-{int(datetime.utcnow().timestamp())}-{os.urandom(2).hex()}"
    sent_at = datetime.utcnow().isoformat() + 'Z'
    
    cursor.execute('''
        INSERT INTO emails (id, to_address, subject, body, sent_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (email_id, to_address, subject, body, sent_at))
    conn.commit()
    conn.close()
    
    print("\n" + "="*40)
    print(f"✉️ [EMAIL SENT] To: {to_address}")
    print(f"Subject: {subject}")
    print(f"Content:\n{body}")
    print("="*40 + "\n")
    return email_id

def validate_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email) is not None

def validate_password(password):
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"
    if not re.search(r'[a-zA-Z]', password):
        return False, "Password must contain at least one alphabet character"
    if not re.search(r'[^a-zA-Z0-9]', password):
        return False, "Password must contain at least one special character"
    return True, ""

# --- GEMINI AI UTILS VIA URLLIB ---
def call_gemini(prompt, system_instruction=None, response_schema=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "MY_GEMINI_API_KEY":
        print("GEMINI_API_KEY not found or is default. Bypassing Gemini API call.")
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # Construct request payload for Gemini 2.5/1.5 REST endpoint
    contents = [{"parts": [{"text": prompt}]}]
    generation_config = {}
    
    if response_schema:
        generation_config["responseMimeType"] = "application/json"
        generation_config["responseSchema"] = response_schema
        
    payload = {
        "contents": contents,
        "generationConfig": generation_config
    }
    
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
        
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': 'aistudio-build-python'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode('utf-8')
            parsed_res = json.loads(res_body)
            # Extract generated text from standard Gemini response structure
            text_out = parsed_res['candidates'][0]['content']['parts'][0]['text']
            return text_out
    except Exception as e:
        print(f"Gemini API Call failed: {e}")
        return None

# --- PARSING ENGINE ---
def parse_resume_text(text, file_name):
    print(f"Parsing resume text: {file_name}")
    
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "Full name of the candidate"},
            "email": {"type": "STRING", "description": "Email address found in resume"},
            "skills": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Technical and soft skills list"
            },
            "education": {"type": "STRING", "description": "Academic degrees, institutions, years"},
            "workExperience": {"type": "STRING", "description": "Professional history, companies, dates"}
        },
        "required": ["name", "email", "skills", "education", "workExperience"]
    }
    
    system_instruction = "Analyze and parse this candidate's resume/CV text into clean, structured candidate parameters. If data is missing, make safe assumptions."
    
    prompt = f"Please extract candidate info from this resume text:\n\n{text}"
    
    gemini_out = call_gemini(prompt, system_instruction, response_schema)
    if gemini_out:
        try:
            return json.loads(gemini_out.strip())
        except Exception as e:
            print("Failed to decode Gemini JSON output, falling back to regex parser.", e)
            
    # Regular expression fallback parser
    print("Executing fallback regex resume parsing engine...")
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    name = lines[0][:35] if lines else "Extracted Candidate"
    
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    email = email_match.group(0) if email_match else ""
    
    common_skills = [
        'react', 'angular', 'vue', 'typescript', 'javascript', 'python', 'node', 'express',
        'sql', 'sqlite', 'mongodb', 'aws', 'docker', 'tailwind', 'css', 'html', 'git', 'figma',
        'project management', 'data analyst', 'excel', 'customer service', 'sales', 'marketing'
    ]
    skills = []
    for skill in common_skills:
        if re.search(rf'\b{re.escape(skill)}\b', text, re.IGNORECASE):
            skills.append(" ".join([w.capitalize() for w in skill.split(' ')]))
            
    education = "Education details extracted from resume text."
    work_exp = "Work experience extracted from resume text."
    
    if "education" in text.lower():
        parts = re.split(r'education', text, flags=re.IGNORECASE)
        if len(parts) > 1:
            education = re.split(r'(experience|work|skills)', parts[1], flags=re.IGNORECASE)[0].strip()
            
    if "experience" in text.lower() or "work" in text.lower():
        parts = re.split(r'(experience|work)', text, flags=re.IGNORECASE)
        if len(parts) > 1:
            work_exp = re.split(r'(education|skills)', parts[2], flags=re.IGNORECASE)[0].strip()
            
    return {
        "name": name,
        "email": email,
        "skills": skills if skills else ["Communication", "Problem Solving", "Adaptability"],
        "education": education,
        "workExperience": work_exp
    }

# --- MATCHING ENGINE ---
def run_job_match(profile, job):
    print(f"Running match for: {profile['name']} VS {job['title']}")
    
    # Built-in basic score matching logic
    req_skills = [s.strip().lower() for s in job['skills_required'].split(',') if s.strip()]
    cand_skills = [s.strip().lower() for s in profile['skills'].split(',') if s.strip()]
    
    matches = 0
    for req in req_skills:
        if any(req in cand or cand in req for cand in cand_skills):
            matches += 1
            
    keyword_pct = (matches / len(req_skills)) * 100 if req_skills else 100
    base_score = int(40 + (keyword_pct * 0.6))
    
    prompt = f"""
    Candidate Resume Parameters:
    Skills: {profile['skills']}
    Education: {profile['education']}
    Work Experience: {profile['work_experience']}
    
    Job Specification:
    Title: {job['title']}
    Required Skills: {job['skills_required']}
    Description: {job['description']}
    
    Evaluate candidate fit and return a JSON object with keys "score" (0-100 integer) and "analysis" (professional markdown response detailing Core Strengths, Identified Gaps, and Final Hiring Recommendation).
    """
    
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "score": {"type": "INTEGER", "description": "Alignment score from 0 to 100"},
            "analysis": {"type": "STRING", "description": "Markdown formatted matching feedback analysis"}
        },
        "required": ["score", "analysis"]
    }
    
    gemini_out = call_gemini(prompt, "Hiring Manager Fit Assessment Engine", response_schema)
    if gemini_out:
        try:
            return json.loads(gemini_out.strip())
        except Exception as e:
            print("Failed to decode Gemini Match JSON:", e)
            
    # Rules-based markdown response
    gap_skills = [s for s in req_skills if s not in cand_skills]
    matched_skills = [s for s in req_skills if s in cand_skills]
    
    analysis = f"""### Match Report (Heuristic SQL Evaluation)
**Matching Alignment: {base_score}%**

#### Core Strengths
* **Matching Core Competencies:** {', '.join(matched_skills) if matched_skills else 'Generic Fit'}
* Active professional history aligned with role requirements.

#### Identified Gaps
* **Missing Skillsets:** {', '.join(gap_skills) if gap_skills else 'Matches all core keywords'}
* Recommend technical screener to verify missing skills.

#### Final Recommendation
{ "Highly Recommended for immediate technical interview." if base_score >= 80 else "Recommend for short phone screening session." if base_score >= 60 else "Keep candidate file on record for closer opportunities." }
"""
    return {
        "score": base_score,
        "analysis": analysis
    }

# --- HTTP REQUEST HANDLER ---
class JobPortalAPIHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Override to suppress noisy server logging, but print errors
        if "40" in format or "50" in format:
            sys.stderr.write("%s - - [%s] %s\n" %
                             (self.address_string(),
                              self.log_date_time_string(),
                              format%args))
            
    def _send_json(self, status, obj):
        try:
            body = json.dumps(obj).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            print("Failed sending JSON response:", e)
            
    def _read_json(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            return json.loads(body)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = self.path
        clean_path = path.split('?')[0].split('#')[0]
        
        # Serve static frontend files for non-API routes
        if not clean_path.startswith('/api'):
            base_dir = os.getcwd()
            rel_path = clean_path.lstrip('/')
            
            if not rel_path:
                file_path = os.path.join(base_dir, 'index.html')
            else:
                file_path = os.path.join(base_dir, rel_path)
            
            # SPA Fallback for routes that do not have file extension
            if not os.path.isfile(file_path):
                _, ext = os.path.splitext(clean_path)
                if not ext:
                    file_path = os.path.join(base_dir, 'index.html')
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"404 Not Found")
                    return
            
            try:
                import mimetypes
                content_type, _ = mimetypes.guess_type(file_path)
                if not content_type:
                    if file_path.endswith('.html'): content_type = 'text/html'
                    elif file_path.endswith('.js'): content_type = 'application/javascript'
                    elif file_path.endswith('.css'): content_type = 'text/css'
                    elif file_path.endswith('.svg'): content_type = 'image/svg+xml'
                    else: content_type = 'application/octet-stream'
                
                # Manual overrides for safety
                if file_path.endswith('.js'):
                    content_type = 'application/javascript'
                elif file_path.endswith('.css'):
                    content_type = 'text/css'
                
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                print(f"Error serving static file {file_path}: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"500 Internal Server Error")
            return

        # 1. Email Logs
        if path == '/api/emails/log':
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, to_address as [to], subject, body, sent_at as sentAt FROM emails ORDER BY sent_at DESC")
            emails = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return self._send_json(200, {"success": True, "emails": emails})
            
        # 2. Get Jobs
        elif path == '/api/jobs':
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            jobs = []
            for row in cursor.fetchall():
                d = dict(row)
                d['skillsRequired'] = [s.strip() for s in d['skills_required'].split(',') if s.strip()] if d['skills_required'] else []
                d['employerId'] = d['employer_id']
                d['companyName'] = d['company_name']
                d['createdAt'] = d['created_at']
                jobs.append(d)
            conn.close()
            return self._send_json(200, {"success": True, "jobs": jobs})
            
        # 3. Get Candidate Profile
        elif path.startswith('/api/profile/candidate/'):
            user_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM candidate_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                d = dict(row)
                d['userId'] = d['user_id']
                d['workExperience'] = d['work_experience']
                d['resumeFileName'] = d['resume_file_name']
                d['resumeText'] = d['resume_text']
                d['skills'] = [s.strip() for s in d['skills'].split(',') if s.strip()] if d['skills'] else []
                return self._send_json(200, {"success": True, "profile": d})
            else:
                return self._send_json(404, {"success": False, "message": "Profile not configured yet"})
                
        # 4. Get Employer Profile
        elif path.startswith('/api/profile/employer/'):
            user_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM employer_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                d = dict(row)
                d['userId'] = d['user_id']
                d['companyName'] = d['company_name']
                d['contactInfo'] = d['contact_info']
                return self._send_json(200, {"success": True, "profile": d})
            else:
                return self._send_json(404, {"success": False, "message": "Company profile not configured yet"})
                
        # 5. Get Candidate's Applications
        elif path.startswith('/api/applications/candidate/'):
            cand_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT a.id, a.job_id, a.candidate_id, a.status, a.match_score, a.match_analysis, a.applied_at,
                       j.title, j.company_name, j.industry, j.salary, j.role, j.location
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.candidate_id = ?
                ORDER BY a.applied_at DESC
            ''', (cand_id,))
            
            apps = []
            for row in cursor.fetchall():
                d = dict(row)
                apps.append({
                    "id": d['id'],
                    "jobId": d['job_id'],
                    "candidateId": d['candidate_id'],
                    "status": d['status'],
                    "matchScore": d['match_score'],
                    "matchAnalysis": d['match_analysis'],
                    "appliedAt": d['applied_at'],
                    "job": {
                        "id": d['job_id'],
                        "title": d['title'],
                        "companyName": d['company_name'],
                        "industry": d['industry'],
                        "salary": d['salary'],
                        "role": d['role'],
                        "location": d['location']
                    }
                })
            conn.close()
            return self._send_json(200, {"success": True, "applications": apps})
            
        # 6. Get Employer's Received Applications
        elif path.startswith('/api/applications/employer/'):
            emp_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT a.id, a.job_id, a.candidate_id, a.status, a.match_score, a.match_analysis, a.applied_at,
                       j.title, j.company_name, j.industry, j.salary, j.role,
                       cp.name as cand_name, cp.email as cand_email, cp.education as cand_edu, cp.work_experience as cand_exp, cp.skills as cand_skills
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                JOIN candidate_profiles cp ON a.candidate_id = cp.user_id
                WHERE j.employer_id = ?
                ORDER BY a.match_score DESC
            ''', (emp_id,))
            
            apps = []
            for row in cursor.fetchall():
                d = dict(row)
                apps.append({
                    "id": d['id'],
                    "jobId": d['job_id'],
                    "candidateId": d['candidate_id'],
                    "status": d['status'],
                    "matchScore": d['match_score'],
                    "matchAnalysis": d['match_analysis'],
                    "appliedAt": d['applied_at'],
                    "job": {
                        "title": d['title'],
                        "companyName": d['company_name'],
                        "industry": d['industry']
                    },
                    "candidate": {
                        "userId": d['candidate_id'],
                        "name": d['cand_name'],
                        "email": d['cand_email'],
                        "education": d['cand_edu'],
                        "workExperience": d['cand_exp'],
                        "skills": [s.strip() for s in d['cand_skills'].split(',') if s.strip()] if d['cand_skills'] else []
                    }
                })
            conn.close()
            return self._send_json(200, {"success": True, "applications": apps})
            
        # 7. Candidate Analytics
        elif path.startswith('/api/analytics/candidate/'):
            cand_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*), AVG(match_score) FROM applications WHERE candidate_id = ?", (cand_id,))
            total, avg = cursor.fetchone()
            
            cursor.execute("SELECT status, COUNT(*) FROM applications WHERE candidate_id = ? GROUP BY status", (cand_id,))
            counts = dict(cursor.fetchall())
            conn.close()
            
            status_breakdown = {
                "applied": counts.get("applied", 0),
                "reviewing": counts.get("reviewing", 0),
                "matched": counts.get("matched", 0),
                "rejected": counts.get("rejected", 0)
            }
            
            return self._send_json(200, {
                "success": True,
                "analytics": {
                    "totalApplied": total or 0,
                    "averageMatchScore": round(avg) if avg else 0,
                    "statusBreakdown": status_breakdown
                }
            })
            
        # 8. Employer Analytics
        elif path.startswith('/api/analytics/employer/'):
            emp_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE employer_id = ?", (emp_id,))
            total_jobs = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*), AVG(a.match_score) 
                FROM applications a 
                JOIN jobs j ON a.job_id = j.id 
                WHERE j.employer_id = ?
            ''', (emp_id,))
            total_apps, avg_score = cursor.fetchone()
            
            cursor.execute('''
                SELECT a.status, COUNT(*) 
                FROM applications a 
                JOIN jobs j ON a.job_id = j.id 
                WHERE j.employer_id = ? 
                GROUP BY a.status
            ''', (emp_id,))
            counts = dict(cursor.fetchall())
            
            cursor.execute("SELECT skills_required FROM jobs WHERE employer_id = ?", (emp_id,))
            all_skills = cursor.fetchall()
            
            conn.close()
            
            skills_count = {}
            for row in all_skills:
                if row[0]:
                    for skill in row[0].split(','):
                        s = skill.strip()
                        if s:
                            skills_count[s] = skills_count.get(s, 0) + 1
                            
            popular_skills = [{"skill": k, "count": v} for k, v in sorted(skills_count.items(), key=lambda x: x[1], reverse=True)[:5]]
            
            status_breakdown = {
                "applied": counts.get("applied", 0),
                "reviewing": counts.get("reviewing", 0),
                "matched": counts.get("matched", 0),
                "rejected": counts.get("rejected", 0)
            }
            
            return self._send_json(200, {
                "success": True,
                "analytics": {
                    "totalJobs": total_jobs or 0,
                    "totalApplicants": total_apps or 0,
                    "averageMatchScore": round(avg_score) if avg_score else 0,
                    "statusBreakdown": status_breakdown,
                    "popularSkills": popular_skills
                }
            })
            
        else:
            return self._send_json(404, {"success": False, "message": "API route not found"})

    def do_POST(self):
        path = self.path
        body = self._read_json()
        
        # 1. Register User
        if path == '/api/auth/register':
            username = body.get('username')
            email = body.get('email')
            password = body.get('password')
            role = body.get('role')
            
            if not username or not email or not password or not role:
                return self._send_json(400, {"success": False, "message": "All fields are required"})
                
            if not validate_email(email):
                return self._send_json(400, {"success": False, "message": "Invalid email format"})
                
            is_valid_p, p_err = validate_password(password)
            if not is_valid_p:
                return self._send_json(400, {"success": False, "message": p_err})
                
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                conn.close()
                return self._send_json(400, {"success": False, "message": "User with this email already exists"})
                
            user_id = f"user-{int(datetime.utcnow().timestamp())}"
            try:
                cursor.execute('''
                    INSERT INTO users (id, username, email, password_hash, role)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, email, password, role))
                conn.commit()
            except Exception as e:
                conn.close()
                return self._send_json(500, {"success": False, "message": f"Database error: {e}"})
            conn.close()
            
            # Simulated welcome email
            send_email_notification(
                email,
                'Welcome to Job Portal Platform!',
                f"Hi {username},\n\nYour account as a {role} has been successfully created in the SQLite database.\n\nPlease log in to build your detailed profile and match with job opportunities.\n\nBest regards,\nJob Portal Team"
            )
            
            return self._send_json(200, {
                "success": True,
                "message": "Account created successfully!",
                "user": {"id": user_id, "username": username, "email": email, "role": role}
            })
            
        # 2. Login User
        elif path == '/api/auth/login':
            email = body.get('email')
            password = body.get('password')
            
            if not email or not password:
                return self._send_json(400, {"success": False, "message": "Email and password are required"})
                
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            conn.close()
            
            if not row or row['password_hash'] != password:
                return self._send_json(401, {"success": False, "message": "Invalid email or password"})
                
            return self._send_json(200, {
                "success": True,
                "message": "Logged in successfully",
                "user": {"id": row['id'], "username": row['username'], "email": row['email'], "role": row['role']}
            })
            
        # 3. Forgot Password
        elif path == '/api/auth/forgot-password':
            email = body.get('email')
            if not email:
                return self._send_json(400, {"success": False, "message": "Email address is required"})
                
            if not validate_email(email):
                return self._send_json(400, {"success": False, "message": "Invalid email format"})
                
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return self._send_json(404, {"success": False, "message": "No registered user found with this email"})
                
            # Random 6 digit verification code
            temp_code = str(100000 + int(os.urandom(2).hex(), 16) % 900000)[:6]
            
            # Send notification email
            send_email_notification(
                email,
                'Password Reset Requested',
                f"Hi {row['username']},\n\nYou requested a password reset. Use verification code: {temp_code} to change your password.\n\nIf you did not request this, please ignore this email.\n\nBest regards,\nJob Portal Team"
            )
            
            return self._send_json(200, {
                "success": True,
                "message": "Reset verification code sent to your email!",
                "code": temp_code
            })
            
        # 4. Reset Password
        elif path == '/api/auth/reset-password':
            email = body.get('email')
            new_password = body.get('newPassword')
            
            if not email or not new_password:
                return self._send_json(400, {"success": False, "message": "All fields are required"})
                
            is_valid_p, p_err = validate_password(new_password)
            if not is_valid_p:
                return self._send_json(400, {"success": False, "message": p_err})
                
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE email = ?", (new_password, email))
            rowcount = cursor.rowcount
            conn.commit()
            conn.close()
            
            if rowcount == 0:
                return self._send_json(404, {"success": False, "message": "User not found"})
                
            # Email update confirmation
            send_email_notification(
                email,
                'Password Changed Successfully',
                "Hello,\n\nYour Job Portal password has been successfully updated in SQLite.\n\nIf you did not perform this action, please contact support immediately.\n\nBest regards,\nJob Portal Team"
            )
            
            return self._send_json(200, {"success": True, "message": "Password has been successfully reset! You can now log in."})
            
        # 5. Save Candidate Profile
        elif path == '/api/profile/candidate':
            user_id = body.get('userId')
            name = body.get('name')
            email = body.get('email')
            education = body.get('education', '')
            work_experience = body.get('workExperience', '')
            skills = body.get('skills', [])
            resume_file_name = body.get('resumeFileName', '')
            resume_text = body.get('resumeText', '')
            
            if not user_id or not name or not email:
                return self._send_json(400, {"success": False, "message": "User ID, Name, and Email are required"})
                
            skills_str = ','.join(skills)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO candidate_profiles (user_id, name, email, education, work_experience, skills, resume_file_name, resume_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    education = excluded.education,
                    work_experience = excluded.work_experience,
                    skills = excluded.skills,
                    resume_file_name = excluded.resume_file_name,
                    resume_text = excluded.resume_text
            ''', (user_id, name, email, education, work_experience, skills_str, resume_file_name, resume_text))
            conn.commit()
            conn.close()
            
            return self._send_json(200, {
                "success": True,
                "message": "Candidate profile updated successfully",
                "profile": {
                    "userId": user_id,
                    "name": name,
                    "email": email,
                    "education": education,
                    "workExperience": work_experience,
                    "skills": skills,
                    "resumeFileName": resume_file_name,
                    "resumeText": resume_text
                }
            })
            
        # 6. Save Employer Profile
        elif path == '/api/profile/employer':
            user_id = body.get('userId')
            company_name = body.get('companyName')
            industry = body.get('industry')
            description = body.get('description', '')
            contact_info = body.get('contactInfo', '')
            
            if not user_id or not company_name or not industry:
                return self._send_json(400, {"success": False, "message": "User ID, Company Name, and Industry are required"})
                
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO employer_profiles (user_id, company_name, industry, description, contact_info)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    company_name = excluded.company_name,
                    industry = excluded.industry,
                    description = excluded.description,
                    contact_info = excluded.contact_info
            ''', (user_id, company_name, industry, description, contact_info))
            conn.commit()
            conn.close()
            
            return self._send_json(200, {
                "success": True,
                "message": "Employer profile updated successfully",
                "profile": {
                    "userId": user_id,
                    "companyName": company_name,
                    "industry": industry,
                    "description": description,
                    "contactInfo": contact_info
                }
            })
            
        # 7. Create Job Posting
        elif path == '/api/jobs':
            employer_id = body.get('employerId')
            title = body.get('title')
            company_name = body.get('companyName')
            industry = body.get('industry', 'Tech')
            description = body.get('description', '')
            salary = body.get('salary')
            role = body.get('role')
            skills_required = body.get('skillsRequired', [])
            location = body.get('location', 'Remote')
            
            if not employer_id or not title or not company_name or not role or not salary:
                return self._send_json(400, {"success": False, "message": "Employer, Title, Company Name, Role, and Salary are required"})
                
            job_id = f"job-{int(datetime.utcnow().timestamp())}"
            skills_str = ','.join(skills_required)
            now_str = datetime.utcnow().isoformat() + 'Z'
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (id, employer_id, title, company_name, industry, description, salary, role, skills_required, location, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (job_id, employer_id, title, company_name, industry, description, salary, role, skills_str, location, now_str))
            conn.commit()
            conn.close()
            
            return self._send_json(200, {
                "success": True,
                "message": "Job posting published successfully",
                "job": {
                    "id": job_id,
                    "employerId": employer_id,
                    "title": title,
                    "companyName": company_name,
                    "industry": industry,
                    "description": description,
                    "salary": salary,
                    "role": role,
                    "skillsRequired": skills_required,
                    "location": location,
                    "createdAt": now_str
                }
            })
            
        # 8. Resume Parsing (Vite Client proxy endpoints)
        elif path == '/api/resume/parse':
            text = body.get('text')
            file_name = body.get('fileName', 'resume.txt')
            if not text:
                return self._send_json(400, {"success": False, "message": "No resume content provided to parse"})
                
            parsed = parse_resume_text(text, file_name)
            return self._send_json(200, {
                "success": True,
                "message": "Resume successfully analyzed and parsed via SQLite Cloud Engine!",
                "parsedData": parsed
            })
            
        # 9. Apply to Job (Core Matching Algorithm)
        elif path == '/api/jobs/apply':
            job_id = body.get('jobId')
            candidate_id = body.get('candidateId')
            
            if not job_id or not candidate_id:
                return self._send_json(400, {"success": False, "message": "Job ID and Candidate ID are required"})
                
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch Job
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            
            # Fetch Candidate Profile
            cursor.execute("SELECT * FROM candidate_profiles WHERE user_id = ?", (candidate_id,))
            profile_row = cursor.fetchone()
            
            # Fetch Candidate User account
            cursor.execute("SELECT * FROM users WHERE id = ?", (candidate_id,))
            user_row = cursor.fetchone()
            
            if not job_row:
                conn.close()
                return self._send_json(404, {"success": False, "message": "Job posting not found"})
                
            if not profile_row:
                conn.close()
                return self._send_json(400, {"success": False, "message": "Please configure your candidate profile before applying!"})
                
            # Check for duplicate
            cursor.execute("SELECT id FROM applications WHERE job_id = ? AND candidate_id = ?", (job_id, candidate_id))
            if cursor.fetchone():
                conn.close()
                return self._send_json(400, {"success": False, "message": "You have already applied to this job posting!"})
                
            job_dict = dict(job_row)
            profile_dict = dict(profile_row)
            
            # Calculate score and matching alignment report
            match_res = run_job_match(profile_dict, job_dict)
            score = match_res['score']
            analysis = match_res['analysis']
            
            app_id = f"app-{int(datetime.utcnow().timestamp())}"
            status = 'matched' if score >= 80 else 'applied'
            applied_at = datetime.utcnow().isoformat() + 'Z'
            
            try:
                cursor.execute('''
                    INSERT INTO applications (id, job_id, candidate_id, status, match_score, match_analysis, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (app_id, job_id, candidate_id, status, score, analysis, applied_at))
                conn.commit()
            except Exception as e:
                conn.close()
                return self._send_json(500, {"success": False, "message": f"Application insertion error: {e}"})
                
            conn.close()
            
            # Simulated Email Notifications (Candidate & Employer)
            send_email_notification(
                profile_dict['email'],
                f"Application Received: {job_dict['title']} at {job_dict['company_name']}",
                f"Hi {profile_dict['name']},\n\nWe have successfully received your application for \"{job_dict['title']}\".\n\nOur system completed a Job Match Assessment and calculated an alignment score of {score}%.\n\nYou can review your detailed Match Analysis on your Candidate Dashboard.\n\nBest of luck!\nJob Portal Team"
            )
            
            # Notify employer if exists
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT email, username FROM users WHERE id = ?", (job_dict['employer_id'],))
            emp_user = cursor.fetchone()
            conn.close()
            
            if emp_user:
                send_email_notification(
                    emp_user[0],
                    f"New Applicant for {job_dict['title']}: {profile_dict['name']}",
                    f"Hi {emp_user[1]},\n\nA new candidate has applied for your job opening: \"{job_dict['title']}\".\n\nApplicant: {profile_dict['name']}\nMatch Score: {score}%\n\nPlease log in to your Employer Analytics Dashboard to view their full profile and match report.\n\nBest regards,\nJob Portal Team"
                )
                
            return self._send_json(200, {
                "success": True,
                "message": "Application submitted successfully!",
                "application": {
                    "id": app_id,
                    "jobId": job_id,
                    "candidateId": candidate_id,
                    "status": status,
                    "matchScore": score,
                    "matchAnalysis": analysis,
                    "appliedAt": applied_at
                }
            })
            
        # 10. Update Application Status
        elif path.startswith('/api/applications/') and path.endswith('/status'):
            app_id = path.split('/')[3]
            status = body.get('status')
            
            if not status or status not in ['reviewing', 'matched', 'rejected']:
                return self._send_json(400, {"success": False, "message": "Invalid status value"})
                
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
            rowcount = cursor.rowcount
            conn.commit()
            
            if rowcount > 0:
                # Fetch candidate & job details to notify
                cursor.execute('''
                    SELECT cp.email, cp.name, j.title, j.company_name
                    FROM applications a
                    JOIN candidate_profiles cp ON a.candidate_id = cp.user_id
                    JOIN jobs j ON a.job_id = j.id
                    WHERE a.id = ?
                ''', (app_id,))
                notify_row = cursor.fetchone()
                conn.close()
                
                if notify_row:
                    send_email_notification(
                        notify_row[0],
                        f"Application Status Updated: {notify_row[2]}",
                        f"Hi {notify_row[1]},\n\nWe wanted to let you know that your application status for \"{notify_row[2]}\" at \"{notify_row[3]}\" has been updated to: \"{status.upper()}\".\n\nPlease log in to your Candidate Dashboard to learn more.\n\nBest regards,\nJob Portal Team"
                    )
                return self._send_json(200, {"success": True, "message": "Status updated successfully"})
            else:
                conn.close()
                return self._send_json(404, {"success": False, "message": "Application not found"})
                
        else:
            return self._send_json(404, {"success": False, "message": "API route not found"})

    def do_DELETE(self):
        path = self.path
        
        # Delete job posting
        if path.startswith('/api/jobs/'):
            job_id = path.split('/')[-1]
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            rowcount = cursor.rowcount
            conn.commit()
            conn.close()
            
            if rowcount > 0:
                return self._send_json(200, {"success": True, "message": "Job posting deleted"})
            else:
                return self._send_json(404, {"success": False, "message": "Job posting not found"})
        else:
            return self._send_json(404, {"success": False, "message": "API route not found"})

def run_server():
    init_db()
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, JobPortalAPIHandler)
    print(f"🐍 [Job Portal Python SQL Server] Running on http://0.0.0.0:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Python server...")
        httpd.server_close()

if __name__ == '__main__':
    run_server()
