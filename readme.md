# Privacy Scraper
Apenas baixa conteúdo de perfis no qual você ja é assinante de forma automatica :)
 
## Updates
<<<<<<< HEAD

**22/03/2026**
- Problema com midias acima de 1000+
=======
 
**23/04/2026**
- Aumentado velocidade dos downloads com paralelização
>>>>>>> 5c07716 (aumentado velocidade de downloads)

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
