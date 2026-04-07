[English README](README.md)

# SF DB 서버

스마트 팩토리 자동 분류 시스템을 위한 데이터베이스 미들웨어 및 대시보드입니다.

---

## 프로젝트 구조

```
db_server/
├── main.py                  # FastAPI 미들웨어 (로컬 DB)
├── main_remote.py           # FastAPI 미들웨어 (원격 DB — 192.168.3.112)
├── db_setup.py              # 데이터베이스 및 테이블 생성 스크립트
├── db_schema_design.md      # 전체 스키마 참조 문서
├── generate_schema_sheet.py # 스키마를 schema_overview.xlsx로 내보내기
├── requirements.txt         # Python 의존성 목록
├── install.bat              # 최초 설치 스크립트
├── start.bat                # 실행 스크립트 (로컬 DB)
├── start_remote.bat         # 실행 스크립트 (원격 DB)
├── snapshots/               # 검사 스냅샷 이미지 (API를 통해 제공)
└── sf-dashboard/            # React 대시보드 (Vite)
```

---

## 최초 설치

> 새 PC에서 한 번만 실행합니다. Python과 Node.js가 PATH에 등록되어 있어야 하며, MySQL 서비스 시작을 위해 관리자 권한이 필요합니다.

`install.bat` 우클릭 → **관리자 권한으로 실행**

실행 순서:
1. 기존 `dbvenv` 가상환경 삭제 후 재생성
2. MySQL81 서비스 시작 및 준비 완료 대기
3. `requirements.txt`에서 Python 패키지 설치
4. `sf-dashboard` Node 패키지 설치
5. `db_setup.py` 실행하여 데이터베이스 및 테이블 생성

---

## 애플리케이션 실행

### 로컬 DB 모드
`start.bat` 더블클릭 (MySQL 서비스 시작을 위해 관리자 권한 필요)

### 원격 DB 모드
`start_remote.bat` 더블클릭
`main_remote.py`를 사용하여 `192.168.3.112`의 MySQL에 접속합니다.

두 스크립트 모두 아래 주소를 엽니다:
- **API** → `http://localhost:8000`
- **대시보드** → `http://localhost:5173`

---

## 데이터베이스 구성

| 데이터베이스 | 용도 |
|---|---|
| `sf_order` | 고객, 주문, 주문 항목 |
| `sf_inventory` | 선박, 부품, 재고 |
| `sf_production` | 분류 결과, 검사 스냅샷, 센서 로그, 로봇 로그 |
| `sf_report` | 알람, 불량 보고서, 교대 요약 |

전체 테이블 및 컬럼 정의는 `db_schema_design.md`를 참조하세요.
Excel 스키마 개요를 생성하려면 아래 명령을 실행하세요:
```
dbvenv\Scripts\python.exe generate_schema_sheet.py
```

---

## API 개요

| 메서드 | 엔드포인트 | 설명 |
|---|---|---|
| GET | `/api/init-data` | 선박, 부품, 고객 초기 데이터 |
| POST | `/api/customers` | 고객 등록 |
| PUT | `/api/customers/{id}` | 고객 정보 수정 |
| DELETE | `/api/customers/{id}` | 고객 삭제 |
| GET | `/api/parts/{id}` | 부품 상세 조회 |
| POST | `/api/parts` | 부품 추가 |
| PUT | `/api/parts/{id}` | 부품 수정 |
| DELETE | `/api/parts/{id}` | 부품 삭제 |
| GET | `/api/ships` | 선박 목록 |
| POST | `/api/ships` | 선박 추가 |
| PUT | `/api/ships/{id}` | 선박 수정 |
| DELETE | `/api/ships/{id}` | 선박 삭제 |
| GET | `/api/orders` | 주문 목록 |
| POST | `/api/orders` | 주문 생성 (선박 자동 생성 포함) |
| PUT | `/api/orders/{id}` | 주문 수정 |
| DELETE | `/api/orders/{id}` | 주문 삭제 |
| POST | `/api/sort-results/{id}/snapshot` | 검사 스냅샷 업로드 |
| GET | `/api/sort-results/{id}/snapshots` | 결과별 스냅샷 목록 조회 |
| DELETE | `/api/snapshots/{id}` | 스냅샷 삭제 |

스냅샷 파일은 `/snapshots/{filename}` 경로로 정적 제공됩니다.

---

## 검사 스냅샷 워크플로우

각 용접 검사 사이클마다 `sort_results` 행이 생성됩니다. 결과가 `NG`이면 해당 부품은 재용접을 위해 반송되고 재검사가 진행되어 새로운 `sort_results` 행이 추가됩니다. 각 사이클에는 여러 장의 이미지를 `inspection_snapshots`에 저장할 수 있습니다:

```
order_item (주문 항목)
  └── sort_results (사이클 1 — NG)
        └── inspection_snapshots: INITIAL, DEFECT_DETAIL
  └── sort_results (사이클 2 — PASS, 재용접 후)
        └── inspection_snapshots: RECHECK, PASS
```

스냅샷 유형: `INITIAL` (최초 검사) · `RECHECK` (재검사) · `DEFECT_DETAIL` (불량 상세) · `PASS` (합격)
