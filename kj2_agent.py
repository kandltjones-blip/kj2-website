#!/usr/bin/env python3
"""KJ2 Personal AI Agent — Full Desktop App with Tool Capabilities"""
import json, os, threading, time, webbrowser, urllib.request, subprocess, platform, re, uuid
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Active Selenium sessions: {session_id: {"driver": ..., "url": ..., "fields": {...}}}
ACTIVE_SESSIONS = {}

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH      = os.path.join(BASE_DIR, 'KJ2_Agent_Config.json')
TASKS_PATH       = os.path.join(BASE_DIR, 'kj2_tasks.json')
VIDEOMAKER_DIR   = os.path.join(BASE_DIR, 'VideoMaker')
VIDEOMAKER_INPUT = os.path.join(VIDEOMAKER_DIR, 'input')
OLLAMA_URL       = "http://localhost:11434"
IMAGE_EXTS       = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

# Memory on D: drive — falls back to C:\KJ2\KJ2_Memory if D: not available
MEMORY_DIR  = 'D:\\KJ2_Memory'
MEMORY_PATH = os.path.join(MEMORY_DIR, 'kj2_memory.json')
try:
    os.makedirs(MEMORY_DIR, exist_ok=True)
except Exception:
    MEMORY_DIR  = os.path.join(BASE_DIR, 'KJ2_Memory')
    MEMORY_PATH = os.path.join(MEMORY_DIR, 'kj2_memory.json')
    os.makedirs(MEMORY_DIR, exist_ok=True)

os.makedirs(VIDEOMAKER_INPUT, exist_ok=True)

# ── Capabilities registry ───────────────────────────────────────────────────────
CAPABILITIES = {
    'web_search':     {'label': 'Web Search',        'desc': 'Search the internet for real-time results',               'packages': ['googlesearch-python']},
    'open_browser':   {'label': 'Open Browser Tab',  'desc': 'Open a new browser tab (Google, YouTube, SoundCloud etc)', 'packages': []},
    'web_reader':     {'label': 'Web Page Reader',   'desc': 'Fetch and read content from any URL you give',           'packages': ['requests', 'beautifulsoup4']},
    'file_search':    {'label': 'File Search',       'desc': 'Search folders on your computer for files by name',       'packages': []},
    'open_files':     {'label': 'Open Files & Apps', 'desc': 'Open programs, documents and folders on your computer',  'packages': []},
    'weather':        {'label': 'Weather',           'desc': 'Get current weather for any location',                   'packages': ['requests']},
    'clipboard':      {'label': 'Clipboard',         'desc': 'Read from and write to your clipboard',                  'packages': ['pyperclip']},
    'text_to_speech': {'label': 'Text to Speech',    'desc': 'KJ2 speaks responses out loud',                         'packages': ['pyttsx3']},
    'shell_commands': {'label': 'Run Commands',      'desc': 'Run commands on your computer on your behalf',           'packages': []},
    'email_draft':    {'label': 'Email Draft',       'desc': 'Write emails and copy them to your clipboard ready to paste', 'packages': ['pyperclip']},
    'web_automation': {'label': 'Web Automation',    'desc': 'Fill out forms on websites — you approve before anything is submitted', 'packages': ['selenium', 'webdriver-manager']},
    'memory':         {'label': 'Memory',            'desc': 'Remember things you tell KJ2 (stored on your D: drive)', 'packages': []},
}

# Keywords that trigger each capability
TOOL_TRIGGERS = {
    'open_browser':   r'\b(open (a |an |the )?(new |internet |browser |chrome |google |search )+(tab|browser|window)|open (chrome|firefox|browser|google)|open a new tab)\b',
    'web_search':     r'\b(search|look up|google|find online|search for|look online|research|what is|who is|latest news|top \d+|most (streamed|popular|played))\b',
    'web_reader':     r'\b(read this|open this url|fetch|read this page|what does this (website|page|site) say|summarise this)\b',
    'file_search':    r'\b(find (file|document|folder)|search my (computer|pc|drive|files)|where is the file|locate)\b',
    'open_files':     r'\b(open|launch|start) .{1,40}(\.exe|\.pdf|\.docx|\.xlsx|\.txt|app|program|folder|notepad|chrome|word|excel)\b',
    'weather':        r'\b(weather|temperature|forecast|rain|sunny|hot today|cold today|degrees)\b',
    'clipboard':      r'\b(clipboard|what did i copy|read my clipboard|what is on my clipboard)\b',
    'text_to_speech': r'\b(read (that |it |this )?aloud|speak (that|it|this)|say that out loud|read (that|it) to me)\b',
    'shell_commands': r'\b(run (this |the )?(command|script)|execute|open (command|cmd|terminal|powershell))\b',
    'email_draft':    r'\b(write (an |a )?email|draft (an |a )?email|email to|compose (an |a )?email)\b',
    'web_automation': r'\b(fill (in|out)|submit (a |the )?form|go to .{1,30} and (fill|login|sign)|log (in|into)|automate)\b',
    'memory':         r'\b(remember|don\'?t forget|keep in mind|note that|store this|save (it |this )?(to )?memory|save to memory|make a note|add to memory|log this|write this down)\b',
}

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"user_name": "there", "story": "", "permanent_rules": [],
                "answers": {}, "extra_instructions": [], "image_generator_url": "",
                "permissions": {}, "file_search_exceptions": []}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def load_tasks():
    if not os.path.exists(TASKS_PATH):
        return []
    with open(TASKS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_tasks(tasks):
    with open(TASKS_PATH, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, indent=2)

def load_memory():
    if not os.path.exists(MEMORY_PATH):
        return []
    with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_memory(items):
    with open(MEMORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

config = load_config()

# Auto-grant harmless capabilities that don't need asking
_cfg = load_config()
if not _cfg.get('permissions', {}).get('open_browser'):
    _cfg.setdefault('permissions', {})['open_browser'] = True
    save_config(_cfg)

# ── Permissions ─────────────────────────────────────────────────────────────────

def has_permission(capability):
    cfg = load_config()
    return cfg.get('permissions', {}).get(capability, False)

def pip_install(package):
    """Install a package via pip and return the result string."""
    for py in ['python', 'python3', 'py']:
        try:
            result = subprocess.run(
                [py, '-m', 'pip', 'install', package, '--quiet'],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                return f"Installed {package}."
            # try next python alias
        except FileNotFoundError:
            continue
        except Exception as e:
            return f"pip install {package} failed: {e}"
    return f"Could not install {package} — python not found in PATH."

def grant_permission(capability):
    cfg = load_config()
    cfg.setdefault('permissions', {})[capability] = True
    save_config(cfg)
    cap = CAPABILITIES.get(capability, {})
    pkgs = cap.get('packages', [])
    results = []
    for pkg in pkgs:
        results.append(pip_install(pkg))
    return results

# ── Ollama ─────────────────────────────────────────────────────────────────────

def ollama_generate(prompt, model="phi3.5", images=None):
    payload = {"model": model, "prompt": prompt, "stream": False}
    if images:
        payload["images"] = images
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read()).get('response', '').strip()
    except Exception as e:
        return f"[KJ2 Error] Could not reach Ollama. Make sure it is running. ({e})"

def build_system():
    cfg     = load_config()
    rules   = '\n'.join(cfg.get('permanent_rules', []))
    extras  = '\n'.join(cfg.get('extra_instructions', []))
    answers = cfg.get('answers', {})
    ans_txt = '\n'.join(f"- {k.replace('_',' ').title()}: {v}" for k, v in answers.items())
    memory  = load_memory()
    mem_txt = '\n'.join(f"- {m}" for m in memory) if memory else ''
    perms   = cfg.get('permissions', {})
    perm_txt = ', '.join(k.replace('_',' ') for k, v in perms.items() if v) or 'none yet'
    name = cfg.get('user_name', 'your owner')
    return (
        f"You are KJ2, the personal AI agent of {name}.\n\n"

        "=== ABSOLUTE RULES — NEVER BREAK THESE ===\n"
        "1. NEVER fabricate, invent, or pretend you have done anything. You cannot check emails, post to YouTube, add songs to a website, look up patents, or do anything on the owner's behalf unless a tool just ran and returned a real result in this exact message.\n"
        "2. NEVER volunteer a status update, briefing, or list of tasks you claim to have completed. NEVER. The owner will ask when they want something.\n"
        "3. NEVER say you have prepared anything, completed anything, or have anything ready — unless it literally just happened in this message.\n"
        "4. If the owner says 'Yes' or gives a short one-word reply, respond ONLY to their last question. Do not launch into a briefing or task list.\n"
        "5. These rules are in your instructions. If the owner asks if you can see a rule, say YES and quote it.\n"
        "6. Be short. Answer the question. Stop.\n"
        "7. NEVER greet the owner. Do NOT start responses with 'G'day Keith', 'Hi Keith', 'Hello', or any greeting. Start with the actual answer.\n"
        "8. NEVER invent song names, YouTube videos, or any content from the owner's music catalogue. If you don't know a song name, say you don't know it — do NOT make one up.\n"
        "9. If the owner asks about their own details (YouTube channel, artist name, website, etc.) and it is in the OWNER PROFILE or MEMORY above, use that information. Do NOT do a web search for it.\n"
        "10. When doing a web search, construct a specific useful query using the owner's real name/channel from OWNER PROFILE — never search for vague phrases like 'my youtube channel'.\n\n"

        f"PERMANENT RULES FROM OWNER:\n{rules}\n\n"
        f"OWNER PROFILE:\n{cfg.get('story', '')}\n\n"
        f"CONFIGURATION:\n{ans_txt}\n\n"
        f"EXTRA INSTRUCTIONS:\n{extras}\n\n"
        f"MEMORY:\n{mem_txt}\n\n"
        f"ACTIVE CAPABILITIES:\n{perm_txt}\n\n"
        "USING TOOLS:\n"
        "- shell_commands: you can run any Windows command or install packages. Use `pip install <package>` to install anything you need. Always run pip install before using a new package.\n"
        "- web_search: search the web and return real results. Copy the actual titles, snippets and URLs verbatim from the results. Do NOT invent article titles, publication dates, or sources. If the results do not contain what was searched for, say so plainly.\n"
        "- open_browser: open a browser tab to any URL.\n"
        "- web_automation: open Chrome and fill/submit web forms (needs approval before submit).\n"
        "- If you need a Python package, use shell_commands to pip install it first.\n\n"
        f"Speak directly to {name}. Australian tone. Short answers. No corporate filler. No volunteered updates."
    )

# ── Tool detection ─────────────────────────────────────────────────────────────

def detect_tool(message):
    msg = message.lower()
    for tool, pattern in TOOL_TRIGGERS.items():
        if re.search(pattern, msg, re.IGNORECASE):
            return tool
    return None

# ── Tool executors ─────────────────────────────────────────────────────────────

def tool_web_search(query):
    import urllib.request as _ur
    import urllib.parse as _up
    import re
    try:
        data = _up.urlencode({'q': query}).encode()
        req = _ur.Request(
            'https://lite.duckduckgo.com/lite/',
            data=data,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        with _ur.urlopen(req, timeout=10) as r:
            html = r.read().decode('utf-8', errors='ignore')
        links = re.findall(r"class='result-link'[^>]*>([^<]+)</a>", html)
        urls = re.findall(r"class='result-link'\s+href=\"([^\"]+)\"", html)
        if not urls:
            urls = re.findall(r"href=\"(https?://[^\"]+)\"[^>]*class='result-link'", html)
        snippets = re.findall(r"class='result-snippet'[^>]*>(.*?)</td>", html, re.DOTALL)
        results = []
        for i in range(min(5, len(links))):
            title = links[i].strip() if i < len(links) else ""
            url = urls[i].strip() if i < len(urls) else ""
            snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
            if title and url:
                results.append(f"**{title}**\n{snippet}\n{url}")
        if results:
            return '\n\n'.join(results)
        return "No results found."
    except Exception as e:
        return f"Search failed: {e}"

def tool_open_browser(url):
    try:
        webbrowser.open(url)
        return f"Opened {url} in your browser."
    except Exception as e:
        return f"Could not open browser: {e}"

def tool_browser_search(query):
    """Open Chrome with Selenium, go to Google, type the query and search — user sees it happen."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=Options())
        except Exception:
            driver = webdriver.Chrome(options=Options())
        driver.get('https://www.google.com')
        wait = WebDriverWait(driver, 10)
        box = wait.until(EC.presence_of_element_located((By.NAME, 'q')))
        box.clear()
        box.send_keys(query)
        box.send_keys(Keys.RETURN)
        return f"Searched Google for: {query}"
    except ImportError:
        # Selenium not installed — fall back to opening the URL directly
        import urllib.parse
        webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
        return f"Opened Google search for: {query}"
    except Exception as e:
        import urllib.parse
        webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
        return f"Opened Google search for: {query} (Selenium error: {e})"

def tool_web_reader(url):
    try:
        import requests as req_lib
        from bs4 import BeautifulSoup
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = req_lib.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = ' '.join(soup.get_text(separator=' ').split())
        return text[:4000]
    except Exception as e:
        return f"Could not read page: {e}"

def tool_file_search(query):
    try:
        cfg = load_config()
        exceptions = cfg.get('file_search_exceptions', [])
        results = []
        search_roots = ['C:\\Users', 'D:\\', 'E:\\']
        for root in search_roots:
            if not os.path.exists(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not any(
                    ex.lower() in os.path.join(dirpath, d).lower() for ex in exceptions
                ) and d not in ['Windows', 'Program Files', 'ProgramData', '$Recycle.Bin', 'AppData']]
                for fn in filenames:
                    if query.lower() in fn.lower():
                        results.append(os.path.join(dirpath, fn))
                if len(results) >= 20:
                    break
            if len(results) >= 20:
                break
        return '\n'.join(results) if results else f"No files found matching '{query}'"
    except Exception as e:
        return f"File search failed: {e}"

def tool_weather(location):
    try:
        import urllib.parse
        loc = urllib.parse.quote(location)
        url = f"https://wttr.in/{loc}?format=3"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode('utf-8').strip()
    except Exception as e:
        return f"Could not get weather: {e}"

def tool_clipboard_read():
    try:
        import pyperclip
        return pyperclip.paste() or "(Clipboard is empty)"
    except Exception as e:
        return f"Could not read clipboard: {e}"

def tool_clipboard_write(text):
    try:
        import pyperclip
        pyperclip.copy(text)
        return "Copied to clipboard."
    except Exception as e:
        return f"Could not write to clipboard: {e}"

def tool_text_to_speech(text):
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return "Speaking..."
    except Exception as e:
        return f"Text to speech failed: {e}"

def tool_run_command(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout or result.stderr or "(No output)"
        return output[:2000]
    except Exception as e:
        return f"Command failed: {e}"

def tool_open_file_or_app(target):
    try:
        if platform.system() == 'Windows':
            os.startfile(target)
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', target])
        else:
            subprocess.Popen(['xdg-open', target])
        return f"Opened: {target}"
    except Exception as e:
        return f"Could not open: {e}"

def tool_memory_save(item):
    memory = load_memory()
    ts = time.strftime('%Y-%m-%d')
    entry = f"[{ts}] {item}"
    memory.append(entry)
    save_memory(memory)
    return f"Remembered: {item}"

# ── Flask ──────────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'kj2_chat.html')

# ── Config info ─────────────────────────────────────────────────────────────────

@app.route('/config/info')
def config_info():
    cfg = load_config()
    return jsonify({
        "user_name":           cfg.get('user_name', 'there'),
        "image_generator_url": cfg.get('image_generator_url', ''),
        "permanent_rules":     cfg.get('permanent_rules', []),
        "extra_instructions":  cfg.get('extra_instructions', []),
        "permissions":         cfg.get('permissions', {}),
    })

# ── Permissions ─────────────────────────────────────────────────────────────────

@app.route('/permissions', methods=['GET'])
def get_permissions():
    cfg = load_config()
    result = {}
    for key, cap in CAPABILITIES.items():
        result[key] = {**cap, 'granted': cfg.get('permissions', {}).get(key, False)}
    return jsonify(result)

@app.route('/permissions/grant', methods=['POST'])
def grant_permission_route():
    capability = (request.json or {}).get('capability', '')
    if capability not in CAPABILITIES:
        return jsonify({"error": "Unknown capability"}), 400
    install_results = grant_permission(capability)
    return jsonify({"ok": True, "capability": capability, "install_results": install_results})

@app.route('/permissions/revoke', methods=['POST'])
def revoke_permission():
    capability = (request.json or {}).get('capability', '')
    cfg = load_config()
    cfg.setdefault('permissions', {})[capability] = False
    save_config(cfg)
    return jsonify({"ok": True})

# ── TAB 1: CHAT ─────────────────────────────────────────────────────────────────

@app.route('/chat', methods=['POST'])
def chat():
    data    = request.json or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({"response": ""}), 400

    # ── Submit / cancel active automation sessions ──────────────────────────────
    submit_match = re.match(r'^submit\s+([a-f0-9]{8})$', message, re.IGNORECASE)
    cancel_match = re.match(r'^cancel\s+([a-f0-9]{8})$', message, re.IGNORECASE)
    if submit_match:
        sid = submit_match.group(1)
        sess = ACTIVE_SESSIONS.get(sid)
        if not sess:
            return jsonify({"response": "Session not found or already closed."})
        if sess['status'] != 'awaiting_approval':
            return jsonify({"response": f"Form is still being filled ({sess['status']}). Give it a moment then try again."})
        try:
            from selenium.webdriver.common.by import By
            driver = sess['driver']
            btns = driver.find_elements(By.CSS_SELECTOR, 'input[type=submit], button[type=submit], button')
            for btn in btns:
                txt = btn.text.lower()
                if any(w in txt for w in ['submit', 'send', 'apply', 'register', 'continue', 'next', 'sign up', 'join', 'save']):
                    btn.click(); break
            else:
                if btns: btns[-1].click()
            del ACTIVE_SESSIONS[sid]
            return jsonify({"response": "Submitted. The form has been sent.", "tool_used": "web_automation"})
        except Exception as e:
            return jsonify({"response": f"Could not submit: {e}"})
    if cancel_match:
        sid = cancel_match.group(1)
        sess = ACTIVE_SESSIONS.get(sid)
        if sess:
            driver = sess.get('driver')
            if driver:
                try: driver.quit()
                except: pass
            del ACTIVE_SESSIONS[sid]
        return jsonify({"response": "Cancelled. Browser closed, nothing was submitted.", "tool_used": "web_automation"})

    # ── Web automation triggered from chat ────────────────────────────────────────
    if re.search(TOOL_TRIGGERS['web_automation'], message, re.IGNORECASE):
        if not has_permission('web_automation'):
            cap = CAPABILITIES['web_automation']
            return jsonify({"permission_required": True, "capability": "web_automation",
                            "label": cap['label'], "description": cap['desc'],
                            "packages": cap['packages'], "original_message": message})
        urls = re.findall(r'https?://\S+', message)
        url  = urls[0] if urls else ''
        if not url:
            return jsonify({"response": "Give me the URL and I will open it and fill the form for you."})
        # Kick off automation inline
        prompt = (f"{build_system()}\n\n"
                  f"Owner wants to fill a web form at: {url}\n"
                  f"Task: {message}\n\n"
                  f"Return ONLY a JSON object with field names as keys and values to fill. "
                  f"Use only info from the owner profile. No explanation, just JSON. KJ2:")
        raw_plan = ollama_generate(prompt)
        try:
            s = raw_plan.find('{'); e2 = raw_plan.rfind('}') + 1
            field_plan = json.loads(raw_plan[s:e2]) if s >= 0 else {}
        except Exception:
            field_plan = {}
        session_id = str(uuid.uuid4())[:8]
        ACTIVE_SESSIONS[session_id] = {
            'status': 'starting', 'url': url, 'task': message,
            'field_plan': field_plan, 'driver': None, 'filled': {}, 'error': None
        }
        threading.Thread(target=_do_automation, args=(session_id, url, field_plan), daemon=True).start()
        return jsonify({
            "response": (f"Opening {url} in Chrome now. Watch the browser — I am filling the form. "
                         f"Once done it will be waiting on screen for your review.\n\n"
                         f"Type SUBMIT to send it or CANCEL to close without submitting."),
            "automation_session": session_id,
            "field_plan": field_plan,
            "tool_used": "web_automation"
        })

    tool = detect_tool(message)

    if tool and not has_permission(tool):
        cap = CAPABILITIES[tool]
        return jsonify({
            "permission_required": True,
            "capability":          tool,
            "label":               cap['label'],
            "description":         cap['desc'],
            "packages":            cap['packages'],
            "original_message":    message
        })

    tool_result = None

    if tool == 'open_browser':
        # Detect specific site or URL; default to Google
        url_match = re.search(r'https?://\S+', message)
        site_match = re.search(r'\b(youtube|soundcloud|spotify|google|twitter|facebook|instagram|reddit)\b', message, re.IGNORECASE)
        if url_match:
            url = url_match.group(0)
        elif site_match:
            site = site_match.group(1).lower()
            url = {'youtube':'https://youtube.com','soundcloud':'https://soundcloud.com',
                   'spotify':'https://open.spotify.com','google':'https://google.com',
                   'twitter':'https://twitter.com','facebook':'https://facebook.com',
                   'instagram':'https://instagram.com','reddit':'https://reddit.com'}.get(site,'https://google.com')
        else:
            url = 'https://google.com'
        tool_open_browser(url)
        return jsonify({"response": f"Opened {url} in your browser.", "tool_used": "open_browser"})

    elif tool == 'web_search':
        # Strip intent words and surrounding quotes to get clean search query
        query = re.sub(r'\b(can you |please |could you )?(search for|look up|google|search|find online|research|find me|tell me about|what are the|give me the|find)\b', '', message, flags=re.IGNORECASE).strip()
        query = re.sub(r'\bcan you\b', '', query, flags=re.IGNORECASE).strip()
        query = query.strip(' ?.,\'"')
        raw = tool_web_search(query or message)
        return jsonify({"response": raw, "tool_used": "web_search", "tool_result": raw})

    elif tool == 'web_reader':
        urls = re.findall(r'https?://\S+', message)
        if urls:
            tool_result = tool_web_reader(urls[0])
        else:
            tool_result = "No URL found in your message. Please include the full URL."

    elif tool == 'weather':
        loc_match = re.search(r'weather (?:in |for |at )?(.+)', message, re.IGNORECASE)
        location = loc_match.group(1).strip() if loc_match else 'current location'
        tool_result = tool_weather(location)

    elif tool == 'clipboard':
        tool_result = tool_clipboard_read()

    elif tool == 'file_search':
        query = re.sub(r'\b(find file|find|search my computer|search files|locate|where is the file|where is)\b', '', message, flags=re.IGNORECASE).strip()
        tool_result = tool_file_search(query or message)

    elif tool == 'memory':
        mem_match = re.sub(r'\b(remember|don\'?t forget|keep in mind|note that|store this|save this to memory|make a note that?)\b', '', message, flags=re.IGNORECASE).strip()
        save_result = tool_memory_save(mem_match or message)
        return jsonify({"response": "Saved to memory.", "tool_used": "memory", "tool_result": save_result})

    elif tool == 'shell_commands':
        # Detect pip install requests first
        pip_match = re.search(r'(?:pip install|install)\s+([\w\-\[\]>=<.]+)', message, re.IGNORECASE)
        cmd_match  = re.search(r'(?:run|execute|open cmd and run|run in cmd)\s+(.+)', message, re.IGNORECASE)
        if pip_match:
            pkg = pip_match.group(1).strip()
            tool_result = pip_install(pkg)
        elif cmd_match:
            tool_result = tool_run_command(cmd_match.group(1).strip())
        else:
            # Let the LLM decide what command to run based on the message
            prompt = (f"{build_system()}\n\n"
                      f"Owner asked: {message}\n\n"
                      "You have shell_commands permission. Determine the exact Windows command to run and respond with ONLY: CMD: <command>\n"
                      "Nothing else. No explanation. Just CMD: followed by the command. KJ2:")
            llm_cmd = ollama_generate(prompt)
            cmd_line = re.search(r'CMD:\s*(.+)', llm_cmd)
            if cmd_line:
                tool_result = tool_run_command(cmd_line.group(1).strip())
            else:
                tool_result = f"Ran: {llm_cmd[:200]}" if llm_cmd else "Could not determine command."

    elif tool == 'email_draft':
        prompt = (f"{build_system()}\n\nUser wants to write an email. Request: {message}\n\n"
                  "Write a complete professional email (Subject line + body). KJ2:")
        draft = ollama_generate(prompt)
        tool_clipboard_write(draft) if has_permission('clipboard') else None
        return jsonify({"response": draft, "email_draft": True})

    elif tool == 'text_to_speech':
        response = ollama_generate(f"{build_system()}\n\nUser: {message}\n\nKJ2:")
        threading.Thread(target=tool_text_to_speech, args=(response,), daemon=True).start()
        return jsonify({"response": response, "speaking": True})

    elif tool == 'open_files':
        target_match = re.search(r'open (.+)', message, re.IGNORECASE)
        if target_match:
            tool_result = tool_open_file_or_app(target_match.group(1).strip())
        else:
            tool_result = "What would you like me to open?"

    if tool_result:
        prompt = (f"{build_system()}\n\n"
                  f"TOOL JUST RAN: {tool}\n"
                  f"User asked: {message}\n\n"
                  f"=== REAL TOOL OUTPUT (report this — do not ignore it, do not make up different results) ===\n"
                  f"{tool_result}\n"
                  f"=== END TOOL OUTPUT ===\n\n"
                  f"Report what the tool found above. If results are there, list them clearly. "
                  f"Do NOT say you could not find anything if results are shown above. KJ2:")
        response = ollama_generate(prompt)
        return jsonify({"response": response, "tool_used": tool, "tool_result": tool_result})

    response = ollama_generate(
        f"{build_system()}\n\n"
        f"Owner's message: {message}\n\n"
        f"IMPORTANT: Answer only what was asked. Do not volunteer any status updates, briefings, or task lists. KJ2:"
    )
    return jsonify({"response": response})

# ── Chat file upload ────────────────────────────────────────────────────────────

READABLE_EXTS = {'.txt', '.md', '.py', '.js', '.ts', '.json', '.csv', '.html', '.css', '.xml', '.yaml', '.yml', '.log', '.bat', '.sh'}

@app.route('/chat/file', methods=['POST'])
def chat_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    f       = request.files['file']
    message = request.form.get('message', 'What is in this file?').strip()
    fname   = f.filename or 'file'
    ext     = os.path.splitext(fname)[1].lower()

    # Images — pass to Ollama vision if supported
    if ext in IMAGE_EXTS:
        import base64 as b64
        img_bytes = f.read()
        img_b64   = b64.b64encode(img_bytes).decode()
        response  = ollama_generate(f"{build_system()}\n\nUser: {message}\n\nKJ2:", images=[img_b64])
        return jsonify({"response": response})

    # PDFs
    if ext == '.pdf':
        try:
            import pdfplumber
            import io
            text = ''
            with pdfplumber.open(io.BytesIO(f.read())) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or '') + '\n'
            text = text[:8000]
        except ImportError:
            try:
                import io
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(f.read()))
                text = '\n'.join(page.extract_text() or '' for page in reader.pages)[:8000]
            except Exception as e:
                return jsonify({"response": f"Cannot read PDF — install pdfplumber: pip install pdfplumber ({e})"})
        except Exception as e:
            return jsonify({"response": f"Could not read PDF: {e}"})

    # Word docs
    elif ext in ('.docx', '.doc'):
        try:
            import io
            from docx import Document
            doc  = Document(io.BytesIO(f.read()))
            text = '\n'.join(p.text for p in doc.paragraphs)[:8000]
        except ImportError:
            return jsonify({"response": "Cannot read Word files — install python-docx: pip install python-docx"})
        except Exception as e:
            return jsonify({"response": f"Could not read file: {e}"})

    # Excel
    elif ext in ('.xlsx', '.xls'):
        try:
            import io
            import openpyxl
            wb   = openpyxl.load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                rows.append(f"Sheet: {ws.title}")
                for row in list(ws.iter_rows(values_only=True))[:50]:
                    rows.append('\t'.join(str(c) if c is not None else '' for c in row))
            text = '\n'.join(rows)[:8000]
        except ImportError:
            return jsonify({"response": "Cannot read Excel files — install openpyxl: pip install openpyxl"})
        except Exception as e:
            return jsonify({"response": f"Could not read file: {e}"})

    # Plain text / code
    elif ext in READABLE_EXTS:
        try:
            text = f.read().decode('utf-8', errors='replace')[:8000]
        except Exception as e:
            return jsonify({"response": f"Could not read file: {e}"})

    else:
        return jsonify({"response": f"File type {ext} not supported. Supported: txt, pdf, csv, docx, xlsx, images, and most code files."})

    prompt = (f"{build_system()}\n\n"
              f"The owner has shared a file: {fname}\n\n"
              f"FILE CONTENTS:\n{text}\n\n"
              f"Owner's request: {message}\n\nKJ2:")
    response = ollama_generate(prompt)
    return jsonify({"response": response, "file_read": fname})

# ── TAB 2: MICROPHONE ───────────────────────────────────────────────────────────

@app.route('/mic/start', methods=['POST'])
def mic_start():
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = 300
        r.dynamic_energy_threshold = True
        try:
            import pyaudio
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.8)
                audio = r.listen(source, timeout=15, phrase_time_limit=45)
        except (ImportError, OSError):
            import sounddevice as sd
            import numpy as np
            import io, wave
            sample_rate = 16000
            duration = 8
            recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='int16')
            sd.wait()
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(recording.tobytes())
            buf.seek(0)
            audio = sr.AudioData(buf.read(), sample_rate, 2)
        text     = r.recognize_google(audio)
        response = ollama_generate(f"{build_system()}\n\nUser (via microphone): {text}\n\nKJ2:")
        return jsonify({"transcribed": text, "response": response})
    except ImportError:
        return jsonify({"error": "Run: pip install SpeechRecognition sounddevice"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── TAB 3: IMAGES ───────────────────────────────────────────────────────────────

@app.route('/image/save-url', methods=['POST'])
def image_save_url():
    try:
        url = request.json.get('url', '').strip()
        if not url:
            return jsonify({"error": "No URL provided"}), 400
        cfg = load_config()
        cfg['image_generator_url'] = url
        save_config(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/image/open-generator', methods=['POST'])
def image_open_generator():
    cfg = load_config()
    url = cfg.get('image_generator_url', '').strip() or 'https://grok.com/imagine'
    try:
        subprocess.Popen(['start', 'chrome', url], shell=True)
    except Exception:
        webbrowser.open(url)
    return jsonify({"ok": True, "url": url})

@app.route('/image/save', methods=['POST'])
def image_save():
    if 'file' not in request.files:
        return jsonify({"error": "No file"}), 400
    f   = request.files['file']
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in IMAGE_EXTS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400
    name = secure_filename(f.filename)
    dest = os.path.join(VIDEOMAKER_INPUT, name)
    f.save(dest)
    return jsonify({"ok": True, "filename": name})

@app.route('/image/list')
def image_list():
    if not os.path.exists(VIDEOMAKER_INPUT):
        return jsonify([])
    files = [
        {"name": fn, "size": os.path.getsize(os.path.join(VIDEOMAKER_INPUT, fn))}
        for fn in sorted(os.listdir(VIDEOMAKER_INPUT))
        if os.path.splitext(fn)[1].lower() in IMAGE_EXTS
    ]
    return jsonify(files)

@app.route('/image/delete/<path:filename>', methods=['DELETE'])
def image_delete(filename):
    path = os.path.join(VIDEOMAKER_INPUT, secure_filename(filename))
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})

@app.route('/image/clear', methods=['POST'])
def image_clear():
    for fn in os.listdir(VIDEOMAKER_INPUT):
        if os.path.splitext(fn)[1].lower() in IMAGE_EXTS:
            os.remove(os.path.join(VIDEOMAKER_INPUT, fn))
    return jsonify({"ok": True})

# ── Open folders ─────────────────────────────────────────────────────────────────

@app.route('/open/videomaker', methods=['POST'])
def open_videomaker():
    _open_folder(VIDEOMAKER_INPUT)
    return jsonify({"ok": True})

@app.route('/open/kj2', methods=['POST'])
def open_kj2():
    _open_folder(BASE_DIR)
    return jsonify({"ok": True})

def _open_folder(path):
    os.makedirs(path, exist_ok=True)
    sys = platform.system()
    if sys == 'Windows':
        os.startfile(path)
    elif sys == 'Darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])

# ── TAB 4: VIDEO ─────────────────────────────────────────────────────────────────

VIDEO_PROMPTS = {
    "script":      "Write a complete video script for: {topic}. Include an attention-grabbing intro hook, all main points with enough detail to fill the full length, and a strong outro call-to-action. Write it as natural speech in my voice, ready to film.",
    "title":       "Write 5 compelling YouTube video titles for: {topic}. Make them click-worthy, honest, and optimised for search.",
    "description": "Write a YouTube video description for: {topic}. Include a hook, main points, and call to action. Include relevant keywords naturally. 200-300 words.",
    "tags":        "Suggest 25 YouTube search tags for a video about: {topic}. Return as a comma-separated list, most important first.",
    "thumbnail":   "Describe the perfect thumbnail for a YouTube video about: {topic}. Be specific — colours, text overlay, imagery, facial expression if applicable.",
    "hook":        "Write 5 different 15-second opening hooks for a video about: {topic}. Each one should grab attention in the first 3 seconds.",
}

@app.route('/video/help', methods=['POST'])
def video_help():
    data      = request.json or {}
    topic     = data.get('topic', '').strip()
    help_type = data.get('type', 'script')
    if not topic:
        return jsonify({"error": "No topic provided"}), 400
    task_prompt = VIDEO_PROMPTS.get(help_type, VIDEO_PROMPTS['script']).format(topic=topic)
    response    = ollama_generate(f"{build_system()}\n\nUser: {task_prompt}\n\nKJ2:")
    return jsonify({"response": response})

# ── TAB 5: TASKS ─────────────────────────────────────────────────────────────────

@app.route('/tasks')
def get_tasks():
    return jsonify(load_tasks())

@app.route('/tasks/generate', methods=['POST'])
def generate_tasks():
    prompt = (f"{build_system()}\n\nGenerate today's morning briefing task list. "
              "Create 8-10 specific actionable tasks based on my profile, goals and business. "
              'Return ONLY a JSON array. Each item: "task" (string), "priority" ("high"/"medium"/"low"), '
              '"category" (string like Email/Social/Business/Personal). No markdown, just JSON.\n\nKJ2:')
    response = ollama_generate(prompt)
    try:
        start = response.find('['); end = response.rfind(']') + 1
        raw   = json.loads(response[start:end]) if start >= 0 and end > start else []
        tasks = [{"id": i, "task": (t.get("task") if isinstance(t, dict) else str(t)),
                  "priority": (t.get("priority", "medium") if isinstance(t, dict) else "medium"),
                  "category": (t.get("category", "General") if isinstance(t, dict) else "General"),
                  "status": "pending"} for i, t in enumerate(raw)]
    except Exception:
        tasks = [{"id": 0, "task": "Could not generate tasks — try again.", "priority": "medium",
                  "category": "General", "status": "pending"}]
    save_tasks(tasks)
    return jsonify(tasks)

@app.route('/tasks/<int:task_id>', methods=['PATCH'])
def update_task(task_id):
    data  = request.json or {}
    tasks = load_tasks()
    for t in tasks:
        if t.get('id') == task_id:
            t['status'] = data.get('status', 'pending')
            break
    save_tasks(tasks)
    return jsonify({"ok": True})

@app.route('/tasks/clear', methods=['POST'])
def clear_tasks():
    save_tasks([])
    return jsonify({"ok": True})

# ── TAB 6: INSTRUCTIONS ──────────────────────────────────────────────────────────

@app.route('/instructions')
def get_instructions():
    cfg = load_config()
    return jsonify({"permanent_rules": cfg.get('permanent_rules', []),
                    "extra_instructions": cfg.get('extra_instructions', [])})

@app.route('/instructions', methods=['POST'])
def add_instruction():
    data        = request.json or {}
    instruction = data.get('instruction', '').strip()
    if not instruction:
        return jsonify({"error": "No instruction provided"}), 400
    cfg = load_config()
    cfg.setdefault('extra_instructions', []).append(instruction)
    save_config(cfg)
    config.update(cfg)
    return jsonify({"ok": True, "total": len(cfg['extra_instructions'])})

@app.route('/instructions/<int:idx>', methods=['DELETE'])
def delete_instruction(idx):
    cfg    = load_config()
    extras = cfg.get('extra_instructions', [])
    if 0 <= idx < len(extras):
        extras.pop(idx)
        cfg['extra_instructions'] = extras
        save_config(cfg)
        config.update(cfg)
    return jsonify({"ok": True})

# ── Memory ────────────────────────────────────────────────────────────────────────

@app.route('/memory', methods=['GET'])
def get_memory():
    return jsonify({"items": load_memory(), "location": MEMORY_PATH})

@app.route('/memory', methods=['DELETE'])
def clear_memory():
    save_memory([])
    return jsonify({"ok": True})

# ── Web automation ────────────────────────────────────────────────────────────────

def _do_automation(session_id, url, field_plan):
    """Runs in a background thread: opens Chrome, fills the form, waits."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait, Select
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        from selenium.webdriver.chrome.service import Service

        options = webdriver.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        ACTIVE_SESSIONS[session_id]['driver'] = driver
        ACTIVE_SESSIONS[session_id]['status'] = 'filling'

        driver.get(url)
        time.sleep(2)

        filled = {}
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select')

        for el in inputs:
            try:
                name  = el.get_attribute('name') or el.get_attribute('id') or el.get_attribute('placeholder') or ''
                itype = el.get_attribute('type') or 'text'
                tag   = el.tag_name.lower()
                # Find matching value from LLM plan
                match_val = None
                for key, val in field_plan.items():
                    if key.lower() in name.lower() or name.lower() in key.lower():
                        match_val = val
                        break
                if match_val:
                    if tag == 'select':
                        Select(el).select_by_visible_text(str(match_val))
                    elif itype in ('checkbox', 'radio'):
                        if str(match_val).lower() in ('true', 'yes', '1'):
                            if not el.is_selected():
                                el.click()
                    else:
                        el.clear()
                        el.send_keys(str(match_val))
                    filled[name or itype] = match_val
            except Exception:
                continue

        ACTIVE_SESSIONS[session_id]['status']  = 'awaiting_approval'
        ACTIVE_SESSIONS[session_id]['filled']  = filled
    except Exception as e:
        ACTIVE_SESSIONS[session_id]['status'] = 'error'
        ACTIVE_SESSIONS[session_id]['error']  = str(e)


@app.route('/automation/fill', methods=['POST'])
def automation_fill():
    if not has_permission('web_automation'):
        return jsonify({"permission_required": True, "capability": "web_automation",
                        "label": CAPABILITIES['web_automation']['label'],
                        "description": CAPABILITIES['web_automation']['desc'],
                        "packages": CAPABILITIES['web_automation']['packages']}), 403
    data = request.json or {}
    url  = data.get('url', '').strip()
    task = data.get('task', '').strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # Ask LLM what to fill based on owner profile + task
    prompt = (f"{build_system()}\n\n"
              f"Owner wants to fill a web form at: {url}\n"
              f"Task: {task}\n\n"
              f"Return ONLY a JSON object with field names as keys and what to fill as values. "
              f"Use only info from the owner profile above. Example: {{\"name\": \"Keith\", \"email\": \"k@example.com\"}}. "
              f"No explanation, just JSON. KJ2:")
    raw_plan = ollama_generate(prompt)
    try:
        start = raw_plan.find('{'); end = raw_plan.rfind('}') + 1
        field_plan = json.loads(raw_plan[start:end]) if start >= 0 else {}
    except Exception:
        field_plan = {}

    session_id = str(uuid.uuid4())[:8]
    ACTIVE_SESSIONS[session_id] = {
        'status': 'starting', 'url': url, 'task': task,
        'field_plan': field_plan, 'driver': None, 'filled': {}, 'error': None
    }

    threading.Thread(target=_do_automation, args=(session_id, url, field_plan), daemon=True).start()
    return jsonify({
        "session_id":  session_id,
        "url":         url,
        "field_plan":  field_plan,
        "message":     (f"Opening {url} in Chrome now. I am filling the form as we speak. "
                        f"Watch the browser window — once I am done it will be waiting for your approval. "
                        f"Type 'submit {session_id}' to send or 'cancel {session_id}' to close without submitting."),
        "automation_started": True
    })


@app.route('/automation/status/<session_id>', methods=['GET'])
def automation_status(session_id):
    sess = ACTIVE_SESSIONS.get(session_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({
        "status": sess['status'],
        "filled": sess.get('filled', {}),
        "error":  sess.get('error')
    })


@app.route('/automation/submit/<session_id>', methods=['POST'])
def automation_submit(session_id):
    sess = ACTIVE_SESSIONS.get(session_id)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    driver = sess.get('driver')
    if not driver:
        return jsonify({"error": "Browser not ready"}), 400
    try:
        from selenium.webdriver.common.by import By
        # Click the first submit button found
        btns = driver.find_elements(By.CSS_SELECTOR, 'input[type=submit], button[type=submit], button')
        for btn in btns:
            txt = btn.text.lower()
            if any(w in txt for w in ['submit', 'send', 'apply', 'register', 'continue', 'next', 'sign up', 'join', 'save']):
                btn.click()
                break
        else:
            if btns:
                btns[-1].click()
        sess['status'] = 'submitted'
        del ACTIVE_SESSIONS[session_id]
        return jsonify({"ok": True, "message": "Submitted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/automation/cancel/<session_id>', methods=['POST'])
def automation_cancel(session_id):
    sess = ACTIVE_SESSIONS.get(session_id)
    if not sess:
        return jsonify({"ok": True})
    driver = sess.get('driver')
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    del ACTIVE_SESSIONS[session_id]
    return jsonify({"ok": True, "message": "Cancelled — browser closed."})

# ── File search exceptions ────────────────────────────────────────────────────────

@app.route('/settings/file-exceptions', methods=['GET'])
def get_file_exceptions():
    cfg = load_config()
    return jsonify({"exceptions": cfg.get('file_search_exceptions', [])})

@app.route('/settings/file-exceptions', methods=['POST'])
def add_file_exception():
    folder = (request.json or {}).get('folder', '').strip()
    if not folder:
        return jsonify({"error": "No folder provided"}), 400
    cfg = load_config()
    cfg.setdefault('file_search_exceptions', []).append(folder)
    save_config(cfg)
    return jsonify({"ok": True})

# ── Start ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    name = config.get('user_name', 'there')
    print(f"\n{'='*54}")
    print(f"  KJ2 Personal AI Agent")
    print(f"  Hello {name}!")
    print(f"  CHAT | MIC | IMAGES | VIDEO | TASKS | INSTRUCTIONS")
    print(f"{'='*54}")
    print(f"  Opening at: http://localhost:5050")
    print(f"  Memory: {MEMORY_PATH}")
    print(f"{'='*54}\n")
    threading.Thread(target=lambda: (time.sleep(2), subprocess.Popen(['start', 'chrome', 'http://localhost:5050'], shell=True)),
                     daemon=True).start()
    app.run(host='0.0.0.0', port=5050, debug=False)
