# 🧭 투자구루 판단의견 (hub:guru) — 설치·운영 가이드

리서치 리포트 허브의 각 종목 리포트에 **룰 기반 6구루 점수 + LLM 정성 필터** 블록을 붙이는 독립 모듈입니다.
설계·산식·검증 게이트의 전체 설명은 `guru.html`(허브에 올리면 `https://kkkfnf.github.io/report-hub/guru.html`)에 있습니다.

- 의존성: Python 3.9+ 표준 라이브러리만 (pykrx 는 레짐 생성 예시 스크립트에서만 선택 사용)
- 리포트 본문은 절대 수정하지 않음(마커 블록 삽입/교체만). 결정카드 판정은 불변(의견 전용).

## 1. 설치 (허브 저장소에 복사)

```bash
cd ~/report-hub              # kkkfnf/report-hub 작업 사본
cp -r /path/to/guru ./guru   # 패키지
cp /path/to/guru.html ./     # 구현 설명 페이지 (내비 링크는 postprocess 가 자동 추가)
python -m guru --help
```

`.gitignore` 에 `*.bak` 를 추가하세요(`--backup` 옵션 사용 시). 캐시·재무 JSON 은 `~/.guru/` 아래에 두므로 저장소에 들어가지 않습니다.

## 2. 환경변수

| 변수 | 용도 |
|---|---|
| `DART_API_KEY` | OpenDART 키(필수 — 없으면 `--no-dart` 로 시장·카드 기반 항목만 계산) |
| `GURU_LLM_BACKEND` | `anthropic` / `command` / `none`(기본) |
| `ANTHROPIC_API_KEY`, `GURU_LLM_MODEL` | anthropic 백엔드 (기본 모델 `claude-sonnet-5-5`, temperature 0) |
| `GURU_LLM_CMD` | command 백엔드: 프롬프트를 stdin 으로 받아 JSON 을 stdout 으로 내는 명령 (예: `claude -p --output-format text`) |
| `GURU_LLM_CACHE` | LLM 응답 캐시 폴더(기본 `~/.guru/cache/llm`) |

## 3. 첫 실행 — 검산부터

```bash
python -m guru fundamentals --code 306200        # DART 추출표 출력 → 사업보고서·반기보고서와 대조
python -m guru fundamentals --code 005930 --save ~/.guru/fundamentals
```

추출표의 계정 매칭이 틀리면 `~/.guru/fundamentals/<코드>.json` 을 손으로 고치세요. 그 파일이 있으면 DART 보다 우선 적용됩니다.
금융·지주는 `--sector-group 금융|지주` 로 지정하면 그린블라트가 '해당없음'으로 처리됩니다.

## 4. 리포트에 주입

```bash
python -m guru inject 20261010-161032-세아제강.md                 # 1건(멱등: 다시 실행하면 교체)
python -m guru inject --codes 306200 --print 20261010-161032-세아제강.md   # 특정 종목만 + 블록 stdout
python -m guru backfill . --since 20260901                        # 블록 없는 리포트 일괄
python -m guru backfill . --force --llm none                      # 룰만으로 전부 재생성
python -m guru remove 20261010-161032-세아제강.md                 # 블록 제거
```

## 5. 허브 빌더 뒤 후처리 (index·html 반영)

```bash
python -m guru postprocess .            # index.html: 내비 링크·필터 칩·카드 배지(data-guru) / 리포트 html: 블록 반영
python -m guru collect . --out guru_index.json --csv guru_ledger.csv   # 원장 조인용
```

**훅 순서**: 리포트 생성 → enrich 주입(기존) → `guru inject` → 빌더(index/html) → `guru postprocess` → `git push`.
가격 갱신(30분)마다 index 가 재생성되므로 LaunchAgent 빌드 스크립트에서 빌더 호출 바로 다음 줄에 `python -m guru postprocess .` 를 넣으세요(수 초).

## 6. 레짐·유니버스 파일(선택이지만 권장)

```bash
python guru/scripts/make_regime_pykrx.py --out ~/.guru/market_regime.json   # KOSPI MA200·60일·외인 20일 (VKOSPI·USDKRW 는 매크로 잡에서 보강)
python -m guru universe-build --codes codes.txt --mcap mcap.json --out ~/.guru/universe_stats.json   # 그린블라트 순위용(DART 대량 조회, 하루 1회)
```

레짐 파일이 없으면 드러켄밀러 레짐 점수는 중립 0.5, 유니버스 파일이 없으면 그린블라트는 절대 스케일로 계산되며 블록에 그 사실이 표기됩니다.

## 7. 테스트

```bash
GURU_TEST_REPO=~/report-hub python -m unittest guru.tests.test_guru guru.tests.test_dart -v
```

2026-10-19 저장소 355건 기준: 종목코드 식별 349 · 결정카드 322 · enrich 시장데이터 347 · 복수종목 리포트 29.

## 8. 문서 재생성

가중치·임계값을 `guru/config.py` 에서 바꾸면 `RULES_VERSION` 을 올리고 `python -m guru docs --out guru.html` 로 페이지를 다시 만듭니다(표가 config 에서 자동 생성).

## 9. 검증 게이트(요약)

v1 은 의견 전용입니다. 원장에서 D+20 평가 ≥60건, 합의 hi − lo 초과수익 ≥3%p(부트스트랩 p<0.1)가 확인될 때만 v2 에서 판정 입력으로 승격합니다. 그 전에는 사후 성과를 보고 가중치를 손대지 않습니다.
