# Supabase 공개 데이터 스냅샷

이 폴더의 `snapshot` 디렉터리는 2026-07-30에 연결된 Supabase Postgres에서 추출한 GitHub 발표·검증용 정적 CSV입니다. 앱의 실제 운영 데이터는 계속 Supabase에서 읽으며, 이 CSV를 수정해도 DB에는 반영되지 않습니다.

## 포함된 파일

| 파일 | 내용 |
| --- | --- |
| `snapshot/affiliations.csv` | 단과대·학과 소속 정보 46건 |
| `snapshot/restaurants.csv` | 매장 기본정보·좌표·별점·AI 요약 45건 |
| `snapshot/partnerships.csv` | 제휴 원문·AI 혜택 JSON·B 점수 구성요소 31건 |
| `snapshot/reviews_public.csv` | 공개 가능한 별점 스냅샷 281건 |
| `snapshot/benefit_scoring_rules.csv` | 혜택·조건 점수 규칙 27건 |
| `snapshot/snapshot_manifest.csv` | 파일별 행 수와 생성 시각 |

## 개인정보 및 보안 처리

- 실제 사용자 리뷰는 `review_type=user_review`, `author_display=익명 사용자`로 표시합니다.
- 실제 사용자 리뷰 본문은 `[실제 리뷰 내용 비공개]`로 대체했습니다.
- 발표용 더미 리뷰의 본문만 `[더미 리뷰]` 표시와 함께 남겼습니다.
- 사용자 계정, 관리자 세션, 즐겨찾기, 신고, 이용 이벤트, 일괄등록 작업 이력은 공개 스냅샷에서 제외했습니다.
- DB 비밀번호, API 키, 세션 쿠키, `SECRET_KEY`는 포함하지 않습니다.

`schema.sql`은 테이블 구조를 재현하기 위한 SQL이고, `snapshot/*.csv`는 현재 저장된 데이터를 사람이 확인하기 위한 참고자료입니다.
