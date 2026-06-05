import asyncio
import json
import re
import builtins
import threading
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000

def parse_episodes(ep_input):
    """Parses user input like '1-8, 10' into a set of requested numbers"""
    ep_input = str(ep_input).strip()
    if ep_input.lower() == 'all' or not ep_input:
        return 'all'
    
    selected = set()
    for part in ep_input.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                selected.update(range(int(start), int(end) + 1))
            except:
                pass
        elif part.isdigit():
            selected.add(int(part))
    return selected

async def scrape_api(url, episodes_to_fetch='all'):
    results = []
    title = "Unknown Title"
    poster = ""
    is_tv = "tv_show" in url

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()

        print(f"[API] ⏳ Scraping: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3000)

        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        next_data_script = soup.find("script", id="__NEXT_DATA__")
        
        if next_data_script:
            try:
                next_json = json.loads(next_data_script.string)
                page_props = next_json.get("props", {}).get("pageProps", {})
                data = page_props.get("data", {})
                
                title = data.get("name", title)
                poster = data.get("cover_path", "")
                
                if not is_tv and "link" in page_props:
                    drive_url = page_props["link"].get("drive_url")
                    if drive_url and "mega.nz" in drive_url:
                        results.append({"name": "Full Movie", "url": drive_url})
                        await browser.close()
                        return title, poster, results, is_tv
            except Exception as e:
                print(f"[API] Error parsing JSON: {e}")

        if is_tv:
            try:
                await page.wait_for_selector(".download-grid", timeout=10000)
            except:
                pass

            buttons = await page.locator(".download-grid button").all()
            if buttons:
                selected_episodes = parse_episodes(episodes_to_fetch)
                
                for btn in buttons:
                    raw_text = await btn.text_content()
                    ep_text = raw_text.strip() if raw_text else "Unknown"
                    
                    ep_num = None
                    numbers = re.findall(r'\d+', ep_text)
                    if numbers:
                        ep_num = int(numbers[0])

                    if selected_episodes != 'all':
                        if ep_num is None or ep_num not in selected_episodes:
                            continue

                    ep_name = f"Episode {ep_text}" if ep_text.isdigit() else ep_text

                    try:
                        await page.wait_for_timeout(500)
                        async with context.expect_page(timeout=20000) as new_page_info:
                            await btn.scroll_into_view_if_needed()
                            await btn.click(force=True)
                        
                        new_page = await new_page_info.value
                        
                        try:
                            await new_page.wait_for_url("**/*mega.nz*", timeout=15000)
                        except:
                            await new_page.wait_for_load_state("domcontentloaded")

                        if "mega.nz" in new_page.url:
                            results.append({"name": ep_name, "url": new_page.url})
                        
                        await new_page.close()
                    except:
                        pass # Skip failed episodes silently

        await browser.close()
    return title, poster, results, is_tv

# --- API Server Handler ---
class APIHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Silence terminal logs
        
    def do_POST(self):
        if self.path == '/api/scrape':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                # 1. Read JSON from Android app
                req = json.loads(post_data.decode('utf-8'))
                url = req.get('url')
                episodes = req.get('episodes', 'all')

                if not url:
                    raise ValueError("URL is required")

                # 2. Run Playwright Scraper
                title, poster, links, is_tv = asyncio.run(scrape_api(url, episodes))

                # 3. Format Response
                response = {
                    "success": True,
                    "title": title,
                    "poster": poster,
                    "is_tv": is_tv,
                    "links": links
                }
            except Exception as e:
                response = {"success": False, "error": str(e)}

            # 4. Send JSON back to Android app
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_error(404)

if __name__ == "__main__":
    server = ThreadingHTTPServer(("", PORT), APIHandler)
    print(f"🚀 VPS Headless API Server running on port {PORT}...")
    server.serve_forever()
