# 제휴식당 어디지?

광운대학교 학생의 소속, 동행자, 위치, 제휴 혜택을 바탕으로 지금 이용하기 좋은 제휴 매장을 추천하는 웹앱 MVP입니다.

이 저장소에는 앱 소스 코드뿐 아니라 발표에서 구현 과정을 설명할 수 있는 설문·전처리·DB 스냅샷 CSV도 함께 포함되어 있습니다.

## 발표용 핵심 흐름

```text
학생 설문조사
    ↓
혜택(B)·거리(D)·만족도(S)의 중요도 산출
    ↓
제휴 원본 엑셀 정리
    ↓
Gemini가 혜택 문장 구조화 및 점수 입력값 추출
    ↓
Supabase Postgres에 원문·AI 분석 결과·점수 저장
    ↓
사용자 요청 시 DB 조회 + 위치별 거리 점수 계산
    ↓
CDI 기준으로 제휴 매장 추천
```

발표용 참고자료는 [`docs/presentation-data`](docs/presentation-data)에 있습니다.

- `01_survey_results.csv`: 31명 설문 응답과 응답별 정규화 비율
- `02_partnerships_before_ai.csv`: AI 전처리 전 제휴등록 원본 45건
- `03_partnerships_after_ai_db_snapshot.csv`: Supabase에서 AI 전처리된 제휴정보 31건의 DB 스냅샷

## 설문으로 가중치를 정한 근거

설문 문항은 식당을 고를 때 혜택, 이용 만족도, 학교와의 거리의 중요도를 총 10점으로 배분하도록 구성했습니다.

31개 유효 응답의 평균 배점은 다음과 같습니다.

| 요소 | 평균 배점 | 정규화 결과 |
| --- | ---: | ---: |
| 혜택(Benefit, B) | 5.2581 | 52.58% |
| 만족도(Satisfaction, S) | 2.0323 | 20.32% |
| 거리(Distance, D) | 2.7097 | 27.10% |

코드에서는 설문 결과를 발표와 서비스 적용에 사용할 수 있도록 반올림하여 다음 CDI를 사용합니다.

```text
CDI = (B × 0.53) + (D × 0.27) + (S × 0.20)
```

### B: 혜택 점수

관리자가 입력한 혜택 원문을 Gemini가 한 번 분석하여 할인율, 정액 할인, 무료 제공 품목, 적용 메뉴와 이용 조건을 구조화합니다. 이후 점수 계산 결과를 Supabase의 다음 컬럼에 저장합니다.

- `benefit_base_score`: 기본 혜택 점수
- `benefit_bonus_score`: 복수 혜택·할인과 서비스 동시 제공 등에 대한 추가점수
- `benefit_condition_penalty`: 이용 조건 감점
- `benefit_score_cached`: 최종 혜택점수 B
- `benefit_ai_json`: AI가 추출한 구조화 JSON
- `benefit_preprocessed_at`: AI 전처리 시각

최종 혜택점수는 `기본점수 + 추가점수 - 조건감점`으로 계산하며 0~100점으로 제한합니다.

### D: 거리 점수

사용자의 현재 위치와 매장 좌표로 하버사인 거리를 계산합니다. 거리점수는 DB에 고정하지 않고 추천 요청마다 계산합니다.

현재 코드의 거리 구간은 다음과 같습니다.

| 거리 | 점수 |
| --- | ---: |
| 0~100m | 5 |
| 100~200m | 4 |
| 200~400m | 3 |
| 400~600m | 2 |
| 700~1000m | 1 |
| 1000m 이상 | 0 |

보고서 표에 600~700m 구간이 별도로 기재되지 않아, 코드에서는 점수 공백이 생기지 않도록 600~1000m를 1점으로 처리합니다.

### S: 베이즈 만족도

리뷰가 적은 신규 매장이 소수의 극단적인 평점 때문에 불리해지지 않도록 베이즈 평균을 사용합니다.

```text
S = (C × m + N × x) / (C + N)
```

- `C`: 신뢰도 확보를 위한 최소 리뷰 수, 현재 10건
- `m`: 전체 제휴 매장의 플랫폼 평균 점수
- `N`: 해당 매장의 리뷰 수
- `x`: 해당 매장의 실제 평점 환산값

전체 리뷰가 없으면 현재 플랫폼 기본 만족도 60점을 사용합니다.

## AI가 사용되는 기능

- 관리자 제휴 등록·수정 시 혜택 원문 분석
- 기존 제휴정보 전체 혜택 AI 전처리
- 매장에 대한 한 줄 AI 요약
- 추천 상단의 AI 추천 이유 생성

사용자가 검색하고 추천을 요청하는 동안에는 Gemini나 카카오 API를 호출하지 않습니다. 사용자 조회는 Supabase DB의 저장 데이터를 사용하고, 거리점수만 사용자 위치에 따라 계산합니다.

## 좌표 자동 생성

신규 매장 등록 또는 일괄등록에서 위도·경도가 비어 있으면 다음 순서로 보완합니다.

1. 같은 매장이 DB에 있고 유효한 좌표가 있으면 DB 좌표를 재사용합니다.
2. DB 좌표가 없으면 카카오 Local REST API에서 가게명과 주소로 검색합니다.
3. 동일한 매장이 같은 요청에 반복되면 검색 결과를 캐시하여 API를 한 번만 호출합니다.
4. 검색에 실패하면 광운대학교 중심 좌표를 임의로 넣지 않고 등록을 중단합니다.

필요한 환경변수는 다음과 같습니다.

```env
PLACE_SEARCH_PROVIDER=kakao
KAKAO_REST_API_KEY=카카오디벨로퍼스_REST_API_KEY
```

## 기술 구성

- FastAPI
- SQLAlchemy 2.0
- Supabase Postgres
- Vanilla JavaScript
- Leaflet / OpenStreetMap
- Gemini API
- Kakao Local REST API
- CSV, XLS, XLSX, XLSM 일괄등록

## VS Code에서 실행

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행합니다.

```powershell
Set-Location -LiteralPath 'C:\Users\leewo\Documents\우리학교 제휴 앱'
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

접속 주소:

- 사용자 화면: http://127.0.0.1:8000/
- 관리자 화면: http://127.0.0.1:8000/admin

관리자 초기 비밀번호는 프로젝트의 `.env`에 설정된 `ADMIN_PASSWORD_HASH`에 해당하는 값으로 관리합니다. `.env` 자체는 보안을 위해 GitHub에 올리지 않습니다.

## Supabase 설정

`.env`에 Supabase Session Pooler 연결 문자열을 설정합니다.

```env
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@YOUR_POOLER_HOST:5432/postgres?sslmode=require
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_KEY
SECRET_KEY=긴_랜덤_문자열
SEED_ON_STARTUP=false
```

처음 구성하는 Supabase 프로젝트라면 [`supabase/schema.sql`](supabase/schema.sql)을 SQL Editor에서 실행할 수 있습니다.

## 주요 API

- `POST /api/recommendations`: 조건에 맞는 제휴 매장 추천
- `POST /api/reviews`: 리뷰 저장
- `POST /api/admin/login`: 관리자 로그인
- `GET /api/admin/import/template`: 일괄등록 양식 다운로드
- `POST /api/admin/import/preview`: 일괄등록 미리보기 및 좌표 자동 보완
- `POST /api/admin/import/commit`: 일괄등록 저장
- `GET /api/admin/places/search`: 관리자 장소 검색
- `POST /api/admin/places/{restaurant_id}/refresh`: 관리자가 직접 장소정보 새로고침
- `POST /api/admin/ai/analyze-benefit`: 혜택 문장 분석
- `POST /api/admin/ai/preprocess-benefits`: 기존 제휴 혜택 전체 AI 전처리
- `POST /api/admin/ai/generate-summaries`: 매장 요약 생성

## 검증

```powershell
pytest -q
python -m compileall -q app seed.py
node --check app/static/js/admin.js
```

## 발표에서 보여줄 파일

발표 시 GitHub의 [`docs/presentation-data`](docs/presentation-data) 폴더를 열어 다음 순서로 설명할 수 있습니다.

1. 설문 결과로 B·D·S의 상대적 중요도를 수치화했습니다.
2. 원본 제휴 엑셀은 9개 표준 컬럼으로 정리했습니다.
3. AI가 혜택 원문을 분석하고, Supabase에 구조화 JSON과 B·S 점수를 저장했습니다.
4. 최종 CDI의 D는 사용자 위치에 따라 달라지므로 추천 시점에 계산합니다.
