import cloudscraper
import os
import time
import ffmpeg
import re
import urllib.parse
import shutil
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from tqdm import tqdm

if not shutil.which("ffmpeg"):
    raise Exception("FFmpeg não encontrado. Instale e adicione ao PATH: https://ffmpeg.org/download.html")

load_dotenv()

class PrivacyScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.scraper.cookies.clear()  # Limpa cookies persistentes
        self.scraper.headers = {}
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

        response = self.scraper.post(login_url, json=login_data)

        if response.status_code == 200:
            tokens = response.json()
            self.token_v1 = tokens.get("tokenV1")
            self.token_v2 = tokens.get("token")

            second_url = f"https://privacy.com.br/strangler/Authorize?TokenV1={self.token_v1}&TokenV2={self.token_v2}"
            response = self.scraper.get(second_url)

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

        response = self.scraper.get(profile_url, headers=headers_profile)
        if response.status_code == 200:
            profiles = response.json()
            return [profile["profileName"] for profile in profiles]
        else:
            print(f"Falha ao obter perfis: {response.status_code}")
            return []

    def get_total_media_count(self, profile_name):
        url = f"https://privacy.com.br/profile/{profile_name}/Mosaico"
        response = self.scraper.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            total_match = soup.find('a', class_='filter-button selected')
            photos_match = soup.find('a', href=f"/profile/{profile_name}/Fotos")
            videos_match = soup.find('a', href=f"/profile/{profile_name}/Videos")

            total = int(total_match.text.split()[0]) if total_match else 0
            photos = int(photos_match.text.split()[0]) if photos_match else 0
            videos = int(videos_match.text.split()[0]) if videos_match else 0

            return total, photos, videos
        return 0, 0, 0

class MediaDownloader:
    def __init__(self, scraper):
        self.scraper = scraper

    def download_file(self, url, filename, pbar=None):
        headers = {
            "Referer": "https://privacy.com.br/",
        }
        try:
            response = self.scraper.get(url, headers=headers, stream=True)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
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

    def process_m3u8(self, m3u8_url, base_path):
        m3u8_filename = os.path.join(base_path, "playlist.m3u8")
        if self.download_file(m3u8_url, m3u8_filename):
            with open(m3u8_filename, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = content.split('\n')
            modified_content = []
            key_counter = 1
            
            for line in lines:
                # Processa chaves de sessão e segmentos
                if line.startswith('#EXT-X-SESSION-KEY') or line.startswith('#EXT-X-KEY'):
                    uri_match = re.search(r'URI="([^"]+)"', line)
                    if uri_match:
                        key_url = uri_match.group(1)
                        original_key_name = os.path.basename(urllib.parse.urlparse(key_url).path)
                        new_key_name = f"key_{key_counter}.key"
                        key_path = os.path.join(base_path, new_key_name)
                        
                        if self.download_file(key_url, key_path):
                            new_line = line.replace(uri_match.group(0), f'URI="{new_key_name}"')
                            modified_content.append(new_line)
                            key_counter += 1
                elif line.strip() and not line.startswith('#'):
                    segment_url = urllib.parse.urljoin(m3u8_url, line.strip())
                    segment_filename = os.path.join(base_path, os.path.basename(segment_url))
                    if self.download_file(segment_url, segment_filename):
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
            print(f"Convertendo {input_file} para MP4...")
            
            if not os.path.exists(input_file):
                raise FileNotFoundError(f"Arquivo de entrada não encontrado: {input_file}")

            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            (
                ffmpeg
                .input(input_file, allowed_extensions='ALL')
                .output(output_file, 
                        vcodec='libx264', 
                        acodec='aac',
                        loglevel='error')
                .overwrite_output()
                .run()
            )
            
            print(f"Conversão concluída: {output_file}")
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
            print(f"Arquivos temporários removidos: {base_path}")
        except Exception as e:
            print(f"Erro ao remover arquivos temporários: {e}")

def main():
    privacy_scraper = PrivacyScraper()
    if privacy_scraper.login():
        profiles = privacy_scraper.get_profiles()
        if profiles:
            print("Perfis disponíveis:")
            for idx, profile in enumerate(profiles):
                print(f"{idx + 1} - {profile}")

            selected_idx = int(input("Selecione o número do profile desejado (0 para todos): "))
            selected_profiles = profiles if selected_idx == 0 else [profiles[selected_idx - 1]]

            media_type = input("Selecione o tipo de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos): ")

            media_downloader = MediaDownloader(privacy_scraper.scraper)
            for selected_profile_name in selected_profiles:
                print(f"Processando perfil: {selected_profile_name}")

                total, total_photos, total_videos = privacy_scraper.get_total_media_count(selected_profile_name)
                print(f"Total de mídias: {total} (Fotos: {total_photos}, Vídeos: {total_videos})")

                os.makedirs(f"./{selected_profile_name}/fotos", exist_ok=True)
                os.makedirs(f"./{selected_profile_name}/videos", exist_ok=True)

                skip = 0
                downloaded_photos = 0
                downloaded_videos = 0
                with tqdm(total=total_photos + total_videos, desc="Progresso total") as pbar:
                    while True:
                        unix_timestamp = int(time.time() * 1000)
                        third_url = f"https://privacy.com.br/Profile?handler=PartialPosts&skip={skip}&take=10&nomePerfil={selected_profile_name}&filter=mosaico&_={unix_timestamp}"
                        response = privacy_scraper.scraper.get(third_url)

                        if response.status_code == 200:
                            response_data = response.json()
                            if not response_data.get("mosaicItems"):
                                break

                            for item in response_data.get("mosaicItems", []):
                                for file in item.get("files", []):
                                    if not file["isLocked"]:
                                        file_type = file["type"]
                                        file_url = file["url"]

                                        if file_type == "image" and media_type in ["1", "3"]:
                                            filename = f"./{selected_profile_name}/fotos/{file['mediaId']}.jpg"
                                            if media_downloader.download_file(file_url, filename, pbar):
                                                downloaded_photos += 1
                                        elif file_type == "video" and media_type in ["2", "3"]:
                                            base_path = f"./{selected_profile_name}/videos/{file['mediaId']}_temp"
                                            os.makedirs(base_path, exist_ok=True)
                                            main_m3u8_filename = os.path.join(base_path, "main.m3u8")

                                            if media_downloader.download_file(file_url, main_m3u8_filename):
                                                with open(main_m3u8_filename, 'r', encoding='utf-8') as f:
                                                    main_m3u8_content = f.read()

                                                best_quality_url = media_downloader.get_best_quality_m3u8(file_url, main_m3u8_content)
                                                if best_quality_url:
                                                    best_m3u8_filename = media_downloader.process_m3u8(best_quality_url, base_path)
                                                    
                                                    if best_m3u8_filename and os.path.exists(best_m3u8_filename):
                                                        output_filename = f"./{selected_profile_name}/videos/{file['mediaId']}.mp4"
                                                        print(f"Tentando converter: {best_m3u8_filename} -> {output_filename}")
                                                        
                                                        if media_downloader.convert_m3u8_to_mp4(best_m3u8_filename, output_filename):
                                                            downloaded_videos += 1
                                                            pbar.update(1)

                                            media_downloader.clean_temp_files(base_path)
                        else:
                            print(f"Falha ao buscar mosaico: {response.status_code}")

                        skip += 10
                        if skip >= total:
                            break

                print(f"Download concluído para {selected_profile_name}. Fotos: {downloaded_photos}, Vídeos: {downloaded_videos}")
        else:
            print("Nenhum perfil encontrado.")
    else:
        print("Falha no login.")

if __name__ == "__main__":
    main()