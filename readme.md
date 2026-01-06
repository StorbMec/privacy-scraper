# Privacy Scraper

Apenas baixa conteúdo de perfis no qual você ja é assinante

## Atenção
Apartir do dia 05/01/2026 o login do Privacy começou a exigir captcha então voce tem duas opções:

## Opção 1 (login automatico)
1. Acesse https://capmonster.cloud/
2. Crie uma conta
3. Adicione saldo à sua conta (o serviço é pago por captcha resolvido)
5. Copie sua chave de API e adicione ao arquivo .env
<img src="https://i.imgur.com/ZdduW64.png">

## Opção 2 (login manual)
1. Va para: https://privacy.com.br/auth?route=sign-in
2. Pressione F12 -> Aba Network
3. Faca login normalmente
4. Procure a requisicao "login"
5. Na aba Response, copie TODO o JSON
6. Cole no programa quando pedir
<img src="https://i.imgur.com/atNzJAT.png">

## Como utilizar:

1. Instale os requerimentos utilizando o comando

```
pip install -r requirements.txt
```

2. Crie um arquivo na raiz chamado .env com a seguinte arvore:
```
EMAIL=exemplo@gmail.com
PASSWORD=exemplo123
CAPMONSTER_API_KEY=sua_chave_capmonster_aqui
```

3. Após tudo configurado, apenas faça
```
python privacy_scraper.py
```

4. Quando aparecer a lista de perfis, aperta o numero do perfil escolhido ou 0 para varrer todos os perfis.

5. Depois selecione o tipo de midia, aperte o numero de mídia para download (1 - Fotos, 2 - Vídeos, 3 - Ambos).

## Dependecias (FFMPeg)
(https://github.com/BtbN/FFmpeg-Builds/releases)

1. Extraia o arquivo ZIP em uma pasta (ex: C:\ffmpeg\bin)

2. Adicione o caminho do FFmpeg às variáveis de ambiente do sistema:

3. Pressione Win + S e digite "variáveis de ambiente"

4. Clique em "Editar as variáveis de ambiente do sistema"

5. Em "Variáveis do sistema", selecione Path > Editar > Novo

6. Adicione o caminho da pasta bin do FFmpeg (ex: C:\ffmpeg\bin)

## Contato
discord: st8rb 
