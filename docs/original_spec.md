# Instant J-Pop Karaoke — Web Hackathon Technical Spec

## 0. 한 줄 요약

**노래방에 없는 J-Pop도 웹사이트에서 오디오/링크와 가사만 넣으면, 보컬이 제거된 MR + 한글 독음 + 노래방식 가사 하이라이트가 자동 생성되는 즉석 노래방 서비스.**

핵심 경험:

1. 사용자가 웹사이트에 접속한다.
2. J-Pop 원곡 파일 또는 링크를 넣는다.
3. 일본어 가사를 붙여넣는다.
4. 서버에서 보컬과 반주를 분리한다.
5. 원보컬과 가사를 정렬해 시간축을 만든다.
6. 일본어 원문을 kana/mora와 한글 독음으로 변환한다.
7. 생성이 끝나면 웹 노래방 플레이어가 열린다.
8. 반주가 재생되면 가사가 실제 발음 타이밍과 길이에 맞춰 노래방처럼 색이 차오른다.
9. 사용자는 폰/노트북 화면을 보고 그대로 따라 부른다.

이 프로젝트의 본질은 일본어 학습 앱이 아니라:

> **“노래방에 없는 곡을 바로 부르게 만드는 Instant Karaoke Generator”**

이다.

---

# 1. 문제 정의

한국 노래방에는 유명한 J-Pop만 수록되는 경우가 많고,
마이너 J-Pop / 애니송 / 인디 / 신곡은 수록되지 않거나 매우 늦게 들어온다.

기존 보컬 제거 서비스는 MR 생성에는 강하지만,
한국 사용자가 실제 노래방처럼 부르기에는 다음이 부족하다.

- 일본어 가사의 **한글 독음**
- 음악과 정확히 맞는 **노래방식 lyric sweep**
- 긴 음을 끄는 구간까지 반영한 **시간축 기반 highlighting**
- 키 조절 / guide vocal 등 **노래방 UX**
- 원곡 하나로 바로 부를 수 있는 **end-to-end 생성 경험**

---

# 2. 제품 정의

## 입력

- 로컬 MP3 / WAV
- Optional: YouTube URL
- 일본어 가사
  - MVP: 직접 붙여넣기
  - Optional: 자동 가사 검색
- 선택 옵션
  - Key shift
  - Guide vocal volume

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

핵심 UX는 최대한 단순하게 유지한다.

페이지는 실질적으로 2개면 충분하다.

1. **Generate Page**
2. **Karaoke Player Page**

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
│ - Lyric highlighting         │
│ - Key / Guide vocal controls │
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

# 6. 웹 UX

## Screen 1 — Generate Page

```text
┌────────────────────────────────┐
│         MAKE KARAOKE           │
│                                │
│ YouTube URL                    │
│ [__________________________]   │
│                                │
│ or Upload Audio                │
│ [ Choose File ]                │
│                                │
│ Japanese Lyrics                │
│ ┌────────────────────────────┐ │
│ │ 僕らはストレンジャーズ       │ │
│ │ 君のいない夜を越えて         │ │
│ │                            │ │
│ └────────────────────────────┘ │
│                                │
│        [ CREATE KARAOKE ]      │
└────────────────────────────────┘
```

---

## Processing State

```text
Creating your karaoke...

✓ Extracting audio
✓ Separating vocals
◉ Aligning lyrics
○ Generating Korean pronunciation
○ Building karaoke
```

처리 단계가 보이게 해서
오디오 분석 시간이 있어도 사용자가 기다릴 이유를 이해하도록 한다.

---

## Screen 2 — Karaoke Player

```text
              晩餐歌
              tuki.

         忘れられない夜に
       와스레라레나이 요루니

       ███████████░░░░

        次の歌詞がここに...

────────────────────────────
1:32                        3:47

               ▶

KEY       -2  -1  [0]  +1  +2

GUIDE
0% ─────────●──────── 30%
```

핵심:
- 현재 가사 크게
- 다음 가사 작게
- 일본어 원문
- 한글 독음
- 실시간 sweep
- Play / Pause
- Key
- Guide vocal

---

# 7. 가장 중요한 기술 판단

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

# 8. 전체 오디오/가사 파이프라인

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

# 9. Audio Input

## MVP

- 로컬 MP3 / WAV 업로드

## Optional

- YouTube URL
- URL → audio extraction

주의:
- 해커톤 데모에서는 네트워크/다운로드 문제를 피하기 위해 데모 곡을 로컬에 캐시해 두는 것을 권장
- YouTube URL은 제품 UX 요소이지 핵심 기술이 아님

---

# 10. Vocal Separation

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
- 완벽한 separation이 아니라
- **보컬이 충분히 줄어든 usable karaoke backing track**

---

# 11. GPU 필요성 판단

## 결론

**GPU는 필수가 아니다.**

하지만:
- 라이브 생성 속도
- 발표 데모 안정성
- 실제 제품 UX

를 위해서는 강하게 권장한다.

---

## 단계별 GPU 필요성

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

# 12. 해커톤 서버 구성

## GPU 노트북이 있다면

```text
React/Vite Frontend
        │
        ▼
Local FastAPI
        │
        ├─ Demucs
        ├─ Alignment
        ├─ Japanese Processing
        └─ FFmpeg
```

가 가장 빠르고 단순하다.

---

## GPU 노트북이 없다면

```text
Web Frontend
     │
     ▼
CPU API Server
     │
 Create Job
     │
     ▼
GPU Worker
├─ Demucs
└─ Alignment
     │
     ▼
Generated Assets
```

권장 VRAM:
- 최소 현실적: 8GB
- 안정적: 12GB+
- 16GB면 여유

Demucs와 Whisper 계열 모델을
동시에 메모리에 올릴 필요는 없다.

```text
Demucs
→ unload
→ Alignment model
→ unload
```

순차 실행 가능.

---

# 13. CPU-only도 가능

CPU에서도 기능 자체는 동작 가능하다.

단점:
- 보컬 분리가 가장 느린 병목
- 긴 곡은 생성 시간이 길어질 수 있음

발표용 데모는 cache를 적극 활용한다.

```text
demo/
├── original.mp3
├── vocals.wav
├── karaoke.wav
├── lyrics.json
└── metadata.json
```

---

# 14. Karaoke Mix Processing

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
optional key shift
      ↓
karaoke.wav
```

Optional:
- Guide vocal 0~30%
- Backing vocal 보존
- Light reverb / echo
- Key shift (-3 ~ +3 semitones)

---

# 15. 일본어 가사 처리

## 입력

```text
僕らはストレンジャーズ
君のいない夜を越えて
```

---

## Kanji → Reading

```text
僕らはストレンジャーズ
        ↓
ぼくらはすとれんじゃーず
```

---

## Mora Split

```text
ぼ / く / ら / は / す / と / れ / ん / じゃ / ー / ず
```

---

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

# 16. Alignment 전략

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

---

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

---

## Whisper의 역할

사용자가 정확한 가사를 제공하므로
Whisper의 주 역할은 가사 생성이 아니라:

```text
rough timing estimation
```

이다.

fallback:

```text
Whisper / WhisperX timestamps
        ↓
provided lyrics와 sequence matching
        ↓
timing correction
```

---

# 17. Singing Voice Alignment의 어려움

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

# 18. Fallback Alignment Levels

## Level A — Mora-level

```text
ぼ / く / ら / は
```

가장 이상적.

---

## Level B — Word-level

```text
僕らは / ストレンジャーズ
```

충분히 노래방 느낌 가능.

---

## Level C — Line-level

```text
僕らはストレンジャーズ
```

최소 fallback.

**18시간 안에 Level A가 완벽하지 않아도
Level B/C로 전체 사용자 흐름을 반드시 완성할 것.**

---

# 19. 긴 음 처리

노래방 가사 렌더링에는
BPM 분석이나 악보 채보가 필수 아니다.

필요한 것은 각 mora의:

```text
start
end
```

timestamp다.

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

따라서 긴 음도 노래방처럼 자연스럽게 표현 가능.

---

# 20. BPM / Note Tracking 필요 여부

## MVP에서는 필요 없음

가사 표시의 핵심은:

```text
beat tracking
```

이 아니라

```text
vocal ↔ lyric alignment
```

이다.

Pitch tracking은
나중에 가창 점수 기능을 넣을 때 필요하다.

---

# 21. 데이터 구조

```json
{
  "title": "Song Title",
  "artist": "Artist",
  "duration": 238.2,
  "audioUrl": "/generated/karaoke.wav",
  "guideVocalUrl": "/generated/vocals.wav",
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

# 22. Karaoke Highlight는 프론트에서 처리

중요:

**재생 중 가사 애니메이션을 서버에서 처리하지 않는다.**

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

예:

```text
if start <= currentTime <= end:
    progress = (currentTime - start) / (end - start)
```

이 값을 이용해 글자 fill을 렌더링한다.

즉 노래 재생 중에는:
- GPU 불필요
- 서버 inference 불필요
- 브라우저만으로 처리 가능

---

# 23. Frontend Rendering

권장:
- React
- CSS gradient / mask
- SVG도 가능

각 mora span을 독립적으로 렌더링한다.

```text
default text
+
same text overlay
+
clip width = progress%
```

방식이 구현하기 쉽다.

---

# 24. 플레이어 오디오 구조

가능하면 MR과 guide vocal을 별도 트랙으로 유지한다.

```text
karaoke.wav
vocals.wav
```

두 `<audio>` 또는 Web Audio API source를 동기화해서:

```text
MR volume = 100%
Guide Vocal = 0~30%
```

사용자가 조절하게 한다.

---

# 25. Key Shift

MVP 선택지:

### 서버에서 미리 처리
- FFmpeg / librosa

### 브라우저에서 처리
- Web Audio 기반 pitch shift library

해커톤에서는 구현 안정성이 높은 쪽 선택.

Key:

```text
-3 -2 -1 0 +1 +2 +3
```

정도면 충분.

---

# 26. 기술 스택

## Frontend
- React
- Vite
- TypeScript
- Web Audio API
- CSS / SVG karaoke sweep

## Backend
- Python
- FastAPI

## Audio
- FFmpeg
- Demucs or UVR
- librosa

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

# 27. 18시간 개발 계획

## Phase 0 — 0~3h
### Alignment Feasibility Test

절대 UI부터 만들지 않는다.

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
Vocal separation

```text
audio
→ vocals.wav
→ instrumental.wav
```

---

## Phase 2 — 5~7h
Japanese processing

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

## Phase 4 — 10~13h
Web Karaoke Player

- MR 재생
- currentTime 추적
- 현재 라인
- 다음 라인
- timestamp highlighting
- 장음 sweep

---

## Phase 5 — 13~15h
Web UX

- Generate Page
- processing state
- player route
- key shift
- guide vocal
- styling

---

## Phase 6 — 15~18h
- error handling
- cache
- demo song 최적화
- deployment
- 발표 준비

---

# 28. 절대 하지 말 것

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

---

# 29. 시간이 남으면 추가

우선순위:

1. Key shift
2. Guide vocal slider
3. 자동 한글 독음
4. Furigana
5. 번역
6. Mic recording
7. Pitch scoring
8. Singer-following karaoke
9. 자동 가사 검색
10. YouTube direct import

---

# 30. 성공 기준

## 최소 성공

웹에서 한 곡에 대해:

```text
Audio upload
→ vocal separation
→ karaoke backing track
→ Japanese lyrics
→ Korean pronunciation
→ synced lyric highlighting
→ browser karaoke playback
```

가 실제 동작.

---

## 좋은 결과

- word/mora 단위 sweep
- 긴 음 표현
- key shift
- guide vocal
- 실제 J-Pop을 사용자가 브라우저에서 바로 따라 부름

---

# 31. Demo Scenario

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

Player로 자동 이동.

```text
僕らはストレンジャーズ
보쿠라와 스토렌자즈

████████░░░░░░
```

MR이 나오고 사용자가 직접 한 소절 부른다.

마지막:

> **노래방에 곡이 없으면, 그냥 만들면 됩니다.**

또는:

> **Every song is now a karaoke song.**

---

# 32. 가장 중요한 구현 원칙

이 프로젝트의 리스크는
**웹을 만들 수 있냐 / GPU가 있냐가 아니라 alignment가 실제 노래에서 먹히냐**다.

따라서:

1. GPU 서버부터 만들지 말 것
2. 실제 J-Pop 2~3곡으로 alignment PoC 먼저
3. Mora-level이 안 되면 word/line으로 즉시 degrade
4. 전체 웹 사용자 흐름을 우선 완성
5. 생성 결과는 karaoke.wav + karaoke.json으로 단순화
6. 재생 중 로직은 최대한 브라우저에서 처리
7. GPU는 생성 속도 최적화 용도로 나중에 붙인다

---

# 33. 최종 기술 판단

## 제품 형태
웹사이트

## 기술적 실현 가능성
높음

## GPU 필수 여부
아님

## GPU 권장 여부
매우 높음

## 가장 큰 병목
Singing Voice ↔ Japanese Lyrics Alignment

## 가장 쉬운 부분
- 웹 UI
- 보컬 분리
- 한글 독음
- lyric rendering
- MR 후처리

## 가장 위험한 부분
- mora-level singing alignment 정확도

## 해커톤 전략
- React + FastAPI
- Frontend는 Vercel
- Audio backend는 별도 서버
- alignment PoC가 최우선
- line/word fallback 필수
- demo song은 반드시 미리 검증
