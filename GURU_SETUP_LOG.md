# GURU_SETUP_LOG — 투자구루 판단의견(hub:guru) 설치

허브 실구조가 CLAUDE_HANDOFF.md 가정(셸 빌드 스크립트 1개 → push)과 달라 아래처럼 맞춤. 재두형 승인(2026-10-21).

## 0. 저장소·환경 (2026-10-21)
- 저장소 루트 = `~/report-hub/gh-redirect` (main, 작업 전 clean, HEAD 8e0667d). 리포트 원본은 `~/report-hub/reports/`, 서빙 사본 `serve/`, 발행본 `gh-redirect/` — 셋 다 같은 md(미발행 2건 제외, cmp 확인).
- index.html 생성 주체가 여럿(add_report · amend_report · refresh_prices 30분 cron · rebuild_all · earnings_page). 전부 `hublib.gh_publish()` 로 쓰고 바로 push → 셸 훅 자리 없음.
- Python 3.13(/usr/local/bin/python3), `.gitignore` 신규(`__pycache__/`, `*.bak`, `*.bak-*`).

## 1. 테스트
- `GURU_TEST_REPO=. python3 -m unittest guru.tests.test_guru guru.tests.test_dart` → 12건 OK.

## 2. 키·LLM·레짐
- DART 키: `~/.secrets/dart.env` 에서 실행 시점에만 export(파일·로그에 미기록).
- LLM: `command` 백엔드, `claude -p --output-format text --model sonnet --tools '' --strict-mcp-config`, cwd `~/.guru`(홈 AGENTS.md 미로딩). 호출 테스트 OK.
- 레짐: `make_regime_pykrx.py` 실패(pykrx `'지수명'` — KRX 지수 API 변경). 대체 `~/report-hub/guru_regime.py` = 매크로 원장 영업일 코스피·USDKRW로 산출. 2026-10-21: KOSPI MA200 아래, 60영업일 −21.8%, USDKRW 20일 −3.7%. VKOSPI·외인20 = 없음(None).

## 3. DART 검산
- 306200 세아제강 / 005930 삼성전자 / 131970 두산테스나: 매출·영업이익·지배순이익·자산총계 전부 채워짐, 단위 억원 정상(삼성 FY2024 매출 3,008,709억·자산 5,145,320억 = 기존 실측과 일치). 표: `guru/verify_<코드>.md`.
- 한계: ① CB·BW 조회 실패(`bdwtWithWtsNrdmpBlce` status=101 잘못된 URL → 희석 플래그 미산출) ② TTM 에 영업CF·CAPEX 없음 → 피오트로스키 CF 3항목·버핏 FCF 수익률 '미확인' ③ 감가상각(da) 미추출 ④ 일부 연도 '연결 없음→별도' 폴백.

## 4. 백필 (룰만, LLM 없음)
- 대상 = 원본 `reports/` (amend/rebuild 가 reports 에서 재발행하므로 원본에 넣어야 유지됨).
- `guru backfill reports --llm none` → 369건 처리, 블록 403개(362파일), 코드 없음 7건 건너뜀, DART 호출 2,417회, LLM 0회.
- DART 실패: ETF·ETN 코드(233740·232080·229200·494310·455850·488080·462330 등, corpCode 없음 — 정상) · 950260(외국법인, 사업보고서 재무 없음). 해당 블록은 재무 항목 '데이터부족'.
- 본문 불변 검증: 발행본 367건에서 guru 블록 제거 후 HEAD 와 비교 → 공백 외 차이 0건.

## 5. 후처리
- `guru postprocess gh-redirect` → blocks 401 · index_cards 217 · report_htmls 401.
- index.html: `guru-badge` 217 · `href="./guru.html"` 1 · `data-f="guru:hi"` 1.
- `guru collect` → guru_index.json / guru_ledger.csv (401 블록).

## 6. 훅
- `hublib.py` 에 `_guru_postprocess(names)` 추가(gh-redirect 에서 `python3 -m guru postprocess`, 실패해도 발행 계속, 로그 `~/report-hub/guru_run.log`).
- **미완료**: `gh_publish._do()` 의 `_git("add", ...)` 직전 `names += _guru_postprocess(names)` 한 줄 — 자동권한 분류기 거부로 대기. 이 줄 전까지는 refresh_prices(30분)가 index 를 재생성하면 배지·칩·내비가 빠짐(리포트 md/html 블록은 유지).
- 새 리포트 주입: `~/report-hub/guru_cycle.py`(최근 3일 블록 없는 리포트 → 룰+LLM 주입은 lock 밖, 동기화·발행은 hub_lock 안). 크론 등록 대기.

## 7. 커밋·푸시
- 아래 커밋 참조.
