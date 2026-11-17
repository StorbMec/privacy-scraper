# Privacy Scraper
Apenas baixa conteúdo de perfis no qual você ja é assinante de forma automatica :)
 
## Updates
 
**26/10/2026**
- Adicionada opção para baixar um post específico (ao invés do perfil inteiro), com lista mostrando data, legenda e quantidade de fotos/vídeos de cada post
- Ajuste nas midias baixadas no chat

**23/04/2026**
- Aumentado velocidade dos downloads com paralelização

**12/03/2026**
- Problema com download de vídeos resolvido
 
**07/03/2026**
- Bypass do captcha do Privacy implementado
- Tokens de login agora são armazenados localmente, permitindo logins mais rápidos até expirarem
 
## Como utilizar
 
1. Instale os requerimentos utilizando o comando
```
pip install -r requirements.txt
```
 
2. Crie um arquivo na raiz chamado .env com a seguinte arvore:
```
EMAIL=exemplo@gmail.com
PASSWORD=exemplo123
DEBUG_MODE=false
```
 
3. Após tudo configurado, apenas faça
```
python privacy_scraper.py
```
 
4. Quando aparecer a lista de perfis, aperta o numero do perfil escolhido ou 0 para sair.
 
5. Depois selecione o tipo de midia, aperte o numero de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos).
 
6. No menu do perfil, a opção **5 - Escolher um item específico para baixar** permite baixar só alguns posts em vez do perfil inteiro:
   - Escolha a origem (Perfil, Compradas ou Chat) e o tipo de mídia
   - É mostrada uma lista com data, legenda e quantidade de fotos/vídeos de cada post (itens bloqueados/não comprados não aparecem)
   - Digite o(s) número(s) do post (ex: `3`, `1,3,5-7` ou `todos`) para baixar
   - `U` permite colar uma URL de vídeo (.mp4/.m3u8) ou um `mediaId` diretamente, sem precisar da lista
 
## Dependencias (FFmpeg)
 
https://github.com/BtbN/FFmpeg-Builds/releases
 
1. Extraia o arquivo ZIP em uma pasta (ex: C:\ffmpeg\bin)
2. Adicione o caminho do FFmpeg às variáveis de ambiente do sistema
3. Pressione Win + S e digite "variáveis de ambiente"
4. Clique em "Editar as variáveis de ambiente do sistema"
5. Em "Variáveis do sistema", selecione Path > Editar > Novo
6. Adicione o caminho da pasta bin do FFmpeg (ex: C:\ffmpeg\bin)
 
## Contato
 
Discord: st8rb

## Agradecimentos

https://github.com/Theyka/Turnstile-Solver
