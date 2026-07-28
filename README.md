# 제휴업체 어디지?

교내 소속과 동행자 정보를 기준으로 대학가 제휴 혜택을 비교하는 실제 실행 가능한 MVP입니다. 사용자 화면은 로그인 없이 이용하고, `/admin`에서 제휴 CRUD·CSV/Excel 미리보기·신고 처리를 할 수 있습니다.

## 기술 구성

- FastAPI + SQLAlchemy 2.0 + Pydantic
- Supabase Postgres 연결 지원 (`DATABASE_URL`), 자격 증명 없이 로컬 SQLite fallback
- Vanilla JavaScript ES Modules, Leaflet + OpenStreetMap, Chart.js
- Pandas + openpyxl 기반 CSV/Excel import

## 실행

```powershell
Set-Location -LiteralPath 'C:\Users\leewo\Documents\우리학교 제휴 앱'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
Copy-Item .env.example .env
python seed.py
python -m uvicorn app.main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. `SEED_ON_STARTUP=true`이면 빈 DB에 DEMO 샘플 데이터가 자동 생성됩니다.

VS Code에서는 `Run and Debug`에서 `FastAPI · 제휴식당 어디지?` 설정을 선택하고 실행 버튼을 누르면 됩니다. 이 설정은 프로젝트 루트, `.venv`, `.env`, Uvicorn 모듈을 자동으로 사용합니다.

## Supabase 연결

Supabase 프로젝트의 Postgres 연결 문자열을 `.env`의 `DATABASE_URL`에 넣습니다. 운영 환경에서는 Session Pooler 연결 문자열을 권장합니다. 직접 SQL Editor에서 먼저 만들고 싶으면 [`supabase/schema.sql`](supabase/schema.sql)을 실행할 수 있습니다.

```env
DATABASE_URL=postgresql+psycopg://postgres:비밀번호@db.프로젝트참조.supabase.co:5432/postgres?sslmode=require
```

앱 시작 시 SQLAlchemy가 테이블을 생성합니다. 실제 운영에서는 Supabase 백업·마이그레이션 정책에 맞춰 테이블 생성 후 `SEED_ON_STARTUP=false`로 두세요. 애플리케이션은 Supabase의 Postgres를 직접 사용하므로 프론트엔드에 Supabase 비밀키를 노출하지 않습니다.

## 관리자 계정

비밀번호는 코드에 넣지 않고 PBKDF2 해시로 `.env`에 저장합니다. 해시는 다음 명령으로 생성합니다.

```powershell
python -c "from app.security import make_password_hash; print(make_password_hash('원하는-비밀번호'))"
```

출력값을 `ADMIN_PASSWORD_HASH`에 붙여 넣고 서버를 재시작한 뒤 `/admin`으로 접속합니다. 세션은 서명된 HttpOnly 쿠키와 DB의 만료 세션으로 관리합니다.

## 추천 점수

추천 API는 현재 날짜 유효성, 카테고리, 직선거리, 소속 계층(학과 → 단과대 → 대학), 최소 주문/인원, 결제 방식을 순서대로 확인합니다.

`CDI = B × 0.4 + D × 0.2 + S × 0.4`

- B: 할인율·정액/서비스 가치를 0~100으로 정규화하고 적용 범위를 반영
- D: 허용 거리 대비 가까울수록 높은 점수
- S: 평균 별점 ÷ 5 × 100, 리뷰가 없으면 60점과 “리뷰 부족” 표시
- 동점이면 예상 절약 금액 내림차순, 거리 오름차순

추천 요청 예시:

```json
{
  "location": {"lat": 37.6194, "lng": 127.0598, "source": "campus_default"},
  "category": "식사류",
  "budget_per_person": 12000,
  "max_distance_m": 1500,
  "groups": [{"affiliation_id": 3, "count": 2}],
  "payment_method": "카드"
}
```

## import 형식

`.xlsx`, `.xls`, `.csv`, `.txt`를 `/api/admin/import/preview`에 업로드합니다. `restaurant_name`, `category`, `start_date`, `end_date`, `latitude`, `longitude`가 필수이며, `college` 또는 `department`가 기존 소속 이름과 일치해야 저장됩니다. 먼저 고정 컬럼명 규칙으로 변환하고, 오류 행을 미리보기에서 확인한 뒤 `/api/admin/import/commit`으로 저장합니다. Gemini 키가 없어도 일반 CSV/Excel은 동작합니다.

## 주요 API

- `GET /api/affiliations`
- `GET /api/restaurants`, `GET /api/restaurants/{id}`
- `POST /api/recommendations`
- `POST /api/reviews`, `POST /api/reports`, `POST /api/usage-events`
- `POST /api/admin/login`, `POST /api/admin/logout`
- `GET/POST/PUT/DELETE /api/admin/partnerships...`, `POST /api/admin/partnerships/bulk-approve`
- `POST /api/admin/import/preview`, `POST /api/admin/import/commit`
- `GET /api/admin/dashboard`, `GET /api/admin/analytics`, `GET/PUT /api/admin/reports...`

새 클라이언트는 같은 API의 `/api/v1/...` 경로를 사용합니다. 기존 `/api/...` 경로도 이전 화면과의 호환을 위해 유지됩니다.

## 기본 Excel 양식

관리자 로그인 후 `데이터 일괄 등록` 화면에서 `광운대 제휴정보 일괄등록용 다운로드`를 누릅니다. 다운로드 파일명은 `광운대 제휴정보 일괄등록용.xlsx`으로 통일했습니다. 첫 시트의 기본 컬럼은 `가게명, 카테고리, 주소, 위도, 경도, 제휴대상, 혜택, 시작일, 종료일`이며 두 번째 시트에 작성 안내가 있습니다. 제휴대상에 여러 학과/단과대를 넣을 때는 쉼표로 구분합니다. 업로드는 미리보기와 검증을 거친 뒤 `검증 통과 행 저장`을 눌러야 DB에 반영됩니다.

`제휴 정보 관리`에서는 승인 대기 행의 체크박스를 선택한 뒤 `선택 항목 일괄 승인`을 눌러 여러 제휴를 한 번에 운영 중 상태로 변경할 수 있습니다.

## Google 로그인 설정

브라우저의 Google 로그인 버튼은 Supabase Auth의 Google Provider를 사용합니다. 코드에는 Google Client Secret을 넣지 않습니다.

1. Supabase Dashboard → Authentication → Providers → Google을 켭니다.
2. Google Cloud Console에서 OAuth Web Client를 만들고 Client ID/Secret을 Supabase에 입력합니다.
3. Supabase Auth URL Configuration의 Redirect URLs에 로컬 주소 `http://127.0.0.1:8000`과 배포된 주소를 추가합니다.
4. `.env`의 `SUPABASE_URL`, `SUPABASE_ANON_KEY`를 설정한 상태로 서버를 재시작합니다.

로그인 성공 시 브라우저가 Supabase 세션을 받고 `/api/v1/auth/sync`를 호출합니다. 서버는 `users` 테이블에 Google 사용자 ID, 이메일, 이름, 프로필 이미지, 마지막 로그인 시각을 저장합니다. DB 비밀번호와 `SECRET_KEY`는 브라우저로 보내지 않습니다.

## 테스트

```powershell
pytest -q
```

소속 계층 판별, 유효 기간, 적용 범위, 절약액, CDI 입력값 필터링, 만료 제휴 제외를 검증합니다.

## 배포

Render, Railway, Fly.io 등에서 Python 3.12 서비스로 배포할 수 있습니다. 시작 명령은 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`로 설정하고, Supabase `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH`를 배포 환경변수로 등록합니다. Leaflet/OpenStreetMap은 별도 API 키 없이 기본 지도를 제공하며, 주소 자동 좌표 변환이 필요할 때만 `GOOGLE_GEOCODING_API_KEY`를 추가합니다.
