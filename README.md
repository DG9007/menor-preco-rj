# Menor Preço RJ 🛒

Compara preços de supermercados no Rio de Janeiro. **100% gratuito**, sem API paga.

## Como funciona

1. **Scraper Python** roda todo dia às 7h via GitHub Actions
2. Salva os encartes em `data/encartes.json` no próprio repositório
3. O site na **Vercel** lê esse JSON — sem banco de dados, sem custo

---

## Configuração (passo a passo)

### 1. Criar o repositório no GitHub

1. Acesse [github.com](https://github.com) e crie uma conta se não tiver
2. Clique em **New repository**
3. Nome: `menor-preco-rj`
4. Marque **Public**
5. Clique em **Create repository**

### 2. Subir os arquivos

Faça upload de todos os arquivos desta pasta para o repositório:
- `index.html`
- `scraper.py`
- `data/encartes.json`
- `.github/workflows/scraper.yml`

### 3. Ativar o GitHub Actions

1. No repositório, clique em **Actions**
2. Se pedir permissão, clique em **I understand my workflows, go ahead and enable them**
3. Para rodar agora (sem esperar amanhã): clique em **Atualizar Encartes** → **Run workflow** → **Run workflow**

### 4. Publicar na Vercel

1. Acesse [vercel.com](https://vercel.com) e crie conta com seu GitHub
2. Clique em **Add New Project**
3. Selecione o repositório `menor-preco-rj`
4. Clique em **Deploy**
5. Pronto! Você receberá um link como `https://menor-preco-rj.vercel.app`

### 5. Atualizar a URL do JSON no index.html

Abra `index.html` e na linha:
```js
const DATA_URL = "./data/encartes.json";
```
Pode deixar assim mesmo — a Vercel serve os arquivos do repositório corretamente.

---

## Atualização automática

O scraper roda todo dia às **07:00 horário de Brasília** automaticamente.
Quando detecta mudança nos encartes, faz commit automático do `data/encartes.json`.
A Vercel detecta o commit e atualiza o site em ~30 segundos.

## Custo

| Serviço | Plano | Custo |
|---------|-------|-------|
| GitHub  | Free  | R$ 0  |
| GitHub Actions | Free (2.000 min/mês) | R$ 0 |
| Vercel  | Hobby | R$ 0  |
| **Total** | | **R$ 0** |
