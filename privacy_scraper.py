import json
import os
import time
import ffmpeg
import re
import urllib.parse
import shutil
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from tqdm import tqdm
from curl_cffi import requests as cffi_requests

# ──────────────────────────────────────────────────────────────
# Pré‑requisitos
# ──────────────────────────────────────────────────────────────
if not shutil.which("ffmpeg"):
    raise Exception("FFmpeg não encontrado. Instale e adicione ao PATH: https://ffmpeg.org/download.html")

if not os.path.isfile('.env'):
    print("Erro: Arquivo .env não encontrado!")
    exit(1)

load_dotenv()

# ──────────────────────────────────────────────────────────────
# Converte URL da chave .key no manifesto .m3u8
# ──────────────────────────────────────────────────────────────

def key_to_m3u8(url_key: str) -> str:
    """Converte a URL da chave AES (.key) no manifesto HLS (.m3u8).

    Espera formato:
      https://keyaes.privacy.com.br/keys/{profile}/{file_id}/{timestamp}/keyaes.key
    → https://video.privacy.com.br/hls/{profile}/{file_id}/{timestamp}/main.m3u8
    """
    parts = urllib.parse.urlparse(url_key)
    path_parts = parts.path.split("/")
    # Verifica se segue o padrão esperado /keys/<profile>/<file_id>/<ts>/keyaes.key
    if len(path_parts) >= 5 and path_parts[1] == "keys":
        profile, file_id, ts = path_parts[2:5]
        return f"https://video.privacy.com.br/hls/{profile}/{file_id}/{ts}/main.m3u8"
    # Caso o formato seja diferente, devolve inalterado
    return url_key

# ──────────────────────────────────────────────────────────────
# 1.  Scraper de login / navegação
# ──────────────────────────────────────────────────────────────
class PrivacyScraper:
    """Centraliza autenticação e chamadas à API do privacy.com.br."""

    def __init__(self):
        self.cffi_session = cffi_requests.Session()
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token_v1: str | None = None
        self.token_v2: str | None = None

    # ─────────────── login ───────────────
    def login(self) -> bool:
        login_url = "https://service.privacy.com.br/auth/login"
        payload = {
            "Email": self.email,
            "Password": self.password,
            "Locale": "pt-BR",
            "CanReceiveEmail": True,
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        }

        resp = self.cffi_session.post(login_url, json=payload, headers=headers, impersonate="chrome120")
        if resp.status_code != 200:
            print(f"Falha no login: {resp.status_code}")
            return False

        tokens = resp.json()
        self.token_v1 = tokens.get("tokenV1")
        self.token_v2 = tokens.get("token")

        second_url = (
            "https://privacy.com.br/strangler/Authorize"
            f"?TokenV1={self.token_v1}&TokenV2={self.token_v2}"
        )
        second_headers = {
            "Host": "privacy.com.br",
            "Referer": "https://privacy.com.br/auth?route=sign-in",
        }
        second = self.cffi_session.get(second_url, headers=second_headers, impersonate="chrome120")
        if second.status_code == 200:
            return True
        print(f"Falha na segunda requisição: {second.status_code}")
        return False
    
    # ─────────────── listagem de perfis ───────────────
    def get_profiles(self) -> list[str]:
        headers = {"authorization": f"Bearer {self.token_v2}"}
        url = "https://service.privacy.com.br/profile/UserFollowing?page=0&limit=30&nickName="
        resp = self.cffi_session.get(url, headers=headers, impersonate="chrome120")
        if resp.status_code != 200:
            print(f"Falha ao obter perfis: {resp.status_code}")
            return []
        data = resp.json()
        return [p["profileName"] for p in data]

    # ─────────────── contagem de mídias ───────────────
    def get_total_media_count(self, profile_name: str) -> tuple[int, int, int]:
        url = f"https://privacy.com.br/profile/{profile_name}"
        resp = self.cffi_session.get(url, impersonate="chrome120")
        if resp.status_code != 200:
            return 0, 0, 0
        soup = BeautifulSoup(resp.text, "html.parser")
        counts = {"total": 0, "photos": 0, "videos": 0}
        for a in soup.find_all("a", {"data-filter": True}):
            txt = a.get_text(strip=True)
            m = re.search(r"([\d,.]+)", txt)
            n = int(m.group(1).replace(".", "").replace(",", "")) if m else 0
            fld = a["data-filter"]
            if fld == "mosaico":
                counts["total"] = n
            elif fld == "fotos":
                counts["photos"] = n
            elif fld == "videos":
                counts["videos"] = n
        return counts["total"], counts["photos"], counts["videos"]

    # ─────────────── listagem completa de posts ───────────────
    def fetch_all_posts(self, profile_name: str, page_size: int = 10) -> list[dict]:
        """Retorna todas as entradas de 'mosaicItems' de um perfil."""
        posts: list[dict] = []
        skip = 0
        while True:
            ts = int(time.time() * 1000)
            url = (
                "https://privacy.com.br/Profile?handler=PartialPosts"
                f"&skip={skip}&take={page_size}&nomePerfil={profile_name}"
                f"&filter=mosaico&_={ts}"
            )
            r = self.cffi_session.get(url, impersonate="chrome120")
            if r.status_code != 200:
                break
            batch = r.json().get("mosaicItems", [])
            if not batch:
                break
            posts.extend(batch)
            skip += page_size
        return posts

    # ─────────────── token de vídeo ───────────────
    def get_video_token(self, file_id: str):
        token_url = "https://service.privacy.com.br/media/video/token"
        data = {"file_id": file_id, "exp": 3600}
        hdrs = {
            "Host": "service.privacy.com.br",
            "Authorization": f"Bearer {self.token_v2}",
            "Content-Type": "application/json",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        }
        r = self.cffi_session.post(token_url, json=data, headers=hdrs, impersonate="chrome120")
        return r.json() if r.status_code == 200 else None


# ──────────────────────────────────────────────────────────────
# 2.  Downloader (fotos / vídeos)
# ──────────────────────────────────────────────────────────────
class MediaDownloader:
    def __init__(self, cffi_session, privacy_scraper: PrivacyScraper):
        self.cffi_session = cffi_session
        self.scraper = privacy_scraper

    # ─────────────── download bruto ───────────────
    def download_file(self, url: str, filename: str, pbar: tqdm | None = None, is_video: bool = False) -> bool:
        headers = {
            "Referer": "https://privacy.com.br/",
            "Origin": "https://privacy.com.br",
        }
        if is_video and ".mp4" not in url:
            # é HLS – precisa token
            if "/hls/" not in url:
                print(f"URL de vídeo inválida: {url}")
                return False
            file_id = url.split("/hls/")[0].split("/")[-1]
            part = url.split("/hls/", 1)[1]
            token = self.scraper.get_video_token(file_id)
            if not token:
                print(f"Falha ao obter token para o vídeo {file_id}")
                return False
            headers.update(
                {
                    "Host": "video.privacy.com.br",
                    "x-content-uri": urllib.parse.quote(part),
                    "content": token["content"],
                    "User-Agent": "Mozilla/5.0",
                }
            )
        try:
            r = self.cffi_session.get(url, headers=headers, impersonate="chrome120")
            if r.status_code not in (200, 206):
                print(f"Falha ao baixar {filename}: {r.status_code}")
                return False
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "wb") as f:
                f.write(r.content)
            if pbar:
                pbar.update(1)
            return True
        except Exception as e:
            print(f"Erro ao baixar {url}: {e}")
            return False

    # ─────────────── m3u8 util ───────────────
    @staticmethod
    def _best_quality_m3u8(master_url: str, master_text: str) -> str | None:
        """Escolhe a variante com maior BANDWIDTH de um master playlist HLS."""
        best, max_bw, current_bw = None, 0, 0
        for ln in master_text.splitlines():
            if ln.startswith("#EXT-X-STREAM-INF"):
                m = re.search(r"BANDWIDTH=(\d+)", ln)
                current_bw = int(m.group(1)) if m else 0
            elif ln.strip() and not ln.startswith("#"):
                if current_bw > max_bw:
                    max_bw = current_bw
                    best = urllib.parse.urljoin(master_url, ln.strip())
        return best

    # ──────────────────────────────────────────────────────────
    #  Processa (e baixa localmente) um playlist .m3u8
    # ──────────────────────────────────────────────────────────
    def _process_m3u8(self, m3u8_url: str, base_path: str) -> str | None:
        """Baixa a árvore HLS inteira para `base_path` e devolve o caminho
        do playlist local (já reescrito para apontar para arquivos locais)."""
        m3u8_local = os.path.join(base_path, "playlist.m3u8")
        if not self.download_file(m3u8_url, m3u8_local, is_video=True):
            return None

        with open(m3u8_local, "r", encoding="utf-8") as fh:
            content = fh.read()

        modified: list[str] = []
        for ln in content.splitlines():
            # ─── chave AES ───
            if ln.startswith("#EXT-X-KEY"):
                uri = re.search(r'URI="([^"]+)"', ln)
                if uri:
                    key_url = uri.group(1)
                    key_name = os.path.basename(urllib.parse.urlparse(key_url).path)
                    # chave NÃO precisa de token, logo is_video = False
                    self.download_file(key_url, os.path.join(base_path, key_name))
                    ln = ln.replace(uri.group(1), key_name)
                modified.append(ln)
            # ─── segmento de vídeo ───
            elif ln.strip() and not ln.startswith("#"):
                seg_url = urllib.parse.urljoin(m3u8_url, ln.strip())
                seg_name = os.path.basename(seg_url)
                self.download_file(seg_url, os.path.join(base_path, seg_name), is_video=True)
                modified.append(seg_name)
            else:
                modified.append(ln)

        with open(m3u8_local, "w", encoding="utf-8") as fh:
            fh.write("\n".join(modified))

        return m3u8_local

    # ─────────────── conversão HLS → MP4 ───────────────
    @staticmethod
    def _convert_hls(input_m3u8: str, output_mp4: str) -> bool:
        try:
            os.makedirs(os.path.dirname(output_mp4), exist_ok=True)
            (
                ffmpeg.input(input_m3u8, allowed_extensions="ALL")
                .output(output_mp4, vcodec="copy", acodec="copy", loglevel="error")
                .overwrite_output()
                .run()
            )
            return True
        except ffmpeg.Error as e:
            print("Erro FFmpeg:", e.stderr.decode() if e.stderr else "UNKNOWN")
            return False

    @staticmethod
    def _clean(path: str):
        """Remove diretório temporário sem lançar exceções."""
        try:
            shutil.rmtree(path)
        except Exception:
            pass

    # ─────────────── wrapper alto nível para HLS ───────────────
    def handle_hls(
        self,
        master_url: str,
        media_id: str,
        out_dir: str,
        pbar: tqdm | None = None,
    ):
        """Baixa e converte um vídeo HLS para MP4."""
        base = os.path.join(out_dir, f"{media_id}_temp")
        os.makedirs(base, exist_ok=True)

        # Baixa o master playlist
        main_m3u8 = os.path.join(base, "main.m3u8")
        if not self.download_file(master_url, main_m3u8, pbar, is_video=True):
            self._clean(base)
            return

        # Escolhe a melhor variante
        with open(main_m3u8, "r", encoding="utf-8") as fh:
            master_text = fh.read()
        best_url = self._best_quality_m3u8(master_url, master_text)
        if not best_url:
            print("Falha ao localizar variante de melhor qualidade para", media_id)
            self._clean(base)
            return

        # Desce a árvore, reescrevendo as URLs para locais
        local_playlist = self._process_m3u8(best_url, base)
        if not local_playlist:
            self._clean(base)
            return

        # Converte para MP4
        final_mp4 = os.path.join(out_dir, f"{media_id}.mp4")
        if self._convert_hls(local_playlist, final_mp4) and pbar:
            pbar.update(1)
        
        # Limpeza
        self._clean(base)

# ──────────────────────────────────────────────────────────────
# 3.  Entrypoint / CLI
# ──────────────────────────────────────────────────────────────

def main():
    scraper = PrivacyScraper()
    if not scraper.login():
        print("Falha no login.")
        return

    profiles = scraper.get_profiles()
    if not profiles:
        print("Nenhum perfil encontrado.")
        return

    print("Perfis disponíveis:")
    for idx, p in enumerate(profiles, 1):
        print(f"{idx} - {p}")

    # ─────────── seleção de perfil ───────────
    while True:
        try:
            sel = int(input("Selecione o número do profile desejado (0 para todos): "))
            if sel == 0:
                selected_profiles = profiles
                break
            elif 1 <= sel <= len(profiles):
                selected_profiles = [profiles[sel - 1]]
                break
            print(f"Erro: Digite de 0 a {len(profiles)}")
        except ValueError:
            print("Erro: Digite apenas números!")

    # ─────────── escolha de mídia ───────────
    while True:
        media_input = input(
            "Selecione o tipo de mídia para download "
            "(1 - Fotos, 2 - Vídeos, 3 - Ambos, 4 - Post Específico por Data): "
        )
        if media_input in {"1", "2", "3", "4"}:
            media_type = media_input
            break
        print("Erro: Opção inválida! Digite apenas 1, 2, 3 ou 4.")

    # ─────────────────────────────────────────────
    #  op 4 – download de UM post por data
    # ─────────────────────────────────────────────
    if media_type == "4":
        if len(selected_profiles) != 1:
            print("A opção 4 requer escolher apenas um profile.")
            return

        profile_name = selected_profiles[0]
        print(f"\nBuscando lista de posts de {profile_name}…")
        posts = scraper.fetch_all_posts(profile_name)
        if not posts:
            print("Nenhum post encontrado.")
            return

        # ordena do mais recente para o mais antigo
        posts.sort(
            key=lambda p: time.strptime(
                p.get("postDate", "01/01/1970 00:00:00"), "%d/%m/%Y %H:%M:%S"
            ),
            reverse=True,
        )
        for i, p in enumerate(posts, 1):
            print(f"{i:3d} – {p['postDate']} • {len(p['files'])} arquivo(s)")

        while True:
            try:
                choice = int(input("\nDigite o número do post desejado: "))
                if 1 <= choice <= len(posts):
                    chosen = posts[choice - 1]
                    break
                print("Número fora da faixa!")
            except ValueError:
                print("Digite apenas números.")

        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        dl = MediaDownloader(scraper.cffi_session, scraper)
        total_files = sum(1 for f in chosen["files"] if not f["isLocked"])

        with tqdm(total=total_files, desc="Baixando post") as bar:
            for f in chosen["files"]:
                if f["isLocked"]:
                    continue

                if f["type"] == "image":
                    out = f"./{profile_name}/fotos/{f['mediaId']}.jpg"
                    dl.download_file(f["url"], out, bar)

                elif f["type"] == "video":
                    url = f["url"]
                    if url.endswith(".key"):
                        url = key_to_m3u8(url)

                    if ".mp4" in url:
                        out = f"./{profile_name}/videos/{f['mediaId']}.mp4"
                        dl.download_file(url, out, bar, is_video=True)
                    else:
                        dl.handle_hls(url, f["mediaId"], f"./{profile_name}/videos", bar)

        print("\nDownload do post concluído!")
        return

    # ─────────────────────────────────────────────
    #  opções 1-3 – varre TODO o mosaico
    # ─────────────────────────────────────────────
    dl = MediaDownloader(scraper.cffi_session, scraper)

    for profile_name in selected_profiles:
        print(f"\nProcessando perfil: {profile_name}")
        total, total_photos, total_videos = scraper.get_total_media_count(profile_name)
        print(f"Total: {total} (Fotos: {total_photos}, Vídeos: {total_videos})")

        if media_type == "1":
            grand_total = total_photos
        elif media_type == "2":
            grand_total = total_videos
        else:
            grand_total = total_photos + total_videos

        os.makedirs(f"./{profile_name}/fotos", exist_ok=True)
        os.makedirs(f"./{profile_name}/videos", exist_ok=True)

        skip = 0
        with tqdm(total=grand_total, desc="Progresso total") as bar:
            while True:
                ts = int(time.time() * 1000)
                url = (
                    "https://privacy.com.br/Profile?handler=PartialPosts"
                    f"&skip={skip}&take=10&nomePerfil={profile_name}"
                    f"&filter=mosaico&_={ts}"
                )
                r = scraper.cffi_session.get(url, impersonate="chrome120")
                if r.status_code != 200:
                    print(f"Falha ao obter mosaico: {r.status_code}")
                    break

                items = r.json().get("mosaicItems", [])
                if not items:
                    break

                for item in items:
                    for f in item.get("files", []):
                        if f["isLocked"]:
                            continue

                        if f["type"] == "image" and media_type in {"1", "3"}:
                            out = f"./{profile_name}/fotos/{f['mediaId']}.jpg"
                            dl.download_file(f["url"], out, bar)

                        elif f["type"] == "video" and media_type in {"2", "3"}:
                            url = f["url"]
                            if url.endswith(".key"):         # ⇢ ajuste ❷
                                url = key_to_m3u8(url)       # ⇢ ajuste ❷

                            if ".mp4" in url:
                                out = f"./{profile_name}/videos/{f['mediaId']}.mp4"
                                dl.download_file(url, out, bar, is_video=True)
                            else:
                                dl.handle_hls(
                                    url,
                                    f["mediaId"],
                                    f"./{profile_name}/videos",
                                    bar,
                                )
                skip += 10

        print("Download concluído para", profile_name)

if __name__ == "__main__":
    main()