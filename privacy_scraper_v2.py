import json
import os
import time
import ffmpeg
import re
import urllib.parse
import shutil
import uuid
import base64
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from tqdm import tqdm
from curl_cffi import requests as cffi_requests

try:
    from camoufox.sync_api import Camoufox
    _CAMOUFOX_AVAILABLE = True
except ImportError:
    _CAMOUFOX_AVAILABLE = False

if not _CAMOUFOX_AVAILABLE:
    print("Erro: camoufox não instalado.")
    print("Execute: pip install camoufox && python -m camoufox fetch")
    exit(1)

if not shutil.which("ffmpeg"):
    print("FFmpeg não encontrado. Instale e adicione ao PATH: https://ffmpeg.org/download.html")
    exit(1)

if not os.path.isfile('.env'):
    print("Erro: Arquivo .env não encontrado!")
    exit(1)

load_dotenv()

TOKEN_CACHE_FILE  = "token_cache.json"
TURNSTILE_URL     = "https://privacy.com.br"
TURNSTILE_SITEKEY = "0x4AAAAAACDFv8IsPDbdsS-x"
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Turnstile</title>
    <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async></script>
</head>
<body>
    <!-- cf turnstile -->
</body>
</html>"""

_camoufox_instance = None
_camoufox_browser  = None

def get_browser():
    global _camoufox_instance, _camoufox_browser
    if _camoufox_browser is None:
        _camoufox_instance = Camoufox(headless=True)
        _camoufox_browser  = _camoufox_instance.start()
    return _camoufox_browser

def resolve_turnstile():
    turnstile_div = (
        f'<div class="cf-turnstile" data-sitekey="{TURNSTILE_SITEKEY}" '
        f'data-action="login"></div>'
    )
    page_html      = HTML_TEMPLATE.replace("<!-- cf turnstile -->", turnstile_div)
    url_with_slash = TURNSTILE_URL + "/"

    try:
        browser = get_browser()
        page    = browser.new_page()
        try:
            page.route(url_with_slash, lambda route: route.fulfill(body=page_html, status=200))
            page.goto(url_with_slash)

            token = None
            for _ in range(15):
                try:
                    value = page.input_value("[name=cf-turnstile-response]", timeout=2000)
                    if value:
                        token = value
                        break
                    page.locator("//div[@class='cf-turnstile']").click(timeout=1000)
                    time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)

            return token
        finally:
            page.close()

    except Exception as e:
        print(f"[Turnstile] Erro ao resolver: {e}")
        global _camoufox_browser, _camoufox_instance
        try:
            _camoufox_browser.close()
        except Exception:
            pass
        _camoufox_browser  = None
        _camoufox_instance = None
        return None


class PrivacyScraper:
    def __init__(self):
        self.cffi_session = cffi_requests.Session()
        self.email    = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token_v1 = None
        self.token_v2 = None

        if os.getenv('DEBUG_MODE', 'false').lower() in ['true', '1', 'yes']:
            self.cffi_session.proxies = {
                'http':  'http://localhost:8888',
                'https': 'http://localhost:8888'
            }
            self.cffi_session.verify = False

    def _load_token_cache(self):
        if not os.path.isfile(TOKEN_CACHE_FILE):
            return None
        try:
            with open(TOKEN_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if cache.get("email") != self.email:
                return None
            if time.time() >= cache.get("expires_at", 0) - 300:
                print("Cache de tokens expirado.")
                return None
            return cache
        except Exception:
            return None

    def _save_token_cache(self, token_v1, token_v2, expires_at):
        try:
            with open(TOKEN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "email":      self.email,
                    "token_v1":   token_v1,
                    "token_v2":   token_v2,
                    "expires_at": expires_at,
                }, f, indent=2)
        except Exception as e:
            print(f"[Cache] Aviso: não foi possível salvar o cache: {e}")

    def _decode_token_expiry(self, token_v2):
        try:
            payload_b64 = token_v2.split('.')[1]
            padding     = '=' * ((4 - len(payload_b64) % 4) % 4)
            payload     = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
            return payload.get("exp")
        except Exception:
            return None

    def _apply_tokens(self, token_v1, token_v2):
        self.token_v1 = token_v1
        self.token_v2 = token_v2
        r = self.cffi_session.get(
            f"https://privacy.com.br/strangler/Authorize?TokenV1={token_v1}&TokenV2={token_v2}",
            headers={"Host": "privacy.com.br", "Referer": "https://privacy.com.br/auth?route=sign-in"},
            impersonate="chrome120"
        )
        return r.status_code == 200

    def login(self):
        cache = self._load_token_cache()
        if cache:
            print("Tokens encontrados no cache, reutilizando...")
            if self._apply_tokens(cache["token_v1"], cache["token_v2"]):
                print("Login via cache realizado com sucesso!")
                return True
            print("Cache inválido, fazendo novo login...")

        print("Resolvendo captcha...", end="", flush=True)
        turnstile_token = resolve_turnstile()
        if not turnstile_token:
            print("\nErro: Falha ao resolver o captcha. Tente novamente.")
            return False
        print(" OK")

        response = self.cffi_session.post(
            "https://service.privacy.com.br/auth/login",
            json={
                "Email":           self.email,
                "Document":        None,
                "Password":        self.password,
                "Locale":          "pt-BR",
                "CanReceiveEmail": True,
                "TurnstileToken":  turnstile_token,
                "TurnstileMode":   "invisible"
            },
            headers={
                'Host':         'service.privacy.com.br',
                'Accept':       'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'User-Agent':   'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
                'Sec-GPC':      '1',
                'Origin':       'https://privacy.com.br',
                'Referer':      'https://privacy.com.br/',
            },
            impersonate="chrome120"
        )

        if response.status_code == 200:
            tokens = response.json()
            t1, t2 = tokens.get("tokenV1"), tokens.get("token")
            if self._apply_tokens(t1, t2):
                expires_at = self._decode_token_expiry(t2) or (int(time.time()) + 3600)
                self._save_token_cache(t1, t2, expires_at)
                return True

        try:
            err = response.json().get("message") or response.json().get("error") or response.text
        except Exception:
            err = response.text
        print(f"Erro no login: {err}")
        return False

    def get_profiles(self):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return []

        response = self.cffi_session.get(
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
        response    = self.cffi_session.get(f"https://privacy.com.br/profile/{profile_name}", impersonate="chrome120")
        total_posts = 0
        total_media = 0

        if response.status_code == 200:
            tabs_div = BeautifulSoup(response.text, 'html.parser').find('div', {'id': 'profile-tabs'})
            if tabs_div:
                posts_tab = tabs_div.find('div', {'data-view': 'posts'})
                if posts_tab:
                    m = re.search(r'(\d+)\s+(?:Posts|Postagens)', posts_tab.get_text(strip=True))
                    if m:
                        total_posts = int(m.group(1))
                media_tab = tabs_div.find('div', {'data-view': 'mosaic'})
                if media_tab:
                    m = re.search(r'(\d+)\s+(?:Media|Mídias)', media_tab.get_text(strip=True))
                    if m:
                        total_media = int(m.group(1))

        print(f"Total de mídias encontradas para {profile_name}: {total_media} (Posts: {total_posts})")
        return total_media, total_posts, 0

    def get_purchased_media(self, offset=0, limit=20):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return None
        response = self.cffi_session.get(
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
            print("Erro: Não autenticado!")
            return None
        response = self.cffi_session.get(
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
            print("Erro: Não autenticado!")
            return None
        response = self.cffi_session.post(
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
            token      = match.group(1)
            padding    = '=' * ((4 - len(token) % 4) % 4)
            token_json = json.loads(base64.urlsafe_b64decode(token + padding))
            token_json['edits'] = {}
            cleaned = base64.urlsafe_b64encode(json.dumps(token_json).encode()).decode().rstrip("=")
            return image_url.replace(token, cleaned)
        except Exception:
            return image_url


class MediaDownloader:
    def __init__(self, cffi_session, privacy_scraper):
        self.cffi_session    = cffi_session
        self.privacy_scraper = privacy_scraper

    def download_file(self, url, filename, is_video=False, file_id=None, is_image=False, use_original_url=False):
        headers   = {"Referer": "https://privacy.com.br/", "Origin": "https://privacy.com.br"}
        final_url = url

        if is_image and not is_video and not use_original_url:
            final_url = self.privacy_scraper.strip_edits_from_image_url(url)

        if is_video:
            if '.mp4' in final_url:
                headers.update({
                    "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Dest": "video",
                    "Range":          "bytes=0-"
                })
            else:
                if '/hls/' not in final_url:
                    return False
                if not file_id:
                    file_id = self.extract_file_id_from_url(final_url)
                content_uri_part = final_url.split('/hls/', 1)[1]
                token_data = self.privacy_scraper.get_video_token(file_id)
                if not token_data:
                    return False
                headers.update({
                    "Host":               "video.privacy.com.br",
                    "Connection":         "keep-alive",
                    "sec-ch-ua-platform": '"Windows"',
                    "User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "sec-ch-ua":          '"Brave";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
                    "x-content-uri":      urllib.parse.quote(content_uri_part),
                    "content":            token_data['content'],
                    "sec-ch-ua-mobile":   "?0",
                    "Accept":             "*/*",
                    "Sec-GPC":            "1",
                    "Accept-Language":    "pt-BR,pt;q=0.6",
                    "Origin":             "https://privacy.com.br",
                    "Sec-Fetch-Site":     "same-site",
                    "Sec-Fetch-Mode":     "cors",
                    "Sec-Fetch-Dest":     "empty",
                    "Accept-Encoding":    "gzip, deflate, br, zstd"
                })
        try:
            response = self.cffi_session.get(final_url, headers=headers, impersonate="chrome120")
            if response.status_code in (200, 206):
                with open(filename, 'wb') as f:
                    f.write(response.content)
                return True
            return False
        except Exception:
            return False

    def download_image_with_fallback(self, url, filename):
        if self.download_file(url, filename, is_image=True, use_original_url=False):
            return True
        return self.download_file(url, filename, is_image=True, use_original_url=True)

    def get_best_quality_m3u8(self, main_m3u8_url, main_m3u8_content):
        lines, best_quality_url, max_bandwidth, current_bandwidth = main_m3u8_content.split('\n'), None, 0, 0
        for line in lines:
            if line.startswith('#EXT-X-STREAM-INF'):
                m = re.search(r'BANDWIDTH=(\d+)', line)
                if m:
                    current_bandwidth = int(m.group(1))
            elif line.strip() and not line.startswith('#'):
                if current_bandwidth > max_bandwidth:
                    max_bandwidth    = current_bandwidth
                    best_quality_url = urllib.parse.urljoin(main_m3u8_url, line.strip())
        return best_quality_url

    def process_m3u8(self, m3u8_url, base_path, file_id=None):
        m3u8_filename = os.path.join(base_path, "playlist.m3u8")
        if not self.download_file(m3u8_url, m3u8_filename, is_video=True, file_id=file_id):
            return None

        with open(m3u8_filename, 'r', encoding='utf-8') as f:
            content = f.read()

        lines, modified_content, key_counter = content.split('\n'), [], 1
        for line in lines:
            if line.startswith('#EXT-X-SESSION-KEY') or line.startswith('#EXT-X-KEY'):
                uri_match = re.search(r'URI="([^"]+)"', line)
                if uri_match:
                    new_key_name = f"key_{key_counter}.key"
                    if self.download_file(uri_match.group(1), os.path.join(base_path, new_key_name), file_id=file_id):
                        modified_content.append(line.replace(uri_match.group(0), f'URI="{new_key_name}"'))
                        key_counter += 1
            elif line.strip() and not line.startswith('#'):
                segment_url      = urllib.parse.urljoin(m3u8_url, line.strip())
                segment_filename = os.path.join(base_path, os.path.basename(segment_url))
                self.download_file(segment_url, segment_filename, file_id=file_id)
                modified_content.append(os.path.basename(segment_filename))
            else:
                modified_content.append(line)

        with open(m3u8_filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(modified_content))
        return m3u8_filename

    def convert_m3u8_to_mp4(self, input_file, output_file):
        try:
            if not os.path.exists(input_file):
                return False
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            (
                ffmpeg
                .input(input_file, allowed_extensions='ALL')
                .output(output_file, vcodec='copy', acodec='copy', loglevel='error')
                .overwrite_output()
                .run()
            )
            return True
        except Exception:
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

    def _download_hls_video(self, file_url, filename, pbar=None):
        file_id   = self.extract_file_id_from_url(file_url)
        base_path = os.path.join(os.path.dirname(filename), f"{self.ensure_media_id(None)}_temp")
        os.makedirs(base_path, exist_ok=True)

        success   = False
        main_m3u8 = os.path.join(base_path, "main.m3u8")
        if self.download_file(file_url, main_m3u8, is_video=True, file_id=file_id):
            with open(main_m3u8, 'r', encoding='utf-8') as f:
                content = f.read()
            best_url = self.get_best_quality_m3u8(file_url, content)
            if best_url:
                best_m3u8 = self.process_m3u8(best_url, base_path, file_id)
                if best_m3u8 and os.path.exists(best_m3u8):
                    success = self.convert_m3u8_to_mp4(best_m3u8, filename)

        self.clean_temp_files(base_path)
        if pbar:
            pbar.update(1)
        return success

    def _process_media_list(self, files, profile_name, media_type, pbar):
        photos, videos = 0, 0
        for file_data in files:
            if file_data.get("isLocked", True):
                continue
            file_type = file_data.get("type", "")
            file_url  = file_data.get("url", "")
            media_id  = self.ensure_media_id(file_data.get("mediaId"))

            if file_type == "image" and media_type in ["1", "3"]:
                filename = f"./{profile_name}/fotos/{media_id}.jpg"
                if not os.path.exists(filename):
                    if self.download_image_with_fallback(file_url, filename):
                        photos += 1
                        if pbar:
                            pbar.update(1)

            elif file_type == "video" and media_type in ["2", "3"]:
                filename = f"./{profile_name}/videos/{media_id}.mp4"
                if not os.path.exists(filename):
                    if '.mp4' in file_url:
                        if self.download_file(file_url, filename, is_video=True):
                            videos += 1
                            if pbar:
                                pbar.update(1)
                    else:
                        if self._download_hls_video(file_url, filename, pbar):
                            videos += 1

        return photos, videos

    def download_profile_media(self, profile_name, media_type="3", pbar=None, total_media=None):
        if total_media is None:
            total_media, _, _ = self.privacy_scraper.get_total_media_count(profile_name)
        os.makedirs(f"./{profile_name}/fotos",  exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        if total_media == 0:
            return 0, 0

        skip, downloaded_photos, downloaded_videos = 0, 0, 0
        while True:
            response = self.privacy_scraper.cffi_session.get(
                f"https://privacy.com.br/Profile?handler=PartialPosts"
                f"&skip={skip}&take=10&nomePerfil={profile_name}&filter=mosaico&_={int(time.time() * 1000)}",
                impersonate="chrome120"
            )
            if response.status_code == 200:
                data = response.json()
                if not data.get("mosaicItems"):
                    break
                for item in data.get("mosaicItems", []):
                    p, v = self._process_media_list(item.get("files", []), profile_name, media_type, pbar)
                    downloaded_photos += p
                    downloaded_videos += v

            skip += 10
            if skip >= total_media:
                break

        return downloaded_photos, downloaded_videos

    def download_purchased_media_for_profile(self, profile_name, media_type="3", pbar=None):
        os.makedirs(f"./{profile_name}/fotos",  exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        offset, limit = 0, 20
        downloaded_photos, downloaded_videos = 0, 0
        while True:
            media_data = self.privacy_scraper.get_purchased_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            for post in media_data["items"]:
                if post.get("creator", {}).get("profileName") != profile_name:
                    continue
                p, v = self._process_media_list(post.get("medias", []), profile_name, media_type, pbar)
                downloaded_photos += p
                downloaded_videos += v
            if len(media_data["items"]) < limit:
                break
            offset += limit

        return downloaded_photos, downloaded_videos

    def download_chat_media_for_profile(self, profile_name, media_type="3", pbar=None):
        os.makedirs(f"./{profile_name}/fotos",  exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        offset, limit = 0, 20
        downloaded_photos, downloaded_videos = 0, 0
        while True:
            media_data = self.privacy_scraper.get_chat_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            for chat in media_data["items"]:
                if chat.get("creator", {}).get("profileName") != profile_name:
                    continue
                p, v = self._process_media_list(chat.get("files") or chat.get("medias") or [], profile_name, media_type, pbar)
                downloaded_photos += p
                downloaded_videos += v
            if len(media_data["items"]) < limit:
                break
            offset += limit

        return downloaded_photos, downloaded_videos

    def count_total_items(self, profile_name, media_type, action):
        total = 0

        if action in ["1", "4"]:
            self._cached_total_media, _, _ = self.privacy_scraper.get_total_media_count(profile_name)
            total += self._cached_total_media

        if action in ["2", "4"]:
            offset, limit = 0, 20
            while True:
                media_data = self.privacy_scraper.get_purchased_media(offset, limit)
                if not media_data or not media_data.get("items"):
                    break
                for post in media_data["items"]:
                    if post.get("creator", {}).get("profileName") != profile_name:
                        continue
                    for media in post.get("medias", []):
                        if not media.get("isLocked", True):
                            ft = media.get("type", "")
                            if (ft == "image" and media_type in ["1", "3"]) or (ft == "video" and media_type in ["2", "3"]):
                                total += 1
                if len(media_data["items"]) < limit:
                    break
                offset += limit

        if action in ["3", "4"]:
            offset, limit = 0, 20
            while True:
                media_data = self.privacy_scraper.get_chat_media(offset, limit)
                if not media_data or not media_data.get("items"):
                    break
                for chat in media_data["items"]:
                    if chat.get("creator", {}).get("profileName") != profile_name:
                        continue
                    for fd in chat.get("files") or chat.get("medias") or []:
                        if not fd.get("isLocked", True):
                            ft = fd.get("type", "")
                            if (ft == "image" and media_type in ["1", "3"]) or (ft == "video" and media_type in ["2", "3"]):
                                total += 1
                if len(media_data["items"]) < limit:
                    break
                offset += limit

        return total


def select_media_type():
    while True:
        v = input("Selecione o tipo de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos): ")
        if v in {'1', '2', '3'}:
            return v
        print("Erro: Opção inválida! Digite apenas 1, 2 ou 3")


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
        profile_name     = selected_profile['profileName']
        nickname         = selected_profile['nickname']
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

            media_type       = select_media_type()
            media_downloader = MediaDownloader(scraper.cffi_session, scraper)

            print("Contando total de itens...")
            total_items = media_downloader.count_total_items(profile_name, media_type, action)

            if total_items == 0:
                print("Nenhuma mídia encontrada.")
                continue

            with tqdm(total=total_items, desc=f"Download {nickname}") as pbar:
                if action == "1":
                    p, v = media_downloader.download_profile_media(profile_name, media_type, pbar)
                    print(f"\nDownload concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "2":
                    p, v = media_downloader.download_purchased_media_for_profile(profile_name, media_type, pbar)
                    print(f"\nDownload de compras concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "3":
                    p, v = media_downloader.download_chat_media_for_profile(profile_name, media_type, pbar)
                    print(f"\nDownload do chat concluído! Fotos: {p}, Vídeos: {v}")
                elif action == "4":
                    p1, v1 = media_downloader.download_profile_media(profile_name, media_type, pbar, total_media=getattr(media_downloader, '_cached_total_media', None))
                    p2, v2 = media_downloader.download_purchased_media_for_profile(profile_name, media_type, pbar)
                    p3, v3 = media_downloader.download_chat_media_for_profile(profile_name, media_type, pbar)
                    print(f"\nDownload completo! Fotos: {p1+p2+p3}, Vídeos: {v1+v2+v3}")


if __name__ == "__main__":
    main()