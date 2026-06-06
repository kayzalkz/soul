import os
import sys
import json
import time
import shutil
import threading
import subprocess
import requests
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import pyfiglet
from colorama import Fore, Style, init
import builtins

PORT = 8000
ACTIVE_DOWNLOADS = {}

# ------------------------
# Banner & Config
# ------------------------
init(autoreset=True)
RAINBOW_COLORS = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.MAGENTA, Fore.BLUE]

def banner():
    os.system("clear" if os.name != "nt" else "cls")
    ascii_banner = pyfiglet.figlet_format("SoulKingdom Termux")
    for i, line in enumerate(ascii_banner.splitlines()):
        print(RAINBOW_COLORS[i % len(RAINBOW_COLORS)] + line)
    print(Style.RESET_ALL)

def get_vps_url():
    """Stores the base URL so we can use multiple API endpoints"""
    config_file = "vps_config.txt"
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            vps_ip = f.read().strip()
            # Clean up old saved configs that included /api/scrape
            if vps_ip.endswith("/api/scrape"):
                vps_ip = vps_ip.replace("/api/scrape", "")
            return vps_ip.rstrip("/")
    
    print(Fore.CYAN + "⚙️ First Time Setup: Enter your VPS API Base URL" + Style.RESET_ALL)
    vps_ip = builtins.input("Example (http://123.45.67.89:8000): ").strip()
    if vps_ip.endswith("/api/scrape"):
        vps_ip = vps_ip.replace("/api/scrape", "")
        
    vps_ip = vps_ip.rstrip("/")
        
    with open(config_file, "w") as f:
        f.write(vps_ip)
    return vps_ip

# ------------------------
# Storage Setup (Android)
# ------------------------
def get_download_dir():
    # Saves directly to your Android's main Download folder so it shows up in file managers
    base_dir = os.path.expanduser("~/storage/shared/Download/SoulKingdom")
    if platform.system() == "Windows": # Fallback for testing on PC
        base_dir = os.path.join(os.getcwd(), "Downloads")
        
    try:
        os.makedirs(base_dir, exist_ok=True)
        return base_dir
    except PermissionError:
        print(Fore.RED + "\n❌ ERROR: Termux does not have storage permission!" + Style.RESET_ALL)
        print("Please run: " + Fore.YELLOW + "termux-setup-storage" + Style.RESET_ALL + " and restart the script.")
        sys.exit(1)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def natural_sort_key(item):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', item['name'])]

# ------------------------
# Background Downloader (Megatools on Termux)
# ------------------------
def background_mega_download(url, title, ep_name, is_tv):
    global ACTIVE_DOWNLOADS
    ACTIVE_DOWNLOADS[url] = {"active": True, "mb": 0.0, "filename": "Connecting to Mega..."}
    
    base_dir = get_download_dir()
    safe_title = sanitize_filename(title)
    folder_name = safe_title.replace(" ", "_")
    category_folder = "TV_Shows" if is_tv else "Movies"
    
    target_dir = os.path.join(base_dir, category_folder, folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    temp_dir = os.path.join(target_dir, "temp_" + str(int(time.time())))
    os.makedirs(temp_dir, exist_ok=True)
    
    def file_monitor():
        while ACTIVE_DOWNLOADS[url]["active"]:
            try:
                files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if files:
                    file_path = os.path.join(temp_dir, files[0])
                    clean_name = files[0].replace(".tmp", "")
                    ACTIVE_DOWNLOADS[url]["filename"] = clean_name
                    if os.path.exists(file_path):
                        size = os.path.getsize(file_path)
                        ACTIVE_DOWNLOADS[url]["mb"] = round(size / (1024 * 1024), 2)
            except:
                pass
            time.sleep(1)

    threading.Thread(target=file_monitor, daemon=True).start()

    try:
        print(Fore.YELLOW + f"\n[MEGATOOLS] 📥 Downloading to your phone: {category_folder}/{folder_name}" + Style.RESET_ALL)
        
        executable = "megadl.exe" if platform.system() == "Windows" else "megadl"
        process = subprocess.run([executable, '--path', temp_dir, url], capture_output=True, text=True)
        
        if process.returncode != 0:
            raise Exception(f"megadl failed: {process.stderr}")
        
        files = os.listdir(temp_dir)
        if files:
            downloaded_file = files[0]
            ext = os.path.splitext(downloaded_file)[1] 
            
            if is_tv and ep_name:
                final_filename = f"{safe_title} - {sanitize_filename(ep_name)}{ext}"
            else:
                final_filename = f"{safe_title}{ext}"
                
            final_path = os.path.join(target_dir, final_filename)
            
            if os.path.exists(final_path):
                os.remove(final_path)
                
            shutil.move(os.path.join(temp_dir, downloaded_file), final_path)
            print(Fore.GREEN + f"\n[MEGATOOLS] ✅ Saved to phone: {final_filename}" + Style.RESET_ALL)
        else:
            print(Fore.RED + "\n[MEGATOOLS] ❌ Download failed." + Style.RESET_ALL)

    except Exception as e:
        print(Fore.RED + f"\n[MEGATOOLS] ❌ Error: {e}" + Style.RESET_ALL)
    finally:
        ACTIVE_DOWNLOADS[url]["active"] = False
        ACTIVE_DOWNLOADS[url]["filename"] = "✅ Download Complete"
        try:
            shutil.rmtree(temp_dir) 
        except:
            pass

# ------------------------
# Local API Server (For Web GUI)
# ------------------------
class LocalAppHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Silence logs
        
    def do_POST(self):
        if self.path == '/api/download':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                mega_url = data.get('url')
                title = data.get('title', 'Unknown Title')
                ep_name = data.get('ep_name', '')
                is_tv = data.get('is_tv', False)

                if mega_url in ACTIVE_DOWNLOADS and ACTIVE_DOWNLOADS[mega_url]["active"]:
                    raise ValueError("Already downloading.")

                threading.Thread(target=background_mega_download, args=(mega_url, title, ep_name, is_tv), daemon=True).start()
                response = {"success": True}
            except Exception as e:
                response = {"success": False, "error": str(e)}

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_error(404)
            
    def do_GET(self):
        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(ACTIVE_DOWNLOADS).encode('utf-8'))
        else:
            super().do_GET() 

# ------------------------
# VPS API Wrappers
# ------------------------
def search_vps_catalog(vps_base_url, query):
    """Sends a search request to the VPS database"""
    if not vps_base_url.startswith("http"):
        vps_base_url = "http://" + vps_base_url
        
    search_url = f"{vps_base_url}/api/search"
    print(Fore.CYAN + f"\n🔍 Searching VPS database..." + Style.RESET_ALL)
    try:
        response = requests.post(search_url, json={"query": query}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            return data.get("results", [])
        return []
    except Exception as e:
        print(Fore.RED + f"❌ Failed to reach VPS search API: {e}" + Style.RESET_ALL)
        return []

def fetch_from_vps(vps_base_url, target_url, episodes):
    if not vps_base_url.startswith("http"):
        vps_base_url = "http://" + vps_base_url
        
    scrape_url = f"{vps_base_url}/api/scrape"
    print(Fore.CYAN + f"\n⏳ Sending request to VPS: {scrape_url}" + Style.RESET_ALL)
    print(Fore.CYAN + "Please wait while your VPS scrapes the site..." + Style.RESET_ALL)
    
    payload = {
        "url": target_url,
        "episodes": episodes
    }
    
    try:
        response = requests.post(scrape_url, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            print(Fore.RED + f"❌ VPS Error: {data.get('error')}" + Style.RESET_ALL)
            return None, None, [], False
            
        return data.get("title"), data.get("poster"), data.get("links", []), data.get("is_tv")
    except Exception as e:
        print(Fore.RED + f"❌ Failed to connect to VPS: {e}" + Style.RESET_ALL)
        return None, None, [], False

# ------------------------
# HTML Generator
# ------------------------
def generate_html(title, poster, links, filepath, is_tv):
    print(Fore.CYAN + f"💾 Generating Mobile UI..." + Style.RESET_ALL)
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - Downloads</title>
<style>
body {{ font-family: Arial; background: #f4f6f9; padding: 20px; max-width: 1000px; margin: auto; }}
.header {{ text-align: center; margin-bottom: 30px; }}
.header img {{ max-width: 200px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }}
.movie {{ display: flex; gap: 15px; background: #fff; padding: 15px; margin-bottom: 15px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); flex-wrap: wrap; align-items: center; }}
.info {{ flex: 1; width: 100%; }}
.info h3 {{ margin-top: 0; color: #0066cc; font-size: 18px; }}
.info a, .info button {{ display: inline-block; margin: 5px 5px 0 0; padding: 8px 15px; background: #e91e63; color: #fff; border-radius: 5px; text-decoration: none; border: none; cursor: pointer; font-size: 14px; font-weight: bold; }}
.info a:hover, .info button:hover {{ background: #c2185b; }}
.btn-vlc {{ background: #ff8800 !important; }}
.btn-stream {{ background: #4CAF50 !important; }}
.btn-direct {{ background: #1E88E5 !important; }}
video, iframe {{ width: 100%; max-width: 600px; border-radius: 8px; margin-top: 10px; }}

.progress-container {{ display:none; background: #e3f2fd; padding: 10px; border-radius: 5px; margin-top: 10px; border-left: 4px solid #1E88E5; }}
.progress-text {{ font-size: 13px; color: #333; font-weight: bold; margin:0; word-break: break-all; }}
</style>
</head>
<body>

<div class="header">
    {f'<img src="{poster}" alt="Poster">' if poster else ''}
    <h1>🎬 {title}</h1>
</div>
<div id="movies">
"""

    safe_title_js = title.replace("'", "\\'")
    is_tv_js = "true" if is_tv else "false"

    for item in links:
        safe_url = item["url"].replace(" ", "%20")
        ep_name_js = item['name'].replace("'", "\\'")
        
        html_content += f"""
        <div class="movie" data-url="{safe_url}">
            <div class="info">
                <h3>{item['name']}</h3>
                <button class="btn-direct" onclick="triggerDirectDownload('{safe_url}', '{safe_title_js}', '{ep_name_js}', {is_tv_js})">📥 Download to Phone</button>
                <a href="{safe_url}" target="_blank">⬇ Open Mega</a>
                <a href="vlc://{safe_url}" class="btn-vlc">🟠 VLC Play</a>
                <button class="btn-stream" onclick="toggleStream(this,'{safe_url}')">▶ Web Stream</button>
                
                <div class="progress-container">
                    <p class="progress-text">Waiting to start...</p>
                </div>
            </div>
        </div>"""

    html_content += """
</div>
<script>
setInterval(pollStatus, 1000);

async function triggerDirectDownload(url, title, ep_name, is_tv) {
    let block = document.querySelector(`.movie[data-url="${url}"]`);
    let container = block.querySelector('.progress-container');
    container.style.display = 'block';
    block.querySelector('.progress-text').innerText = "Connecting to Mega...";
    
    try {
        let response = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: url, title: title, ep_name: ep_name, is_tv: is_tv })
        });
        let result = await response.json();
        if(!result.success) {
            alert("Error: " + result.error);
            container.style.display = 'none';
        }
    } catch(e) {
        alert("Error communicating with Termux app.");
        container.style.display = 'none';
    }
}

async function pollStatus() {
    try {
        let res = await fetch("/api/status");
        let tasks = await res.json();
        
        document.querySelectorAll('.movie').forEach(block => {
            let url = block.getAttribute('data-url');
            let container = block.querySelector('.progress-container');
            let textElem = block.querySelector('.progress-text');
            
            let task = tasks[url];
            if (task) {
                container.style.display = 'block';
                if (task.active) {
                    container.style.borderColor = '#1E88E5';
                    textElem.innerText = `⏳ ${task.filename}\\nDownloaded: ${task.mb} MB`;
                } else {
                    container.style.borderColor = '#4CAF50';
                    textElem.innerText = task.filename; 
                }
            }
        });
    } catch(e) { }
}

function toggleStream(btn, url) {
    let streamDiv = btn.parentElement;
    let existingIframe = streamDiv.querySelector("iframe");
    
    if (existingIframe) {
        existingIframe.remove();
        btn.textContent = "▶ Web Stream";
    } else {
        let embedUrl = url.replace("file/", "embed/");
        let iframe = document.createElement("iframe");
        iframe.src = embedUrl;
        iframe.width = "100%";
        iframe.height = "400px";
        iframe.frameBorder = "0";
        iframe.allowFullscreen = true;
        iframe.style.marginTop = "15px";
        iframe.style.borderRadius = "8px";
        streamDiv.appendChild(iframe);
        btn.textContent = "⏹ Stop Stream";
    }
}
</script>
</body>
</html>
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

# ------------------------
# Server & App Logic
# ------------------------
def start_server_daemon():
    server = ThreadingHTTPServer(("", PORT), LocalAppHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

def open_browser(url_path):
    url = f"http://localhost:{PORT}/{url_path}"
    system_name = platform.system().lower()
    try:
        if "linux" in system_name:
            if shutil.which("termux-open"):
                subprocess.Popen(["termux-open", url])
            elif os.path.exists("/system/bin/am"):
                subprocess.Popen(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])
            else:
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif "windows" in system_name:
            os.startfile(url)
        elif "darwin" in system_name: 
            subprocess.Popen(["open", url])
        else:
            webbrowser.open(url)
    except Exception:
        print(f"Please open manually: {url}")

def main():
    banner()
    vps_url = get_vps_url()
    base_dir = get_download_dir()
    
    start_server_daemon()
    
    # Switch directory to the base download dir so the web server serves files from there
    os.chdir(base_dir)
    
    while True:
        print("\n" + "="*60)
        target_input = builtins.input(Fore.YELLOW + "🔗 Enter Movie/TV URL, ID, Name, or MM_Name (or 'q' to quit): " + Style.RESET_ALL).strip()
        
        if target_input.lower() in ['q', 'quit', 'exit']:
            sys.exit(0)

        # 1. PROCESS DATABASE SEARCH IF NOT A URL
        if not target_input.startswith("http"):
            results = search_vps_catalog(vps_url, target_input)
            
            if not results:
                print(Fore.RED + "❌ No matches found in the VPS database." + Style.RESET_ALL)
                continue
            elif len(results) == 1:
                selected_item = results[0]
            else:
                print(Fore.CYAN + f"\n🔍 Found {len(results)} matches. Please select one:" + Style.RESET_ALL)
                for i, res in enumerate(results):
                    name = res.get('name', 'Unknown')
                    mm = f" ({res.get('mm_name')})" if res.get('mm_name') else ""
                    print(f"  {i+1}. {name}{mm} [ID: {res.get('id')}]")
                    
                sel_idx = builtins.input(Fore.YELLOW + "\nEnter the number of your choice (or 'c' to cancel): " + Style.RESET_ALL).strip()
                if sel_idx.isdigit() and 1 <= int(sel_idx) <= len(results):
                    selected_item = results[int(sel_idx) - 1]
                else:
                    print("Selection cancelled.")
                    continue
            
            # Construct the final SoulKingdom URL from the selected ID
            s_type = selected_item.get("show_type", "movie").lower()
            route = "tv_show" if "tv" in s_type or "series" in s_type else "movie"
            target_url = f"https://www.soulkingdom.net/{route}/{selected_item['id']}"
            
            print(Fore.GREEN + f"✅ Selected: {selected_item.get('name')}")
            print(Fore.GREEN + f"🔗 Generated URL: {target_url}" + Style.RESET_ALL)
        else:
            target_url = target_input

        # 2. ASK FOR EPISODES IF TV SHOW
        episodes = "all"
        if "tv_show" in target_url:
            episodes = builtins.input(Fore.YELLOW + "📺 TV Show Detected! Enter episodes to fetch (e.g., '1-8', '2', or 'all'): " + Style.RESET_ALL).strip()
            if not episodes:
                episodes = "all"

        # 3. SCRAPE VIA VPS
        title, poster, new_links, is_tv = fetch_from_vps(vps_url, target_url, episodes)
        
        if not new_links:
            continue

        # 4. STRUCTURE DIRECTORIES
        safe_title = sanitize_filename(title)
        folder_name = safe_title.replace(" ", "_")
        category_folder = "TV_Shows" if is_tv else "Movies"
        
        target_dir = os.path.join(base_dir, category_folder, folder_name)
        os.makedirs(target_dir, exist_ok=True)

        json_filepath = os.path.join(target_dir, "_data.json")
        html_filename = f"{folder_name}.html"
        html_filepath = os.path.join(target_dir, html_filename)

        # 5. MERGE JSON DATA
        if os.path.exists(json_filepath):
            with open(json_filepath, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    links_dict = {item['name']: item for item in data.get("links", [])}
                except:
                    links_dict = {}
        else:
            links_dict = {}

        for link in new_links:
            links_dict[link['name']] = link

        merged_links = list(links_dict.values())
        merged_links.sort(key=natural_sort_key) 

        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump({"title": title, "poster": poster, "is_tv": is_tv, "links": merged_links}, f)

        # 6. GENERATE HTML & OPEN
        generate_html(title, poster, merged_links, html_filepath, is_tv)
        
        url_path = f"{category_folder}/{folder_name}/{html_filename}"
        print(Fore.GREEN + f"\n✅ Ready! Opening your browser..." + Style.RESET_ALL)
        
        open_browser(url_path)

if __name__ == "__main__":
    main()
