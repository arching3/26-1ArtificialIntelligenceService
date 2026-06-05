# API Specification

Backend entrypoint: `src/api_server.py`

Run locally:

```bash
uvicorn src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

Base URL:

```text
http://127.0.0.1:8000
```

FastAPI docs:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/openapi.json
```

## Notes

- Authentication is currently development-only.
- `POST /api/dev-login` stores only a process-local username.
- Watchlist and index job status are stored in process memory.
- Filing metadata, chunks, financial data, and FAISS indexes are persisted under `storage/`.
- Stock APIs currently return deterministic mock data for UI integration, not live market data.

## Endpoints

```http
GET    /api/health
GET    /api/me
POST   /api/dev-login

GET    /api/me/watchlist
POST   /api/me/watchlist
DELETE /api/me/watchlist/{company_value}

GET    /api/companies/search?query={keyword}
POST   /api/companies/list

POST   /api/companies/{company_value}/index
GET    /api/companies/{company_value}/index-status

GET    /api/companies/{company_value}/summary
POST   /api/companies/{company_value}/summary

GET    /api/companies/{company_value}/filings?index_type={regular|event}&limit=50
GET    /api/filings/{receipt_no}

POST   /api/chat
POST   /api/companies/stocks
POST   /api/companies/stocks_realtime
```

## Health

### `GET /api/health`

Returns service status.

Response:

```json
{
  "status": "ok",
  "service": "dart-lens-backend",
  "time": "2026-06-04T12:34:56"
}
```

## Development User

### `GET /api/me`

Returns the current development user.

Response:

```json
{
  "username": "dev",
  "auth": "dev"
}
```

### `POST /api/dev-login`

Sets the current development username.

Request:

```json
{
  "username": "dev"
}
```

Response:

```json
{
  "username": "dev",
  "auth": "dev"
}
```

## Watchlist

### `GET /api/me/watchlist`

Returns the current process-local watchlist.

Response:

```json
{
  "username": "dev",
  "companies": ["005930", "351320"]
}
```

### `POST /api/me/watchlist`

Replaces the current watchlist and queues indexing jobs for resolved companies.

Request:

```json
{
  "companies": ["005930", "삼성전자"]
}
```

Response:

```json
{
  "ok": true,
  "companies": ["005930", "삼성전자"],
  "index_jobs": [
    {
      "stock_code": "005930",
      "corp_name": "삼성전자",
      "status": "queued",
      "started_at": "2026-06-04T12:34:56",
      "updated_at": "2026-06-04T12:34:56",
      "error": "",
      "result": null
    }
  ]
}
```

### `DELETE /api/me/watchlist/{company_value}`

Removes a company from the watchlist. `company_value` may be a company name or stock code.

Response:

```json
{
  "username": "dev",
  "companies": ["351320"]
}
```

### `POST /api/companies/list`

Alias for replacing the current watchlist. Same request and response as `POST /api/me/watchlist`.

## Companies

### `GET /api/companies/search`

Searches companies by name, stock code, or known fallback entries.

Query parameters:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `query` | string | `""` | Search keyword. |

Response:

```json
{
  "companies": [
    {
      "stock_code": "005930",
      "corp_name": "삼성전자"
    }
  ]
}
```

Company objects may include additional fields depending on the lookup source.

## Indexing

### `POST /api/companies/{company_value}/index`

Queues a background indexing job for a company. `company_value` may be a company name or stock code.

Response when queued:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "status": "queued",
  "started_at": "2026-06-04T12:34:56",
  "updated_at": "2026-06-04T12:34:56",
  "error": "",
  "result": null
}
```

Response when already indexed:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "status": "ready",
  "indexes": {
    "regular": {
      "ready": true,
      "index_file_exists": true,
      "active_chunks": 95,
      "path": "storage/companies/005930/indexes/regular"
    },
    "event": {
      "ready": true,
      "index_file_exists": true,
      "active_chunks": 4,
      "path": "storage/companies/005930/indexes/event"
    }
  },
  "updated_at": "2026-06-04T12:34:56"
}
```

### `GET /api/companies/{company_value}/index-status`

Returns current index status. `status` can be `queued`, `indexing`, `ready`, `failed`, or `not_indexed`.

Response:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "status": "ready",
  "indexes": {
    "regular": {
      "ready": true,
      "index_file_exists": true,
      "active_chunks": 95,
      "path": "storage/companies/005930/indexes/regular"
    },
    "event": {
      "ready": true,
      "index_file_exists": true,
      "active_chunks": 4,
      "path": "storage/companies/005930/indexes/event"
    }
  },
  "updated_at": "2026-06-04T12:34:56"
}
```

## Summary

### `GET /api/companies/{company_value}/summary`

Returns summary card text for a company.

Response:

```json
{
  "overview": "사업 개요 요약...",
  "benefit": "분기보고서 (2026.03) 3개월 누적 기준 매출액 ...",
  "earnings": "최근 저장된 보고서는 ...",
  "risk": "리스크 요약...",
  "changing": "최근 이벤트 공시 요약...",
  "status": "정기공시 인덱스: 준비됨, 이벤트 공시 인덱스: 준비됨",
  "anomaly": "최근 이벤트 공시로 ... 등이 저장되어 있습니다."
}
```

### `POST /api/companies/{company_value}/summary`

Returns summary card text. If `name` is provided in the body, it is used for company resolution instead of the path value.

Request:

```json
{
  "name": "삼성전자",
  "period": "latest"
}
```

Response: same as `GET /api/companies/{company_value}/summary`.

## Filings

### `GET /api/companies/{company_value}/filings`

Returns filings for a company.

Query parameters:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `index_type` | string or null | `null` | Optional index filter. Expected values are `regular` or `event`. |
| `limit` | integer | `50` | Maximum number of filings. |

Response:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "filings": [
    {
      "rcept_no": "20260515002181",
      "receipt_no": "20260515002181",
      "report_name": "분기보고서",
      "rcept_dt": "20260515",
      "receipt_date": "20260515",
      "filing_type": "regular",
      "detail_type": "quarterly",
      "index_type": "regular",
      "raw_path": "storage/companies/005930/raw/20260515002181.xml",
      "cleaned_path": "storage/companies/005930/cleaned/20260515002181.txt"
    }
  ]
}
```

### `GET /api/filings/{receipt_no}`

Returns one filing by receipt number.

Response:

```json
{
  "rcept_no": "20260515002181",
  "receipt_no": "20260515002181",
  "report_name": "분기보고서",
  "rcept_dt": "20260515",
  "receipt_date": "20260515",
  "filing_type": "regular",
  "detail_type": "quarterly",
  "index_type": "regular",
  "raw_path": "storage/companies/005930/raw/20260515002181.xml",
  "cleaned_path": "storage/companies/005930/cleaned/20260515002181.txt"
}
```

## Chat

### `POST /api/chat`

Answers a disclosure-grounded question. Stock prediction, buy/sell advice, target prices, and portfolio allocation advice are blocked by the answer engine.

Request:

```json
{
  "prompt": "삼성전자 주요 리스크는?",
  "message": null,
  "company": "삼성전자",
  "company_name": null,
  "corp_code": null,
  "stock_code": "005930",
  "period": "latest"
}
```

Field behavior:

| Field | Description |
| --- | --- |
| `prompt` | Primary question text. |
| `message` | Fallback question text if `prompt` is empty. |
| `stock_code` | Preferred company identifier if present. |
| `corp_code` | Fallback company identifier. |
| `company` | Fallback company identifier. |
| `company_name` | Fallback company identifier. |
| `period` | Accepted by the API model but not directly used by the route. |

Response shape is produced by `src.answer_engine.answer_question` and may include:

```json
{
  "answer": "공시 기반 답변...",
  "route": "raw_filing_rag",
  "sources": [
    {
      "receipt_no": "20260515002181",
      "report_name": "분기보고서"
    }
  ],
  "missing_indexes": []
}
```

## Stocks

### `POST /api/companies/stocks`

Returns historical stock data for UI integration. Current implementation is mock data.

Request:

```json
{
  "company": "삼성전자",
  "name": null,
  "period": "1M"
}
```

Response:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "period": "1M",
  "prices": []
}
```

Actual response fields depend on `src.stock_service.fetch_stock_history`.

### `POST /api/companies/stocks_realtime`

Returns realtime-style stock data for UI integration. Current implementation is mock data.

Request:

```json
{
  "company": "삼성전자",
  "name": null,
  "period": null
}
```

Response:

```json
{
  "stock_code": "005930",
  "corp_name": "삼성전자",
  "price": 0,
  "change": 0,
  "change_rate": 0
}
```

Actual response fields depend on `src.stock_service.fetch_realtime_stock`.

## Error Responses

Company lookup failure:

```json
HTTP 404
{
  "detail": "company not found: {value}"
}
```

Filing lookup failure:

```json
HTTP 404
{
  "detail": "filing not found"
}
```

FastAPI validation errors use the default `422 Unprocessable Entity` response format.
