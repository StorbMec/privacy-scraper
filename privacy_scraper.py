import json
import os
import time
import re
import urllib.parse
import shutil
import uuid
import base64
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from tqdm import tqdm
from curl_cffi import requests as cffi_requests

try:
    from camoufox.sync_api import Camoufox
    _CAMOUFOX_AVAILABLE = True
except ImportError:
    _CAMOUFOX_AVAILABLE = False

RED = '\033[91m'
GREEN = '\033[92m'
RESET = '\033[0m'

if not _CAMOUFOX_AVAILABLE:
    print(f"{RED}Erro: camoufox não instalado.{RESET}")
    print(f"{RED}Execute: pip install camoufox && python -m camoufox fetch{RESET}")
    exit(1)

if not shutil.which("ffmpeg"):
    print(f"{RED}Erro: FFmpeg não instalado.{RESET}")
    print(f"{RED}Instale e adicione ao PATH: https://ffmpeg.org/download.html{RESET}")
    exit(1)

if not os.path.isfile('.env'):
    print(f"{RED}Erro: Arquivo .env não encontrado!{RESET}")
    exit(1)

load_dotenv()

TOKEN_CACHE_FILE = "token_cache.json"
TURNSTILE_URL = "https://privacy.com.br"
TURNSTILE_SITEKEY = "0x4AAAAAACDFv8IsPDbdsS-x"
TQDM_FORMAT = "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}"
TOKEN_REFRESH_MARGIN = 1800
DOWNLOAD_CHUNK_SIZE = 64 * 1024

MAX_WORKERS_MEDIA = 8
MAX_WORKERS_HLS = 16


class TurnstileResolver:
    def __init__(self):
        self._instance = None
        self._browser = None
        self.turnstile_html_url = "https://storb.lol/turnstile.html"

    def _get_browser(self):
        if self._browser is None:
            self._instance = Camoufox(headless=True)
            self._browser = self._instance.start()
        return self._browser

    def close(self):
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        self._browser = None
        self._instance = None

    def resolve(self):
        dots = 0
        animating = True

        def animate():
            nonlocal dots
            while animating:
                dots = (dots % 3) + 1
                print(f"\rResolvendo captcha{'.' * dots} ", end="", flush=True)
                time.sleep(0.2)

        anim_thread = threading.Thread(target=animate, daemon=True)
        anim_thread.start()

        def stop_anim(msg):
            nonlocal animating
            animating = False
            anim_thread.join()
            print(f"\rResolvendo captcha... {msg}")

        try:
            response = cffi_requests.get(self.turnstile_html_url, impersonate="chrome120")
            if response.status_code != 200:
                stop_anim("Falha ao baixar HTML")
                return None
            html_template = response.text
        except Exception:
            stop_anim("Falha ao baixar HTML")
            return None

        turnstile_div = f'<div class="cf-turnstile" data-sitekey="{TURNSTILE_SITEKEY}" data-action="login"></div>'
        page_html = html_template.replace("<!-- cf turnstile -->", turnstile_div)
        url_with_slash = TURNSTILE_URL + "/"

        try:
            browser = self._get_browser()
            page = browser.new_page()
            try:
                page.route(url_with_slash, lambda route: route.fulfill(body=page_html, status=200))
                page.goto(url_with_slash)

                for _ in range(15):
                    try:
                        value = page.input_value("[name=cf-turnstile-response]", timeout=2000)
                        if value:
                            stop_anim("OK")
                            return value
                        page.locator("//div[@class='cf-turnstile']").click(timeout=1000)
                    except Exception:
                        pass
                    time.sleep(0.5)

                stop_anim("Falhou")
                return None
            finally:
                page.close()
        except Exception as e:
            stop_anim("Erro")
            self.close()
            raise e


class TokenCache:
    def __init__(self, cache_file=TOKEN_CACHE_FILE):
        self.cache_file = cache_file
        self.accounts = {}

    def load(self):
        if not os.path.isfile(self.cache_file):
            return {}
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.accounts = data
                return self.accounts
        except Exception:
            return {}

    def save(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2)
        except Exception:
            pass

    def get_token(self, email):
        self.load()
        account_data = self.accounts.get("privacy")
        if not account_data:
            return None
        if account_data.get("email") != email:
            return None
        if time.time() >= account_data.get("expires_at", 0) - TOKEN_REFRESH_MARGIN:
            return None
        return account_data

    def set_token(self, email, token_v1, token_v2, expires_at):
        self.accounts["privacy"] = {
            "email": email,
            "token_v1": token_v1,
            "token_v2": token_v2,
            "expires_at": expires_at
        }
        self.save()

    def clear(self):
        self.accounts = {}
        if os.path.isfile(self.cache_file):
            os.remove(self.cache_file)


class PrivacyScraper:
    def __init__(self):
        self.session = cffi_requests.Session()
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token_v1 = None
        self.token_v2 = None
        self.token_expires_at = None
        self.cache = TokenCache()
        self.turnstile = TurnstileResolver()
        self._refresh_lock = threading.Lock()

        if os.getenv('DEBUG_MODE', 'false').lower() in ['true', '1', 'yes']:
            self.session.proxies = {
                'http': 'http://localhost:8888',
                'https': 'http://localhost:8888'
            }
            self.session.verify = False

    def _decode_token_expiry(self, token_v2):
        try:
            payload_b64 = token_v2.split('.')[1]
            padding = '=' * ((4 - len(payload_b64) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
            return payload.get("exp")
        except Exception:
            return None

    def _apply_tokens(self, token_v1, token_v2):
        self.token_v1 = token_v1
        self.token_v2 = token_v2
        response = self.session.get(
            f"https://privacy.com.br/strangler/Authorize?TokenV1={token_v1}&TokenV2={token_v2}",
            headers={"Host": "privacy.com.br", "Referer": "https://privacy.com.br/auth?route=sign-in"},
            impersonate="chrome120"
        )
        return response.status_code == 200

    def _do_login_request(self, turnstile_token):
        response = self.session.post(
            "https://service.privacy.com.br/auth/login",
            json={
                "Email": self.email,
                "Document": None,
                "Password": self.password,
                "Locale": "pt-BR",
                "CanReceiveEmail": True,
                "TurnstileToken": turnstile_token,
                "TurnstileMode": "invisible"
            },
            headers={
                'Host': 'service.privacy.com.br',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
                'Sec-GPC': '1',
                'Origin': 'https://privacy.com.br',
                'Referer': 'https://privacy.com.br/',
            },
            impersonate="chrome120"
        )
        if response.status_code == 200:
            tokens = response.json()
            t1, t2 = tokens.get("tokenV1"), tokens.get("token")
            if self._apply_tokens(t1, t2):
                expires_at = self._decode_token_expiry(t2) or (int(time.time()) + 3600)
                self.token_expires_at = expires_at
                self.cache.set_token(self.email, t1, t2, expires_at)
                return True
        return False

    def login(self):
        cached = self.cache.get_token(self.email)
        if cached:
            if self._apply_tokens(cached["token_v1"], cached["token_v2"]):
                self.token_expires_at = cached.get("expires_at")
                return True

        turnstile_token = self.turnstile.resolve()
        if not turnstile_token:
            return False

        return self._do_login_request(turnstile_token)

    def refresh_token_if_needed(self):
        if not self.token_expires_at:
            return
        if self.token_expires_at - time.time() > TOKEN_REFRESH_MARGIN:
            return

        with self._refresh_lock:
            if self.token_expires_at - time.time() > TOKEN_REFRESH_MARGIN:
                return
            tqdm.write("\nToken próximo de expirar, renovando...")
            self.cache.clear()
            turnstile_token = self.turnstile.resolve()
            if turnstile_token and self._do_login_request(turnstile_token):
                tqdm.write("Token renovado com sucesso!")
            else:
                tqdm.write(f"{RED}Falha ao renovar token!{RESET}")

    def get_profiles(self):
        if not self.token_v2:
            return []

        response = self.session.get(
            "https://service.privacy.com.br/profile/UserFollowing?page=0&limit=999&nickName=",
            headers={"authorization": f"Bearer {self.token_v2}"},
            impersonate="chrome120"
        )
        if response.status_code == 200:
            return [
                {"profileName": p["profileName"], "nickname": p.get("nickname", p["profileName"])}
                for p in response.json()
            ]
        return []

    def get_total_media_count(self, profile_name):
        response = self.session.get(f"https://privacy.com.br/profile/{profile_name}", impersonate="chrome120")
        total_posts = 0
        total_media = 0

        if response.status_code == 200:
            tabs_div = BeautifulSoup(response.text, 'html.parser').find('div', {'id': 'profile-tabs'})
            if tabs_div:
                posts_tab = tabs_div.find('div', {'data-view': 'posts'})
                if posts_tab:
                    m = re.search(r'([\d.,]+)\s+(?:Posts|Postagens)', posts_tab.get_text(strip=True))
                    if m:
                        total_posts = int(re.sub(r'[.,]', '', m.group(1)))
                media_tab = tabs_div.find('div', {'data-view': 'mosaic'})
                if media_tab:
                    m = re.search(r'([\d.,]+)\s+(?:Media|Mídias)', media_tab.get_text(strip=True))
                    if m:
                        total_media = int(re.sub(r'[.,]', '', m.group(1)))

        return total_media, total_posts

    def get_purchased_media(self, offset=0, limit=20):
        if not self.token_v2:
            return None
        response = self.session.get(
            f"https://service.privacy.com.br/timelinequeries/post/paid/{offset}/{limit}",
            headers={
                "authorization": f"Bearer {self.token_v2}",
                "Host": "service.privacy.com.br",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Origin": "https://privacy.com.br",
                "Referer": "https://privacy.com.br/",
            },
            impersonate="chrome120"
        )
        return response.json() if response.status_code == 200 else None

    def get_chat_media(self, offset=0, limit=20):
        if not self.token_v2:
            return None
        response = self.session.get(
            f"https://service.privacy.com.br/timelinequeries/chat/purchases/{offset}/{limit}",
            headers={
                "authorization": f"Bearer {self.token_v2}",
                "Host": "service.privacy.com.br",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Origin": "https://privacy.com.br",
                "Referer": "https://privacy.com.br/",
            },
            impersonate="chrome120"
        )
        return response.json() if response.status_code == 200 else None

    def get_video_token(self, file_id):
        if not self.token_v2:
            return None
        response = self.session.post(
            "https://service.privacy.com.br/media/video/token",
            json={"file_id": file_id, "exp": 3600},
            headers={
                "Host": "service.privacy.com.br",
                "Authorization": f"Bearer {self.token_v2}",
                "Content-Type": "application/json",
                "Origin": "https://privacy.com.br",
                "Referer": "https://privacy.com.br/",
            },
            impersonate="chrome120"
        )
        return response.json() if response.status_code == 200 else None

    def strip_edits_from_image_url(self, image_url):
        try:
            if any(v in image_url.lower() for v in ['.mp4', '.m3u8', '/hls/', 'video']):
                return image_url
            match = re.search(r"https:\/\/[^\/]+\/([^\/?]+)", image_url)
            if not match:
                return image_url
            token = match.group(1)
            padding = '=' * ((4 - len(token) % 4) % 4)
            token_json = json.loads(base64.urlsafe_b64decode(token + padding))
            token_json['edits'] = {}
            cleaned = base64.urlsafe_b64encode(json.dumps(token_json).encode()).decode().rstrip("=")
            return image_url.replace(token, cleaned)
        except Exception:
            return image_url


class MediaDownloader:
    def __init__(self, session, scraper, max_workers_media=MAX_WORKERS_MEDIA, max_workers_hls=MAX_WORKERS_HLS):
        self.session = session
        self.scraper = scraper
        self.max_workers_media = max_workers_media
        self.max_workers_hls = max_workers_hls
        self._pbar_lock = threading.Lock()

    def download_file(self, url, filename, is_video=False, file_id=None, is_image=False, use_original_url=False):
        self.scraper.refresh_token_if_needed()
        headers = {"Referer": "https://privacy.com.br/", "Origin": "https://privacy.com.br"}
        final_url = url

        if is_image and not is_video and not use_original_url:
            final_url = self.scraper.strip_edits_from_image_url(url)

        if is_video:
            if '.mp4' in final_url:
                headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Dest": "video",
                    "Range": "bytes=0-"
                })
            else:
                if '/hls/' not in final_url:
                    return False
                if not file_id:
                    file_id = self.extract_file_id_from_url(final_url)
                content_uri_part = final_url.split('/hls/', 1)[1]
                token_data = self.scraper.get_video_token(file_id)
                if not token_data:
                    return False
                headers.update({
                    "Host": "video.privacy.com.br",
                    "Connection": "keep-alive",
                    "sec-ch-ua-platform": '"Windows"',
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "sec-ch-ua": '"Brave";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
                    "x-content-uri": urllib.parse.quote(content_uri_part),
                    "content": token_data['content'],
                    "sec-ch-ua-mobile": "?0",
                    "Accept": "*/*",
                    "Sec-GPC": "1",
                    "Accept-Language": "pt-BR,pt;q=0.6",
                    "Origin": "https://privacy.com.br",
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                    "Accept-Encoding": "gzip, deflate, br, zstd"
                })

        target_dir = os.path.dirname(os.path.abspath(filename))
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

        try:
            response = self.session.get(final_url, headers=headers, impersonate="chrome120", stream=True)
            if response.status_code in (200, 206):
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except Exception:
            try:
                response = self.session.get(final_url, headers=headers, impersonate="chrome120")
                if response.status_code in (200, 206):
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    return True
            except Exception:
                pass
            return False

    def download_image_with_fallback(self, url, filename):
        if self.download_file(url, filename, is_image=True, use_original_url=False):
            return True
        return self.download_file(url, filename, is_image=True, use_original_url=True)

    def get_best_quality_m3u8(self, main_m3u8_url, main_m3u8_content):
        best_quality_url, max_bandwidth, current_bandwidth = None, 0, 0
        for line in main_m3u8_content.split('\n'):
            if line.startswith('#EXT-X-STREAM-INF'):
                m = re.search(r'BANDWIDTH=(\d+)', line)
                if m:
                    current_bandwidth = int(m.group(1))
            elif line.strip() and not line.startswith('#'):
                if current_bandwidth > max_bandwidth:
                    max_bandwidth = current_bandwidth
                    best_quality_url = urllib.parse.urljoin(main_m3u8_url, line.strip())
        return best_quality_url

    def process_m3u8(self, m3u8_url, base_path, file_id=None):
        m3u8_filename = os.path.join(base_path, "playlist.m3u8")
        if not self.download_file(m3u8_url, m3u8_filename, is_video=True, file_id=file_id):
            return None

        with open(m3u8_filename, 'r', encoding='utf-8') as f:
            content = f.read()

        modified_content = []
        key_tasks = []
        segment_tasks = []
        key_counter = 1

        for line in content.split('\n'):
            if line.startswith('#EXT-X-SESSION-KEY') or line.startswith('#EXT-X-KEY'):
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    new_key_name = f"key_{key_counter}.key"
                    key_counter += 1
                    key_tasks.append((uri_match.group(1), os.path.join(base_path, new_key_name)))
                    modified_content.append(line.replace(uri_match.group(0), f'URI="{new_key_name}"'))
                else:
                    modified_content.append(line)
            elif line.strip() and not line.startswith('#'):
                segment_url = urllib.parse.urljoin(m3u8_url, line.strip())
                segment_filename = os.path.join(base_path, os.path.basename(segment_url))
                segment_tasks.append((segment_url, segment_filename))
                modified_content.append(os.path.basename(segment_filename))
            else:
                modified_content.append(line)

        for key_url, key_path in key_tasks:
            self.download_file(key_url, key_path, file_id=file_id)

        if segment_tasks:
            with ThreadPoolExecutor(max_workers=self.max_workers_hls) as pool:
                futures = [
                    pool.submit(self.download_file, url, path, is_video=False, file_id=file_id)
                    for url, path in segment_tasks
                ]
                for _ in as_completed(futures):
                    pass

        with open(m3u8_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(modified_content))
        return m3u8_filename

    def convert_m3u8_to_mp4(self, input_file, output_file):
        try:
            if not os.path.exists(input_file):
                return False
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            result = subprocess.run(
                ["ffmpeg", "-allowed_extensions", "ALL", "-i", input_file,
                "-c:v", "copy", "-c:a", "copy", "-y", output_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return result.returncode == 0
        except Exception as e:
            tqdm.write(f"\nErro na conversão: {e}")
            return False

    def clean_temp_files(self, base_path):
        try:
            shutil.rmtree(base_path)
        except Exception:
            pass

    def extract_file_id_from_url(self, url):
        if '/hls/' in url:
            return url.split('/hls/', 1)[0].split('/')[-1]
        return None

    def ensure_media_id(self, media_id):
        if not media_id or media_id == "undefined":
            return str(uuid.uuid4())
        return media_id

    def _download_hls_video(self, file_url, filename):
        file_id = self.extract_file_id_from_url(file_url)
        base_path = os.path.join(os.path.dirname(filename), f"{uuid.uuid4()}_temp")
        os.makedirs(base_path, exist_ok=True)

        try:
            main_m3u8 = os.path.join(base_path, "main.m3u8")
            if not self.download_file(file_url, main_m3u8, is_video=True, file_id=file_id):
                return False
            with open(main_m3u8, 'r', encoding='utf-8') as f:
                content = f.read()
            best_url = self.get_best_quality_m3u8(file_url, content)
            if not best_url:
                return False
            best_m3u8 = self.process_m3u8(best_url, base_path, file_id)
            if best_m3u8 and os.path.exists(best_m3u8):
                return self.convert_m3u8_to_mp4(best_m3u8, filename)
            return False
        finally:
            self.clean_temp_files(base_path)

    def _download_single_media(self, file_data, profile_name, media_type):
        if file_data.get("isLocked", True):
            return (None, False)
        file_type = file_data.get("type", "")
        file_url = file_data.get("url", "")
        media_id = self.ensure_media_id(file_data.get("mediaId"))

        if file_type == "image" and media_type in ["1", "3"]:
            filename = f"./{profile_name}/fotos/{media_id}.jpg"
            if os.path.exists(filename):
                return ("photo", False)
            ok = self.download_image_with_fallback(file_url, filename)
            return ("photo", ok)

        if file_type == "video" and media_type in ["2", "3"]:
            filename = f"./{profile_name}/videos/{media_id}.mp4"
            if os.path.exists(filename):
                return ("video", False)
            if '.mp4' in file_url:
                ok = self.download_file(file_url, filename, is_video=True)
            else:
                ok = self._download_hls_video(file_url, filename)
            return ("video", ok)

        return (None, False)

    def _collect_eligible(self, files, media_type):
        for f in files:
            if f.get("isLocked", True):
                continue
            ft = f.get("type", "")
            if ft == "image" and media_type in ["1", "3"]:
                yield f
            elif ft == "video" and media_type in ["2", "3"]:
                yield f

    def _discover(self, iterator, discover_label):
        items = []
        with tqdm(
            total=0,
            desc=discover_label,
            bar_format="{desc}: {n} encontradas",
            leave=False,
        ) as d:
            for it in iterator:
                items.append(it)
                d.update(1)
        return items

    def _drain(self, iterator, profile_name, media_type, pbar, discover_label):
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        items = self._discover(iterator, discover_label)
        if not items:
            return 0, 0

        if pbar is not None:
            with self._pbar_lock:
                pbar.total = (pbar.total or 0) + len(items)
                pbar.refresh()

        counters = {"photos": 0, "videos": 0}
        counter_lock = threading.Lock()

        def task(item):
            try:
                return self._download_single_media(item, profile_name, media_type)
            except Exception as e:
                tqdm.write(f"{RED}Erro no download: {e}{RESET}")
                return (None, False)

        with ThreadPoolExecutor(max_workers=self.max_workers_media) as pool:
            futures = [pool.submit(task, it) for it in items]
            for f in as_completed(futures):
                kind, ok = f.result()
                if pbar is not None:
                    with self._pbar_lock:
                        pbar.update(1)
                if ok and kind in ("photo", "video"):
                    with counter_lock:
                        counters[f"{kind}s"] += 1

        return counters["photos"], counters["videos"]

    def _iter_profile_media(self, profile_name, media_type, total_media):
        skip = 0
        while skip < total_media:
            self.scraper.refresh_token_if_needed()
            response = self.scraper.session.get(
                f"https://privacy.com.br/Profile?handler=PartialPosts"
                f"&skip={skip}&take=10&nomePerfil={profile_name}&filter=mosaico&_={int(time.time() * 1000)}",
                impersonate="chrome120"
            )
            if response.status_code != 200:
                break
            data = response.json()
            if not data.get("mosaicItems"):
                break
            for item in data.get("mosaicItems", []):
                yield from self._collect_eligible(item.get("files", []), media_type)
            skip += 10

    def _iter_purchased_media(self, profile_name, media_type):
        offset, limit = 0, 20
        while True:
            self.scraper.refresh_token_if_needed()
            media_data = self.scraper.get_purchased_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            for post in media_data["items"]:
                if post.get("creator", {}).get("profileName") != profile_name:
                    continue
                yield from self._collect_eligible(post.get("medias", []), media_type)
            if len(media_data["items"]) < limit:
                break
            offset += limit

    def _iter_chat_media(self, profile_name, media_type):
        offset, limit = 0, 20
        while True:
            self.scraper.refresh_token_if_needed()
            media_data = self.scraper.get_chat_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            for chat in media_data["items"]:
                if chat.get("creator", {}).get("profileName") != profile_name:
                    continue
                files = chat.get("files") or chat.get("medias") or []
                yield from self._collect_eligible(files, media_type)
            if len(media_data["items"]) < limit:
                break
            offset += limit

    def download_profile_media(self, profile_name, media_type="3", pbar=None):
        total_media, _ = self.scraper.get_total_media_count(profile_name)
        if total_media == 0:
            return 0, 0
        return self._drain(
            self._iter_profile_media(profile_name, media_type, total_media),
            profile_name, media_type, pbar, "Descobrindo mídias do perfil"
        )

    def download_purchased_media_for_profile(self, profile_name, media_type="3", pbar=None):
        return self._drain(
            self._iter_purchased_media(profile_name, media_type),
            profile_name, media_type, pbar, "Descobrindo mídias compradas"
        )

    def download_chat_media_for_profile(self, profile_name, media_type="3", pbar=None):
        return self._drain(
            self._iter_chat_media(profile_name, media_type),
            profile_name, media_type, pbar, "Descobrindo mídias do chat"
        )

    def download_all(self, profile_name, media_type="3", pbar=None):
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        total_media, _ = self.scraper.get_total_media_count(profile_name)
        items = []
        if total_media > 0:
            items += self._discover(
                self._iter_profile_media(profile_name, media_type, total_media),
                "Descobrindo mídias do perfil",
            )
        items += self._discover(
            self._iter_purchased_media(profile_name, media_type),
            "Descobrindo mídias compradas",
        )
        items += self._discover(
            self._iter_chat_media(profile_name, media_type),
            "Descobrindo mídias do chat",
        )

        if not items:
            return 0, 0

        if pbar is not None:
            with self._pbar_lock:
                pbar.total = (pbar.total or 0) + len(items)
                pbar.refresh()

        counters = {"photos": 0, "videos": 0}
        counter_lock = threading.Lock()

        def task(item):
            try:
                return self._download_single_media(item, profile_name, media_type)
            except Exception as e:
                tqdm.write(f"{RED}Erro no download: {e}{RESET}")
                return (None, False)

        with ThreadPoolExecutor(max_workers=self.max_workers_media) as pool:
            futures = [pool.submit(task, it) for it in items]
            for f in as_completed(futures):
                kind, ok = f.result()
                if pbar is not None:
                    with self._pbar_lock:
                        pbar.update(1)
                if ok and kind in ("photo", "video"):
                    with counter_lock:
                        counters[f"{kind}s"] += 1

        return counters["photos"], counters["videos"]


def select_media_type():
    while True:
        v = input("Selecione o tipo de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos): ")
        if v in {'1', '2', '3'}:
            return v
        print("Erro: Opção inválida! Digite apenas 1, 2 ou 3")


def ask_int(prompt, default, min_value=1, max_value=64):
    while True:
        raw = input(f"{prompt} [padrão {default}]: ").strip()
        if not raw:
            return default
        try:
            n = int(raw)
        except ValueError:
            print(f"Erro: digite um número entre {min_value} e {max_value}")
            continue
        if not (min_value <= n <= max_value):
            print(f"Erro: valor fora do intervalo ({min_value}-{max_value})")
            continue
        return n


def main():
    scraper = PrivacyScraper()

    if not scraper.login():
        print("Falha no login.")
        return

    print("Login realizado com sucesso!")
    profiles = scraper.get_profiles()
    if not profiles:
        print("Nenhum perfil encontrado.")
        return

    last_workers_media = MAX_WORKERS_MEDIA
    last_workers_hls = MAX_WORKERS_HLS

    while True:
        print("\n=== PERFIS DISPONÍVEIS ===")
        for idx, profile in enumerate(profiles):
            print(f"{idx + 1} - {profile['nickname']} (@{profile['profileName']})")
        print("0 - Sair")

        try:
            selected_idx = int(input("\nSelecione o número do perfil: "))
        except ValueError:
            print("Erro: Digite apenas números!")
            continue

        if selected_idx == 0:
            break
        if not (1 <= selected_idx <= len(profiles)):
            print(f"Erro: Digite um número entre 0 e {len(profiles)}")
            continue

        selected_profile = profiles[selected_idx - 1]
        profile_name = selected_profile['profileName']
        nickname = selected_profile['nickname']
        print(f"\nPerfil selecionado: {nickname} (@{profile_name})")

        while True:
            print(f"\n=== MENU - {nickname} ===")
            print("1 - Baixar mídias do perfil")
            print("2 - Baixar mídias compradas")
            print("3 - Baixar mídias do chat")
            print("4 - Baixar tudo")
            print("0 - Voltar para seleção de perfil")
            action = input("Selecione uma ação: ")

            if action == "0":
                break
            if action not in ["1", "2", "3", "4"]:
                print("Opção inválida!")
                continue

            media_type = select_media_type()

            workers_media = ask_int(
                "Threads para downloads de mídia em paralelo?",
                last_workers_media, 1, 64
            )
            workers_hls = ask_int(
                "Threads para segmentos HLS (dentro de cada vídeo HLS)?",
                last_workers_hls, 1, 64
            )
            last_workers_media, last_workers_hls = workers_media, workers_hls
            print(f"{GREEN}Usando {workers_media} threads p/ mídia, {workers_hls} threads p/ HLS.{RESET}")

            downloader = MediaDownloader(scraper.session, scraper, workers_media, workers_hls)

            with tqdm(total=0, desc=f"Download {nickname}", bar_format=TQDM_FORMAT) as pbar:
                if action == "1":
                    p, v = downloader.download_profile_media(profile_name, media_type, pbar)
                    tqdm.write(f"Download concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "2":
                    p, v = downloader.download_purchased_media_for_profile(profile_name, media_type, pbar)
                    tqdm.write(f"Download de compras concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "3":
                    p, v = downloader.download_chat_media_for_profile(profile_name, media_type, pbar)
                    tqdm.write(f"Download do chat concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "4":
                    p, v = downloader.download_all(profile_name, media_type, pbar)
                    tqdm.write(f"Download completo! Fotos: {p}, Vídeos: {v}")

    scraper.turnstile.close()


if __name__ == "__main__":
    main()
