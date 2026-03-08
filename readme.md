# ⚠️ Privacy Scraper ⚠️

Script para baixar conteúdo de perfis do Privacy **nos quais você já é assinante**.

⚠️ **Aviso de manutenção**  
O script está **temporariamente em manutenção** até que seja resolvido um problema relacionado ao **download de vídeos**.  
Downloads de **fotos podem continuar funcionando**, porém o download de **vídeos pode estar desativado ou instável no momento**.

---

# Updates

**07/03/2026**

- Bypass do captcha do Privacy implementado
- Tokens de login agora são **armazenados localmente**, permitindo logins mais rápidos até expirarem

---

# Como utilizar

## 1. Instalar dependências

```bash
pip install -r requirements.txt
```

---

## 2. Criar arquivo `.env`

Crie um arquivo chamado **.env** na raiz do projeto com o seguinte conteúdo:

```env
EMAIL=exemplo@gmail.com
PASSWORD=exemplo123
DEBUG_MODE=false
```

---

## 3. Executar o script

```bash
python privacy_scraper.py
```

---

## 4. Selecionar perfil

Quando aparecer a lista de perfis:

- Digite o **número do perfil desejado**
- Ou digite **0** para varrer todos os perfis

---

## 5. Selecionar tipo de mídia

Escolha o tipo de conteúdo para download:

```
1 - Fotos
2 - Vídeos
3 - Ambos
```

⚠️ **Nota:** O download de **vídeos está temporariamente em manutenção**.

---

# Dependência (FFmpeg)

Necessário para processamento de mídia.

Download:

https://github.com/BtbN/FFmpeg-Builds/releases

## Instalação

1. Extraia o arquivo ZIP em uma pasta  
Exemplo:

```
C:\ffmpeg\bin
```

2. Adicione o caminho do FFmpeg às variáveis de ambiente do sistema

### Passos

1. Pressione **Win + S**
2. Digite **variáveis de ambiente**
3. Clique em **Editar as variáveis de ambiente do sistema**
4. Em **Variáveis do sistema**, selecione **Path**
5. Clique em **Editar**
6. Clique em **Novo**
7. Adicione:

```
C:\ffmpeg\bin
```

---

# Contato

Discord: **st8rb**

---

# Agradecimentos

https://github.com/Theyka/Turnstile-Solver
