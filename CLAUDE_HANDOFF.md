# Claude Code 인수인계 — 투자구루 판단의견(hub:guru) 설치·배포

> Mac mini 의 Claude Code(또는 춘식이)에게 이 파일 전체를 그대로 넘기면 된다. 실행 위치는 리포트 허브 저장소(kkkfnf/report-hub)의 로컬 작업 사본 — 춘식이 빌더가 index.html 을 만들고 push 하는 바로 그 폴더.
>
> 사람이 보낼 한 줄(둘 중 하나):
> - zip 을 Mac mini 에 받아 둔 경우: `claude -p "~/Downloads/guru-hub-addon.zip 을 풀어 report-hub 저장소 루트에 넣고, 그 안의 CLAUDE_HANDOFF.md 지시를 순서대로 수행해줘"`
> - GitHub 에 feature/guru 브랜치가 올라가 있는 경우: `claude -p "report-hub 저장소에서 origin/feature/guru 를 fetch 해 현재 브랜치에 merge 한 뒤 CLAUDE_HANDOFF.md 지시를 순서대로 수행해줘"`

## 목표
리포트 md 에 `🧭 투자구루 판단의견` 블록을 주입하는 `guru/` 패키지를 허브에 설치하고, 기존 리포트에 일괄 적용(backfill)한 뒤, 빌더 뒤에 후처리(postprocess)를 훅으로 걸고, 결과를 GitHub Pages 에 반영한다. 설계·산식 설명은 `guru.html`, 운영 가이드는 `GURU_README.md`.

## 절대 규칙
1. 리포트 본문·결정카드·빌더(춘식이) 코드는 수정하지 않는다. 블록 주입(`guru inject`)과 산출물 후처리(`guru postprocess`)만 한다.
2. 비밀키는 파일에 적지 않는다. 기존 파이프라인이 쓰는 환경변수/설정에서 읽는다(아래 3단계).
3. 되돌릴 수 있게 한다: 작업 전 `git stash`/브랜치 확인, 주입은 `--backup` 없이도 `guru remove` 로 제거 가능.
4. 막히면 추측으로 진행하지 말고, 무엇이 막혔는지 `GURU_SETUP_LOG.md` 에 적고 멈춘다.

## 단계

### 0. 저장소·환경 확인
- `git status`, `git log -1`, 현재 브랜치 확인. 작업 중인 변경이 있으면 건드리지 말고 로그에 적는다.
- 저장소 위치를 모르면 찾는다: `mdfind -name index.html | xargs -I{} dirname {} | xargs -I{} sh -c 'test -f {}/ledger.html && echo {}'` 또는 LaunchAgent plist 의 작업 폴더. 찾은 폴더를 `HUB_DIR` 로 부른다.
- `guru/` 폴더가 저장소 루트에 없으면 가져온다: `git fetch origin && git merge --no-edit origin/feature/guru` (브랜치가 있을 때) / 없으면 `unzip ~/Downloads/guru-hub-addon.zip -d /tmp/guru-addon && cp -R /tmp/guru-addon/guru /tmp/guru-addon/guru.html /tmp/guru-addon/GURU_README.md /tmp/guru-addon/CLAUDE_HANDOFF.md "$HUB_DIR"/`.
- `python3 --version` (3.9 이상), `python3 -m guru --help` 가 동작하는지 확인. `.gitignore` 에 `__pycache__/` 와 `*.bak` 가 없으면 추가한다.
- 빌더 스크립트·LaunchAgent 위치 파악: `ls ~/Library/LaunchAgents | grep -i -E "hub|report|chunsik|openclaw"`, plist 의 ProgramArguments 로 빌드 스크립트 경로를 찾는다. 스크립트 안에서 index.html 을 생성하는 호출과 `git push` 호출 위치를 적어 둔다.

### 1. 테스트
```bash
GURU_TEST_REPO=. python3 -m unittest guru.tests.test_guru guru.tests.test_dart -v
```
전부 OK 가 아니면 멈추고 로그에 실패 내용을 적는다.

### 2. DART 키·LLM 설정 찾기
- DART 키: 기존 OpenDART 연동(파이프라인 .env, OpenDART MCP 설정, `~/.zshrc`, launchd plist 의 EnvironmentVariables)에서 `DART`/`OPENDART` 가 들어간 변수명을 찾아 그 값을 `DART_API_KEY` 로 export 한다. 값은 로그에 적지 않는다.
- LLM: Claude CLI 가 로그인되어 있으면 `export GURU_LLM_BACKEND=command GURU_LLM_CMD='claude -p --output-format text'`. 안 되면 `ANTHROPIC_API_KEY` 가 있을 때 `GURU_LLM_BACKEND=anthropic`. 둘 다 없으면 `GURU_LLM_BACKEND=none` 으로 진행하고 로그에 적는다(룰만으로도 블록은 생성됨).
- 레짐 파일: `python3 guru/scripts/make_regime_pykrx.py --out ~/.guru/market_regime.json` (pykrx 없으면 `python3 -m guru regime-sample --out ~/.guru/market_regime.json` 로 임시 생성하고 로그에 "레짐은 샘플값"이라고 적는다).

### 3. DART 추출 검산(사람이 나중에 볼 수 있게 저장)
```bash
for c in 306200 005930 131970; do python3 -m guru fundamentals --code $c --save ~/.guru/fundamentals > guru/verify_$c.md; done
```
세 파일의 표에서 매출·영업이익·지배주주순이익·자산총계가 비어 있거나 단위가 이상하면(예: 억원인데 1e4 배) 멈추고 로그에 적는다. 정상이면 다음으로.

### 4. 블록 1건 → 전체 백필
```bash
python3 -m guru inject --print 20261010-161032-세아제강.md | tail -40     # 블록 모양 확인
python3 -m guru backfill . --since 20260901                                # 9월 이후 리포트 전부 (멱등)
python3 -m guru backfill .                                                  # 나머지
```
DART 호출/LLM 호출 수를 로그에 적는다. 오류가 난 리포트는 파일명과 메시지를 로그에 적고 계속 진행한다.

### 5. 빌더 실행 → 후처리 → 확인
- 빌더(index.html 생성 스크립트)를 평소대로 1회 실행한다(파이프라인이 쓰는 그 명령 그대로).
- `python3 -m guru postprocess .` 실행. 출력 JSON 의 `index_cards` 가 0 보다 커야 한다.
- 확인: `grep -c 'guru-badge' index.html`, `grep -c 'href="./guru.html"' index.html`(=1), `grep -c 'data-f="guru:hi"' index.html`(=1).
- `python3 -m guru collect . --out guru_index.json --csv guru_ledger.csv`

### 6. 훅 등록(빌더 뒤 한 줄)
빌드 스크립트에서 index.html 을 만드는 호출 **직후, git push 전** 에 다음 두 줄을 추가한다(스크립트 언어에 맞게):
```bash
python3 -m guru backfill "$HUB_DIR" --since "$(date -v-3d +%Y%m%d)" >> "$HUB_DIR/guru_run.log" 2>&1 || true   # 새 리포트에 블록(실패해도 빌드는 계속)
python3 -m guru postprocess "$HUB_DIR" >> "$HUB_DIR/guru_run.log" 2>&1 || true
```
수정 전 스크립트는 `*.bak-YYYYMMDD` 로 복사해 둔다. 수정한 파일 경로와 diff 를 로그에 적는다.
(리포트 생성 직후 enrich 를 주입하는 지점이 따로 있으면 `guru inject <그 리포트>` 를 그 바로 뒤에 넣는 편이 더 좋다 — 가능하면 그렇게 하고 로그에 적는다.)

### 7. 커밋·푸시
```bash
git add guru guru.html GURU_README.md CLAUDE_HANDOFF.md GURU_SETUP_LOG.md guru_index.json guru_ledger.csv 2026*.md 2026*.html index.html
git commit -m "guru: 투자구루 판단의견 블록(룰+LLM, 의견 전용) 추가 및 백필"
git pull --rebase && git push
```
푸시 후 1~2분 뒤 `https://kkkfnf.github.io/report-hub/guru.html` 과 index 의 `🧭 구루` 배지를 확인하고 로그에 적는다.

### 8. 로그 파일
`GURU_SETUP_LOG.md` 에 단계별 결과(시각, 명령, 핵심 출력, 막힌 것)를 적어 커밋한다. 사람이 읽을 보고서다 — 짧고 사실만.

## 성공 기준
- index.html 상단 내비에 `🧭 투자구루 판단`, 카드에 `🧭 구루 N/6` 배지, 필터 칩 2개.
- 최근 리포트 md 끝부분(결정카드 앞)에 `<!-- hub:guru:begin:코드 v1 -->` 블록.
- `guru.html` 이 Pages 에서 열림. `GURU_SETUP_LOG.md` 에 DART 검산 결과·호출 수·훅 위치가 적혀 있음.
