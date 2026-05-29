# dart-inform-v2 Backend Data Pipeline

This v2 copy keeps API and Streamlit work out of scope and focuses on the backend data layer:

- SQLite owns filing metadata, chunk text, chunk metadata, and FAISS vector mappings.
- FAISS is split by physical index type: `regular` and `event`.
- Company storage lives under `storage/companies/{stock_code}/`.

## Main entrypoints

```bash
python -m src.pipeline 005930
python -m src.pipeline 351320 --event-only
```

## Retrieval smoke check

```python
from src.retriever import retrieve_context_text
print(retrieve_context_text("삼성전자 DS 부문은 무엇을 생산하나?", ["005930"])["context"][:1000])
```

## Storage layout

```text
storage/
  finance.db
  companies/
    {stock_code}/
      raw/
      cleaned/
      indexes/
        regular/
        event/
```
