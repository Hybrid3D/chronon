# Chronon

Chronon은 파일 하나마다 독립적인 불변 이력을 만드는 로컬 버전 관리 도구입니다. 커밋을 시간으로 조회하고 YAML·JSON의 값 단위 차이를 볼 수 있습니다. git과 함께 사용할 수 있지만 git을 호출하거나 대체하지 않습니다.

현재 버전은 **manual commit mode**만 지원합니다. auto mode는 누적 변화량과 시간을 관찰하며, 기본적으로 마지막 수정 후 15분 idle 또는 최대 2시간 간격에 AI가 커밋 필요성과 message를 결정하도록 설계되어 있지만 아직 실행되지 않습니다.

## 설치

Python 3.11 이상이 필요합니다.

```bash
python -m pip install -e .
```

개발 테스트까지 설치하려면 다음을 사용합니다.

```bash
python -m pip install -e '.[dev]'
pytest
```

## 시작하기

git처럼 프로젝트 디렉터리를 초기화합니다. 디렉터리를 생략하면 현재 디렉터리가 대상입니다.

```bash
chronon init ./my-project
cd ./my-project

chronon add docs.yml
chronon-cat docs.yml --json                 # working_revision 확인
chronon commit docs.yml -m "initial document" --if-match '<working_revision>'
```

초기화하면 `.chronon/config.toml`과 `.chronon/resources/`가 생기며 `.gitignore`에는 `/.chronon/`이 추가됩니다. 다시 같은 명령을 실행해도 기존 이력을 덮어쓰지 않습니다.

`--mode auto`는 현재 명확한 `not_implemented` 오류를 반환합니다.

## git 대응 명령

```bash
# git add: 파일 추적 시작. staged copy는 만들지 않습니다.
chronon add docs.yml

# git commit: 현재 파일 한 개를 불변 snapshot으로 기록합니다.
chronon commit docs.yml -m "raise web port" --if-match '<working_revision>'

# git diff: 마지막 커밋과 작업본 비교
chronon diff docs.yml

# 날짜/커밋끼리 비교
chronon diff docs.yml --from 2026-08-01 --to working
chronon diff docs.yml --from 1 --to 2 --format both

# git log
chronon log docs.yml

# git status. 인자 생략 시 전체 파일
chronon status
chronon status docs.yml
```

`status`는 각 파일의 상태와 함께 `commits=<이력 개수>`, `last=<마지막 커밋 UTC 시각>`을 표시합니다. 첫 커밋 전에는 `commits=0`, `last=-`입니다.

Chronon에는 staged 영역이 없습니다. `add`는 추적 시작이고, `commit`은 호출 시점의 작업본을 바로 기록합니다. 커밋은 항상 파일 하나 단위이며 message가 필수입니다.

## 파일 이동과 복사

추적되는 파일은 각자 고유한 불투명 `id`(128비트 hex)를 가집니다. `add`할 때 한 번 부여되고 이후 이름을 바꿔도 유지됩니다. `id`가 없던 이전 저장소는 파일을 처음 다룰 때 자동으로 채워집니다. `chronon status <파일>`에 `id=...`로 표시됩니다.

```bash
# git mv: 이력과 id를 그대로 유지한 채 경로만 바꿉니다.
chronon mv docs.yml config/web.yml

# cp: 새 경로에 독립된 리소스로 복사합니다. 새 id가 생기고 이력은 revision 0부터
#     다시 시작합니다(스냅샷 가지치기 없음). descriptor의 copied_from에 원본의 id와
#     복사 시점의 원본 revision(working_revision·seq·content_hash)이 기록됩니다.
chronon cp config/web.yml config/web.backup.yml
```

`mv`와 `cp` 모두 대상 경로에 파일이 이미 있거나 이미 추적 중이면 거부하며, 원본은 그대로 둡니다. `mv`는 작업본 파일과 `.chronon/` 메타데이터(이력·스키마)를 함께 옮깁니다. 이동 후 옛 경로는 더 이상 추적되지 않습니다.

경로 변경 자체도 이력입니다. `mv`는 descriptor의 `path_log`(경로별 적용 시각)에 항목을 추가하고, `chronon diff`는 두 시점의 경로가 다르면 `path_change`(사람용 출력에서는 `renamed: 옛경로 -> 새경로`)를 함께 보고합니다.

```bash
chronon mv docs.yml config/web.yml
chronon diff config/web.yml                    # renamed: docs.yml -> config/web.yml
chronon diff config/web.yml --from 1 --to working   # 이름 변경 + 값 변경을 함께
```

## 조회와 편집

```bash
# 셸의 ls/cat처럼 Chronon이 관리하는 파일을 탐색하고 읽기
chronon-ls .
chronon-ls nested --json
chronon-cat docs.yml
chronon-cat docs.yml --at latest~1
chronon-write notes/new.txt --content "first note" --scratch
chronon-cat notes/new.txt --json             # working_revision 확인
printf 'updated note\n' | chronon-write notes/new.txt --stdin \
  --if-match '<working_revision>' -m "update note"

chronon read docs.yml
chronon show docs.yml latest~1
chronon path-history docs.yml servers.web.port

chronon set docs.yml --path servers.web.port --value 9090 --type int
chronon-cat docs.yml --json
chronon commit docs.yml -m "move web service to 9090" \
  --if-match '<working_revision>'

# 원샷 수정 + 커밋
chronon set docs.yml --path enabled --value true --type bool -m "enable service"

chronon rollback docs.yml 1 -m "restore initial document"
```

`chronon-ls [디렉터리]`는 일반 `ls`처럼 해당 디렉터리의 바로 아래 항목만
표시합니다. Chronon이 추적하지 않는 파일은 보이지 않으며, 더 아래에 추적 파일이
있는 디렉터리는 이름 뒤에 `/`가 붙습니다. `chronon-cat`은 기본적으로 working
revision을 읽고, `--at`에 Chronon revspec을 지정하면 과거 snapshot을 읽습니다.
두 명령은 파일 내용을 읽기 위해 별도로 파일시스템 API를 사용할 필요 없이 Chronon의
operation layer를 통합니다.

`chronon-write <파일>`은 경로가 없으면 파일을 만들고 즉시 추적을 시작하며, 이미
Chronon이 추적하는 파일이면 작업본을 갱신합니다. 기존에 존재하지만 추적되지 않은
파일은 실수로 덮어쓰지 않습니다. 내용은 `--content` 또는 `--stdin` 중 하나로
전달하고, 저장 방식은 `--scratch` 또는 `--message/-m` 중 하나를 반드시 선택합니다.

scratch는 별도 파일이 아니라 Chronon working copy입니다. `chronon-cat --json`이
반환하는 opaque `working_revision`을 다음 `chronon-write --if-match`에 전달해야
scratch를 다시 쓰거나 최종 커밋할 수 있습니다. 다른 쓰기가 먼저 일어나면
`revision_conflict`로 거부되며 파일은 바뀌지 않습니다. 현재 scratch를 그대로
커밋하려면 `chronon-commit ... --if-match <working_revision> -m "..."`을 사용합니다.
`chronon-ls -l`은 `dirty`와 첫 커밋 전 상태를 `scratch`로 표시합니다.

지원 revspec은 `1`, `latest`, `latest~N`, `working`, `YYYY-MM-DD`, timezone이 포함된 ISO 8601 timestamp, `7d ago`, `3h ago`, `30m ago`입니다. 날짜만 쓰면 해당 날짜의 UTC 00:00 기준입니다.

YAML과 JSON은 기본적으로 구조적 diff를 사용합니다. 키 순서나 들여쓰기만 달라진 경우 변화로 표시하지 않습니다. 그 밖의 UTF-8 텍스트 파일은 unified diff를 사용합니다.

## 외부 편집과 git 병행

Chronon을 거치지 않은 변경은 마지막 Chronon 쓰기와 구분되어 `foreign` 상태가 됩니다.

```bash
chronon status docs.yml
chronon accept docs.yml                    # 외부 내용을 dirty 기준선으로 인정
chronon-cat docs.yml --json
chronon commit docs.yml -m "accept upstream configuration" \
  --if-match '<working_revision>'

chronon discard docs.yml                   # Chronon 변경 폐기
chronon discard docs.yml --force           # 외부 변경도 폐기하므로 주의
```

## vault — 이름으로 저장소 찾기

`cd` 없이 이름 하나로 저장소를 가리키고 싶을 때 씁니다. 등록은 사용자 전역(`~/.config/chronon/vaults.toml`)이라 어느 디렉터리에서 실행하든 동작합니다.

```bash
chronon add-vault myvault ./my-project     # 이미 init된 디렉터리를 등록
chronon init ./my-project --register myvault   # init과 동시에 등록

chronon list-vaults
chronon remove-vault myvault               # 레지스트리에서만 제거, 저장소는 그대로

# 어디서든 이름으로 접근
chronon --vault myvault status
chronon --vault myvault diff docs.yml --from 2026-08-01
# 짧게는 -v
chronon -v myvault status docs.yml
```

`--vault`/`-v`는 최상위 전역 옵션이므로 명령어 앞에 둡니다. 생략하면 현재 디렉터리에서 저장소 루트를 찾습니다.

## 에이전트 문서 (MCP 없이)

MCP 서버를 등록하지 않아도, 저장소 루트의 마크다운 문서에 Chronon CLI 사용법을 적어두면 코딩 에이전트가 그대로 읽습니다.

```bash
chronon agents-md                 # 기본값: CHRONON.md 생성/갱신
chronon agents-md AGENTS.md       # 파일 이름 지정 (CLAUDE.md 등도 가능)
chronon init --agents-md          # init과 함께 CHRONON.md 작성
chronon init --agents-md-file AGENTS.md
```

`<!-- chronon:agents-md:begin -->` ~ `<!-- chronon:agents-md:end -->` 구간만 갱신하므로, 직접 작성한 나머지 내용은 재실행해도 보존됩니다.

## MCP

`chronon-mcp`는 stdio MCP 서버를 실행합니다. CLI와 동일한 operation layer를 사용하며 `add_resource`, `move_resource`, `copy_resource`, `read_resource`, `diff_resource`, `history_resource`, `commit_resource`, `write_resource`, `status_resource`, `path_history`, `rollback_resource` 등을 제공합니다.

MCP 서버의 작업 디렉터리는 초기화된 프로젝트 내부여야 합니다.
