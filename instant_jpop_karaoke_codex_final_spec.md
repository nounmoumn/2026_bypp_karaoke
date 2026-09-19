# Instant J-Pop Karaoke — Web Hackathon Final Spec

> **추가 요구 반영 완료:** 이 문서의 제품 방향을 [통합 기획 v3](instant_jpop_karaoke_web_spec.md)와 [구현 계획](docs/implementation_plan.md)에 반영했다. 아래 본문은 요구사항 원문 중심이며, 구체적인 우선순위·상태·API·데이터 계약·시간표는 통합 문서를 따른다. 특히 본문의 간략 JSON은 구현 스키마가 아니다. 변경 내용과 충돌 해소는 마지막 39절을 참고한다.

## 0. 한 줄 요약

**노래방에 없는 J-Pop도 웹사이트에서 오디오/링크와 가사만 넣으면, 보컬이 제거된 MR + 한글 독음 + 노래방식 가사 하이라이트 + 키 조절까지 자동 생성되는 즉석 노래방 서비스.**

핵심 경험:

1. 사용자가 웹사이트에 접속한다.
2. J-Pop 원곡 파일 또는 링크를 넣는다.
3. 일본어 가사를 붙여넣는다.
4. 서버에서 보컬과 반주를 분리한다.
5. 원보컬과 가사를 정렬해 시간축을 만든다.
6. 일본어 원문을 kana/mora와 한글 독음으로 변환한다.
7. 생성이 끝나면 웹 노래방 플레이어가 열린다.
8. 반주가 재생되면 한글 독음이 실제 발음 타이밍과 길이에 맞춰 노래방처럼 색이 차오른다.
9. 사용자는 폰/노트북을 앞에 두고 따라 부른다.
10. 필요하면 남자키/여자키 또는 세부 키 조절로 음정을 바꾼다. MVP는 렌더·로딩 상태를 표시하며 준비된 자산으로 같은 위치에서 재개한다.

이 프로젝트의 본질은 일본어 학습 앱이 아니라:

> **“노래방에 없는 곡을 바로 부르게 만드는 Instant Karaoke Generator”**

이다.

---

# 1. 문제 정의

한국 노래방에는 유명한 J-Pop만 수록되는 경우가 많고,
마이너 J-Pop / 애니송 / 인디 / 신곡은 수록되지 않거나 매우 늦게 들어온다.

특히 한국 사용자가 J-Pop을 실제로 부르려면 다음 문제가 있다.

- 곡 자체가 노래방에 없음
- 일본어 가사를 바로 읽기 어려움
- 보컬 제거만 해서는 노래방처럼 느껴지지 않음
- 가사를 음악에 맞춰 따라가야 함
- 여성 보컬 J-Pop은 원키가 높아 남성이 부르기 어려운 경우가 많음
- 폰 스피커로 반주를 틀고 별도 마이크를 가까이 대는 경우가 많아, 출력이 모바일 환경에 최적화될 필요가 있음

---

# 2. 제품 정의

## 입력

- 로컬 MP3 / WAV
- Optional: YouTube URL
- 일본어 가사
  - MVP: 직접 붙여넣기
  - Optional: 자동 가사 검색
- 선택 옵션
  - 일반 key shift
  - 남자키 / 여자키 preset
  - Guide vocal volume
  - Output mode

## 출력

- Karaoke backing track
- 일본어 원문
- Kana reading
- 한글 독음
- Line / word / mora timestamps
- Karaoke highlighting metadata
- 웹 기반 노래방 플레이어

---

# 3. 제품 형태

이 프로젝트는 **웹사이트 형태**로 구현한다.

설치형 앱이 아니라:

```text
웹사이트 접속
    ↓
곡 입력
    ↓
노래방 생성
    ↓
바로 웹에서 부르기
```

형태다.

핵심 페이지는 2개면 충분하다.

1. Generate Page
2. Karaoke Player Page

---

# 4. 전체 시스템 구조

```text
┌──────────────────────────────┐
│        Web Frontend          │
│ React + Vite + TypeScript    │
│                              │
│ - Audio / URL input          │
│ - Lyrics input               │
│ - Processing progress        │
│ - Karaoke Player             │
│ - Korean lyric sweep         │
│ - Key controls               │
│ - Male/Female key preset     │
│ - Phone Mode                 │
│ - Guide vocal control        │
│ - Optional YouTube backdrop  │
└──────────────┬───────────────┘
               │ HTTP API
               ▼
┌──────────────────────────────┐
│        FastAPI Backend       │
│                              │
│ - FFmpeg                     │
│ - Demucs / UVR               │
│ - Japanese preprocessing     │
│ - Alignment                  │
│ - Hangul pronunciation       │
│ - Key-shift render           │
│ - karaoke.json generation    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     Optional GPU Worker      │
│                              │
│ - Vocal separation           │
│ - WhisperX / alignment       │
└──────────────────────────────┘
```

---

# 5. 배포 구조

권장:

```text
Frontend
→ Vercel

Backend
→ 별도 FastAPI 서버

GPU-heavy tasks
→ 필요 시 GPU worker
```

중요:

**Demucs / WhisperX / FFmpeg 처리를 Vercel serverless 함수에 넣지 않는다.**

Vercel은:
- 웹 UI
- 정적 asset
- 프론트 배포

용도로만 사용한다.

무거운 오디오 처리는 별도 Python 서버에서 처리한다.

---

# 6. 가장 중요한 기술 판단

이 프로젝트에서 가장 어려운 부분은
**보컬 제거가 아니라 Singing Voice ↔ Japanese Lyrics Alignment**다.

따라서 가장 먼저 해야 할 PoC는:

```text
J-Pop vocal stem
+
correct Japanese lyrics
        ↓
timestamp generation
```

이다.

UI나 YouTube 연결부터 만들지 말 것.

---

# 7. 전체 오디오/가사 파이프라인

```text
            INPUT AUDIO
                 │
                 ▼
        Source Separation
          (Demucs / UVR)
            ↙       ↘
      vocals.wav   instrumental.wav
          │                │
          │                └─→ Karaoke Mix Processing
          │
          │
   Japanese Lyrics
          │
          ▼
 Japanese Normalization
 Kanji → Kana → Mora
          │
          ▼
 Singing Voice Alignment
          │
          ▼
 line / word / mora timestamps
          │
          ├─→ Hangul pronunciation
          │
          ▼
      karaoke.json
          │
          ▼
       Web Player
```

---

# 8. Audio Input

## MVP

- 로컬 MP3 / WAV 업로드

## Optional

- YouTube URL
- URL → audio extraction

주의:
- 해커톤 데모에서는 네트워크/다운로드 문제를 피하기 위해 데모 곡을 로컬에 캐시해 둔다.
- YouTube URL은 제품 UX 요소이지 핵심 기술이 아니다.

---

# 9. Vocal Separation

```text
original_audio
      ↓
 source separation
      ↓
├── vocals.wav
└── instrumental.wav
```

추천:
- Demucs
- UVR 계열 모델

MVP 목표:
- 완벽한 stem separation이 아니라
- **보컬이 충분히 줄어든 usable karaoke backing track**

---

# 10. GPU 필요성

## 결론

**GPU는 필수가 아니다.**

하지만:
- 라이브 생성 속도
- 발표 데모 안정성
- 실제 제품 UX

를 위해 강하게 권장한다.

## 단계별 판단

| 단계 | GPU 필요성 | 비고 |
|---|---|---|
| 오디오 변환 | 불필요 | FFmpeg CPU |
| 보컬 분리 | 권장 | CPU 가능하지만 느림 |
| EQ / compression / limiter | 불필요 | CPU |
| 키 조절 | 불필요 | CPU 가능 |
| 일본어 → kana / mora | 불필요 | CPU |
| kana → 한글 독음 | 불필요 | CPU |
| Whisper / WhisperX | 선택 | CPU 가능 |
| Forced alignment | 선택 | CPU 가능 |
| 가사 렌더링 | 불필요 | 브라우저 |
| 플레이어 | 불필요 | 브라우저 |

---

# 11. Karaoke Mix Processing

“노래방 스타일로 편곡”은 MVP에서
**악기를 새로 연주하거나 재편곡하는 것이 아니다.**

다음 수준만 구현:

```text
instrumental.wav
      ↓
loudness normalization
      ↓
light EQ
      ↓
compression
      ↓
limiter
      ↓
tempo-preserving key shift (MVP 필수)
      ↓
karaoke.wav
```

Optional:
- Guide vocal 0~30%
- Backing vocal 보존
- Light reverb / echo

필수:
- Key shift (-5~+5, 템포 유지)

---

# 12. Phone Speaker / Mic 사용 시나리오

실제 사용은 웹에서 WAV 반주를 스피커로 틀고 그 옆에 독립적인 노래방 마이크를 두어 공기 중 소리를 받는 방식이다. 마이크를 폰/PC에 유선·USB·Bluetooth 입력 장치로 연결하는 방식이 아니다. 웹 마이크 권한·입력 확인·상태 UI는 만들지 않는다.

```text
스마트폰
  ├─ MR 재생
  └─ 가사 표시

별도 마이크
  └─ 폰 스피커 가까이 대서
     반주 + 사용자 목소리를 함께 전달
```

따라서 **Phone Mode**를 제공한다.

## Phone Mode 목표

폰 스피커에서 반주가 잘 들리도록:

```text
MR
↓
저역 정리
↓
중역 가독성 확보
↓
Compression
↓
Limiter
↓
Mono compatibility
↓
Phone-optimized output
```

기본 모드:

```text
OUTPUT MODE

[ Original / Headphones ]
[ Phone Speaker ]
```

MVP에서는 완벽한 mastering보다
**폰에서 크게 틀었을 때 반주가 묻히지 않는 것**을 우선한다.

---

# 13. 키 조절 — MVP 필수 기능

키 조절은 필수 기능으로 취급한다.

```text
KEY

[-5] [-4] [-3] [-2] [-1] [0] [+1] [+2] [+3] [+4] [+5]
```

중요:

**템포를 유지한 채 pitch만 변경한다.**

변환 후 템포·길이·시작 지연을 검증하고 필요한 보정을 한 자산에서 기존 가사 timestamp를 재사용한다. 템포 설정만으로 싱크가 자동 보장된다고 가정하지 않는다.

```text
original tempo = 1.0
pitch = -3 semitones

lyrics timestamp = unchanged
```

권장:
- FFmpeg + rubberband
- 또는 동일 목적의 pitch-shift 라이브러리

---

# 14. 남자키 / 여자키 전환 — MVP 필수

J-Pop 여성 보컬 곡을 남성이 부를 때 원키가 너무 높은 경우가 많다.

따라서 일반 키 조절과 별도로:

```text
VOICE RANGE

[ 여성키 ] [ 원키 ] [ 남성키 ]
```

프리셋을 제공한다.

중요:
- “남자키 = 무조건 -5”라는 절대 규칙으로 구현하지 말 것
- MVP에서는 기본 preset 값을 둘 수 있지만, 사용자가 fine tune 가능해야 함

예:

```text
남성키 preset: -5
여성키 preset: +5
```

이후:

```text
FINE TUNE

[-2] [-1] [0] [+1] [+2]
```

또는 최종 absolute key 값을 그대로 보여준다.

예:

```text
현재 키: -4
Preset: Male
```

---

# 15. 미래 확장 — 자동 추천 남/여 키

시간이 남으면 보컬의 음역을 분석해 추천값을 계산할 수 있다.

```text
original vocal pitch contour
        ↓
estimate vocal range
        ↓
recommended shift
```

예:

```text
Original range
A3 ~ E5

Suggested:
Male key: -5
Female key: 0
```

하지만 **18시간 MVP에서는 자동 추천을 구현하지 않는다.**

---

# 16. 일본어 가사 처리

## 입력

```text
僕らはストレンジャーズ
君のいない夜を越えて
```

## Kanji → Reading

```text
僕らはストレンジャーズ
        ↓
ぼくらはすとれんじゃーず
```

## Mora Split

```text
ぼ / く / ら / は / す / と / れ / ん / じゃ / ー / ず
```

## Kana → Hangul

예:

```text
ぼ → 보
く → 쿠
ら → 라
は → 와
す → 스
と → 토
れ → 레
じゃ → 자
ず → 즈
```

표시:

```text
僕らはストレンジャーズ
보쿠라와 스토렌자즈
```

목표는 언어학적 완벽성보다
**한국 사용자가 따라 부르기 쉬운 실용적인 독음**이다.

---

# 17. Alignment 전략

## 핵심 목표

```text
vocals.wav
+
lyrics.txt
        ↓
alignment
        ↓
timestamps
```

## 1차 전략 — Forced Alignment

```text
isolated vocal
+
known lyrics
        ↓
Japanese normalization
        ↓
forced alignment
        ↓
phoneme / character / word timestamps
```

후보:
- WhisperX alignment
- Montreal Forced Aligner
- Japanese wav2vec2 / CTC alignment 계열

## Whisper의 역할

정확한 가사를 사용자가 제공하므로
Whisper의 주 역할은 **가사 생성이 아니라 timing estimation**이다.

fallback:

```text
Whisper / WhisperX timestamps
        ↓
provided lyrics와 sequence matching
        ↓
timing correction
```

---

# 18. Singing Voice Alignment의 어려움

노래는 일반 speech보다 정렬이 어렵다.

문제:
- vibrato
- 장음
- 발음 뭉개기
- 영어 혼용
- ad-lib
- rap
- harmony
- backing vocal

따라서 실제 J-Pop으로 반드시 PoC 테스트한다.

---

# 19. Fallback Alignment Levels

## Level A — Mora-level

```text
ぼ / く / ら / は
```

가장 이상적.

## Level B — Word-level

```text
僕らは / ストレンジャーズ
```

충분히 노래방 느낌 가능.

## Level C — Line-level

```text
僕らはストレンジャーズ
```

최소 fallback.

**18시간 안에 Level A가 완벽하지 않아도 Level B/C로 전체 사용자 흐름을 반드시 완성한다.**

---

# 20. 긴 음 처리

노래방 가사 렌더링에는
BPM 분석이나 악보 채보가 필수 아니다.

필요한 것은 각 mora의 start/end timestamp다.

예:

```json
{
  "mora": "ら",
  "start": 12.51,
  "end": 13.58
}
```

현재 재생 시간이 `t`이면:

```text
progress =
(t - start) / (end - start)
```

0~1로 clamp.

이를 글자 내부 fill 비율로 사용한다.

```text
라
█░░░░

라
██░░░

라
████░

라
█████
```

---

# 21. Karaoke Player 기본 화면

## MVP 디자인

처음에는 **검은 배경 + 한글 독음 중심**으로 간다.

```text
┌────────────────────────────────┐
│                                │
│                                │
│      와스레라레나이 요루니      │
│      █████████░░░░░░░         │
│                                │
│        키미토 마타...           │
│                                │
│                                │
└────────────────────────────────┘
```

현재 줄:
- 중앙
- 크게
- 한글 독음이 메인

다음 줄:
- 아래
- 작게
- 미리 표시

---

# 22. 일본어 원문 표시

2차 UI에서는 일본어 원문을 작은 글씨로 위에 표시할 수 있다.

```text
忘れられない夜に
와스레라레나이 요루니
██████████░░░░
```

표시 옵션:

```text
LYRICS

[ 한글 독음 ]
[ 일본어 + 한글 ]
[ 일본어 원문 ]
```

Optional:
- 번역 표시

---

# 23. Karaoke Highlight는 프론트에서 처리

Backend는:

```text
karaoke.wav
+
karaoke.json
```

만 생성한다.

Frontend는 `<audio>`의:

```text
currentTime
```

을 읽고 현재 가사 위치를 계산한다.

```text
if start <= currentTime <= end:
    progress = (currentTime - start) / (end - start)
```

이 값을 글자 fill에 적용한다.

재생 중에는:
- GPU 불필요
- 서버 inference 불필요
- 브라우저만으로 처리 가능

---

# 24. Frontend Highlight Rendering

권장:
- CSS gradient / mask
- 또는 SVG

구조:

```text
base lyric layer
+
accent lyric layer
+
clip width = progress%
```

각 mora를 독립적으로 렌더링하면
긴 음도 자연스럽게 sweep 가능하다.

---

# 25. Guide Vocal

원보컬을 아주 작게 섞어
사용자가 멜로디를 잊었을 때 따라갈 수 있게 한다.

```text
GUIDE VOCAL

OFF ───────●──────── FULL
           15%
```

권장:
- 기본 0%
- 사용자가 5~30% 정도까지 올릴 수 있게

가능하면 MR과 보컬을 별도 트랙으로 유지한다.

```text
karaoke.wav
vocals.wav
```

---

# 26. 플레이어 UI

예:

```text
┌───────────────────────────────┐

          忘れられない夜に
        와스레라레나이 요루니
        ███████████░░░░

          키미토 마타...

└───────────────────────────────┘

              ▶  01:42

VOICE RANGE
[ 여성 ] [ 원키 ] [ 남성 ]

KEY
-5 -4 -3 -2 -1 [0] +1 +2 +3 +4 +5

OUTPUT
[ 🎤 Phone Mode ] [ 🎧 Original ]

GUIDE VOCAL
────────●────────────
        15%
```

---

# 27. Optional — YouTube MV Background

시간이 남으면 사용자가 입력한 YouTube 영상을
노래방 배경으로 사용한다.

구조:

```text
YouTube Video
(muted)
      ↓
dark overlay
      ↓
Korean lyrics overlay
```

중요:
- YouTube는 화면 배경용
- 실제 소리는 우리가 만든 karaoke.wav 사용

```text
YouTube volume = 0
Karaoke MR volume = 1
```

---

# 28. YouTube Video Sync

기준 clock은 항상:

```text
karaokeAudio.currentTime
```

으로 한다.

YouTube 영상은 slave.

예:

```text
karaoke audio = 83.42
youtube video = 83.70
```

차이가 일정 threshold 이상이면 영상만 보정:

```text
youtube.seekTo(karaokeAudio.currentTime)
```

영상이 정확히 frame-level로 맞지 않아도
배경용이므로 허용 가능하다.

---

# 29. Background UI 단계

## MVP

```text
Black background
+
Hangul lyrics
+
MR
```

## v1.1

```text
Album art blur
+
Hangul lyrics
+
MR
```

## v1.2

```text
Muted YouTube MV
+
dark overlay
+
Hangul lyrics
+
MR
```

MV 배경은 시각적 임팩트 기능이므로
키 조절/가사 싱크보다 우선순위가 낮다.

---

# 30. 데이터 구조

```json
{
  "title": "Song Title",
  "artist": "Artist",
  "duration": 238.2,
  "audioUrl": "/generated/karaoke.wav",
  "guideVocalUrl": "/generated/vocals.wav",
  "originalKey": 0,
  "selectedKey": -4,
  "keyPreset": "male",
  "outputMode": "phone",
  "youtubeVideoId": "optional",
  "lines": [
    {
      "jp": "僕らはストレンジャーズ",
      "reading": "ぼくらはすとれんじゃーず",
      "ko": "보쿠라와 스토렌자즈",
      "start": 21.32,
      "end": 24.80,
      "moras": [
        {
          "jp": "ぼ",
          "ko": "보",
          "start": 21.32,
          "end": 21.48
        },
        {
          "jp": "く",
          "ko": "쿠",
          "start": 21.48,
          "end": 21.65
        }
      ]
    }
  ]
}
```

---

# 31. 기술 스택

## Frontend
- React
- Vite
- TypeScript
- Web Audio API
- CSS / SVG karaoke sweep
- Optional YouTube IFrame API

## Backend
- Python
- FastAPI

## Audio
- FFmpeg
- Demucs or UVR
- librosa
- pitch shift / rubberband

## Japanese
- tokenizer
- kanji → kana
- mora splitter
- kana → Hangul

## Alignment
우선순위:
1. WhisperX Japanese alignment PoC
2. MFA Japanese model PoC
3. ASR timestamp + provided lyrics matching
4. line-level fallback

---

# 32. 18시간 개발 계획

## Phase 0 — 0~3h
### Alignment Feasibility Test

실제 J-Pop 2~3곡:

```text
vocals.wav
+
correct Japanese lyrics
```

→ timestamp 확인

성공 기준:
- 최소 line-level
- 목표 word/mora-level

---

## Phase 1 — 3~5h

```text
audio
→ vocals.wav
→ instrumental.wav
```

---

## Phase 2 — 5~7h

```text
Kanji
→ Kana
→ Mora
→ Hangul
```

---

## Phase 3 — 7~10h

Alignment JSON 생성

최소:
- line start/end

목표:
- word/mora start/end

---

## Phase 4 — 10~12h

Web Karaoke Player

- MR 재생
- currentTime 추적
- 현재 라인
- 다음 라인
- 한글 독음
- timestamp highlighting
- 장음 sweep
- 검은 배경

---

## Phase 5 — 12~14h

필수 노래방 기능

- 일반 key shift
- 남성키 / 여성키 preset
- key 변경 후 timestamp 유지
- guide vocal

---

## Phase 6 — 14~16h

모바일 사용성

- Phone Speaker Mode
- output mastering
- responsive mobile UI

---

## Phase 7 — 16~18h

- Generate page
- processing state
- cache
- deployment
- demo optimization
- error handling

시간이 남으면:
- YouTube MV background
- album art blur

---

# 33. 기능 우선순위

## 반드시 구현

1. Vocal separation
2. Karaoke MR
3. Japanese lyrics input
4. Alignment
5. Hangul pronunciation
6. Karaoke lyric sweep
7. General key shift
8. Male/Female key preset
9. Web player

## 매우 중요

10. Phone Speaker Mode
11. Guide vocal

## 시간 남으면

12. Japanese original toggle
13. Album art background
14. YouTube MV background
15. Translation
16. Automatic key recommendation
17. Mic recording
18. Vocal scoring
19. Singer-following karaoke

---

# 34. 절대 하지 말 것

18시간 MVP에서:

- 악기를 새로 채보해서 재편곡
- AI로 새로운 반주 생성
- 모든 언어 지원
- 회원가입
- 소셜 기능
- playlist
- 실시간 가창 점수
- live score following
- 모든 J-Pop에서 100% mora alignment
- 자동 가사 검색에 시간 과투자
- 복잡한 GPU orchestration부터 구현
- 모바일 네이티브 앱 제작
- MV background를 core feature보다 먼저 구현

---

# 35. 성공 기준

## 최소 성공

웹에서 한 곡에 대해:

```text
Audio upload
→ vocal separation
→ karaoke backing track
→ Japanese lyrics
→ Korean pronunciation
→ synced lyric highlighting
→ key shift
→ browser karaoke playback
```

가 실제 동작.

## 좋은 결과

- word/mora 단위 sweep
- 긴 음 표현
- 남/여 키 preset
- 일반 key fine tune
- guide vocal
- Phone Speaker Mode
- 실제 J-Pop을 사용자가 폰에서 바로 따라 부름

---

# 36. Demo Scenario

발표:

> “저는 J-Pop을 좋아하지만, 제가 좋아하는 곡은 노래방에 없습니다.”

웹사이트 접속:

```text
ourkaraoke.app
```

입력:

```text
Upload Audio
Paste Japanese Lyrics
MAKE KARAOKE
```

Processing:

```text
✓ Vocal separated
✓ Lyrics aligned
✓ Korean pronunciation generated
✓ Karaoke ready
```

Player로 이동.

```text
忘れられない夜に
와스레라레나이 요루니

████████░░░░░░
```

발표자가:

```text
VOICE RANGE → MALE
KEY → -4
PHONE MODE → ON
```

선택.

폰으로 MR을 재생하고
실제로 한 소절 따라 부른다.

마지막:

> **노래방에 곡이 없으면, 그냥 만들면 됩니다.**

또는:

> **Every song is now a karaoke song.**

---

# 37. 가장 중요한 구현 원칙

1. GPU 서버부터 만들지 말 것
2. 실제 J-Pop 2~3곡으로 alignment PoC 먼저
3. Mora-level이 안 되면 word/line으로 즉시 degrade
4. 전체 웹 사용자 흐름을 우선 완성
5. 생성 결과는 karaoke.wav + karaoke.json으로 단순화
6. 재생 중 로직은 최대한 브라우저에서 처리
7. key shift는 tempo를 유지해 lyric timestamps를 그대로 재사용
8. 남/여 키는 preset + fine tune 방식
9. 모바일 스피커 사용을 실제 핵심 사용 시나리오로 본다
10. MV background는 core 기능이 끝난 뒤 추가한다

---

# 38. 최종 기술 판단

## 제품 형태
웹사이트

## 핵심 사용자
노래방에 없는 J-Pop / 인디 / 애니송을 부르고 싶은 사용자

## 기술적 실현 가능성
높음

## GPU 필수 여부
아님

## GPU 권장 여부
매우 높음

## 가장 큰 병목
Singing Voice ↔ Japanese Lyrics Alignment

## 필수 노래방 기능
- Hangul pronunciation
- Lyric sweep
- Key shift
- Male/Female key preset

## 실제 사용성 핵심
- Phone Speaker Mode
- Guide vocal

## 시각적 확장
- Album art
- Muted YouTube MV background

## 해커톤 전략
- React + FastAPI
- Frontend는 Vercel
- Audio backend는 별도 서버
- alignment PoC가 최우선
- line/word fallback 필수
- demo song은 반드시 미리 검증

---

# 39. 통합 구현 결정 — v3 반영

사용자가 추가한 요구와 이전 계획의 충돌을 다음과 같이 해소했다. 상세 구현은 [기획 v3](instant_jpop_karaoke_web_spec.md), 실제 순서·검증은 [구현 계획](docs/implementation_plan.md)이 기준이다.

| 요구 | 확정 범위 | 구체화한 내용 |
|---|---|---|
| 일반 키 조절 | P0 | -5~+5 절대 반음, tempo 유지, 요청 렌더·캐시 |
| 남성/원키/여성 | P0 | 기본 -5/0/+5, 설정 가능한 프리셋·fine tune·현재 절대값 표시 |
| Phone / Original | P0 | Phone 프로필, 같은 위치 전환·롤백, 실제 출력 장치 선택과 구분 |
| 노래방 마이크 사용 | 실제 사용 시나리오 | 웹 WAV→스피커→공기 중 소리→독립 마이크. 웹 입력 기능 없음 |
| 가사 표시 모드 | P0 | 한글 기본, 일본어+한글, 일본어; 오디오 상태 유지 |
| Guide vocal | P1 중요 추가 | 같은 키·공통 시계, 기본 0%, 0~30% |
| 모라 정렬·자동 음역 추천 | 후속 | 정렬 세밀화와 음역 분석은 필수 기능 완료 뒤 |
| MV·앨범아트·녹음·채점 | 후속 | 검은 배경 시연 우선 |

마이크 사용 확정: 웹에서 WAV를 스피커로 재생하고 그 옆에 노래방 마이크를 둔다. 폰/PC와 마이크를 연결하지 않는다. 이전에 추가한 브라우저 입력 확인은 요구를 잘못 확장한 것이므로 제거했다. Phone Mode는 이 사용 환경을 위한 출력 프로필이며, 마이크 상태·권한·레벨 확인·녹음 기능은 구현하지 않는다.

서버 렌더링은 새 키에서 대기가 있을 수 있다. 캐시된 키와 신규 렌더 시간을 따로 측정하고, 전환 중 잠시 정지→동일 위치 재개를 허용한다. 완전한 무중단 실시간 DSP는 MVP 약속이 아니다. 연속 요청은 마지막 선택만 적용하고 실패 시 기존 키·출력으로 돌아간다.

데이터의 `originalKey: 0`은 원곡 대비 이동량을 뜻한다. 조성 분석값이 아니다. 상세 계약은 schemaVersion 1.1의 playbackPreferences·keyPresets와 별도 variant API를 사용한다. 정렬 JSON은 키/출력 선택마다 복제하지 않는다.

모바일은 실제 시연 폰 1대에서 확인한다. 로컬 기본 배포 외에 폰이 접근해 반주를 재생할 수 있는 주소를 준비한다. 마이크 API를 위한 배포·권한 조건은 추가하지 않는다.

18시간 계획은 필수 범위가 늘어난 공격적인 목표다. 키·Phone을 몰래 후순위로 내리지 않는다. 부족하면 Guide·배경·모라 정렬을 제외하고 자동 정렬을 반자동으로 낮춘다. 그래도 남은 P0는 미완료로 기록한다.
