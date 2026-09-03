# Chronon — 설계 계획

## 0. 포지셔닝 (이 도구가 무엇인가)

Chronon은 **문서 단위 · 로컬 · 불변 이력**을 시간 축으로 색인하는 버전 관리 시스템이다.

> **git** = 저장소 단위 · 공개 · 가변(rebase/squash/amend) 이력. 간격은 **사람의 커밋 습관**이 결정.
> **chronon** = 문서 단위 · 로컬 · 불변 이력. **모든 항목에 의도된 message가 붙어 있고**, 시간으로 주소 지정된다.

### 0.1. 핵심 목적
**"현재 버전과 특정 날짜 버전의 차이를 본다"** — 이게 이 프로젝트의 존재 이유다.

```bash
chronon diff docs.yml --from 2026-08-01 --to working
```

### 0.2. git으로 이걸 하기 어려운 이유
1. **`HEAD@{2026-08-01}` 은 신뢰할 수 없다.** reflog 기반이라 로컬 전용이고 만료된다(기본: 도달 가능 90일, 도달 불가 30일 — `gc.reflogExpire`). clone한 저장소엔 아예 없다. 애초에 "커밋 시점"이 아니라 "내 로컬 ref가 움직인 시점"을 가리킨다.
2. **`git log --until=... -- file` 의 답은 시간이 지나면 바뀐다.** committer date 기준인데 rebase / cherry-pick / squash / amend가 그 날짜를 다시 쓴다. 감사 추적으로 쓸 수 없다.
3. **해상도가 저장소 단위 커밋 습관에 종속된다.** 두 git 커밋 사이에 파일을 40번 고쳐도 git이 아는 상태는 2개다. (chronon도 **커밋한 것만** 이력이 된다 — 차이는 해상도가 아니라 **커밋 비용**에 있다. §0.3)
4. **텍스트 diff뿐이다.** YAML/JSON에서 키 순서·들여쓰기·인용부호 변경이 전부 노이즈로 잡힌다.

### 0.3. chronon이 갖는 성질
- **불변 이력** — rebase/amend/squash가 없다. "X 시점의 상태"는 **영원히 같은 답**을 낸다.
- **전부 이름이 붙은 이력** — 커밋에 message가 **필수**다. 시점 조회 시 내용뿐 아니라 "왜 그랬는지"가 같이 나온다. (git은 `--allow-empty-message`까지 허용하고, 이력이 조밀한 구간은 대개 `wip`/`fix` 같은 쓰레기 message다.)
- **커밋 비용이 낮아 이력이 조밀해진다** — chronon의 해상도도 결국 커밋 빈도가 결정한다. 다만 커밋 비용이 git과 다르다:
  1. **범위가 문서 1개** — "저장소 전체가 일관된 상태"라는 선언이 아니라 "이 문서에 대한 완결된 진술"이라 이름 붙이는 문턱이 낮다
  2. **로컬 이력** — 공개되지 않으므로 squash/정리 압박이 없다. 뭉칠 이유가 없다
  3. **1차 사용자가 에이전트** — 사람이 커밋을 뭉치는 진짜 이유는 message 작성의 주의 비용인데, 에이전트에겐 그 비용이 0에 가깝다. 방금 뭘 했는지 이미 알고 있다

  그래서 **message 필수 규칙과 조밀한 이력이 충돌하지 않는다.**
- **구조적 diff** — 값 단위로 비교한다. `servers.web.port: 8080 → 9090`.

### 0.4. Non-goals (하지 않는 것 — 스코프 방어선)
브랜치 · 머지 · rebase · remote · push/pull · blame(텍스트 라인 단위) · bisect · staged 영역 · 태그 · 서브모듈 · **다중 리소스 원자적 커밋(transaction)**.

**커밋 단위는 문서 1개다. 여러 문서를 한 커밋으로 묶지 않는다.**
"여러 파일이 함께 바뀐 하나의 상태"를 표현하는 것은 **저장소 단위 커밋 = git의 모델**이다. 그 일관성이 필요하면 git 커밋이 그 역할을 한다(§0.5). chronon이 이걸 흉내내면 리소스별 독립 선형 이력이라는 전제가 무너지고, 시점 조회(`as_of`)가 "어느 리소스 기준의 시점인가"를 되묻게 된다 — git의 DAG로 되돌아가는 길이다.

**이 중 무엇이 필요해지면 chronon이 아니라 git을 쓴다.** chronon이 머지나 브랜치를 구현하기 시작하면 그건 열등한 git이 된 것이고, 그 시점에 프로젝트는 실패한 것이다.

### 0.5. git과의 병행
chronon은 git을 대체하지 않고 **병행**한다. 래핑하지도 않는다(`chronon commit`이 `git commit`을 부르지 않는다 — 커밋 단위가 문서 1개 vs 저장소 전체로 다르고, 래핑하는 순간 git의 브랜치/충돌 세계가 전부 새어 들어온다).

| | git | chronon |
|---|---|---|
| 단위 | 저장소 | 문서 1개 |
| 축 | 변경 | 시간 |
| 가변성 | 가변 (rebase) | **불변** |
| 범위 | 공유 · 원격 | 로컬 |
| 역할 | 릴리스 단위 장기 이력, 협업 | 조밀한 시점 조회, 구조적 diff, 감사 |

두 이력은 중복이 아니라 **해상도가 다른 두 레이어**다. 자세한 병행 규칙은 §11.

---

## 1. 목표 (동작 요약)

에이전트와 사람이 초기화한 디렉터리 아래의 파일을 자유롭게 읽고, 검증된 작업본을 문서별 불변 이력으로 남기는 시스템이다. 시작점은 git과 같은 `chronon init [DIRECTORY]`이며, 저장소 설정과 모든 이력은 루트의 `.chronon/` 아래에 둔다.

중간 저장은 작업본(working copy)으로 자유롭게 하고(snapshot 안 남김), 의미 있는 시점에만 message를 달아 commit 한다. staged/modified 단계 구분은 없다.

**동등한 두 인터페이스:** CLI는 사람이 쓰는 기본 진입점이고 MCP(Model Context Protocol)는 에이전트가 같은 코어를 호출하는 인터페이스다.

**스택:** Python + Typer CLI + MCP 서버 (둘 다 operation layer를 래핑) + PyYAML + jsonschema

---

## 2. 디렉터리 구조

```
/Users/hybrid/Projects/chronon/
├── pyproject.toml
├── README.md
├── PLAN.md                  # 이 파일
├── src/
│   └── chronon/
│       ├── __init__.py
│       ├── core/            # 핵심 로직 (MCP와 CLI가 공유)
│       │   ├── __init__.py
│       │   ├── store.py     # 문서 저장소 (경로, 작업본, snapshot 디렉터리 관리)
│       │   ├── snapshot.py  # snapshot 생성/조회, index.jsonl 관리
│       │   ├── revspec.py   # revspec 리졸버 (seq | working | latest | 날짜 | 상대시간)
│       │   ├── diff.py      # 구조적 diff 엔진 (값 단위) + 텍스트 diff 폴백
│       │   ├── path.py      # dot-path 파싱/조회/설정 (diff·set·path_history 공유)
│       │   ├── state.py     # 작업본 상태 판정 (untracked | clean | dirty | foreign)
│       │   ├── vaults.py    # 전역(사용자) vault 레지스트리 (name → 저장소 루트)
│       │   ├── docs.py      # 에이전트 문서(CHRONON.md 등) 사용법 섹션 생성/갱신 (MCP 대용, §6.2)
│       │   ├── lock.py      # advisory lock + lease (Phase 2)
│       │   ├── harness.py   # 검증 harness dispatcher (확장자 기반 선택)
│       │   └── errors.py    # 커스텀 예외 (LockError, ValidationError, ForeignChangeError...)
│       ├── harness/         # 확장자별 YAML/JSON/text 파싱 + jsonschema 검증
│       │   ├── __init__.py
│       │   └── base.py      # Issue, parse_content, validate_content dispatcher
│       ├── api/             # MCP와 CLI가 공유하는 함수 레이어 (순수 함수)
│       │   ├── __init__.py
│       │   └── operations.py
│       ├── mcp_server.py    # MCP 서버. api.operations를 tool로 노출
│       ├── cli.py           # Typer CLI. api.operations를 명령으로 노출
│       └── schemas/
└── tests/
    ├── test_revspec.py      # 시간 주소 해석 (핵심)
    ├── test_diff.py         # 구조적 diff (핵심)
    ├── test_path.py         # dot-path 문법 (핵심)
    ├── test_snapshot.py
    ├── test_state.py        # untracked/clean/dirty/foreign 판정 + accept
    ├── test_vaults.py        # 전역 vault 레지스트리 + CLI [vault] 자리
    ├── test_agents_md.py     # 에이전트 문서(CHRONON.md 등) 생성/멱등 갱신/기존 내용 보존
    ├── test_harness.py
    ├── test_lock.py
    ├── test_operations.py
    └── test_mcp_server.py

# chronon init 한 사용자 프로젝트
project/
├── docs.yml                  # 작업본 (루트 아래 임의 경로 가능)
├── nested/config.json
├── .gitignore                # init이 `/.chronon/`을 중복 없이 추가
└── .chronon/
    ├── config.toml           # format version + commit mode
    ├── resources/
    │   ├── docs.yml/
    │   │   ├── resource.json # 루트 기준 원래 경로
    │   │   ├── 0001.yaml     # snapshot (커밋 시점 내용 그대로)
    │   │   ├── 0002.yaml
    │   │   ├── index.jsonl   # 한 줄 = 한 커밋 (append-only)
    │   │   └── state.json    # chronon이 마지막으로 쓴 내용의 해시
    │   └── nested/config.json/...
    ├── schemas/
    └── locks/                # Phase 2

# 저장소 밖, 사용자 전역 (여러 프로젝트가 공유)
~/.config/chronon/
└── vaults.toml               # vault 이름 → 저장소 절대경로. §6.1
```

---

## 3. 핵심 개념

### 3.1. 문서 (Document)
- 파일 하나 = 문서. 예: `docs.yml`, `config.yaml`, `prompts.txt`
- 저장 위치: `chronon init`으로 정한 프로젝트 루트 아래의 임의 경로. `.chronon/` 자체와 루트 밖 경로는 관리할 수 없다
- `chronon add <path>`가 추적을 시작한다. staged copy는 만들지 않으며 이후 `commit`은 그 시점의 작업본을 바로 snapshot으로 남긴다
- 각 문서는 `.chronon/` 메타 폴더에 **자기만의 선형 이력**을 가짐. **문서 간 이력은 완전히 독립**이고 서로를 참조하지 않는다 (공유 seq도, 공유 커밋도 없다)
- 따라서 **커밋은 항상 문서 1개에 대해서만** 일어난다. 다중 리소스 트랜잭션은 non-goal (§0.4)

### 3.2. 작업본(working copy) vs 커밋된 이력

- **현재 파일(`docs.yml`) = 작업본.** 에이전트가 `write` / `set` / `unset`로 자유롭게 수정. **매 저장마다 snapshot을 만들지 않는다.**
- **snapshot(이력) = commit 시에만 생성.** `commit_resource`로 명시적으로 남기거나, write 계열 tool에 `message`를 동봉하면 그 즉시 write + commit(원샷).
- **message는 커밋의 필수 요소다.** manual mode에서는 사람이 제공하고, 향후 auto mode에서는 AI가 변화 내용을 읽고 생성한다. 이름 없는 상태는 어느 모드에서도 이력이 아니다.
- **작업본은 scratch 공간이지 이력이 아니다.** dirty 상태에서 여러 번 저장하면 **마지막 저장 내용만** 다음 커밋에 담긴다. 중간 상태가 남을 가치가 있으면 **그 시점에 커밋한다.**

> 이 규칙 때문에 `as_of(T)` 의 답은 "T 이하 마지막 **커밋**의 내용"이다. 커밋되지 않은 중간 상태는 애초에 "그 시점에 의도된 상태"가 아니므로 이게 올바른 답이다.

### 3.3. 작업본 상태 (untracked / clean / dirty / foreign)

git과 병행하면 `git checkout` / `git stash` / `git pull` / `git merge` 가 chronon 모르게 작업본을 덮어쓴다. "작업본 해시 vs 마지막 snapshot 해시" 2항 비교만으로는 이걸 에이전트의 미커밋 변경과 구분할 수 없고, 그 상태에서 `discard_changes`는 **사용자의 git 작업을 조용히 날린다.**

그래서 `state.json`에 **chronon이 마지막으로 쓴 내용의 해시**를 별도 기록하고 판정한다:

| 상태 | 조건 | 의미 |
|---|---|---|
| `untracked` | 이력 0개 (snapshot 없음) | 아직 추적 안 함. 첫 `commit`으로 이력 시작 |
| `clean` | 작업본 해시 == 마지막 snapshot 해시 | 커밋 안 된 변경 없음 |
| `dirty` | 작업본 해시 == `state.json`의 last_written 해시 ≠ snapshot | **chronon을 통한** 미커밋 scratch 변경 |
| `foreign` | 위 어느 것과도 불일치 | **외부(git/편집기)가 파일을 바꿈** |

**`foreign` 처리:**
- `status_resource`가 명시적으로 보고 (어떤 해시와도 안 맞음 + 파일 mtime)
- `discard_changes` **거부** (`foreign_change` 에러). `--force`로만 강행 (외부 변경을 버림)
- write 계열도 기본 거부 → 에이전트가 덮어쓰기 전에 사람이 판단
- **외부 변경을 자동으로 이력에 기록하지 않는다** (message가 없으므로 §3.2 규칙 위반)

**`foreign` 해소 경로 (git pull 후 작업 재개):**
`git pull` 한 번으로 여러 리소스가 동시에 foreign이 될 수 있다. 해소 수단이 없으면 그때부터 모든 write가 막히고 탈출구가 `--force`뿐이라 위험하다. 세 가지를 둔다:

| 수단 | 동작 | 이력 |
|---|---|---|
| `accept_foreign` | 외부 내용을 **새 기준선으로 인정.** `state.json`만 갱신 | 남기지 않음 → 상태 `dirty` |
| `commit_resource --message` | 외부 내용에 message를 달아 커밋 | 남김 → 상태 `clean` |
| `discard_changes --force` | 외부 내용을 버리고 마지막 커밋으로 되돌림 | 남기지 않음 → 상태 `clean` |

`accept_foreign` 이후 상태는 **`dirty`** ("받아들였지만 아직 커밋 안 함"). 계속 편집하다 나중에 커밋하면 된다. 이력에 아무것도 남기지 않으므로 §3.2의 message 필수 규칙을 위반하지 않는다.

모든 working copy에는 내용 hash와 단조 증가하는 `working_generation`을 결합한
opaque `working_revision`이 있다. dirty 또는 첫 커밋 전 working copy를 변경·커밋·폐기하려면
직전에 읽은 revision을 `expected_revision`/`--if-match`로 제출해야 한다. 일치하지 않으면
`revision_conflict`, scratch가 있는데 revision을 생략하면 `precondition_required`로 거부한다.
검사와 변경은 짧은 resource operation lock 안에서 함께 수행한다.

**`state.json`이 없을 때** (다른 머신에서 clone, 또는 최초 사용):
- 이력 0개 → `untracked`
- 작업본 == 마지막 snapshot → `clean`
- 불일치 → **`foreign`** (chronon이 만든 변경이라는 증거가 없다). `accept_foreign`으로 해소

### 3.4. revspec — 시간을 1급 주소로

모든 조회 tool은 `seq: int` 대신 **revspec**을 받는다. 목적이 "특정 날짜와의 diff"이므로 날짜로 주소를 지정할 수 있어야 한다.

| 형태 | 예 | 의미 |
|---|---|---|
| 정수 | `42` | seq 42 |
| `working` | `working` | 현재 작업본 (커밋 안 됨 포함) |
| `latest` | `latest` | 마지막 커밋 |
| 상대 seq | `latest~3` | 마지막에서 3개 전 |
| 날짜 | `2026-08-01` | 해당 날짜 **00:00 UTC 기준** as-of |
| 타임스탬프 | `2026-08-12T15:00:00Z` | as-of |
| 상대 시간 | `7d ago`, `3h ago`, `30m ago` | 현재 기준 as-of |

**as-of 의미론 (명세):**
- 시각 `T` → **`T` 이하 중 가장 최근 커밋** = "T 시점에 실제로 참이었던 상태"
- `T`가 첫 커밋보다 이전이면 → `no_state_at(T)` 에러 (조용히 첫 커밋을 반환하지 않는다)
- 날짜만 준 경우 `2026-08-01` == `2026-08-01T00:00:00Z`. 즉 **7월 31일까지의 상태**
- `latest~N`이 첫 커밋을 넘어가면 → `no_state_at` 에러 (seq 1로 clamp하지 않는다)
- 해석 불가한 문자열 → `invalid_revspec` 에러 (exit 4). 추측하지 않는다

**revspec을 쓰는 위치별 제한:**
- `at` / `from` / `to` — **모든 형태** 허용 (`working` 포함)
- `since` / `until` (기간 필터) — **시간 형태만** 허용 (날짜 / 타임스탬프 / 상대 시간). `working`·`latest`·정수 seq는 `invalid_revspec`. 기간의 경계로 의미가 없기 때문

**시간 정확성:**
- timestamp는 **UTC** 저장 (ISO 8601, `Z` 접미사)
- **정렬 권한은 `seq`가 갖는다.** timestamp는 조회 키일 뿐. 시스템 시계가 뒤로 가도 이력 순서가 깨지지 않는다
- 커밋 시 timestamp가 직전 커밋보다 이르면 경고를 남기되 seq 순서는 유지
- **timestamp는 커밋 시각이지 편집 시각이 아니다.** 3시간 작업 후 한 번 커밋하면 타임라인상 변경은 마지막에 일어난 것으로 기록된다 (git의 committer date와 같은 성질). 시점 조회를 오해하지 않도록 문서에 명시

### 3.5. advisory lock + lease
- lock 파일에 `{pid, holder, intent, acquired_at, lease_until, token}` 기록
- 획득 시: 파일 없으면 atomically 생성 (O_EXCL), 있으면 lease 만료 여부 확인
- lease 기본값: 30초 (tool 인자로 조정 가능)
- 만료: lease 초과 시 다른 프로세스가 lock을 인수 가능 (stale lock recovery)
- `intent` 필드: `"adding web server"` 같은 자유 문자열. 대기 중인 에이전트가 "기다릴지 다른 일 할지" 판단하는 데 씀

**편집 세션:** write 계열 tool이 lock을 잡으면 commit / discard / 명시적 unlock 전까지 유지(자동 lease 갱신). 원샷 write + commit인 경우엔 작업 직후 자동 해제.

dirty 상태로 lease가 만료되면 다른 에이전트가 lock을 인수할 수 있다. 미커밋 변경은 파일에 그대로 남고(`status_resource`로 노출), 인수한 에이전트가 commit 하거나 discard 한다.

> lock은 이 프로젝트의 **부차적 관심사**다. 버전 관리가 핵심이고 lock은 다중 에이전트 환경의 보조 장치다. 그래서 Phase 2로 둔다 (§10).

**Phase 1(lock 미구현) 동안의 동시성 동작 — 명세:**
- lock 계열 tool은 노출하지 않는다 (호출 시 `not_implemented`)
- write는 **원자적 rename**만으로 보호된다 → 파일이 반쯤 써진 상태로 남지 않는다
- 동시 write 시 마지막 write가 이긴다 (lost update 가능). Phase 1은 단일 에이전트 / 사람 사용을 전제
- 이력은 안전하다: snapshot 파일은 새 seq로만 생성되고 `index.jsonl`은 append-only이므로 **기존 이력이 덮어써지지 않는다**

### 3.6. path 문법 (dot-path)
`set_value` / `unset_value` / `path_history` / `blame_path` / 구조적 diff가 공유하는 하나의 문법.

| 형태 | 예 | 대상 |
|---|---|---|
| 매핑 키 | `servers.web.port` | 중첩 매핑 |
| 리스트 인덱스 | `servers.hosts[2]` | 리스트 원소 (0-based) |
| 혼합 | `servers.hosts[0].name` | |
| 점을 포함한 키 | `servers['api.v2'].port` | 따옴표로 이스케이프 |

- diff 출력의 `path`는 **이 문법 그대로** 쓴다 → `diff` 결과를 그대로 `set_value`에 넘길 수 있다 (에이전트가 경로를 재구성할 필요 없음)
- 존재하지 않는 경로 조회 → `path_not_found`. `set_value`는 중간 매핑을 자동 생성, 리스트 인덱스는 자동 확장하지 않음(범위 초과는 에러)
- `type?` 인자 (`set_value`): `str|int|float|bool|null|json`. 생략 시 YAML 스칼라 규칙으로 추론. 문자열 `"8080"`을 강제하고 싶을 때 `--type str`을 쓴다

### 3.7. 커밋 모드와 초기화

저장소의 커밋 모드는 git 설정처럼 **초기화 시점에 고정**하고 `.chronon/config.toml`에 기록한다.

```bash
chronon init [DIRECTORY]                 # 기본: manual
chronon init [DIRECTORY] --mode manual
```

- `manual`: 사용자가 `chronon commit`을 호출하거나 write 계열 호출에 message를 줄 때만 커밋한다. 현재 구현 범위다
- `auto`: 변화량·경과 시간과 AI가 만든 message를 이용해 자동 커밋한다. **현재는 계획만 있으며 `chronon init --mode auto`는 `not_implemented`로 거부한다**
- 같은 설정으로 다시 `init`하면 성공하는 멱등 동작이다. 기존 저장소를 다른 모드로 암묵 변경하거나 이력을 덮어쓰지 않는다
- init은 `.gitignore`에 `/.chronon/`을 중복 없이 추가한다

향후 auto mode의 scheduler는 누적 변화량과 시간을 함께 추적한다. 기본 트리거는 **마지막 수정 후 15분간 변화가 없는 시점**이다. 편집이 계속되어 idle 조건이 생기지 않으면 **최대 2시간**에 한 번 커밋을 검토한다. 변화량 임계치는 설정 가능하지만 기본값은 비활성화하여 작은 파일과 큰 파일에 같은 바이트 기준을 강요하지 않는다. 실제 커밋 전에는 diff와 누적 변화량을 받은 AI가 변화가 유의미한지 판단하고 message를 생성한다.

AI backend는 초기화 때 하나를 선택한다.

- `command`: 실행 파일과 인자 배열을 저장하고, 셸을 거치지 않고 실행한다
- `openai-compatible`: endpoint/model과 API key가 들어 있는 **환경변수 이름**을 저장한다
- API key 원문은 `.chronon/config.toml`에 저장하지 않는다

---

## 4. 구조적 diff (핵심 기능)

### 4.1. 왜 텍스트 diff로 부족한가
YAML/JSON에서 unified text diff는 **키 순서 변경, 들여쓰기, 앵커, 인용부호 스타일** 때문에 의미 없는 노이즈를 대량 생산한다. 에이전트가 파싱해서 판단하기도 어렵다.

### 4.2. 출력 형식
```jsonc
{
  "resource": "docs.yml",
  "from": {"ref": "2026-08-01", "seq": 12, "timestamp": "2026-08-01T09:14:00Z", "message": "initial staging config"},
  "to":   {"ref": "working", "seq": null, "timestamp": null, "message": null},
  "changes": [
    {"op": "modified", "path": "servers.web.port", "old": 8080, "new": 9090},
    {"op": "added",    "path": "servers.db",       "new": {"host": "localhost", "port": 5432}},
    {"op": "removed",  "path": "servers.legacy",   "old": {"host": "old.internal"}}
  ],
  "summary": {"added": 1, "modified": 1, "removed": 1}
}
```

### 4.3. 동작 규칙
- **파싱 가능한 형식**(yml/yaml/json) → 구조적 diff가 **기본**
- **그 외** → unified text diff 폴백
- `format` 인자로 강제 선택 가능: `structural` | `text` | `both`
- 리스트 비교: 기본은 인덱스 기반(`servers.hosts[2]`). 값 기반 매칭은 Phase 3
- 구조적으로 동일하고 포맷만 다르면 → `changes: []` (**포맷 변경 노이즈 제거**)

### 4.4. 이 엔진 위에 올라가는 기능
- `path_history` — 특정 경로 값의 시간별 변화
- `blame_path` — 그 값을 마지막으로 바꾼 커밋
- `status_resource`의 변경 요약

### 4.5. `path_history` 구현 명세
1. 기간 필터(`since`/`until`)로 대상 커밋 범위를 좁힌다
2. 범위 내 각 snapshot을 파싱해 해당 path의 값을 뽑는다
3. **연속 중복 값은 접는다** — 값이 실제로 바뀐 커밋만 남긴다 (그 path와 무관한 커밋은 결과에 안 나옴)
4. 값이 없다가 생긴 경우 `op: added`, 사라진 경우 `op: removed`

범위 내 snapshot 수만큼 파싱하므로 O(N)이다. 이력이 커지면 path별 인덱스 캐시를 두되, **Phase 1은 매번 파싱한다** (수백~수천 커밋 규모에서 충분히 빠르고, 캐시는 무효화 버그의 원천이다).

---

## 5. MCP tool 설계 (에이전트 인터페이스)

`rev` / `from` / `to` / `at` 인자는 모두 **revspec**(§3.4)을 받는다. 리소스를 다루는 tool은 전부 선택적 `vault?` 인자를 받는다 — 주면 그 이름의 저장소를 쓰고(§6.1), 생략하면 MCP 서버 프로세스의 cwd 기준으로 찾는다(기존 동작).

| Tool | P | 설명 | 주요 인자 |
|---|---|---|---|
| `list_vaults` | 1 | 등록된 vault 목록 (name → 경로) | — |
| `add_vault` | 1 | 이미 init된 디렉터리를 vault로 등록 | `name`, `path` |
| `remove_vault` | 1 | 레지스트리에서 제거 (저장소 자체는 무변화) | `name` |
| `add_resource` | 1 | 기존 파일의 추적 시작 (staged copy 없음) | `resource`, `vault?` |
| `read_resource` | 1 | 리소스 읽기 (lock 불필요). **`at` 생략 시 작업본, 주면 그 시점 내용** | `resource`, `format` (raw\|parsed), `at?` |
| `diff_resource` | 1 | **시점 간 diff.** 기본 `from=latest, to=working` | `resource`, `from?`, `to?`, `format?` |
| `history_resource` | 1 | 커밋 이력. 기간/작성자 필터 | `resource`, `limit?`, `since?`, `until?`, `author?` |
| `path_history` | 1 | **특정 경로 값의 시간별 변화** | `resource`, `path`, `since?`, `until?` |
| `commit_resource` | 1 | 작업본을 이력에 커밋 (snapshot 생성). **message 필수** | `resource`, **`message`**, `author?`, `expected_revision?` |
| `write_resource` | 1 | 작업본 저장 (harness 통과 시). message가 없으면 scratch, 주면 즉시 commit | `resource`, `content`, `message?`, `author?`, `expected_revision?` |
| `set_value` | 1 | 부분 수정 (dot-path §3.6). `message` 주면 즉시 commit | `resource`, `path`, `value`, `type?`, `message?`, `expected_revision?` |
| `unset_value` | 1 | 부분 삭제. `message` 주면 즉시 commit | `resource`, `path`, `message?`, `expected_revision?` |
| `discard_changes` | 1 | 미커밋 변경 폐기. **`foreign`이면 거부** | `resource`, `force?`, `expected_revision?` |
| `accept_foreign` | 1 | **외부 변경을 기준선으로 인정** (state.json만 갱신, 이력 무변경) | `resource` |
| `status_resource` | 1 | 작업본 상태, 변경 요약, 이력 개수, 마지막 커밋 UTC 시각 | `resource` |
| `rollback_resource` | 1 | 특정 시점 복원 (새 커밋 생성). **message 필수** | `resource`, `at`, **`message`** |
| `list_resources` | 1 | 관리 중인 리소스 목록 (상태 포함) | — |
| `validate_resource` | 1 | 현재 값 검증 (쓰기 없이) | `resource` |
| `blame_path` | 2 | 그 값을 마지막으로 바꾼 커밋 | `resource`, `path` |
| `lock_resource` | 2 | lock 수동 획득 | `resource`, `lease_seconds?`, `intent?`, `refresh?`, `force?` |
| `unlock_resource` | 2 | lock 해제 | `resource` |
| `lock_status` | 2 | lock 상태 조회 | `resource` |
| `register_schema` | 2 | jsonschema 등록 | `resource`, `schema_json` |

*P = Phase. Phase 2의 장기 lease tool은 아직 노출하지 않는다. working revision CAS와 짧은 operation lock은 구현되어 있다.*

**통합/제거된 tool:**
- `show_snapshot` → **`read_resource(at:)`로 통합.** 둘은 같은 기능이었다. CLI `chronon show`는 별칭으로 남긴다
- `timeline_resource` → `history_resource`의 `since`/`until` 인자로 통합

### 5.1. 에이전트 사용 패턴

```jsonc
// ── 핵심 사용례: 현재와 특정 날짜의 차이 ──────────────────
{"tool": "diff_resource", "args": {
  "resource": "docs.yml", "from": "2026-08-01", "to": "working"
}}

{"tool": "diff_resource", "args": {"resource": "docs.yml", "from": "7d ago"}}   // to 기본값 = working

// 그 시점 내용 자체를 보기
{"tool": "read_resource", "args": {"resource": "docs.yml", "at": "2026-08-12T15:00:00Z", "format": "parsed"}}

// 특정 값이 언제, 왜 바뀌었나 (message 필수 규칙 덕에 "왜"까지 답한다)
{"tool": "path_history", "args": {"resource": "docs.yml", "path": "servers.web.port", "since": "30d ago"}}
// → [{"seq":12,"timestamp":"...","message":"initial staging config","value":8080},
//    {"seq":19,"timestamp":"...","message":"bump port for staging","value":9090}]

// ── 편집 ──────────────────────────────────────────────
// 중간 저장 (작업본만. 이력 안 남음). 응답의 working_revision을 보관한다.
{"tool": "write_resource", "args": {"resource": "docs.yml", "content": "...작업 중 yml..."}}

// 의미 있는 시점에 커밋. scratch가 있으면 직전에 읽은 revision이 필수다.
{"tool": "commit_resource", "args": {"resource": "docs.yml", "message": "add web server", "author": "agent-1", "expected_revision": "w12:sha256:..."}}

// 원샷 write + commit — 에이전트의 기본 경로 (message 비용이 0이므로 이력이 자연히 조밀해진다)
{"tool": "write_resource", "args": {
  "resource": "docs.yml", "content": "...", "message": "add web server", "author": "agent-1"
}}

// rollback (message 필수)
{"tool": "rollback_resource", "args": {
  "resource": "docs.yml", "at": "2026-08-01", "message": "revert to pre-migration config"
}}
```

### 5.2. 에러 response
```jsonc
// harness 검증 실패
{"error": "validation_failed", "resource": "docs.yml",
 "issues": [{"path": "$.servers.web", "message": "required property 'port' missing", "severity": "error"}]}

// 외부(git 등)가 파일을 바꿈
{"error": "foreign_change", "resource": "docs.yml",
 "message": "working copy was modified outside chronon (git checkout?)",
 "hint": "commit it with a message, or discard --force"}

// 시점 조회 실패
{"error": "no_state_at", "resource": "docs.yml", "at": "2026-07-01",
 "first_commit": "2026-08-01T09:14:00Z"}

// working revision CAS 충돌
{"error": "revision_conflict", "resource": "docs.yml", "expected_revision": "w12:sha256:...", "actual_revision": "w13:sha256:..."}

// 커밋할 변경 없음
{"error": "nothing_to_commit", "resource": "docs.yml", "state": "clean", "latest_seq": 19}

// 해석 불가한 revspec
{"error": "invalid_revspec", "value": "last tuesday",
 "hint": "seq | working | latest | latest~N | YYYY-MM-DD | ISO8601 | '7d ago'"}
```

---

## 6. CLI 명령 설계 (사람의 기본 인터페이스)

MCP tool과 1:1 대응. `<rev>` 자리에는 revspec을 쓴다.

**명령 문법:** `chronon <command> [vault] [옵션] [경로]` — vault는 모든 명령에 공통으로 붙는 자리다.

### 6.1. vault — 이름으로 저장소 찾기

`chronon init`은 여전히 저장소를 "현재 디렉터리 기준 상위 탐색"으로 찾는다(git과 동일). 하지만 에이전트는 매번 그 프로젝트로 `cd`하지 않고 이름 하나로 저장소를 가리키고 싶을 때가 많다. **vault**는 그 이름이다.

- vault 레지스트리는 **저장소 안이 아니라 사용자 전역**에 있다: `~/.config/chronon/vaults.toml` (`CHRONON_CONFIG_HOME`로 재정의 가능). `name → 절대경로` 매핑뿐이다
- 등록은 명시적이다. `chronon init`이 자동으로 등록하지 않는다 — `chronon add-vault <name> <path>`를 쓰거나, `chronon init DIRECTORY --register <name>`으로 초기화와 동시에 등록한다
- vault를 생략하면 기존 동작 그대로: 현재 디렉터리에서 위로 올라가며 `.chronon/`을 찾는다
- vault를 주면 현재 디렉터리는 완전히 무시하고 레지스트리의 경로를 저장소 루트로 쓴다. 그 다음의 `<경로>` 인자는 **그 루트 기준 상대경로**로 해석된다

```bash
chronon add-vault <name> [DIRECTORY]      # DIRECTORY 기본값: 현재 디렉터리. 이미 init된 곳이어야 함
chronon list-vaults
chronon remove-vault <name>               # 레지스트리에서만 제거. 저장소 자체는 그대로
```

**명령 자리의 vault:** 모든 리소스 명령은 `--vault <name>` 옵션을 받는다. 추가로, `[vault]` 자리에 온 토큰이 **등록된 vault 이름과 정확히 일치하면** 자동으로 `--vault`로 해석한다 — 옵션처럼 어디에 있어도 되지만, 관용적으로는 명령 바로 뒤에 둔다:

```bash
chronon diff myvault docs.yml --from 2026-08-01     # == chronon diff docs.yml --from 2026-08-01 --vault myvault
chronon status myvault                              # 리소스 생략 시 전체 목록, vault만 지정
```

리소스 이름이 등록된 vault 이름과 우연히 같으면(드묾) `--vault`를 명시하거나 경로 앞에 `./`를 붙여 리소스로 강제한다 — vault 이름 문법(`[A-Za-z0-9][A-Za-z0-9_-]*`)은 `/`를 허용하지 않으므로 `./같은이름` 은 절대 vault로 오인되지 않는다.

```bash
# ── 저장소 ──
chronon init [DIRECTORY] [--mode manual] [--register <name>] [--agents-md] [--agents-md-file NAME]   # DIRECTORY 기본값: 현재 디렉터리
chronon add [vault] <resource>...                                 # 추적 시작

# ── 핵심: 시점 조회 & diff ──
chronon diff [vault] <resource> [--from <rev>] [--to <rev>] [--format structural|text|both]
chronon diff docs.yml --from 2026-08-01 --to working      # 기본 동작
chronon diff docs.yml --from "7d ago"                      # to 기본 = working

chronon read [vault] <resource> [--at <rev>] [--raw | --parsed]
chronon show [vault] <resource> <rev>                       # read --at 의 별칭. chronon show docs.yml 2026-08-12

chronon history [vault] <resource> [--limit N] [--since <rev>] [--until <rev>] [--author X]
chronon path-history [vault] <resource> <path> [--since <rev>] [--until <rev>]   # servers.web.port 의 변천사
chronon blame [vault] <resource> <path>                     # Phase 2

# ── 편집 ──
chronon write [vault] <resource> (--content "..." | --file x.yml | --stdin) [--if-match <working_revision>]
chronon write [vault] <resource> --file x.yml --message "msg" [--author "agent-1"]   # 저장 + 커밋 원샷

chronon commit [vault] <resource> --message "msg" [--author "agent-1"] [--if-match <working_revision>]
chronon discard [vault] <resource> [--force] [--if-match <working_revision>]
chronon accept [vault] <resource>                                 # 외부 변경을 기준선으로 인정 (git pull 후)
chronon status [vault] [<resource>]                                # untracked|clean|dirty|foreign. 리소스 생략 시 목록

chronon set [vault] <resource> --path "servers.web.port" --value 8080 [--type int] [--message "msg"]
chronon unset [vault] <resource> --path "servers.legacy" [--message "msg"]

chronon rollback [vault] <resource> <rev> --message "msg"          # --message 필수

# ── lock (Phase 2. 보통 자동) ──
chronon lock [vault] <resource> [--lease 30] [--intent "..."] [--refresh] [--force]
chronon unlock [vault] <resource>
chronon lock status [vault] <resource>

# ── 기타 ──
chronon schema-register [vault] <resource> --file schema.json
chronon validate [vault] <resource>
chronon list [vault]
chronon agents-md [vault] [FILE]                                   # 에이전트 문서에 사용법 기록/갱신. FILE 기본값: CHRONON.md. §6.2

# ── vault 레지스트리 ──
chronon add-vault <name> [DIRECTORY]
chronon list-vaults
chronon remove-vault <name>
```

### 6.2. `agents-md` — 에이전트 문서를 MCP 대용으로

MCP 서버가 연결 안 된 에이전트(순수 CLI/Bash로만 동작하는 경우)도 chronon을 쓸 수 있어야 한다. 저장소 루트의 마크다운 문서(`CHRONON.md`, `AGENTS.md`, `CLAUDE.md` 등)는 Claude Code를 비롯한 여러 코딩 에이전트가 **자동으로 읽는** 관례 파일이므로, 여기에 chronon 사용법을 적어두면 MCP tool 목록을 대신할 수 있다.

- `chronon agents-md [FILE]` — 현재 저장소의 에이전트 문서에 chronon 사용법 섹션을 쓰거나 갱신한다. `FILE` 기본값은 `CHRONON.md`이고, `chronon agents-md AGENTS.md`처럼 다른 이름을 줄 수 있다(경로 구분자는 불가, 루트 파일명만). 파일이 없으면 새로 만들고, 있으면 `<!-- chronon:agents-md:begin/end -->` 마커로 감싼 구간만 갱신한다 — 사용자가 직접 쓴 나머지 내용은 절대 건드리지 않는다
- `chronon init --agents-md` — init과 동시에 같은 작업을 한다(`CHRONON.md`). `--agents-md-file NAME`으로 파일명을 지정한다
- 내용은 고정 템플릿이다: message 필수 규칙, 파일별 독립 이력, 구조적 diff, 자주 쓰는 명령 표(`add`/`write --message`/`set --message`/`commit`/`diff`/`show`/`path-history`/`rollback`/`accept`), revspec 형태, vault 사용법
- 몇 번을 다시 실행해도 내용이 같으면 파일을 재작성하지 않는다(`updated: false`) — chronon 업그레이드 후 재실행해서 최신 사용법으로 갱신하는 용도

이 명령은 MCP tool로는 노출하지 않는다 — MCP가 이미 연결된 에이전트에게는 필요 없는 기능이기 때문이다.

---

## 7. 검증 harness 설계

### 7.1. 프로토콜
```python
class Harness(Protocol):
    def validate(self, content: str, path: Path) -> list[Issue]:
        """content 검증. 문제 없으면 빈 리스트 반환"""

@dataclass
class Issue:
    path: str       # "$.servers.web.port" (JSONPath 스타일)
    message: str
    severity: Literal["error", "warning"] = "error"
```

### 7.2. 파일 확장자 기반 자동 선택
- `.yml`, `.yaml` → `YamlHarness` (문법 + 등록된 jsonschema 있으면 스키마 검증)
- `.json` → `JsonHarness`
- 기타 → `TextHarness`

### 7.3. 검증 실패 시 동작
- write 거부. **작업본 파일 자체를 수정하지 않음** (원자적 쓰기: temp 파일 → 검증 통과 시에만 rename)
- 편집 세션 중이면 lock 유지. 원샷 write + commit 시도였다면 lock 자동 해제
- snapshot 생성 안 함
- MCP tool response / CLI에 issues 목록 출력. CLI exit code 1

harness는 **매 write마다** 실행되어 작업본은 항상 유효 상태로 유지된다. 이 덕분에 **디스크 위의 파일은 항상 파싱 가능**하고, 따라서 **모든 snapshot도 항상 파싱 가능**하다 — 구조적 diff(§4)가 어떤 시점 조합에서도 동작한다는 뜻이다.

> git의 pre-commit hook은 이미 깨진 내용이 디스크에 써진 *다음에* 돈다. 이 불변식은 git이 원리적으로 줄 수 없다.

---

## 8. snapshot 저장 상세

### 8.1. 생성 시점 (이게 전부다)
- `commit_resource` 실행 시 — 작업본이 **`clean`이 아닐 때**. 즉 `untracked`(첫 커밋) / `dirty` / `foreign` 모두 커밋 가능하다. `clean`이면 `nothing_to_commit`
  - `foreign`에서의 커밋은 §3.3의 해소 경로 중 하나다. message를 달아 커밋하는 순간 그 상태는 "의도된 상태"가 되므로 §3.2 규칙과 충돌하지 않는다
- `write_resource` / `set_value` / `unset_value`에 `message` 동봉 시 (원샷)
  - **원샷인데 내용이 마지막 커밋과 동일하면** → write는 성공(no-op), 커밋은 하지 않고 `committed: false, reason: "nothing_to_commit"` 을 응답에 담는다. 에러가 아니다
- `rollback_resource` 실행 시 (복원도 새 커밋. rollback of rollback 가능)
  - `at`이 `working`이면 → `invalid_revspec`. "현재를 현재로 되돌린다"는 의미가 없다. 작업본을 남기려면 `commit`을 쓴다
  - 복원 대상 내용이 현재 작업본 또는 마지막 커밋과 동일하면 → `nothing_to_commit`. 작업본도 변경하지 않는다

모든 커밋 경로의 공통 불변식은 **마지막 커밋과 content hash가 같으면 새 이력을 만들지 않는다**는 것이다. 첫 커밋은 비교할 이전 이력이 없는 `untracked` 기준선이므로 허용한다.

> 현재 구현하는 **manual mode에는 자동 스냅샷이 없다.** message 없이 호출된 write/set/unset은 작업본만 갱신한다. 외부 변경도, `accept_foreign`도 이력을 만들지 않는다(§3.3).

### 8.2. snapshot 파일
커밋 시점 내용 그대로. 시간순 seq (`0001.yaml`, `0002.yaml`). 평문 유지 — 에이전트/사람이 도구 없이 `cat`으로 확인 가능한 것이 이 도구에선 실질적 가치가 있다.

### 8.3. index.jsonl (append-only)
한 줄 = 한 커밋. JSON 배열이 아니라 **JSON Lines**를 쓴다:
- append가 O(1) — 전체 read-modify-write 불필요
- 크래시에 강함 (마지막 한 줄만 손상, 앞은 무사)
- **git merge conflict가 거의 안 난다** (JSON 배열은 conflict 상습범). `.chronon/`을 git에 커밋하기로 할 때 결정적

```jsonl
{"seq":1,"timestamp":"2026-08-01T09:14:00Z","author":"agent-1","message":"initial staging config","content_hash":"sha256:abc123...","file":"0001.yaml"}
{"seq":2,"timestamp":"2026-08-05T12:05:00Z","author":"agent-2","message":"add web server","content_hash":"sha256:def456...","file":"0002.yaml"}
```

### 8.4. state.json
```json
{"last_written_hash": "sha256:...", "last_written_at": "2026-08-05T12:04:12Z", "last_seq": 2}
```
`foreign` 판정용(§3.3). chronon이 작업본에 쓸 때마다 갱신.

---

## 9. 에러 처리 & 출력

### 9.1. CLI exit code
- 0: 성공
- 1: 검증 실패 (harness)
- 2: lock 실패
- 3: 파일 오류 (존재하지 않음, 권한)
- 4: 사용 오류 (`invalid_revspec`, `path_not_found`, 잘못된 인자)
- 5: 커밋할 변경 없음 (`nothing_to_commit`)
- 6: **외부 변경 충돌** (`foreign_change`)
- 7: **revision 선행조건/충돌** (`precondition_required`, `revision_conflict`)
- 8: **해당 시점 상태 없음** (`no_state_at`)

### 9.2. 출력 형식
- CLI: 기본 텍스트, `--json` 플래그로 JSON
- MCP: 항상 구조화 response (JSON)

---

## 10. 구현 단계

우선순위 원칙: **버전 관리 > 검증 > lock.** lock은 다중 에이전트 보조 장치이고, 단일 에이전트/사람 사용에는 원자적 rename만으로 파일 깨짐이 막힌다.

### Phase 1: 버전 관리 코어 (필수)

> **현재 상태:** manual mode의 1–16 항목 구현 및 자동 테스트 완료. lock/lease와 auto mode 실행기는 아직 포함하지 않는다.

1. 프로젝트 초기화 (pyproject.toml, src 구조, 의존성: typer, pyyaml, jsonschema, mcp)
2. **`chronon init [DIRECTORY]` + `chronon add`** — `.chronon/config.toml`, resource 등록, `.gitignore`
3. `core/errors.py` — 커스텀 예외
4. `core/store.py` — 리소스 경로 관리, `.chronon/` 구조
5. **`core/snapshot.py`** — snapshot 생성, index.jsonl append/read, 조회
6. **`core/revspec.py`** — revspec 파싱 + as-of 해석 (seq / working / latest / latest~N / 날짜 / 상대시간). **UTC, seq 우선 정렬**
7. **`core/diff.py`** — 구조적 diff 엔진 (값 단위) + 텍스트 diff 폴백
8. `core/path.py` — dot-path 파싱/조회/설정 (§3.6). diff·set·path_history가 공유
9. `core/state.py` — untracked / clean / dirty / foreign 판정 (state.json)
10. YAML/JSON/text harness — 원자적 쓰기 게이팅
11. `api/operations.py` — add/read/diff/history/path_history/commit/write/discard/accept/status/set/unset/rollback/list/validate
12. `mcp_server.py` — tool 노출 (Phase 1 tool만)
13. `cli.py` — Typer CLI (`init/add/commit/diff/log` 포함)
14. 테스트: **test_revspec, test_diff, test_path** 를 최우선. + snapshot/state/harness/operations/CLI 통합 테스트
15. **`core/vaults.py` + `chronon add-vault`/`list-vaults`/`remove-vault`** — 전역 vault 레지스트리, `--vault`/`[vault]` 자리, `init --register` (§6.1)
16. **`core/docs.py` + `chronon agents-md [FILE]`** — 에이전트 문서(기본 CHRONON.md) 사용법 섹션 생성/멱등 갱신, `init --agents-md` (§6.2)

> Phase 1은 수정 단위의 짧은 operation lock과 working revision CAS를 사용한다. 편집 세션 전체를 소유하는 lease lock은 아직 없다.

### Phase 2: 다중 에이전트 & 편의
17. `core/lock.py` — advisory lock + lease + `intent` + stale recovery
18. lease 자동 갱신 (백그라운드 스레드)
19. ~~**working revision CAS** — scratch lost update 방지~~ (구현 완료)
20. `blame_path`
21. `harness/json_harness.py` + 스키마 등록 (`register_schema`)
22. auto mode 실행기 + idle 15분 / 최대 2시간 scheduler + AI backend

### Phase 3: 고급 (선택)
23. `watch` — 리소스 변경 알림 (git이 못 하는 것)
24. 리스트 값 기반 매칭 diff (인덱스 기반의 한계 보완)
25. content-addressed 저장 (`objects/<sha256>`) — 이력이 커지면 dedup. 현재는 불필요
26. snapshot 압축 (gzip) — 25 이후에도 부족할 때만. 평문 inspectability를 잃는 비용이 있음
27. 커스텀 harness (사용자 정의 python 룰)

> 기존 계획의 "감사 로그(별도 파일)"는 제외했다. `index.jsonl`이 이미 감사 로그다 — message 필수 + 불변 + 시간 색인.

---

## 11. git 병행 규칙

### 11.1. 무엇을 git에 커밋하나
| 경로 | git 추적 | 이유 |
|---|---|---|
| 프로젝트의 관리 파일 | ✅ 커밋 | 실제 산출물. git이 장기·공유 이력 담당 |
| `.chronon/` 전체 | ❌ 기본 gitignore | 설정과 이력 모두 로컬. 필요하면 사용자가 ignore 정책을 직접 바꿔 공유 가능 |

`chronon init`이 넣는 기본 `.gitignore` (기본 = 이력 로컬 보관):
```gitignore
/.chronon/
```

`.chronon/` 공유가 필요해 ignore 정책을 바꾸더라도 `resources/**/state.json`과 `locks/`는 머신 로컬이므로 계속 제외해야 한다.

### 11.2. 절대 하지 않을 것
- **chronon이 git을 호출하지 않는다.** `chronon commit`은 `git commit`을 부르지 않는다. 커밋 단위가 다르고(문서 1개 vs 저장소 전체), 래핑하면 git의 브랜치/충돌 세계가 전부 새어 들어온다.
- chronon은 "파일이 유효하고 clean하다"만 보장한다. `git commit`은 사람/에이전트가 평소대로 한다.

### 11.3. git이 작업본을 바꿨을 때
`git checkout` / `stash` / `pull` / `merge` → `foreign` 상태(§3.3). chronon은 자동으로 이력에 남기지 않고(message가 없으므로), `status_resource`로 보고하고 판단을 넘긴다. 이 규칙 덕에 chronon 타임라인에는 **의도되지 않은 항목이 절대 들어가지 않는다.**

전형적인 흐름:
```bash
git pull                          # docs.yml 이 남의 커밋으로 바뀜
chronon status docs.yml           # → foreign
chronon accept docs.yml           # 이 내용을 기준선으로 인정 (이력 무변경) → dirty
# ... 에이전트가 계속 편집 ...
chronon-cat docs.yml --json        # working_revision 확인
chronon commit docs.yml -m "..." --if-match '<working_revision>'  # → clean
```
남의 변경 자체를 chronon 이력에도 남기고 싶다면 `accept` 대신 `commit -m "merge upstream config"`를 쓴다.

---

## 12. 주요 설계 결정 (tradeoff)

| 결정 | 이유 | 대안 |
|---|---|---|
| **커밋 message 필수** | 타임라인의 모든 점이 설명 가능해진다. manual에서는 호출자가, auto에서는 AI가 message를 제공한다 | 이름 없는 주기 스냅샷 |
| **모드는 init 때 고정, 기본 manual** | 저장소마다 이력 생성 정책이 예측 가능하다. auto는 AI backend와 보안 설정까지 명시적으로 선택해야 한다 | 실행마다 모드 지정 |
| **시간을 1급 주소로 (revspec)** | 프로젝트 목적이 "특정 날짜와의 diff". seq만 받으면 목적을 표현할 수 없다 | seq만 (날짜→seq 변환을 호출자에게 전가) |
| **불변 이력 (rebase/amend 없음)** | "X 시점의 상태"가 영원히 같은 답을 낸다. git은 rebase가 이 답을 바꾼다 | 이력 편집 허용 (감사 추적 불가) |
| **구조적 diff 기본** | YAML/JSON 텍스트 diff는 키 순서·들여쓰기 노이즈 투성이. 에이전트가 파싱하기도 어려움 | 텍스트 diff만 (git과 동일 = 차별점 없음) |
| **작업본 = scratch, 이력 아님** | 중간 상태를 전부 남기면 이력이 노이즈로 가득 찬다. 남길 가치가 있으면 그때 커밋한다 | 매 write마다 snapshot |
| **커밋 단위 = 문서 1개 (트랜잭션 없음)** | 리소스별 독립 선형 이력이 `as_of`를 단순하게 만든다. 다중 리소스를 묶으면 "어느 리소스 기준의 시점인가"가 생기고 결국 git의 DAG가 된다. 파일 간 일관성은 git 커밋의 몫 | 다중 리소스 원자적 커밋 (= git 모델 재구현) |
| **4상태 (untracked/clean/dirty/foreign)** | git 병행 시 외부 변경을 에이전트의 미커밋 변경과 구분해야 `discard`가 안전하다 | 2항 해시 비교 (git 작업을 조용히 날림) |
| **`accept_foreign` (이력 무변경)** | `git pull` 후 모든 write가 막히는데 탈출구가 `--force`뿐이면 위험하다. "받아들이되 이름은 아직 안 붙임"이 필요 | foreign에서 강제 write 허용 (외부 변경을 조용히 덮어씀) |
| **dot-path 문법을 diff와 set이 공유** | `diff` 결과의 `path`를 그대로 `set_value`에 넘길 수 있다. 에이전트가 경로를 재구성할 필요 없음 | 각자 다른 문법 (에이전트가 변환해야 함) |
| **index.jsonl (배열 아님)** | append O(1), 크래시 내성, git merge 가능 | index.json 배열 (전체 재작성, conflict 상습) |
| **평문 snapshot 파일 (DB/압축 아님)** | 도구 없이 `cat`으로 확인 가능. 백업 쉬움. 단순함 | SQLite / gzip / git plumbing (불투명해짐) |
| **lock을 Phase 2로** | 버전 관리가 핵심이고 lock은 다중 에이전트 보조. 원자적 rename만으로 파일 깨짐은 막힌다 | lock 우선 (핵심 가치 전달이 늦어짐) |
| **advisory lock 파일 (OS lock 아님)** | cross-platform. 프로세스 죽어도 lease로 복구. lock 파일 내용 확인 가능 | fcntl/msvcrt |
| **CLI와 MCP가 같은 코어를 공유** | 사람은 git과 비슷한 CLI를, 에이전트는 구조화된 MCP tool을 쓴다 | 인터페이스별 별도 구현 |
| **`api/operations.py` 공유 레이어** | MCP와 CLI가 동일 코어. 테스트 한 번에 두 인터페이스 검증 | 각각 구현 (중복) |
| **vault 레지스트리는 저장소 밖, 전역** | `cd` 없이 이름으로 저장소를 가리키려면 그 이름은 어느 저장소에도 속하지 않는 곳에 있어야 한다 (닭-달걀 문제) | 저장소 내부에 별칭 파일 (다른 저장소에서 참조 불가) |
| **vault 등록은 명시적** (`init`이 자동 등록 안 함) | 사람마다 같은 저장소를 다른 이름으로 부르고 싶을 수 있고, 등록 안 된 저장소도 여전히 cwd 기준으로는 잘 동작해야 한다 | init 시 디렉터리 이름으로 자동 등록 |

**`[vault]` 자리와 `--vault` 옵션의 관계:** CLI 파서(Click)는 두 개의 위치 인자가 있을 때 앞자리를 항상 채우려 하므로, `[vault]`가 없을 때 `<resource>`가 그 자리로 밀려 들어가는 걸 막을 수 없다. 그래서 실제로는 모든 명령이 `--vault` **옵션**을 받고, `[vault]` 자리의 bare 토큰이 등록된 vault 이름과 정확히 일치할 때만 CLI가 파싱 전에 `--vault <이름>`으로 바꿔치기한다(§6.1). 사용자에게는 위치 인자처럼 보이지만 내부적으로는 옵션이다 — 모호할 일이 있으면 `--vault`를 명시하면 항상 정확하다.

---

## 13. 향후 확장 (현재 범위 外)
- 다중 머신 (네트워크 lock). Redis/etcd
- 다중 형식 (toml, xml). harness 프로토콜로 확장
- 웹 UI (타임라인 시각화 — 시간 축 이력과 궁합이 좋음)

---

## 확인 사항 (결정 완료)
- [x] CLI와 MCP가 같은 코어를 공유
- [x] Python (Typer CLI + PyYAML + jsonschema + mcp)
- [x] 내장 스토어 (snapshot 파일. git 없어도 동작)
- [x] 중간 저장은 작업본(dirty), 명시적 commit 시에만 snapshot. staged 단계 없음
- [x] **커밋 message 필수. 현재 manual mode만 구현; auto는 AI가 message 생성**
- [x] **`chronon init [DIRECTORY]`, 기본 manual, `.chronon/` 메타 저장소**
- [x] **`chronon add`는 추적 시작이며 staged 영역은 두지 않음**
- [x] **시간(날짜/상대시간)으로 시점 주소 지정 — revspec**
- [x] **구조적 diff가 기본, 텍스트 diff는 폴백**
- [x] **불변 이력. rebase/amend/squash 없음**
- [x] **커밋 단위는 문서 1개. 다중 리소스 원자적 커밋은 하지 않음 (git의 모델)**
- [x] **작업본 4상태: untracked / clean / dirty / foreign (git 병행 안전성)**
- [x] **`accept_foreign` — 외부 변경을 이력 없이 기준선으로 인정 (git pull 후 작업 재개 경로)**
- [x] **dot-path 문법 하나를 diff·set·path_history가 공유**
- [x] **`chronon <command> [vault] [옵션] [경로]` — vault는 전역(사용자) 레지스트리, 등록은 명시적(`chronon add-vault`), 생략 시 cwd 기준 상위 탐색(기존 동작)**
- [x] **`chronon agents-md [FILE]` / `init --agents-md` — 에이전트 문서에 사용법 기록(FILE 기본 CHRONON.md, AGENTS.md 등 지정 가능). MCP 미연결 에이전트를 위한 대용. MCP tool로는 노출 안 함**
- [x] advisory lock + lease (Phase 2). **Phase 1은 lock 없이 동작**
- [x] git과 병행. chronon이 git을 래핑하지 않음
