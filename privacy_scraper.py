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
import requests

if not shutil.which("ffmpeg"):
    print("FFmpeg não encontrado. Instale e adicione ao PATH: https://ffmpeg.org/download.html")
    exit(1)

if not os.path.isfile('.env'):
    print("Erro: Arquivo .env não encontrado!")
    exit(1)

load_dotenv()

class TurnstileSolver:
    def __init__(self):
        self.api_key = os.getenv('CAPMONSTER_API_KEY')
        self.api_url = "https://api.capmonster.cloud"
    
    def is_available(self):
        return bool(self.api_key)
    
    def solve_turnstile(self, page_url="https://privacy.com.br/auth"):
        if not self.api_key:
            raise Exception("Chave CAPMONSTER_API_KEY não configurada no arquivo .env!")
        
        task_data = {
            "clientKey": self.api_key,
            "task": {
                "type": "TurnstileTask",
                "websiteURL": page_url,
                "websiteKey": "0x4AAAAAACDFv8IsPDbdsS-x"
            }
        }
        
        create_response = requests.post(f"{self.api_url}/createTask", json=task_data)
        if create_response.status_code != 200:
            raise Exception(f"Erro ao criar tarefa: {create_response.text}")
        
        task_result = create_response.json()
        if task_result.get("errorId") != 0:
            raise Exception(f"Erro na API: {task_result.get('errorDescription')}")
        
        task_id = task_result.get("taskId")
        
        print("Resolvendo captcha...", end="", flush=True)
        for _ in range(60):
            time.sleep(2)
            print(".", end="", flush=True)
            
            result_data = {
                "clientKey": self.api_key,
                "taskId": task_id
            }
            
            result_response = requests.post(f"{self.api_url}/getTaskResult", json=result_data)
            if result_response.status_code != 200:
                continue
            
            result = result_response.json()
            if result.get("errorId") != 0:
                raise Exception(f"Erro ao obter resultado: {result.get('errorDescription')}")
            
            status = result.get("status")
            if status == "ready":
                print("\nCaptcha resolvido!")
                solution = result.get("solution", {})
                return solution.get("token")
            elif status == "processing":
                continue
        
        raise Exception("Tempo esgotado ao aguardar resolução do captcha")

class PrivacyScraper:
    def __init__(self):
        self.cffi_session = cffi_requests.Session()
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token_v1 = None
        self.token_v2 = None
        self.turnstile_solver = TurnstileSolver()
    
    def login_manual(self, auth_json):
        try:
            if isinstance(auth_json, str):
                auth_data = json.loads(auth_json)
            else:
                auth_data = auth_json
            
            self.token_v1 = auth_data.get("tokenV1")
            self.token_v2 = auth_data.get("token")
            
            if not self.token_v1 or not self.token_v2:
                print("Erro: JSON de autenticação não contém tokenV1 e/ou token!")
                return False
            
            headers = {
                "authorization": f"Bearer {self.token_v2}",
                "Host": "service.privacy.com.br",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Origin": "https://privacy.com.br",
                "Referer": "https://privacy.com.br/",
            }
            
            test_url = "https://service.privacy.com.br/profile/UserFollowing?page=0&limit=1&nickName="
            response = self.cffi_session.get(test_url, headers=headers, impersonate="chrome120")
            
            if response.status_code == 200:
                print("Tokens validados com sucesso!")
                return True
            else:
                print(f"Erro ao validar tokens: Status {response.status_code}")
                return False
                
        except json.JSONDecodeError:
            print("Erro: JSON inválido!")
            return False
        except Exception as e:
            print(f"Erro no login manual: {e}")
            return False
    
    def login_auto(self):
        if not self.turnstile_solver.is_available():
            print("Erro: Para login automático, configure CAPMONSTER_API_KEY no arquivo .env")
            return False
            
        login_url = "https://service.privacy.com.br/auth/login"
        
        try:
            turnstile_token = self.turnstile_solver.solve_turnstile()
        except Exception as e:
            print(f"Erro ao resolver captcha: {e}")
            return False
        
        login_data = {
            "Email": self.email,
            "Document": None,
            "Password": self.password,
            "Locale": "pt-BR",
            "CanReceiveEmail": True,
            "TurnstileToken": turnstile_token,
            "TurnstileMode": "invisible"
        }
        
        headers = {
            'Host': 'service.privacy.com.br',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
            'Sec-GPC': '1',
            'Origin': 'https://privacy.com.br',
            'Referer': 'https://privacy.com.br/',
        }
        
        response = self.cffi_session.post(
            login_url,
            json=login_data,
            headers=headers,
            impersonate="chrome120"
        )
        
        if response.status_code == 200:
            tokens = response.json()
            self.token_v1 = tokens.get("tokenV1")
            self.token_v2 = tokens.get("token")
            
            headers_second = {
                "Host": "privacy.com.br",
                "Referer": "https://privacy.com.br/auth?route=sign-in",
            }
            second_url = f"https://privacy.com.br/strangler/Authorize?TokenV1={self.token_v1}&TokenV2={self.token_v2}"
            response = self.cffi_session.get(second_url, headers=headers_second, impersonate="chrome120")
            
            if response.status_code == 200:
                return True
        return False

    def login(self, method="auto", auth_json=None):
        if method == "manual":
            if auth_json:
                return self.login_manual(auth_json)
            else:
                print("Erro: Para login manual, forneça o JSON de autenticação.")
                return False
        else:
            return self.login_auto()

    def get_profiles(self):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return []
            
        headers_profile = {
            "authorization": f"Bearer {self.token_v2}",
        }
        profile_url = "https://service.privacy.com.br/profile/UserFollowing?page=0&limit=30&nickName="
        response = self.cffi_session.get(profile_url, headers=headers_profile, impersonate="chrome120")
        if response.status_code == 200:
            profiles = response.json()
            return [{"profileName": profile["profileName"], "nickname": profile.get("nickname", profile["profileName"])} for profile in profiles]
        return []

    def get_total_media_count(self, profile_name):
        url = f"https://privacy.com.br/profile/{profile_name}"
        response = self.cffi_session.get(url, impersonate="chrome120")
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tabs_div = soup.find('div', {'id': 'profile-tabs'})
            total_posts = 0
            total_media = 0
            
            if tabs_div:
                posts_tab = tabs_div.find('div', {'data-view': 'posts'})
                if posts_tab:
                    posts_text = posts_tab.get_text(strip=True)
                    posts_match = re.search(r'(\d+)\s+(?:Posts|Postagens)', posts_text)
                    if posts_match:
                        total_posts = int(posts_match.group(1))
                
                media_tab = tabs_div.find('div', {'data-view': 'mosaic'})
                if media_tab:
                    media_text = media_tab.get_text(strip=True)
                    media_match = re.search(r'(\d+)\s+(?:Media|Mídias)', media_text)
                    if media_match:
                        total_media = int(media_match.group(1))
            
            return total_media, total_posts, 0
        return 0, 0, 0

    def get_purchased_media(self, offset=0, limit=20):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return None
            
        url = f"https://service.privacy.com.br/timelinequeries/post/paid/{offset}/{limit}"
        headers = {
            "authorization": f"Bearer {self.token_v2}",
            "Host": "service.privacy.com.br",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        }
        response = self.cffi_session.get(url, headers=headers, impersonate="chrome120")
        if response.status_code == 200:
            return response.json()
        return None

    def get_chat_media(self, offset=0, limit=20):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return None
            
        url = f"https://service.privacy.com.br/timelinequeries/chat/purchases/{offset}/{limit}"
        headers = {
            "authorization": f"Bearer {self.token_v2}",
            "Host": "service.privacy.com.br",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        }
        response = self.cffi_session.get(url, headers=headers, impersonate="chrome120")
        if response.status_code == 200:
            return response.json()
        return None

    def get_video_token(self, file_id):
        if not self.token_v2:
            print("Erro: Não autenticado!")
            return None
            
        token_url = "https://service.privacy.com.br/media/video/token"
        data = {
            "file_id": file_id,
            "exp": 3600
        }
        headers = {
            "Host": "service.privacy.com.br",
            "Authorization": f"Bearer {self.token_v2}",
            "Content-Type": "application/json",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        }
        response = self.cffi_session.post(
            token_url,
            json=data,
            headers=headers,
            impersonate="chrome120"
        )
        if response.status_code == 200:
            return response.json()
        return None

    def strip_edits_from_image_url(self, image_url):
        try:
            if any(video_ext in image_url.lower() for video_ext in ['.mp4', '.m3u8', '/hls/', 'video']):
                return image_url
                
            match = re.search(r"https:\/\/[^\/]+\/([^\/?]+)", image_url)
            if not match:
                return image_url
                
            token = match.group(1)
            padding = '=' * ((4 - len(token) % 4) % 4)
            token_bytes = base64.urlsafe_b64decode(token + padding)
            token_json = json.loads(token_bytes)
            
            token_json['edits'] = {}
            
            cleaned_token = base64.urlsafe_b64encode(json.dumps(token_json).encode()).decode().rstrip("=")
            return image_url.replace(token, cleaned_token)
            
        except:
            return image_url

class MediaDownloader:
    def __init__(self, cffi_session, privacy_scraper):
        self.cffi_session = cffi_session
        self.privacy_scraper = privacy_scraper

    def download_file(self, url, filename, is_video=False, file_id=None, is_image=False, use_original_url=False):
        headers = {
            "Referer": "https://privacy.com.br/",
            "Origin": "https://privacy.com.br"
        }
        
        final_url = url
        if is_image and not is_video and not use_original_url:
            final_url = self.privacy_scraper.strip_edits_from_image_url(url)
        
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
                token_data = self.privacy_scraper.get_video_token(file_id)
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
        try:
            response = self.cffi_session.get(
                final_url,
                headers=headers,
                impersonate="chrome120",
            )
            if response.status_code == 200 or response.status_code == 206:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                return True
            return False
        except:
            return False

    def download_image_with_fallback(self, url, filename):
        if self.download_file(url, filename, is_image=True, use_original_url=False):
            return True
        
        if self.download_file(url, filename, is_image=True, use_original_url=True):
            return True
        
        return False

    def get_best_quality_m3u8(self, main_m3u8_url, main_m3u8_content):
        lines = main_m3u8_content.split('\n')
        best_quality_url = None
        max_bandwidth = 0
        current_bandwidth = 0
        for line in lines:
            if line.startswith('#EXT-X-STREAM-INF'):
                bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
                if bandwidth_match:
                    current_bandwidth = int(bandwidth_match.group(1))
            elif line.strip() and not line.startswith('#'):
                if current_bandwidth > max_bandwidth:
                    max_bandwidth = current_bandwidth
                    best_quality_url = urllib.parse.urljoin(main_m3u8_url, line.strip())
        return best_quality_url

    def process_m3u8(self, m3u8_url, base_path, file_id=None):
        m3u8_filename = os.path.join(base_path, "playlist.m3u8")
        if self.download_file(m3u8_url, m3u8_filename, is_video=True, file_id=file_id):
            with open(m3u8_filename, 'r', encoding='utf-8') as f:
                content = f.read()
            lines = content.split('\n')
            modified_content = []
            key_counter = 1
            for line in lines:
                if line.startswith('#EXT-X-SESSION-KEY') or line.startswith('#EXT-X-KEY'):
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        key_url = uri_match.group(1)
                        new_key_name = f"key_{key_counter}.key"
                        key_path = os.path.join(base_path, new_key_name)
                        if self.download_file(key_url, key_path, file_id=file_id):
                            new_line = line.replace(uri_match.group(0), f'URI="{new_key_name}"')
                            modified_content.append(new_line)
                            key_counter += 1
                elif line.strip() and not line.startswith('#'):
                    segment_url = urllib.parse.urljoin(m3u8_url, line.strip())
                    segment_filename = os.path.join(base_path, os.path.basename(segment_url))
                    if self.download_file(segment_url, segment_filename, file_id=file_id):
                        modified_content.append(os.path.basename(segment_filename))
                    else:
                        modified_content.append(line)
                else:
                    modified_content.append(line)
            with open(m3u8_filename, 'w', encoding='utf-8') as f:
                f.write('\n'.join(modified_content))
            return m3u8_filename
        return None

    def convert_m3u8_to_mp4(self, input_file, output_file):
        try:
            if not os.path.exists(input_file):
                return False
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            (
                ffmpeg
                .input(input_file, allowed_extensions='ALL')
                .output(output_file, 
                        vcodec='copy',
                        acodec='copy',
                        loglevel='error')
                .overwrite_output()
                .run()
            )
            return True
        except:
            return False

    def clean_temp_files(self, base_path):
        try:
            shutil.rmtree(base_path)
        except:
            pass

    def extract_file_id_from_url(self, url):
        if '/hls/' in url:
            split_result = url.split('/hls/', 1)
            return split_result[0].split('/')[-1]
        return None

    def ensure_media_id(self, media_id):
        if not media_id or media_id == "undefined":
            return str(uuid.uuid4())
        return media_id

    def download_profile_media(self, profile_name, media_type="3", pbar=None):
        total_media, _, _ = self.privacy_scraper.get_total_media_count(profile_name)
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)
        skip = 0
        downloaded_photos = 0
        downloaded_videos = 0
        if total_media == 0:
            return downloaded_photos, downloaded_videos
        
        while True:
            unix_timestamp = int(time.time() * 1000)
            third_url = f"https://privacy.com.br/Profile?handler=PartialPosts&skip={skip}&take=10&nomePerfil={profile_name}&filter=mosaico&_={unix_timestamp}"
            response = self.privacy_scraper.cffi_session.get(
                third_url,
                impersonate="chrome120"
            )
            if response.status_code == 200:
                response_data = response.json()
                if not response_data.get("mosaicItems"):
                    break
                for item in response_data.get("mosaicItems", []):
                    for file in item.get("files", []):
                        if not file["isLocked"]:
                            file_type = file["type"]
                            file_url = file["url"]
                            media_id = self.ensure_media_id(file.get("mediaId"))
                            if file_type == "image" and media_type in ["1", "3"]:
                                filename = f"./{profile_name}/fotos/{media_id}.jpg"
                                if not os.path.exists(filename):
                                    if self.download_image_with_fallback(file_url, filename):
                                        downloaded_photos += 1
                                        if pbar:
                                            pbar.update(1)
                            elif file_type == "video" and media_type in ["2", "3"]:
                                filename = f"./{profile_name}/videos/{media_id}.mp4"
                                if not os.path.exists(filename):
                                    if '.mp4' in file_url:
                                        if self.download_file(file_url, filename, is_video=True):
                                            downloaded_videos += 1
                                            if pbar:
                                                pbar.update(1)
                                    else:
                                        file_id = self.extract_file_id_from_url(file_url)
                                        base_path = f"./{profile_name}/videos/{media_id}_temp"
                                        os.makedirs(base_path, exist_ok=True)
                                        main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                        if self.download_file(file_url, main_m3u8_filename, is_video=True, file_id=file_id):
                                            with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                                main_m3u8_content = f.read()
                                            best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                            if best_quality_url:
                                                best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                                if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                    if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                        downloaded_videos += 1
                                        self.clean_temp_files(base_path)
                                        if pbar:
                                            pbar.update(1)
            skip += 10
            if skip >= total_media:
                break
        return downloaded_photos, downloaded_videos

    def download_purchased_media_for_profile(self, profile_name, media_type="3", pbar=None):
        offset = 0
        limit = 20
        downloaded_photos = 0
        downloaded_videos = 0
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)
        while True:
            media_data = self.privacy_scraper.get_purchased_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            profile_posts = [post for post in media_data["items"] if post.get("creator", {}).get("profileName") == profile_name]
            if not profile_posts:
                offset += limit
                continue
            
            for post in profile_posts:
                for media in post.get("medias", []):
                    if not media.get("isLocked", True):
                        file_type = media.get("type", "")
                        file_url = media.get("url", "")
                        media_id = self.ensure_media_id(media.get("mediaId"))
                        if file_type == "image" and media_type in ["1", "3"]:
                            filename = f"./{profile_name}/fotos/{media_id}.jpg"
                            if not os.path.exists(filename):
                                if self.download_image_with_fallback(file_url, filename):
                                    downloaded_photos += 1
                                    if pbar:
                                        pbar.update(1)
                        elif file_type == "video" and media_type in ["2", "3"]:
                            filename = f"./{profile_name}/videos/{media_id}.mp4"
                            if not os.path.exists(filename):
                                if '.mp4' in file_url:
                                    if self.download_file(file_url, filename, is_video=True):
                                        downloaded_videos += 1
                                        if pbar:
                                            pbar.update(1)
                                else:
                                    file_id = self.extract_file_id_from_url(file_url)
                                    base_path = f"./{profile_name}/videos/{media_id}_temp"
                                    os.makedirs(base_path, exist_ok=True)
                                    main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                    if self.download_file(file_url, main_m3u8_filename, is_video=True, file_id=file_id):
                                        with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                            main_m3u8_content = f.read()
                                        best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                        if best_quality_url:
                                            best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                            if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                    downloaded_videos += 1
                                    self.clean_temp_files(base_path)
                                    if pbar:
                                        pbar.update(1)
            if len(media_data["items"]) < limit:
                break
            offset += limit
        return downloaded_photos, downloaded_videos

    def download_chat_media_for_profile(self, profile_name, media_type="3", pbar=None):
        offset = 0
        limit = 20
        downloaded_photos = 0
        downloaded_videos = 0
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)
        while True:
            media_data = self.privacy_scraper.get_chat_media(offset, limit)
            if not media_data or not media_data.get("items"):
                break
            profile_chats = [chat for chat in media_data["items"] if chat.get("creator", {}).get("profileName") == profile_name]
            if not profile_chats:
                offset += limit
                continue
            
            for chat in profile_chats:
                files = []
                if "files" in chat:
                    files = chat["files"]
                elif "medias" in chat:
                    files = chat["medias"]
                for file_data in files:
                    if not file_data.get("isLocked", True):
                        file_type = file_data.get("type", "")
                        file_url = file_data.get("url", "")
                        media_id = self.ensure_media_id(file_data.get("mediaId"))
                        if file_type == "image" and media_type in ["1", "3"]:
                            filename = f"./{profile_name}/fotos/{media_id}.jpg"
                            if not os.path.exists(filename):
                                if self.download_image_with_fallback(file_url, filename):
                                    downloaded_photos += 1
                                    if pbar:
                                        pbar.update(1)
                        elif file_type == "video" and media_type in ["2", "3"]:
                            filename = f"./{profile_name}/videos/{media_id}.mp4"
                            if not os.path.exists(filename):
                                if '.mp4' in file_url:
                                    if self.download_file(file_url, filename, is_video=True):
                                        downloaded_videos += 1
                                        if pbar:
                                            pbar.update(1)
                                else:
                                    file_id = self.extract_file_id_from_url(file_url)
                                    base_path = f"./{profile_name}/videos/{media_id}_temp"
                                    os.makedirs(base_path, exist_ok=True)
                                    main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                    if self.download_file(file_url, main_m3u8_filename, is_video=True, file_id=file_id):
                                        with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                            main_m3u8_content = f.read()
                                        best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                        if best_quality_url:
                                            best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                            if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                    downloaded_videos += 1
                                    self.clean_temp_files(base_path)
                                    if pbar:
                                        pbar.update(1)
            if len(media_data["items"]) < limit:
                break
            offset += limit
        return downloaded_photos, downloaded_videos

    def count_total_items(self, profile_name, media_type, action):
        total = 0
        
        if action in ["1", "4"]:
            total_media, _, _ = self.privacy_scraper.get_total_media_count(profile_name)
            total += total_media
        
        if action in ["2", "4"]:
            offset = 0
            limit = 20
            while True:
                media_data = self.privacy_scraper.get_purchased_media(offset, limit)
                if not media_data or not media_data.get("items"):
                    break
                profile_posts = [post for post in media_data["items"] if post.get("creator", {}).get("profileName") == profile_name]
                for post in profile_posts:
                    for media in post.get("medias", []):
                        if not media.get("isLocked", True):
                            file_type = media.get("type", "")
                            if (file_type == "image" and media_type in ["1", "3"]) or (file_type == "video" and media_type in ["2", "3"]):
                                total += 1
                if len(media_data["items"]) < limit:
                    break
                offset += limit
        
        if action in ["3", "4"]:
            offset = 0
            limit = 20
            while True:
                media_data = self.privacy_scraper.get_chat_media(offset, limit)
                if not media_data or not media_data.get("items"):
                    break
                profile_chats = [chat for chat in media_data["items"] if chat.get("creator", {}).get("profileName") == profile_name]
                for chat in profile_chats:
                    files = []
                    if "files" in chat:
                        files = chat["files"]
                    elif "medias" in chat:
                        files = chat["medias"]
                    for file_data in files:
                        if not file_data.get("isLocked", True):
                            file_type = file_data.get("type", "")
                            if (file_type == "image" and media_type in ["1", "3"]) or (file_type == "video" and media_type in ["2", "3"]):
                                total += 1
                if len(media_data["items"]) < limit:
                    break
                offset += limit
        
        return total

def select_media_type():
    while True:
        media_input = input("Selecione o tipo de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos): ")
        if media_input in {'1', '2', '3'}:
            return media_input
        print("Erro: Opção inválida! Digite apenas 1, 2 ou 3")

def get_auth_json_from_user():
    print("\n=== INSTRUÇÕES PARA LOGIN MANUAL ===")
    print("1. Abra o navegador e vá para: https://privacy.com.br/auth?route=sign-in")
    print("2. Faça login normalmente (resolva o captcha manualmente)")
    print("3. Abra o DevTools (F12) e vá para a aba Network")
    print("4. Filtre por XHR/Fetch requests")
    print("5. Procure pela request 'login' (https://service.privacy.com.br/auth/login)")
    print("6. Na aba Response, copie todo o conteúdo JSON")
    print("\nCole o JSON completo abaixo:")
    
    try:
        print("(Cole tudo e pressione Enter):")
        auth_json = input()
        
        if auth_json.count('\n') == 0 and '{' in auth_json and '}' in auth_json:
            pass
        else:
            more_lines = []
            while True:
                try:
                    line = input()
                    if line.strip() == '':
                        break
                    more_lines.append(line)
                except EOFError:
                    break
            
            if more_lines:
                auth_json = auth_json + '\n' + '\n'.join(more_lines)
                
    except KeyboardInterrupt:
        print("\nOperação cancelada pelo usuário.")
        return None
    
    if not auth_json.strip():
        print("Erro: Nenhum JSON foi fornecido!")
        return None
    
    try:
        json.loads(auth_json)
        return auth_json
    except json.JSONDecodeError:
        print("Erro: O texto fornecido não é um JSON válido!")
        return None

def main():
    print("=== PRIVACY SCRAPER ===")
    print("Selecione o método de login:")
    print("1 - Login automático (com captcha via CapMonster)")
    print("2 - Login manual (inserir JSON de autenticação)")
    
    while True:
        login_method = input("\nEscolha a opção (1 ou 2): ")
        if login_method in ['1', '2']:
            break
        print("Erro: Digite 1 ou 2!")
    
    privacy_scraper = PrivacyScraper()
    login_success = False
    
    if login_method == '1':
        print("\nTentando login automático...")
        login_success = privacy_scraper.login(method="auto")
    else:
        print("\n=== MODO LOGIN MANUAL ===")
        auth_json = get_auth_json_from_user()
        if auth_json:
            login_success = privacy_scraper.login(method="manual", auth_json=auth_json)
    
    if login_success:
        print("Login realizado com sucesso!")
        profiles = privacy_scraper.get_profiles()
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
                if selected_idx == 0:
                    break
                elif 1 <= selected_idx <= len(profiles):
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
                        elif action in ["1", "2", "3", "4"]:
                            media_type = select_media_type()
                            media_downloader = MediaDownloader(privacy_scraper.cffi_session, privacy_scraper)
                            
                            print("Contando total de itens...")
                            total_items = media_downloader.count_total_items(profile_name, media_type, action)
                            
                            if total_items == 0:
                                print("Nenhuma mídia encontrada.")
                                continue
                            
                            with tqdm(total=total_items, desc=f"Download {nickname}") as pbar:
                                if action == "1":
                                    photos, videos = media_downloader.download_profile_media(profile_name, media_type, pbar)
                                    print(f"\nDownload concluído! Fotos: {photos}, Vídeos: {videos}")
                                elif action == "2":
                                    photos, videos = media_downloader.download_purchased_media_for_profile(profile_name, media_type, pbar)
                                    print(f"\nDownload de compras concluído! Fotos: {photos}, Vídeos: {videos}")
                                elif action == "3":
                                    photos, videos = media_downloader.download_chat_media_for_profile(profile_name, media_type, pbar)
                                    print(f"\nDownload do chat concluído! Fotos: {photos}, Vídeos: {videos}")
                                elif action == "4":
                                    photos1, videos1 = media_downloader.download_profile_media(profile_name, media_type, pbar)
                                    photos2, videos2 = media_downloader.download_purchased_media_for_profile(profile_name, media_type, pbar)
                                    photos3, videos3 = media_downloader.download_chat_media_for_profile(profile_name, media_type, pbar)
                                    total_photos = photos1 + photos2 + photos3
                                    total_videos = videos1 + videos2 + videos3
                                    print(f"\nDownload completo concluído! Total: Fotos: {total_photos}, Vídeos: {total_videos}")
                        else:
                            print("Opção inválida!")
                else:
                    print(f"Erro: Digite um número entre 0 e {len(profiles)}")
            except ValueError:
                print("Erro: Digite apenas números!")
    else:
        print("Falha no login.")

if __name__ == "__main__":
    main()