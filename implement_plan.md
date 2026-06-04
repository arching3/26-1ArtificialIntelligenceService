# 구현 계획: OpenDART XML 기반 정기공시 청킹 개선

## 배경

현재 정기공시 인덱싱은 DART 원문을 텍스트로 정리한 뒤 `II. 사업의 내용` 전체를 2500자 단위 `RecursiveCharacterTextSplitter`로 나눈다. 이 방식은 구현은 단순하지만, 사업 부문/위험/연구개발/수주/설비/표 같은 의미 단위가 섞여 LLM 요약 카드가 덜 깔끔해진다.

OpenDART 공식 문서상 `document.xml`은 `rcept_no`로 공시서류 원본파일을 내려주는 API이며, 응답 포맷은 `Zip FILE (binary)`다. 따라서 원문 XML을 활용하되, XML DOM이 곧바로 의미론적 섹션 트리를 보장한다고 가정하지 않는다.

공식 문서:
- https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003
- https://opendart.fss.or.kr/intro/main.do

## 목표

- 정기공시 원문에서 섹션, 문단, 표의 경계를 최대한 보존해 chunk 품질을 높인다.
- 요약 카드 생성에 필요한 chunk가 사업 개요, 매출/제품, 위험, 연구개발, 설비/투자, 수주/계약 등으로 더 잘 분리되게 한다.
- 기존 인덱싱 파이프라인과 DB/index 저장 구조는 크게 바꾸지 않는다.
- XML 파싱 실패나 예외적인 보고서 형식에서는 현재 텍스트 기반 청킹으로 fallback한다.

## 구현 범위

### 1. 원문 파싱 계층 추가

새 모듈 후보: `src/filing_parser.py`

- `parse_filing_document(raw_document: str) -> ParsedFiling`
- BeautifulSoup/lxml 기반으로 XML/HTML-like 원문을 파싱한다.
- `title`, `p`, `div`, `section`, `table`, `tr`, `td`, `th` 계열 태그를 구조화한다.
- 태그가 불안정한 보고서는 기존 `_clean_text()` 결과를 함께 보관한다.

핵심 자료 구조:

```python
@dataclass
class ParsedBlock:
    block_type: str  # heading, paragraph, table
    text: str
    markdown: str = ""
    level: int = 0
    order: int = 0

@dataclass
class ParsedSection:
    title: str
    path: list[str]
    blocks: list[ParsedBlock]
    start_order: int
    end_order: int
```

### 2. 섹션 탐지 개선

현재는 정리된 텍스트에서 `II. 사업의 내용` 시작/종료 패턴을 찾는다. 개선 후에는 다음 순서로 탐지한다.

1. XML/HTML 태그 중 제목 후보를 수집한다.
2. 제목 텍스트에서 `II. 사업의 내용`, `2. 사업의 내용`, `제2부 사업의 내용`을 찾는다.
3. 다음 대분류인 `III. 재무에 관한 사항` 전까지 block을 잘라낸다.
4. XML 제목 후보가 부족하면 현재 `_extract_business_section(clean_text)`를 fallback한다.

제목 후보 필터:
- 짧은 단일 라인
- 표 내부 cell이 아닌 블록
- `^\d+\.\s+`, `^[가-하]\.\s+`, `^\(\d+\)`, `^\([가-하]\)` 패턴
- `사업의 개요`, `주요 제품`, `원재료`, `생산`, `매출`, `수주`, `위험`, `연구개발`, `설비`, `투자` 키워드

### 3. 섹션 기반 청킹

새 함수 후보: `chunk_business_sections(parsed_sections, fallback_text) -> list[BusinessChunk]`

- 대분류/중분류 제목을 chunk metadata에 저장한다.
- 한 섹션이 너무 길면 문단 경계 기준으로 1000~1400자 단위 child chunk를 만든다.
- overlap은 100~180자로 줄인다.
- 기존 2500자 chunk는 fallback 전용으로 유지한다.

권장 metadata:
- `section`
- `section_path`
- `section_title`
- `section_level`
- `chunk_strategy`
- `block_types`
- `receipt_no`
- 기존 `report_kind`, `business_year`, `company_name` 등

### 4. 표 처리 분리

현재 `_clean_text()`는 표를 markdown 또는 plain text로 본문에 섞는다. 개선 후에는 표 block을 별도 chunk 후보로 만든다.

- 작은 표: markdown table로 `table_text` chunk 생성
- 대형 표: 행 단위 요약/분할 chunk 생성
- 단위/주석 표: plain text annotation chunk 생성
- 표 앞뒤 제목을 `section_path`에 연결

표 chunk metadata:
- `data_type = "table_text"`
- `section_path`
- `table_index`
- `row_count`, `col_count`

### 5. 위험 문단 추출 개선

현재는 사업 chunk 전체에서 위험 키워드를 찾고, 같은 chunk를 `risk_text`로 중복 저장한다. 개선 후에는 위험 관련 섹션과 문단을 먼저 분리한다.

- 제목에 `위험`, `리스크`, `우발`, `소송`, `제재` 등이 있으면 해당 섹션을 risk section으로 표시한다.
- risk section 내부는 문단 단위로 더 작게 chunk한다.
- 일반 섹션에서도 high-signal risk keyword가 있는 문단만 `risk_text` 후보로 만든다.

### 6. 파이프라인 연결

`src/pipeline.py`의 정기공시 루프를 다음 흐름으로 바꾼다.

1. `raw_document` 저장
2. `parsed = parse_filing_document(raw_document)`
3. `clean_text = parsed.clean_text or clean_document(raw_document)`
4. `business_sections = extract_business_sections(parsed, clean_text)`
5. `business_chunks = chunk_business_sections(business_sections, fallback_text)`
6. `build_regular_chunk_records()`에 section-aware chunk를 전달

기존 `chunk_business_text()` 경로는 fallback 및 비교용으로 남긴다.

## 단계별 작업

### Phase 1: Parser와 fallback 추가

- `src/filing_parser.py` 추가
- 원문에서 block/section 후보를 추출한다.
- `parse_filing_document()` 실패 시 기존 `clean_document()` 경로가 유지되게 한다.
- 저장소 내 샘플 XML 1~2개로 block 수, section 후보, table 후보를 로깅한다.

### Phase 2: Section-aware chunk 생성

- `BusinessChunk` 형태를 도입하거나 dict 기반으로 chunk text와 metadata를 함께 전달한다.
- `build_regular_chunk_records()`가 문자열 list뿐 아니라 section metadata가 있는 chunk도 처리하게 한다.
- 기존 DB schema 변경 없이 `metadata` JSON에 section 정보를 넣는다.

### Phase 3: Table/risk chunk 분리

- 표 chunk를 `table_text`로 별도 저장한다.
- 위험 문단은 section-aware 기준으로 `risk_text`를 생성한다.
- 기존 risk keyword 함수는 재사용하되 입력 단위를 chunk 전체에서 문단/섹션 단위로 낮춘다.

### Phase 4: 품질 점검

검증을 자동화한다면 다음 지표를 본다.

- 보고서별 chunk 수가 과도하게 늘지 않는지
- `section_path`가 비어 있는 chunk 비율
- `table_text`, `risk_text`, `business_text` 분포
- 요약 카드 생성에 사용된 retrieved chunk의 section 다양성

이번 구현에서 검증을 생략해야 한다면 최소한 parser 실패 시 기존 인덱싱이 계속 동작하도록 fallback만 강하게 둔다.

## 범위 밖

- OpenDART 원문 다운로드 방식 자체 교체
- DB schema 변경
- LLM prompt 대규모 개편
- 실시간 UI 변경
- XBRL 재무제표 전체 파싱

## 기대 효과

- 요약 카드가 거대한 텍스트 조각보다 의미 단위 chunk를 참조하게 된다.
- 제품/매출/위험/연구개발/설비/수주 같은 항목별 요약 안정성이 좋아진다.
- 표가 본문 문장과 섞이는 문제가 줄어든다.
- XML 구조가 깨진 보고서에서도 기존 방식으로 인덱싱이 계속된다.
