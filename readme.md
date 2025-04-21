# Privacy Scraper

Apenas baixa conteúdo de perfis no qual você ja é assinante

## Como utilizar:

1. Instale os requerimentos utilizando o comando

```
pip install -r requirements.txt
```

2. Crie um arquivo na raiz chamado .env com a seguinte arvore:
```
EMAIL=exemplo@gmail.com
PASSWORD=exemplo123
```

3. Após tudo configurado, apenas faça
```
python privacy_scraper.py
```

4. Quando aparecer a lista de perfis, aperta o numero do perfil escolhido ou 0 para varrer todos os perfis.

5. Depois selecione o tipo de midia, aperte o numero de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos).

## FFMPeg
(https://github.com/BtbN/FFmpeg-Builds/releases)

1. Extraia o arquivo ZIP em uma pasta (ex: C:\ffmpeg\bin)

2. Adicione o caminho do FFmpeg às variáveis de ambiente do sistema:

3. Pressione Win + S e digite "variáveis de ambiente"

4. Clique em "Editar as variáveis de ambiente do sistema"

5. Em "Variáveis do sistema", selecione Path > Editar > Novo

6. Adicione o caminho da pasta bin do FFmpeg (ex: C:\ffmpeg\bin)