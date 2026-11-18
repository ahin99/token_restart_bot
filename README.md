# tokenbot — 5시간 사용량 윈도우 자동 갱신 봇

Claude Code와 Codex의 5시간 사용량 윈도우는 **5시간이 지나면 자동으로 다시 시작되지 않습니다.**
리셋 후 **다음 메시지를 보낸 순간** 새 윈도우가 시작됩니다.
그래서 자는 동안이나 자리를 비운 동안에는 윈도우가 비어 있는 시간이 생깁니다.

tokenbot은 항상 켜 둔 Mac mini에서 1분마다 상태를 확인합니다.
**윈도우가 끝나면 바로 짧은 메시지("Reply with just: ok")를 보내서** 다음 윈도우를 시작시킵니다.
자기 전에 아무 채팅이나 쳐 두는 걸 자동으로 해 주는 프로그램입니다.

> ⚠️ 주간 한도는 늘지 않습니다. 리셋이 **더 빨리, 끊김 없이** 오게 할 뿐입니다.

---

## 단계별 실행 안내 (처음부터 끝까지)

현재 설정(`config.json`)은 **01:00~06:00에는 핑을 보내지 않고, 매일 06:00에 첫 핑**을 보냅니다.
아래 순서대로 Mac mini에서 따라 하면 됩니다. 각 단계의 자세한 설명은 [설치](#설치-mac-mini) 절에 있습니다.

### 1단계. 폴더를 Mac mini로 옮기기

`token_restart_bot` 폴더 전체를 Mac mini의 홈 폴더(`~/token_restart_bot`)에 복사합니다. AirDrop이나 USB도 됩니다.
**`config.json`도 함께 옮기세요.** git으로 옮기면 `config.json`이 빠지니, 그때는 2단계 뒤에 아래 설정 변경을 다시 해야 합니다.

다른 Mac에서 `scp`로 보내는 예 (`mini.local`은 Mac mini 주소로 바꾸세요):

```bash
scp -r ~/token_restart_bot mini.local:~/
```

### 2단계. Mac mini에서 터미널을 열고 폴더로 이동

```bash
cd ~/token_restart_bot
```

Python 버전을 확인합니다. 3.9 이상이면 됩니다.

```bash
python3 --version
```

### 3단계. CLI 설치와 로그인

이미 설치되어 있다면 건너뜁니다.

```bash
npm install -g @anthropic-ai/claude-code @openai/codex
```

각각 한 번 실행해서 로그인합니다. 로그인이 끝나면 `/exit`이나 Ctrl+C로 나옵니다.

```bash
claude
```

```bash
codex
```

### 4단계. 설정과 시각표 확인 (핑을 보내지 않음)

`config.json`이 없으면 먼저 만듭니다. 이미 있으면 건너뜁니다.

```bash
python3 tokenbot.py init
```

`quiet_hours`가 `["01:00-06:00"]`인지 확인합니다. 아니라면 텍스트 편집기로 고칩니다.

```bash
grep quiet_hours config.json
```

현재 상태와 앞으로의 핑 시각을 봅니다. 핑이 06:00, 11:02, 16:04, 21:06으로 나오면 정상입니다.

```bash
python3 tokenbot.py status
```

```bash
python3 tokenbot.py plan
```

Codex를 쓰지 않는다면 `config.json`에서 `"codex"`의 `"enabled"`를 `false`로 바꿉니다.

### 5단계. 테스트 핑 한 번 보내기

> 이 명령은 **실제 메시지를 보내므로 지금부터 5시간 윈도우가 시작됩니다.**
> 사용량이 아깝다면 01:00 직전처럼 어차피 곧 핑이 멈추는 시간에 해도 됩니다.

```bash
python3 tokenbot.py ping claude
```

```bash
python3 tokenbot.py ping codex
```

로그에 `성공 → 새 윈도우 시작`이 찍히면 됩니다. 그다음 [claude.ai/settings/usage](https://claude.ai/settings/usage)와 Codex 사용량 화면에서 윈도우가 실제로 시작됐는지 확인합니다.

### 6단계. Mac mini가 잠들지 않게 설정

시스템 설정에서 아래 세 가지를 켭니다.

- **에너지** → "디스플레이가 꺼져 있을 때 자동으로 잠자지 않기"
- **에너지** → "정전 후 자동으로 시동"
- **사용자 및 그룹** → 자동 로그인 (FileVault가 켜져 있으면 쓸 수 없음. [설치 6번](#6-mac-mini를-서버로-만드는-시스템-설정) 참고)

터미널로 하려면 (관리자 비밀번호 필요):

```bash
sudo pmset -a sleep 0
```

```bash
sudo pmset -a autorestart 1
```

### 7단계. 자동 실행 등록

```bash
python3 tokenbot.py install
```

`설치 완료`가 나오면 이제부터 1분마다 봇이 돌아갑니다.

### 8단계. 제대로 돌고 있는지 확인

1~2분 뒤 상태를 봅니다. **"마지막 tick"이 방금 시각이면 정상**입니다.

```bash
python3 tokenbot.py status
```

자동 실행 등록 상태를 직접 보고 싶다면:

```bash
launchctl print gui/$(id -u)/com.tokenbot.tick
```

### 9단계. 다음 날 아침에 확인

06:00 이후에 로그를 봅니다. `06:00` 근처에 `핑 전송`과 `성공`이 찍혀 있으면 완료입니다.

```bash
python3 tokenbot.py log
```

### 이후 관리

- **시각 바꾸기:** `config.json`의 `quiet_hours`만 고치면 됩니다. 다음 tick부터 바로 적용되니 다시 설치할 필요는 없습니다. 예를 들어 첫 핑을 07:00으로 바꾸려면 `["02:00-07:00"]`로 고칩니다.
- **CLI를 다시 설치했거나 폴더를 옮겼다면:** `python3 tokenbot.py install`을 다시 실행합니다.
- **잠시 멈추기 / 완전히 끄기:**

```bash
python3 tokenbot.py uninstall
```

---

## 동작 방식

```
launchd (1분마다)
   └─ tokenbot.py tick
        ├─ 로컬 로그에서 최근 사용 시각 수집
        │    · Claude: ~/.claude/projects/**/*.jsonl
        │    · Codex : ~/.codex/sessions/**/*.jsonl
        ├─ "현재 윈도우 = 리셋 이후 첫 사용 시각 ~ +5시간" 계산
        ├─ 윈도우가 없고, 핑 금지 시간이 아니면
        │    → claude -p "..." --model haiku / codex exec "..." 실행
        └─ 결과를 data/state.json, data/bot.log 에 기록
```

- **윈도우 계산:** Mac mini에서 직접 쓴 사용도 로그로 반영되니, 수동 사용과 봇 핑이 섞여도 계산이 맞습니다.
- **여유 시간:** 윈도우 만료 후 2분(`buffer_minutes`)을 두고 핑을 보냅니다. 살아 있는 윈도우 안에서 핑을 낭비하지 않기 위해서입니다.
- **한도 초과 응답:** "usage limit reached" 같은 응답은 아직 윈도우가 남아 있다는 뜻으로 보고 10분 뒤 다시 시도합니다. 이 실패한 시도는 사용으로 계산하지 않습니다.
- **실패 알림:** 명령을 찾지 못하거나 시간 초과 같은 진짜 오류가 나면 macOS 알림을 띄웁니다.

### 다른 기기에서 쓴 사용은 반영되지 않습니다

봇은 **Mac mini의 로그만** 읽습니다. 노트북에서 직접 대화를 시작한 기록은 Mac mini가 모릅니다.

그래도 문제는 작습니다. 노트북에서 쓰는 동안은 봇이 계산한 윈도우가 이미 살아 있거나 곧 끝납니다. 봇이 이미 활성화된 윈도우 안에서 핑을 보내면 짧은 메시지 하나가 낭비되고, 그 핑을 새 윈도우의 시작으로 기록합니다. 이 경우 다음 핑이 실제 리셋보다 최대 몇 시간 늦어질 수 있습니다.

정확도를 높이려면 아래 [작업 시간에 맞추기](#작업-시간에-맞추기-핑-금지-시간) 설정을 쓰세요.

---

## 요구 사항

- macOS가 설치된 Mac mini (항상 켜 둠)
- Python 3.9 이상 (외부 패키지 불필요)
- Claude Code CLI(`claude`)와 Codex CLI(`codex`)가 설치되고 **로그인된 상태**

---

## 설치 (Mac mini)

### 1. CLI 설치와 로그인 확인

```bash
npm install -g @anthropic-ai/claude-code @openai/codex
```

Claude Code 로그인 확인 (응답이 오면 정상):

```bash
claude -p "Reply with just: ok" --model haiku
```

Codex 로그인 확인:

```bash
codex exec --skip-git-repo-check "Reply with just: ok"
```

로그인이 안 되어 있다면 Mac mini에서 `claude`와 `codex`를 한 번씩 실행해 로그인하세요.

> **처음 한 번은 꼭 확인하세요.** 위 명령을 실행한 뒤
> [claude.ai/settings/usage](https://claude.ai/settings/usage)와 Codex 사용량 화면에서
> 5시간 윈도우가 실제로 시작됐는지 확인합니다. 아주 짧은 핑으로도 윈도우가 시작되는지 확인하는 단계입니다.

### 2. 이 폴더를 Mac mini에 두기

예: `~/token_restart_bot`. git, AirDrop, `scp` 중 편한 방법으로 옮깁니다.

### 3. 설정 파일 만들기 (선택)

```bash
python3 tokenbot.py init
```

`config.json`이 생성됩니다. 없으면 `config.example.json`을 그대로 씁니다. Codex를 쓰지 않는다면 `"codex"`의 `"enabled"`를 `false`로 바꾸세요.

### 4. 동작 미리 보기 (핑 없음)

```bash
python3 tokenbot.py status
```

```bash
python3 tokenbot.py plan
```

```bash
python3 tokenbot.py tick --dry-run -v
```

### 5. 자동 실행 등록

```bash
python3 tokenbot.py install
```

`~/Library/LaunchAgents/com.tokenbot.tick.plist`가 만들어지고, 1분마다 `tick`이 실행됩니다.
등록할 때 `claude`, `codex`, `node`의 경로를 찾아 plist에 넣어 둡니다. CLI를 다른 곳에 다시 설치했다면 `install`을 한 번 더 실행하세요.

### 6. Mac mini를 "서버"로 만드는 시스템 설정

| 설정 | 위치 / 명령 | 이유 |
|---|---|---|
| 잠자기 끄기 | 시스템 설정 → 에너지 → **"디스플레이가 꺼져 있을 때 자동으로 잠자지 않기"** 켜기, 또는 아래 명령 1 | 잠자기 상태에서는 launchd가 실행되지 않음 |
| 정전 후 자동 켜기 | 시스템 설정 → 에너지 → **"정전 후 자동으로 시동"** 켜기, 또는 아래 명령 2 | 정전이 끝나면 다시 켜지게 |
| 자동 로그인 | 시스템 설정 → 사용자 및 그룹 → **자동 로그인** | 봇은 사용자 세션에서 도는 LaunchAgent라, 로그인되어 있어야 실행됨 |
| (선택) 원격 접속 | 시스템 설정 → 일반 → 공유 → **원격 로그인(SSH)** / **화면 공유** | 다른 기기에서 상태 확인 |

명령 1 (잠자기 끄기):

```bash
sudo pmset -a sleep 0
```

명령 2 (정전 후 자동 시동):

```bash
sudo pmset -a autorestart 1
```

> **FileVault를 켜 두면 자동 로그인을 쓸 수 없습니다.** 정전 후 재부팅되면 누군가 비밀번호를 입력해야 봇이 다시 돕니다.
> 보안과 편의 중 무엇을 고를지 직접 판단하세요. 화면은 꺼져도 되고, 잠금 화면 상태여도 로그인 세션만 살아 있으면 동작합니다.

---

## 명령어

| 명령 | 설명 |
|---|---|
| `python3 tokenbot.py status` | 서비스별 현재 윈도우, 남은 시간, 다음 핑 시각, 마지막 결과 |
| `python3 tokenbot.py plan [--hours 48]` | 직접 쓰지 않는다고 가정했을 때 앞으로의 핑과 리셋 시각 |
| `python3 tokenbot.py ping [claude\|codex]` | 지금 바로 핑 보내기 (생략하면 전부) |
| `python3 tokenbot.py tick [--dry-run] [-v]` | 한 번 검사 (launchd가 1분마다 실행) |
| `python3 tokenbot.py log [-n 50]` | 최근 로그 |
| `python3 tokenbot.py install` / `uninstall` | launchd 등록 / 해제 |
| `python3 tokenbot.py init [--force]` | `config.json` 생성 |

---

## 설정 (`config.json`)

```json
{
  "window_hours": 5,
  "buffer_minutes": 2,
  "retry_minutes": 10,
  "quiet_hours": [],
  "notify_on_failure": true,
  "ping_timeout_seconds": 180,
  "providers": {
    "claude": {
      "enabled": true,
      "command": ["claude", "-p", "{prompt}", "--model", "haiku"],
      "prompt": "Reply with just: ok",
      "log_globs": ["~/.claude/projects/**/*.jsonl"],
      "activity_types": ["user", "assistant"],
      "floor_window_start_to_hour": false
    },
    "codex": { "...": "같은 구조" }
  }
}
```

| 키 | 의미 |
|---|---|
| `window_hours` | 윈도우 길이. 정책이 바뀌면 여기만 수정 |
| `buffer_minutes` | 만료 후 몇 분 뒤에 핑을 보낼지 |
| `retry_minutes` | 실패하거나 한도에 걸렸을 때 재시도 간격 |
| `quiet_hours` | 핑을 보내지 않는 시간대. 예: `["01:00-06:00"]`, 자정을 넘는 `"23:00-05:00"`도 가능 |
| `command` | 실행할 명령. `{prompt}`가 `prompt`로 바뀜. 더 싼 모델을 쓰려면 여기 수정 (Codex 예: `"-m", "<모델명>"` 추가) |
| `log_globs` | 사용 시각을 읽을 로그 위치 |
| `activity_types` | 로그 줄 중 사용으로 칠 `type` 값. 빈 배열이면 전부 |
| `floor_window_start_to_hour` | 윈도우 시작을 정시로 내림해서 계산할지. 실제 정책이 정시 내림이라고 확인되면 `true` |

핑은 `data/ping-workdir/`에서 실행됩니다. 그래서 Claude Code의 프로젝트 목록에 이 폴더가 하나 생깁니다.

---

## 작업 시간에 맞추기 (핑 금지 시간)

봇은 윈도우를 계속 이어 붙입니다. 하루는 24시간이라 5시간 간격과 딱 맞지 않아서, 그냥 두면 리셋 시각이 매일 조금씩 밀립니다.

`quiet_hours`를 쓰면 **매일 같은 시각에 첫 윈도우가 시작되게** 고정할 수 있습니다.

**예: 10시~22시에 작업하는 경우**

```json
"quiet_hours": ["01:00-06:00"]
```

| 시각 | 동작 |
|---|---|
| 01:00~06:00 | 핑 없음 |
| 06:00 | 첫 핑 → 11:00에 리셋 |
| 11:02 | 핑 → 16:02에 리셋 |
| 16:04 | 핑 → 21:04에 리셋 |
| 21:06 | 핑 → 02:06에 리셋 (그 뒤는 핑 금지 시간이라 대기) |

10시에 작업을 시작하면 **1시간 만에 첫 리셋**이 옵니다. 오전에 한도를 다 써도 금방 다시 쓸 수 있습니다.

원칙은 **"핑 금지 시간이 끝나는 시각 = 작업 시작 3~4시간 전"** 입니다. `python3 tokenbot.py plan`으로 실제 시각표를 확인하세요.

---

## 파일 구조

```
token_restart_bot/
├── tokenbot.py            # 프로그램 본체 (표준 라이브러리만 사용)
├── config.example.json    # 기본 설정
├── config.json            # 내 설정 (init 으로 생성, git 제외)
├── tests/test_tokenbot.py # 단위 테스트
└── data/                  # 실행 중 생성 (git 제외)
    ├── state.json         # 마지막 성공/실패, 재시도 시각
    ├── bot.log            # 핑 기록
    ├── launchd.*.log      # launchd 표준 출력/에러
    └── ping-workdir/      # 핑 실행 폴더
```

테스트 실행 (실제 Claude나 Codex를 호출하지 않음):

```bash
python3 -m unittest discover -s tests -v
```

---

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 핑이 전혀 안 감 | `status`에서 "마지막 tick"이 최근 시각인지 확인. 오래됐다면 `data/launchd.err.log`를 보고, `launchctl print gui/$(id -u)/com.tokenbot.tick`으로 등록 상태 확인 |
| `명령을 찾을 수 없음` | CLI 경로가 바뀐 경우입니다. `install`을 다시 실행 |
| 터미널에서는 되는데 launchd에서는 로그인 오류 | 로그인 정보가 키체인에 있으면 잠긴 세션에서 못 읽을 수 있습니다. 자동 로그인을 켜거나, Claude는 `claude setup-token`으로 발급한 토큰을 plist의 `EnvironmentVariables`에 `CLAUDE_CODE_OAUTH_TOKEN`으로 추가 |
| 계속 `limited` | 실제로 윈도우가 살아 있는 상태입니다. 다른 기기에서 쓴 경우 정상이며, 10분마다 재시도합니다 |
| 리셋 시각이 사용량 화면과 몇십 분 다름 | 실제 정책이 정시 내림일 수 있습니다. `floor_window_start_to_hour: true`로 바꿔 보세요 |

---

## 제거

```bash
python3 tokenbot.py uninstall
```

`data/`는 남아 있으니 필요 없으면 직접 지우세요.

---

## 주의

- 봇은 이미 로그인된 공식 CLI를 호출만 합니다. 토큰이나 비밀번호를 따로 저장하지 않습니다.
- 핑은 윈도우당 1번, 가장 싼 모델로 아주 짧게 보냅니다.
- 사용량 정책(윈도우 길이, 계산 방식)은 바뀔 수 있습니다. 정책이 바뀌면 `config.json`을 고치세요.
- 자동 메시지 전송이 각 서비스 약관에 맞는지는 직접 확인하세요.
