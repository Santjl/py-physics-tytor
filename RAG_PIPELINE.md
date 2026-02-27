# Pipeline RAG — Physics Tutor API

## Visao Geral

O sistema utiliza Retrieval-Augmented Generation (RAG) para gerar feedback personalizado a partir de materiais didaticos (PDFs) enviados pelo professor. O pipeline completo possui tres grandes etapas: **Ingestao**, **Retrieval Hibrido** e **Geracao de Feedback**.

```
PDF Upload ──► Extracao ──► Chunking ──► Classificacao ──► Embedding ──► Armazenamento
                                                                              │
Aluno erra questao ──► Retrieval Hibrido ──► Geracao LLM ──► Feedback final  │
                            │                                                 │
                            └───── consulta chunks armazenados ◄──────────────┘
```

---

## 1. Ingestao de Documentos

**Arquivo:** `app/rag/processing.py`

### 1.1 Extracao de Texto

O PyMuPDF (`fitz`) abre o PDF e extrai texto pagina a pagina. Paginas vazias sao contabilizadas — se mais de 90% das paginas estiverem vazias, um warning e emitido (indicando PDF de imagens sem OCR).

### 1.2 Chunking

**Arquivo:** `app/rag/chunking.py`

O texto de cada pagina e dividido em chunks com as seguintes configuracoes:

| Parametro | Valor padrao | Descricao |
|---|---|---|
| `max_tokens` | 256 (~1024 chars) | Tamanho maximo de cada chunk |
| `overlap_tokens` | 50 (~200 chars) | Sobreposicao entre chunks consecutivos |
| `MAX_INPUT_TOKENS` | 8192 | Limite do modelo `nomic-embed-text` |

A estrategia de divisao segue esta hierarquia:

1. **Paragrafos** — o texto e separado por linhas vazias.
2. **Sentencas** — paragrafos que excedem o limite sao divididos em boundaries de sentenca (`.`, `!`, `?`).
3. **Palavras** — ultimo recurso para textos sem pontuacao, corta em espacos para nao quebrar palavras.

O **overlap** funciona copiando a cauda do chunk anterior para o inicio do proximo. Isso garante que informacoes que caiam na fronteira entre dois chunks nao sejam perdidas. A funcao `_safe_tail` evita cortar no meio de palavras ao extrair essa cauda.

### 1.3 Classificacao de Chunks

Cada chunk e classificado por heuristica de palavras-chave (sem acentos, case-insensitive):

- **`exercise`** — contem marcadores como "exercicio", "problema", "gabarito", "resolva", etc.
- **`theory`** — texto nao-vazio que nao contem marcadores de exercicio.
- **`unknown`** — texto vazio apos normalizacao.

Tambem sao extraidos metadados estruturais via regex: titulo de capitulo (`Capitulo N`) e titulo de secao (`Secao N.N`).

### 1.4 Embedding

**Arquivo:** `app/rag/ollama_client.py`

Os textos dos chunks sao enviados ao Ollama (modelo `nomic-embed-text`) via HTTP POST para `/api/embed`. Cada texto e convertido em um vetor de **768 dimensoes**.

Mecanismos de resiliencia:

- **Retry com backoff exponencial** — ate 3 tentativas, com espera de 1s, 2s, 4s (max 10s). Erros 4xx nao fazem retry.
- **Fallback one-by-one** — se o batch retornar quantidade errada de vetores, cada texto e processado individualmente.
- **Normalizacao** — vetores com dimensao incorreta sao truncados ou preenchidos com zeros.

### 1.5 Armazenamento

Os chunks e seus embeddings sao persistidos na tabela `chunks` do PostgreSQL, utilizando a extensao **pgvector** para armazenar e indexar os vetores. Cada registro contem: texto, embedding, tipo (`theory`/`exercise`/`unknown`), pagina, nome do arquivo, titulo de capitulo e secao.

---

## 2. Retrieval Hibrido

**Arquivo:** `app/rag/retrieval.py`

O retrieval e o componente central do RAG — e responsavel por encontrar os chunks mais relevantes para uma dada query. Esta aplicacao implementa um **retrieval hibrido** que combina duas abordagens complementares, funde seus rankings e aplica re-ranking por diversidade.

### 2.1 Por que Retrieval Hibrido?

Busca semantica e busca lexical tem forcas e fraquezas opostas:

| Aspecto | Busca Semantica (vetorial) | Busca Lexical (BM25) |
|---|---|---|
| **Forca** | Captura significado e sinonimos | Precisa com termos tecnicos exatos |
| **Fraqueza** | Pode perder termos especificos | Nao entende sinonimos ou parafrases |
| **Exemplo bom** | "forca resultante" encontra "soma vetorial" | "2a Lei de Newton" encontra exatamente esse texto |
| **Exemplo ruim** | "F=ma" pode retornar qualquer formula | "impulso" nao encontra "variacao de momento" |

Combinando ambas, o sistema se torna robusto: a busca semantica garante cobertura conceitual, enquanto a BM25 garante precisao terminologica.

### 2.2 Busca Semantica (Cosine Distance)

```python
def _semantic_search(db, query_vec, limit) -> list[(chunk_id, rank)]
```

**Como funciona:**

1. A query do aluno e convertida em um vetor de 768 dimensoes pelo mesmo modelo de embedding (`nomic-embed-text`).
2. O pgvector calcula a **distancia cosseno** entre o vetor da query e o embedding de cada chunk armazenado.
3. Os chunks sao ordenados por menor distancia (maior similaridade) e os top-N sao retornados.

**Distancia cosseno** mede o angulo entre dois vetores, ignorando magnitude:

```
cosine_distance(A, B) = 1 - (A · B) / (||A|| * ||B||)
```

- Valor 0 = vetores identicos (mesma direcao)
- Valor 1 = vetores ortogonais (sem relacao)
- Valor 2 = vetores opostos

O pgvector implementa isso nativamente com indice otimizado (IVFFlat ou HNSW), permitindo busca eficiente mesmo com milhares de chunks.

### 2.3 Busca Lexical (BM25 via PostgreSQL Full-Text Search)

```python
def _bm25_search(db, query, limit, fts_config) -> list[(chunk_id, rank)]
```

**Como funciona:**

1. A coluna `text_search` (tipo `tsvector`) armazena os tokens normalizados de cada chunk, ja processados pelo PostgreSQL.
2. A query do aluno e convertida em `tsquery` via `plainto_tsquery`, que tokeniza, remove stopwords e aplica stemming.
3. O operador `@@` faz o match entre `tsvector` e `tsquery`.
4. A funcao `ts_rank` pontua cada match — internamente o PostgreSQL usa uma variante de BM25/TF-IDF.

**BM25 (Best Matching 25)** e o algoritmo padrao de ranking em information retrieval. Ele pontua documentos com base em:

- **TF (Term Frequency)** — quantas vezes o termo aparece no documento. Usa saturacao logaritmica: a 10a ocorrencia contribui muito menos que a 1a.
- **IDF (Inverse Document Frequency)** — termos raros no corpus tem peso maior. "Newton" vale mais que "de".
- **Normalizacao por tamanho** — documentos longos nao sao artificialmente favorecidos.

A formula simplificada:

```
BM25(q, d) = Σ IDF(t) * [TF(t,d) * (k1 + 1)] / [TF(t,d) + k1 * (1 - b + b * |d|/avgdl)]
```

Onde `k1` controla a saturacao de TF e `b` controla a normalizacao por tamanho.

O `fts_config` (configuravel via settings, ex: `"portuguese"`) define as regras de stemming e stopwords do idioma.

**Fallback:** se a busca BM25 falhar (ex: coluna `text_search` nao existe), ela retorna lista vazia silenciosamente, e o sistema continua apenas com busca semantica.

### 2.4 Reciprocal Rank Fusion (RRF)

```python
def reciprocal_rank_fusion(semantic_ranks, bm25_ranks, semantic_weight, bm25_weight, k=60)
    -> list[(chunk_id, fused_score)]
```

Apos obter os rankings de ambas as buscas, e necessario fundi-los em um unico ranking. O **RRF** e a tecnica escolhida por ser simples, robusta e nao depender de calibracao de scores.

**O problema:** os scores das duas buscas estao em escalas incompativeis — distancia cosseno retorna valores entre 0 e 2, enquanto `ts_rank` retorna valores arbitrarios. Nao podemos simplesmente soma-los.

**A solucao do RRF:** em vez de usar scores absolutos, usa apenas a **posicao (rank)** de cada resultado. A formula:

```
RRF_score(chunk) = Σ weight_i / (k + rank_i)
```

Para cada chunk que aparece em alguma das buscas:

```
score = semantic_weight / (k + rank_semantico) + bm25_weight / (k + rank_bm25)
```

**Parametros:**

| Parametro | Padrao | Funcao |
|---|---|---|
| `k` | 60 | Constante de suavizacao. Valores maiores reduzem a diferenca entre posicoes proximas. O valor 60 e o padrao classico do paper original (Cormack et al., 2009). |
| `semantic_weight` | configuravel | Peso da busca semantica na fusao |
| `bm25_weight` | configuravel | Peso da busca BM25 na fusao |

**Exemplo concreto:**

Suponha que o chunk #42 apareceu em 1o lugar na busca semantica e em 3o na BM25, com pesos iguais (1.0):

```
score(#42) = 1.0 / (60 + 1) + 1.0 / (60 + 3) = 0.01639 + 0.01587 = 0.03226
```

Ja o chunk #17, que apareceu apenas em 2o lugar na BM25:

```
score(#17) = 0 + 1.0 / (60 + 2) = 0.01613
```

O chunk #42 vence por aparecer em ambas as buscas — essa e a forca do RRF: **documentos relevantes para ambos os metodos sao naturalmente promovidos**.

**Por que RRF e nao outras tecnicas?**

- **Simples** — nao precisa normalizar scores nem treinar modelo.
- **Robusto** — funciona bem mesmo quando uma das buscas retorna poucos ou nenhum resultado.
- **Sem hiperparametros criticos** — o `k=60` funciona bem na maioria dos cenarios.
- **Aditivo** — chunks que aparecem em ambas as listas recebem boost natural.

### 2.5 Filtragem por Tipo de Chunk

Apos a fusao RRF, os chunks candidatos sao filtrados por tipo:

**Para retrieval de teoria** (`retrieve_chunks`):
1. Prioriza chunks `theory`.
2. Se nenhum `theory` for encontrado, usa chunks `unknown`.
3. Chunks `exercise` sao **sempre excluidos** do pool teorico.

**Para retrieval de exercicios** (`retrieve_exercise_chunks`):
1. Mantem apenas chunks `exercise`.

Essa separacao garante que o feedback teorico nao seja contaminado com enunciados de exercicios, e vice-versa.

### 2.6 MMR Re-ranking (Maximal Marginal Relevance)

```python
def mmr_rerank(chunks, query_vec, fused_scores, mmr_lambda, top_k) -> list[Chunk]
```

O ultimo estagio do retrieval aborda um problema comum: **redundancia**. Chunks consecutivos de um mesmo capitulo tendem a ser muito similares entre si. Retornar 5 chunks quase identicos desperdicaria o contexto limitado do prompt.

O **MMR** resolve isso selecionando chunks que sao simultaneamente **relevantes para a query** e **diversos entre si**.

**Algoritmo (selecao gulosa iterativa):**

```
Para cada vaga no top_k:
    Para cada chunk candidato:
        relevancia  = score_RRF_normalizado(chunk)
        redundancia = max similaridade_cosseno(chunk, chunk_ja_selecionado) para todos ja selecionados
        mmr_score   = λ * relevancia - (1 - λ) * redundancia
    Seleciona o chunk com maior mmr_score
```

**O parametro λ (lambda):**

| Valor | Comportamento |
|---|---|
| λ = 1.0 | Pura relevancia (ignora diversidade, equivale a nao usar MMR) |
| λ = 0.5 | Equilibrio entre relevancia e diversidade |
| λ = 0.0 | Pura diversidade (ignora relevancia) |

Na pratica, valores entre 0.5 e 0.8 funcionam bem para RAG educacional.

**Exemplo:**

Suponha 3 chunks candidatos sobre "Leis de Newton":

- Chunk A: "A segunda lei de Newton, F=ma, relaciona forca e aceleracao..."
- Chunk B: "Pela 2a lei de Newton, a aceleracao e proporcional a forca resultante..."
- Chunk C: "O principio de acao e reacao (3a lei) afirma que forcas sempre..."

Sem MMR, A e B seriam selecionados (ambos sobre 2a lei). Com MMR, apos selecionar A, o chunk B recebe penalidade alta por ser muito similar a A, e o chunk C (sobre 3a lei) sobe no ranking — resultando em cobertura mais ampla do tema.

**Detalhes de implementacao:**

- Os embeddings sao pre-normalizados (divididos pela norma L2) para que o produto escalar seja equivalente a similaridade cosseno.
- Os scores RRF sao normalizados pelo score maximo para ficar em [0, 1].
- A complexidade e O(top_k * n_candidatos * top_k), aceitavel para n_candidatos tipicamente < 50.

### 2.7 Pipeline Completo do Retrieval

Resumo visual do fluxo para uma unica query:

```
Query do aluno
    │
    ├──► Embedding (Ollama) ──► Busca Semantica (pgvector cosine) ──► Ranking S
    │                                                                      │
    └──► Tokenizacao (PostgreSQL) ──► Busca BM25 (tsvector/tsquery) ──► Ranking B
                                                                           │
                                                    Reciprocal Rank Fusion ◄┘
                                                            │
                                                    Filtragem por tipo
                                                    (theory > unknown)
                                                            │
                                                    MMR Re-ranking
                                                    (diversidade)
                                                            │
                                                    Top-K chunks finais
```

**Parametros configuráveis** (via `Settings`):

| Parametro | Funcao |
|---|---|
| `retrieval_candidate_multiplier` | Multiplica `top_k` para obter mais candidatos antes de filtrar |
| `retrieval_semantic_weight` | Peso da busca semantica no RRF |
| `retrieval_bm25_weight` | Peso da busca BM25 no RRF |
| `retrieval_rrf_k` | Constante de suavizacao do RRF |
| `retrieval_mmr_lambda` | Balanco relevancia vs diversidade no MMR |
| `retrieval_fts_config` | Configuracao de idioma do full-text search (ex: `"portuguese"`) |

---

## 3. Geracao de Feedback

**Arquivo:** `app/rag/feedback.py`

### 3.1 Retrieval por Questao

O feedback e gerado **individualmente por questao incorreta**, nao de forma global. Para cada questao errada, o sistema monta uma query combinando o enunciado, a resposta do aluno e a resposta correta, e executa o pipeline de retrieval completo (semantico + BM25 + RRF + MMR).

Sao feitas duas buscas separadas:
- `retrieve_chunks` (top_k=4) — busca chunks teoricos.
- `retrieve_exercise_chunks` (top_k=2) — busca chunks de exercicio similar.

### 3.2 Construcao do Prompt

Cada questao recebe um prompt com:

- **System prompt** — instrucoes detalhadas sobre formato, tom (PT-BR, conversacional), limites de caracteres por secao e regras de citacao.
- **User prompt** — enunciado da questao, resposta escolhida, resposta correta, fontes teoricas identificadas como `S1..Sk` e exercicios como `E1..Ek` (apenas metadados: arquivo, pagina, ID — sem o texto do livro, para evitar copia).

### 3.3 Invocacao do LLM

O `ChatOllama` (LangChain) envia o prompt ao modelo `llama3.1` com temperature=0 (determinismo maximo). O LLM retorna texto estruturado com secoes:

- **Explicacao** — raciocinio correto especifico para a questao.
- **Erro conceitual do aluno** — deducao de qual confusao levou a resposta errada.
- **Onde estudar no livro** — indicacao de topico e capitulo, citando fontes `(S1)`.
- **Exercicio similar** — exercicio do material para praticar, citando `(E1)`.
- **Dica** — conselho pratico para evitar o erro no futuro.

### 3.4 Parsing e Sanitizacao

A resposta do LLM e parseada por regex nos cabecalhos das secoes. Citacoes (`S1`, `E1`) sao mapeadas de volta aos chunks reais para extrair arquivo e pagina. O feedback e entao sanitizado:

- Explicacao truncada em 1500 chars.
- Erro conceitual truncado em 600 chars.
- Dica truncada em 300 chars.
- Paginas deduplicadas e ordenadas nos items de estudo.

### 3.5 Fallback

Se o LLM falhar (timeout, erro, resposta invalida), um feedback padrao e gerado com mensagens genericas e as fontes recuperadas pelo retrieval, garantindo que o aluno sempre receba alguma orientacao.

---

## 4. Modo de Teste

Quando `APP_ENV=test`:

- **Embeddings** retornam vetores deterministicos `[0.1, 0.1, ...]`.
- **Retrieval** usa fallback SQLite (ordenacao por ID, sem busca vetorial).
- **Feedback** retorna sempre o template padrao, sem invocar o LLM.

Isso permite rodar toda a suite de testes sem dependencia do Ollama.
