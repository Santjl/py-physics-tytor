# Exemplos de payloads por endpoint

## Auth
### POST /auth/register
```json
{
  "email": "alice@example.com",
  "password": "minha_senha_forte"
}
```

### POST /auth/login (form-data)
```
Content-Type: application/x-www-form-urlencoded

username=alice@example.com&password=minha_senha_forte
```
Resposta
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

## Health
### GET /health
Sem payload. Resposta:
```json
{"status": "ok"}
```

## Questionnaires
### POST /questionnaires/ (admin)
Headers: `Authorization: Bearer <ADMIN_TOKEN>`
```json
{
  "title": "Cinemática",
  "description": "Movimento retilíneo uniforme"
}
```

### GET /questionnaires/
Sem payload.

### GET /questionnaires/{id}
Sem payload.

### POST /questionnaires/{id}/questions (admin)
Headers: `Authorization: Bearer <ADMIN_TOKEN>`
```json
{
  "statement": "Qual a aceleração gravitacional na Terra?",
  "options": [
    {"letter": "A", "text": "9,8 m/s²", "is_correct": true},
    {"letter": "B", "text": "8,9 m/s²", "is_correct": false},
    {"letter": "C", "text": "10 m/s²", "is_correct": false}
  ]
}
```

### GET /questionnaires/{id}/questions
Sem payload.

### POST /questionnaires/{id}/attempts (student)
Headers: `Authorization: Bearer <STUDENT_TOKEN>`
```json
{
  "answers": [
    {"question_id": 1, "selected_option_id": 2},
    {"question_id": 2, "selected_option_id": 5}
  ]
}
```
Resposta:
```json
{
  "attempt_id": 10,
  "score": 1.0,
  "total": 2,
  "answers": [
    {"question_id": 1, "selected_option_id": 2, "is_correct": true},
    {"question_id": 2, "selected_option_id": 5, "is_correct": false}
  ]
}
```

## Documents (admin)
### POST /documents/upload
Headers: `Authorization: Bearer <ADMIN_TOKEN>`
Multipart form:
- `file`: (`gravity.pdf`, `application/pdf`)

Resposta:
```json
{
  "id": 3,
  "filename": "gravity.pdf",
  "status": "processing",
  "created_at": "2025-12-14T22:35:34.000000"
}
```

### GET /documents/{id}
Headers: `Authorization: Bearer <ADMIN_TOKEN>`
Sem payload. Resposta:
```json
{
  "id": 3,
  "filename": "gravity.pdf",
  "status": "ready",
  "created_at": "2025-12-14T22:35:34.000000"
}
```

## Observações
- Use tokens adequados: admin vs student.
- Content-Type: JSON, exceto login (form) e upload (multipart).
