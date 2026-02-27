# API Documentation - Physics Tutor

## Base URL
```
http://localhost:8000
```

## Autenticação

A API usa autenticação JWT (JSON Web Tokens). Para endpoints protegidos, inclua o token no header:
```
Authorization: Bearer <seu_token_aqui>
```

---

## 📋 Índice
- [Autenticação (Auth)](#autenticação-auth)
- [Health Check](#health-check)
- [Questionários (Questionnaires)](#questionários-questionnaires)
- [Documentos (Documents)](#documentos-documents)
- [Feedback](#feedback)

---

## Autenticação (Auth)

### Registrar Novo Usuário
**POST** `/auth/register`

Cria um novo usuário no sistema.

**Body:**
```json
{
  "email": "alice@example.com",
  "password": "minha_senha_forte",
  "role": "student"
}
```

**Campos:**
- `email` (string, obrigatório): Email válido do usuário
- `password` (string, obrigatório): Senha do usuário
- `role` (string, obrigatório): Papel do usuário - `"student"` ou `"admin"`

**Resposta de Sucesso (201):**
```json
{
  "id": 1,
  "email": "alice@example.com",
  "role": "student"
}
```

**Erros:**
- `400`: Email já cadastrado

---

### Login
**POST** `/auth/login`

Autentica um usuário e retorna um token de acesso.

**Content-Type:** `application/x-www-form-urlencoded`

**Body (form-data):**
```
username=alice@example.com&password=minha_senha_forte
```

**Campos:**
- `username` (string, obrigatório): Email do usuário
- `password` (string, obrigatório): Senha do usuário

**Resposta de Sucesso (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Erros:**
- `401`: Credenciais inválidas

---

## Health Check

### Verificar Status da API
**GET** `/health`

Verifica se a API está funcionando.

**Sem autenticação necessária**

**Resposta de Sucesso (200):**
```json
{
  "status": "ok"
}
```

---

## Questionários (Questionnaires)

### Criar Questionário
**POST** `/questionnaires/`

Cria um novo questionário (sem questões).

**🔒 Requer autenticação: Admin**

**Body:**
```json
{
  "title": "Cinemática",
  "description": "Movimento retilíneo uniforme"
}
```

**Campos:**
- `title` (string, obrigatório): Título do questionário
- `description` (string, opcional): Descrição do questionário

**Resposta de Sucesso (201):**
```json
{
  "id": 1,
  "title": "Cinemática",
  "description": "Movimento retilíneo uniforme"
}
```

**Erros:**
- `400`: Título vazio
- `401`: Não autenticado
- `403`: Apenas admins

---

### Criar Questionário Completo
**POST** `/questionnaires/full`

Cria um questionário completo com questões e opções.

**🔒 Requer autenticação: Admin**

**Body:**
```json
{
  "title": "Cinemática Básica",
  "description": "Teste sobre movimento uniforme",
  "questions": [
    {
      "statement": "Qual a aceleração gravitacional na Terra?",
      "options": [
        {
          "letter": "A",
          "text": "9,8 m/s²",
          "is_correct": true
        },
        {
          "letter": "B",
          "text": "8,9 m/s²",
          "is_correct": false
        },
        {
          "letter": "C",
          "text": "10 m/s²",
          "is_correct": false
        }
      ]
    }
  ]
}
```

**Campos:**
- `title` (string, obrigatório): Título do questionário
- `description` (string, opcional): Descrição
- `questions` (array, obrigatório): Lista de questões
  - `statement` (string): Enunciado da questão
  - `options` (array): Opções de resposta
    - `letter` (string): Letra da opção (A, B, C, etc.)
    - `text` (string): Texto da opção
    - `is_correct` (boolean): Se é a resposta correta

**Resposta de Sucesso (201):**
```json
{
  "id": 1,
  "title": "Cinemática Básica",
  "description": "Teste sobre movimento uniforme",
  "questions": [
    {
      "id": 1,
      "statement": "Qual a aceleração gravitacional na Terra?",
      "options": [
        {
          "id": 1,
          "letter": "A",
          "text": "9,8 m/s²",
          "is_correct": true
        },
        {
          "id": 2,
          "letter": "B",
          "text": "8,9 m/s²",
          "is_correct": false
        },
        {
          "id": 3,
          "letter": "C",
          "text": "10 m/s²",
          "is_correct": false
        }
      ]
    }
  ]
}
```

**Erros:**
- `400`: Validação falhou (título vazio, sem questões, letras duplicadas, sem resposta correta)
- `401`: Não autenticado
- `403`: Apenas admins

---

### Listar Questionários
**GET** `/questionnaires/`

Lista todos os questionários disponíveis.

**Sem autenticação necessária**

**Resposta de Sucesso (200):**
```json
[
  {
    "id": 1,
    "title": "Cinemática",
    "description": "Movimento retilíneo uniforme"
  },
  {
    "id": 2,
    "title": "Dinâmica",
    "description": "Leis de Newton"
  }
]
```

---

### Obter Questionário
**GET** `/questionnaires/{questionnaire_id}`

Obtém detalhes de um questionário específico com todas as suas questões e opções.

**Sem autenticação necessária**

**Resposta de Sucesso (200):**
```json
{
  "id": 1,
  "title": "Cinemática",
  "description": "Movimento retilíneo uniforme",
  "questions": [
    {
      "id": 1,
      "statement": "Qual a aceleração gravitacional na Terra?",
      "options": [
        {
          "id": 1,
          "letter": "A",
          "text": "9,8 m/s²",
          "is_correct": true
        },
        {
          "id": 2,
          "letter": "B",
          "text": "8,9 m/s²",
          "is_correct": false
        }
      ]
    }
  ]
}
```

**Erros:**
- `404`: Questionário não encontrado

---

### Adicionar Questão
**POST** `/questionnaires/{questionnaire_id}/questions`

Adiciona uma nova questão a um questionário existente.

**🔒 Requer autenticação: Admin**

**Body:**
```json
{
  "statement": "Qual a velocidade da luz no vácuo?",
  "options": [
    {
      "letter": "A",
      "text": "300.000 km/s",
      "is_correct": true
    },
    {
      "letter": "B",
      "text": "250.000 km/s",
      "is_correct": false
    }
  ]
}
```

**Campos:**
- `statement` (string, obrigatório): Enunciado da questão
- `options` (array, obrigatório): Mínimo 1 opção
  - `letter` (string): Letra única da opção
  - `text` (string): Texto da opção
  - `is_correct` (boolean): Pelo menos uma deve ser true

**Resposta de Sucesso (201):**
```json
{
  "id": 2,
  "statement": "Qual a velocidade da luz no vácuo?",
  "options": [
    {
      "id": 3,
      "letter": "A",
      "text": "300.000 km/s",
      "is_correct": true
    },
    {
      "id": 4,
      "letter": "B",
      "text": "250.000 km/s",
      "is_correct": false
    }
  ]
}
```

**Erros:**
- `400`: Validação falhou
- `401`: Não autenticado
- `403`: Apenas admins
- `404`: Questionário não encontrado

---

### Listar Questões
**GET** `/questionnaires/{questionnaire_id}/questions`

Lista todas as questões de um questionário.

**Sem autenticação necessária**

**Resposta de Sucesso (200):**
```json
[
  {
    "id": 1,
    "statement": "Qual a aceleração gravitacional na Terra?",
    "options": [
      {
        "id": 1,
        "letter": "A",
        "text": "9,8 m/s²",
        "is_correct": true
      },
      {
        "id": 2,
        "letter": "B",
        "text": "8,9 m/s²",
        "is_correct": false
      }
    ]
  }
]
```

**Erros:**
- `404`: Questionário não encontrado

---

### Submeter Tentativa
**POST** `/questionnaires/{questionnaire_id}/attempts`

Submete uma tentativa de resposta ao questionário e retorna a pontuação.

**🔒 Requer autenticação: Student**

**Body:**
```json
{
  "answers": [
    {
      "question_id": 1,
      "selected_option_id": 2
    },
    {
      "question_id": 2,
      "selected_option_id": 5
    }
  ]
}
```

**Campos:**
- `answers` (array, obrigatório): Lista de respostas
  - `question_id` (integer): ID da questão
  - `selected_option_id` (integer): ID da opção selecionada

**Resposta de Sucesso (201):**
```json
{
  "attempt_id": 10,
  "score": 1.0,
  "total": 2,
  "answers": [
    {
      "question_id": 1,
      "selected_option_id": 2,
      "is_correct": true
    },
    {
      "question_id": 2,
      "selected_option_id": 5,
      "is_correct": false
    }
  ]
}
```

**Campos de Resposta:**
- `attempt_id`: ID da tentativa (usar para solicitar feedback)
- `score`: Número de respostas corretas
- `total`: Total de questões respondidas
- `answers`: Detalhes de cada resposta

**Erros:**
- `401`: Não autenticado
- `403`: Apenas estudantes
- `404`: Questionário não encontrado

---

## Documentos (Documents)

### Upload de Documento
**POST** `/documents/upload`

Faz upload de um documento PDF para processamento RAG.

**🔒 Requer autenticação: Admin**

**Content-Type:** `multipart/form-data`

**Body (form-data):**
- `file` (file, obrigatório): Arquivo PDF

**Resposta de Sucesso (201):**
```json
{
  "id": 3,
  "filename": "gravity.pdf",
  "status": "processing",
  "created_at": "2025-12-14T22:35:34.000000"
}
```

**Campos de Resposta:**
- `id`: ID do documento
- `filename`: Nome do arquivo
- `status`: Status do processamento - `"pending"`, `"processing"`, `"ready"`, ou `"error"`
- `created_at`: Data/hora de criação

**Erros:**
- `400`: Tipo de arquivo não suportado (apenas PDF)
- `401`: Não autenticado
- `403`: Apenas admins

---

### Obter Documento
**GET** `/documents/{document_id}`

Obtém informações sobre um documento específico.

**🔒 Requer autenticação: Admin**

**Resposta de Sucesso (200):**
```json
{
  "id": 3,
  "filename": "gravity.pdf",
  "status": "ready",
  "created_at": "2025-12-14T22:35:34.000000"
}
```

**Erros:**
- `401`: Não autenticado
- `403`: Apenas admins
- `404`: Documento não encontrado

---

## Feedback

### Obter Feedback de Tentativa
**POST** `/attempts/{attempt_id}/feedback`

Gera feedback personalizado baseado em RAG para uma tentativa de questionário.

**🔒 Requer autenticação: Student**

**Sem body necessário**

**Resposta de Sucesso (200):**
```json
{
  "attempt_id": 10,
  "summary": {
    "score": 1.0,
    "total": 2,
    "strengths": [
      "Boa compreensão de cinemática básica"
    ],
    "weaknesses": [
      "Revisar conceitos de aceleração"
    ]
  },
  "per_question": [
    {
      "question_id": 1,
      "is_correct": true,
      "explanation": "Resposta correta! A aceleração gravitacional na Terra é aproximadamente 9,8 m/s².",
      "misconception": null,
      "tip": "Continue praticando questões similares.",
      "similar_question": {
        "filename": "fisica_exercicios.pdf",
        "page": 45,
        "description": "Exercício sobre queda livre"
      },
      "study": [
        {
          "filename": "halliday_vol1.pdf",
          "pages": [23, 24, 25],
          "chapter": "Capítulo 2",
          "topic": "Aceleração"
        }
      ]
    },
    {
      "question_id": 2,
      "is_correct": false,
      "explanation": "A resposta correta seria outra opção. Você confundiu velocidade média com velocidade instantânea.",
      "misconception": "Velocidade média vs instantânea",
      "tip": "Lembre-se que velocidade média é calculada pelo deslocamento total dividido pelo tempo total.",
      "similar_question": null,
      "study": [
        {
          "filename": "fisica_basica.pdf",
          "pages": [12, 13],
          "chapter": "Capítulo 1",
          "topic": "Velocidade"
        }
      ]
    }
  ],
  "global_references": [
    {
      "filename": "halliday_vol1.pdf",
      "page": 23,
      "snippet": "A aceleração gravitacional na superfície da Terra..."
    }
  ]
}
```

**Campos de Resposta:**
- `attempt_id`: ID da tentativa
- `summary`: Resumo geral da performance
  - `score`: Pontuação obtida
  - `total`: Total de questões
  - `strengths`: Lista de pontos fortes
  - `weaknesses`: Lista de pontos a melhorar
- `per_question`: Feedback detalhado por questão
  - `question_id`: ID da questão
  - `is_correct`: Se respondeu corretamente
  - `explanation`: Explicação da resposta
  - `misconception`: Conceito mal compreendido (se houver)
  - `tip`: Dica de estudo
  - `similar_question`: Exercício similar recomendado
  - `study`: Materiais de estudo recomendados
- `global_references`: Citações dos documentos utilizados

**Erros:**
- `401`: Não autenticado
- `403`: Tentativa não pertence ao usuário ou apenas estudantes
- `404`: Tentativa não encontrada

---

## Códigos de Status HTTP

- `200 OK`: Requisição bem-sucedida
- `201 Created`: Recurso criado com sucesso
- `400 Bad Request`: Dados inválidos
- `401 Unauthorized`: Não autenticado
- `403 Forbidden`: Sem permissão (role incorreto)
- `404 Not Found`: Recurso não encontrado
- `500 Internal Server Error`: Erro no servidor

---

## Fluxo de Uso Típico

### Para Administradores:
1. `POST /auth/register` - Criar conta admin
2. `POST /auth/login` - Fazer login
3. `POST /documents/upload` - Upload de materiais de estudo (PDFs)
4. `POST /questionnaires/full` - Criar questionário completo
5. `GET /documents/{id}` - Verificar status de processamento

### Para Estudantes:
1. `POST /auth/register` - Criar conta de estudante
2. `POST /auth/login` - Fazer login
3. `GET /questionnaires/` - Listar questionários disponíveis
4. `GET /questionnaires/{id}` - Ver questões do questionário
5. `POST /questionnaires/{id}/attempts` - Submeter respostas
6. `POST /attempts/{attempt_id}/feedback` - Obter feedback personalizado

---

## Observações Importantes

### Autenticação
- Tokens JWT expiram após um período configurado
- Use o token retornado no login em todas as requisições protegidas
- Roles: `admin` para gestão, `student` para fazer questionários

### Content-Type
- JSON: `application/json` (maioria dos endpoints)
- Login: `application/x-www-form-urlencoded`
- Upload: `multipart/form-data`

### Processamento de Documentos
- Upload de PDFs é assíncrono (background task)
- Status `pending` → `processing` → `ready` ou `error`
- Verificar status antes de usar para feedback

### Performance
- Feedback RAG pode levar alguns segundos
- Considere loading states no frontend
- Documentos devem ser processados antes de gerar feedback útil
