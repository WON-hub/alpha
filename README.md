# 제휴업체 어디지?

광운대학교 학생이 소속, 동행자, 위치를 기준으로 이용할 수 있는 제휴식당을 찾는 FastAPI MVP입니다. 일반 사용자는 로그인 없이 추천을 이용하고, `/admin`은 관리자 비밀번호를 입력해야 내부 화면을 볼 수 있습니다.

## 기술 구성

- FastAPI + SQLAlchemy 2.0 + Pydantic
- Supabase Postgres 또는 로컬 SQLite
- Vanilla JavaScript + Leaflet/OpenStreetMap
- CSV, XLS, XLSX, XLSM 일괄등록
- 선택 기능: Gemini API를 이용한 Excel 표준화와 가게 설명 생성

## VS Code에서 실행

PowerShell 터미널에서 프로젝트 폴더를 연 뒤 실행합니다.

```powershell
Set-Location -LiteralPath 'C:\Users\leewo\Documents\우리학교 제휴 앱'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

브라우저에서 다음 주소를 엽니다.

- 사용자 화면: http://127.0.0.1:8000/
- 관리자 화면: http://127.0.0.1:8000/admin

관리자 비밀번호는 `.env`의 `ADMIN_PASSWORD_HASH`에 해시로 저장합니다. 새 비밀번호 해시는 아래처럼 생성한 뒤 출력값을 `.env`에 붙여 넣습니다.

```powershell
python -c "from getpass import getpass; from app.security import make_password_hash; print(make_password_hash(getpass('새 관리자 비밀번호: ')))"
```

## Supabase 연결

`.env`의 `DATABASE_URL`에 Supabase Postgres 연결 문자열을 넣습니다. 운영 배포에서는 Session Pooler 연결을 권장합니다.

```env
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@YOUR_POOLER_HOST:5432/postgres?sslmode=require
SEED_ON_STARTUP=false
```

처음 사용하는 Supabase 프로젝트라면 [supabase/schema.sql](supabase/schema.sql)을 SQL Editor에서 실행하거나, 앱 시작 시 SQLAlchemy가 테이블을 생성하도록 둘 수 있습니다. 이미 사용 중인 DB에는 `ai_summary` 컬럼을 시작 시 자동 보완합니다.

`SUPABASE_URL`과 `SUPABASE_ANON_KEY`는 Google 로그인 동기화 기능에서 사용합니다. DB 비밀번호와 `SECRET_KEY`는 브라우저 코드에 넣지 않습니다.

## 추천 점수

추천 내부 정렬 점수는 다음 CDI를 사용합니다.

```text
CDI = (B × 0.53) + (D × 0.27) + (S × 0.20)
```

- `B`(Benefit): 할인율, 정액 할인, 서비스 혜택을 0~100점으로 환산하고 이용 조건 감점을 최대 20점까지 적용합니다.
- `D`(Distance): 0~100m 5점, 100~200m 4점, 200~400m 3점, 400~600m 2점, 600~1000m 1점, 1000m 이상 0점입니다. (보고서의 600~700m 누락 구간은 1점으로 연속 적용합니다.)
- `S`(Satisfaction): 전체 제휴 매장 평균을 사전값으로 사용하는 베이즈 평균입니다. 최소 신뢰 리뷰 수는 10건이며, 전체 리뷰가 없으면 60점을 초기값으로 사용합니다.
- 혜택이 할인과 서비스를 동시에 제공하거나 복수 혜택으로 분석되면 보고서 기준에 따라 5점 단위의 추가점수를 적용하며, 최종 B는 100점으로 제한합니다.
- 1인당 결제 기준은 항상 12,000원입니다. 검색 반경 제한은 없으며 활성·유효 기간인 제휴를 대상으로 합니다.

CDI 원점수, 예상 절약액, 숫자로 된 할인율은 사용자 카드에 노출하지 않습니다. 대신 카드에서 AI 가게 요약, 혜택 목록, 이용 조건, 적용 가능한 단과대를 바로 확인할 수 있습니다. 같은 업체의 제휴가 여러 개면 한 카드로 합쳐집니다.

혜택 등급은 다음과 같습니다.

- 80~100점: 황금밥알 🌟🍚
- 60~79점: 은빛밥알 ✨🍚
- 40~59점: 고운밥알 🌸🍚
- 0~39점: 한톨밥알 🍚

## 관리자 일괄등록

관리자 화면의 `데이터 일괄등록`에서 **광운대 제휴정보 일괄등록용 다운로드**를 누르면 표준 Excel 양식을 받을 수 있습니다. 파일명은 `광운대 제휴정보 일괄등록용.xlsx`으로 통일되어 있습니다.

표준 열은 아래와 같습니다.

```text
가게명, 카테고리, 주소, 위도, 경도, 제휴대상, 혜택, 시작일, 종료일
```

원본 파일은 `.xlsx`, `.xls`, `.xlsm`, `.csv`, `.txt`를 지원합니다.

1. 기본 형식으로 미리보기: 기존 열 별칭과 혜택 문장을 사용해 변환합니다.
2. AI로 표준 형식 변환: `GEMINI_API_KEY`를 사용해 서로 다른 열 이름과 문장을 표준 열로 매핑합니다.
3. 미리보기에서 검증 결과를 확인한 뒤 저장합니다.
4. `기존 매장 AI 요약 생성`은 아직 요약이 없는 활성 매장의 설명을 채웁니다.

AI 가게 요약은 제휴 혜택을 설명하는 문장이 아니라 매장이 무엇을 하는 곳인지, 어떤 메뉴나 특징으로 알려져 있는지를 설명합니다. 키가 없어도 일반 일괄등록은 사용할 수 있고, AI 버튼만 안내 오류를 표시합니다.

`.env`에 키를 넣으면 활성화됩니다.

```env
GEMINI_API_KEY=발급받은_Gemini_API_KEY
GEMINI_MODEL=gemini-3.5-flash
```

현재 기본 모델은 [Gemini 2.5 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash)이며, 가게 요약과 표준화 모두 Gemini `generateContent` API를 사용합니다.

## 주요 API

- `GET /api/affiliations`
- `GET /api/restaurants`, `GET /api/restaurants/{id}`
- `POST /api/recommendations`
- `POST /api/reviews`, `POST /api/reports`, `POST /api/usage-events`
- `POST /api/admin/login`, `POST /api/admin/logout`
- `GET/POST/PUT/DELETE /api/admin/partnerships...`
- `POST /api/admin/partnerships/bulk-approve`
- `GET /api/admin/import/template`
- `POST /api/admin/import/preview`
- `GET /api/admin/places/search` (admin only, one-time provider lookup)
- `POST /api/admin/places/{restaurant_id}/refresh` (explicit admin refresh)
- `POST /api/admin/ai/analyze-benefit`
- `POST /api/admin/ai/preprocess-benefits`
- `POST /api/admin/import/commit`
- `POST /api/admin/ai/generate-summaries`
- `GET/PUT /api/admin/reports...`

신규 클라이언트는 `/api/v1/...` 경로도 사용할 수 있습니다. 기존 `/api/...` 경로도 호환을 위해 유지합니다.

## Google 로그인

Google 로그인은 Supabase Auth의 Google Provider를 사용합니다.

1. Supabase Dashboard의 Authentication → Providers → Google을 활성화합니다.
2. Google Cloud Console에서 OAuth Web Client를 만들고 Client ID/Secret을 Supabase에 입력합니다.
3. Supabase Auth URL Configuration에 로컬 주소와 배포 주소를 Redirect URL로 등록합니다.
4. `.env`에 `SUPABASE_URL`, `SUPABASE_ANON_KEY`를 설정합니다.

## 테스트 및 배포

```powershell
pytest -q
python -m compileall -q app
```

Render, Railway, Fly.io 등의 Python 서비스에서 다음 명령으로 실행할 수 있습니다.

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

배포 환경 변수에는 최소한 `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `SEED_ON_STARTUP=false`를 등록합니다. AI 기능을 사용할 때만 `GEMINI_API_KEY`를 추가합니다.
