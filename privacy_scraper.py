import json
import os
import time
import ffmpeg
import re
import urllib.parse
import shutil
import uuid
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from tqdm import tqdm
from curl_cffi import requests as cffi_requests

if not shutil.which("ffmpeg"):
    raise Exception("FFmpeg não encontrado. Instale e adicione ao PATH: https://ffmpeg.org/download.html")

if not os.path.isfile('.env'):
    print("Erro: Arquivo .env não encontrado!")
    exit(1)

load_dotenv()

class PrivacyScraper:
    def __init__(self):
        self.cffi_session = cffi_requests.Session()
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token_v1 = None
        self.token_v2 = None

    def login(self):
        login_url = "https://service.privacy.com.br/auth/login"
        login_data = {
            "Email": self.email,
            "Document": None,
            "Password": self.password,
            "Locale": "pt-BR",
            "CanReceiveEmail": True
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
            else:
                print(f"Falha na segunda requisição: {response.status_code}")
        else:
            print(f"Falha no login: {response.status_code}")
        return False

    def get_profiles(self):
        headers_profile = {
            "authorization": f"Bearer {self.token_v2}",
        }
        profile_url = "https://service.privacy.com.br/profile/UserFollowing?page=0&limit=30&nickName="
        response = self.cffi_session.get(profile_url, headers=headers_profile, impersonate="chrome120")
        if response.status_code == 200:
            profiles = response.json()
            return [{"profileName": profile["profileName"], "nickname": profile.get("nickname", profile["profileName"])} for profile in profiles]
        else:
            print(f"Falha ao obter perfis: {response.status_code}")
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
    
        print(f"Falha ao acessar perfil: {response.status_code}")
        return 0, 0, 0

    def get_purchased_media(self, offset=0, limit=20):
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
        else:
            print(f"Falha ao buscar mídias compradas: {response.status_code}")
            return None

    def get_chat_media(self, offset=0, limit=20):
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
        else:
            print(f"Falha ao buscar mídias do chat: {response.status_code}")
            return None

    def get_video_token(self, file_id):
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

class MediaDownloader:
    def __init__(self, cffi_session, privacy_scraper):
        self.cffi_session = cffi_session
        self.privacy_scraper = privacy_scraper

    def download_file(self, url, filename, pbar=None, is_video=False, file_id=None):
        headers = {
            "Referer": "https://privacy.com.br/",
            "Origin": "https://privacy.com.br"
        }
        if is_video:
            if '.mp4' in url:
                headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Dest": "video",
                    "Range": "bytes=0-"
                })
            else:
                if '/hls/' not in url:
                    print(f"URL de vídeo inválida: {url}")
                    return False
                if not file_id:
                    file_id = self.extract_file_id_from_url(url)
                content_uri_part = url.split('/hls/', 1)[1]
                token_data = self.privacy_scraper.get_video_token(file_id)
                if not token_data:
                    print(f"Falha ao obter token para o vídeo {file_id}")
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
                url,
                headers=headers,
                impersonate="chrome120",
            )
            if response.status_code == 200 or response.status_code == 206:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                    if pbar:
                        pbar.update(1)
                return True
            else:
                print(f"Falha ao baixar {filename}: Status {response.status_code}")
                return False
        except Exception as e:
            print(f"Erro ao baixar o arquivo: {e}")
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
        start_time = time.time()
        try:
            if not os.path.exists(input_file):
                raise FileNotFoundError(f"Arquivo de entrada não encontrado: {input_file}")
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
        except ffmpeg.Error as e:
            print("Erro na conversão do vídeo:")
            print(e.stderr.decode() if e.stderr else "Erro desconhecido")
            return False
        except Exception as e:
            print(f"Erro geral na conversão: {str(e)}")
            return False

    def clean_temp_files(self, base_path):
        try:
            shutil.rmtree(base_path)
        except Exception as e:
            print(f"Erro ao remover arquivos temporários: {e}")

    def extract_file_id_from_url(self, url):
        if '/hls/' in url:
            split_result = url.split('/hls/', 1)
            return split_result[0].split('/')[-1]
        return None

    def ensure_media_id(self, media_id):
        if not media_id or media_id == "undefined":
            return str(uuid.uuid4())
        return media_id

    def download_profile_media(self, profile_name, media_type="3"):
        print(f"Processando perfil: {profile_name}")
        total_media, _, _ = self.privacy_scraper.get_total_media_count(profile_name)
        print(f"Total de mídias: {total_media}")
        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)
        skip = 0
        downloaded_photos = 0
        downloaded_videos = 0
        if total_media == 0:
            print("Nenhuma mídia encontrada para este perfil.")
            return downloaded_photos, downloaded_videos
        with tqdm(total=total_media, desc=f"Progresso {profile_name}") as pbar:
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
                                        if self.download_file(file_url, filename, pbar):
                                            downloaded_photos += 1
                                elif file_type == "video" and media_type in ["2", "3"]:
                                    filename = f"./{profile_name}/videos/{media_id}.mp4"
                                    if not os.path.exists(filename):
                                        if '.mp4' in file_url:
                                            if self.download_file(file_url, filename, pbar, is_video=True):
                                                downloaded_videos += 1
                                        else:
                                            file_id = self.extract_file_id_from_url(file_url)
                                            base_path = f"./{profile_name}/videos/{media_id}_temp"
                                            os.makedirs(base_path, exist_ok=True)
                                            main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                            if self.download_file(file_url, main_m3u8_filename, pbar, is_video=True, file_id=file_id):
                                                with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                                    main_m3u8_content = f.read()
                                                best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                                if best_quality_url:
                                                    best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                                    if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                        if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                            downloaded_videos += 1
                                                            pbar.update(1)
                                            self.clean_temp_files(base_path)
                else:
                    print(f"Falha ao buscar mosaico: {response.status_code}")
                skip += 10
                if skip >= total_media:
                    break
        return downloaded_photos, downloaded_videos

    def download_purchased_media_for_profile(self, profile_name, media_type="3"):
        print(f"Buscando mídias compradas de {profile_name}...")
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
            with tqdm(total=len(profile_posts), desc=f"Compras {profile_name}") as pbar:
                for post in profile_posts:
                    for media in post.get("medias", []):
                        if not media.get("isLocked", True):
                            file_type = media.get("type", "")
                            file_url = media.get("url", "")
                            media_id = self.ensure_media_id(media.get("mediaId"))
                            if file_type == "image" and media_type in ["1", "3"]:
                                filename = f"./{profile_name}/fotos/{media_id}.jpg"
                                if not os.path.exists(filename):
                                    if self.download_file(file_url, filename, pbar):
                                        downloaded_photos += 1
                            elif file_type == "video" and media_type in ["2", "3"]:
                                filename = f"./{profile_name}/videos/{media_id}.mp4"
                                if not os.path.exists(filename):
                                    if '.mp4' in file_url:
                                        if self.download_file(file_url, filename, pbar, is_video=True):
                                            downloaded_videos += 1
                                    else:
                                        file_id = self.extract_file_id_from_url(file_url)
                                        base_path = f"./{profile_name}/videos/{media_id}_temp"
                                        os.makedirs(base_path, exist_ok=True)
                                        main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                        if self.download_file(file_url, main_m3u8_filename, pbar, is_video=True, file_id=file_id):
                                            with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                                main_m3u8_content = f.read()
                                            best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                            if best_quality_url:
                                                best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                                if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                    if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                        downloaded_videos += 1
                                                        pbar.update(1)
                                        self.clean_temp_files(base_path)
                    pbar.update(1)
            if len(media_data["items"]) < limit:
                break
            offset += limit
        return downloaded_photos, downloaded_videos

    def download_chat_media_for_profile(self, profile_name, media_type="3"):
        print(f"Buscando mídias do chat de {profile_name}...")
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
            with tqdm(total=len(profile_chats), desc=f"Chat {profile_name}") as pbar:
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
                                    if self.download_file(file_url, filename, pbar):
                                        downloaded_photos += 1
                            elif file_type == "video" and media_type in ["2", "3"]:
                                filename = f"./{profile_name}/videos/{media_id}.mp4"
                                if not os.path.exists(filename):
                                    if '.mp4' in file_url:
                                        if self.download_file(file_url, filename, pbar, is_video=True):
                                            downloaded_videos += 1
                                    else:
                                        file_id = self.extract_file_id_from_url(file_url)
                                        base_path = f"./{profile_name}/videos/{media_id}_temp"
                                        os.makedirs(base_path, exist_ok=True)
                                        main_m3u8_filename = os.path.join(base_path, "main.m3u8")
                                        if self.download_file(file_url, main_m3u8_filename, pbar, is_video=True, file_id=file_id):
                                            with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                                main_m3u8_content = f.read()
                                            best_quality_url = self.get_best_quality_m3u8(file_url, main_m3u8_content)
                                            if best_quality_url:
                                                best_m3u8_filename = self.process_m3u8(best_quality_url, base_path, file_id)
                                                if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                    if self.convert_m3u8_to_mp4(best_m3u8_filename, filename):
                                                        downloaded_videos += 1
                                                        pbar.update(1)
                                        self.clean_temp_files(base_path)
                    pbar.update(1)
            if len(media_data["items"]) < limit:
                break
            offset += limit
        return downloaded_photos, downloaded_videos

def select_media_type():
    while True:
        media_input = input("Selecione o tipo de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos): ")
        if media_input in {'1', '2', '3'}:
            return media_input
        print("Erro: Opção inválida! Digite apenas 1, 2 ou 3")

def main():
    privacy_scraper = PrivacyScraper()
    if privacy_scraper.login():
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
                            if action == "1":
                                photos, videos = media_downloader.download_profile_media(profile_name, media_type)
                                print(f"Download concluído! Fotos: {photos}, Vídeos: {videos}")
                            elif action == "2":
                                photos, videos = media_downloader.download_purchased_media_for_profile(profile_name, media_type)
                                print(f"Download de compras concluído! Fotos: {photos}, Vídeos: {videos}")
                            elif action == "3":
                                photos, videos = media_downloader.download_chat_media_for_profile(profile_name, media_type)
                                print(f"Download do chat concluído! Fotos: {photos}, Vídeos: {videos}")
                            elif action == "4":
                                print("Iniciando download completo...")
                                photos1, videos1 = media_downloader.download_profile_media(profile_name, media_type)
                                photos2, videos2 = media_downloader.download_purchased_media_for_profile(profile_name, media_type)
                                photos3, videos3 = media_downloader.download_chat_media_for_profile(profile_name, media_type)
                                total_photos = photos1 + photos2 + photos3
                                total_videos = videos1 + videos2 + videos3
                                print(f"Download completo concluído! Total: Fotos: {total_photos}, Vídeos: {total_videos}")
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
