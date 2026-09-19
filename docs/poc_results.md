# T01 PoC 진행 기록

## 환경 (2026-09-18)

| 항목 | 확인 결과 |
|---|---|
| OS | Windows |
| CPU | Intel Core i7-1355U |
| RAM | 16.85 GB |
| 디스크 여유 (C:) | 약 88.7 GB |
| Python | 3.12.10 |
| Node | 26.7.0 |
| PyTorch | 2.14.0+cpu, CUDA 사용 불가 |
| FFmpeg | 9.0.1 full build (winget Gyan.FFmpeg), rubberband 필터 확인 |
| Demucs / WhisperX | Demucs 4.1.0 (기본 Python), WhisperX 3.8.6 (`.venv-align`) |

## 합성음 키 변환 smoke test

`scripts/run_pitch_smoke.py`가 생성한 440 Hz, 3초 단음 WAV를 FFmpeg `rubberband=pitch=2^(n/12):tempo=1`로 변환했다. 테스트 명령: `python scripts/run_pitch_smoke.py --ffmpeg <ffmpeg.exe 경로>`. 측정은 중앙 1초의 FFT 최대 성분이므로 주파수 해상도는 약 1 Hz다.

| 반음 | 목표 Hz | 측정 Hz | 출력 길이 | 길이 오차 |
|---:|---:|---:|---:|---:|
| -5 | 329.628 | 329 | 3.000초 | 0 ms |
| 0 | 440.000 | 440 | 3.000초 | 0 ms |
| +5 | 587.330 | 588 | 3.000초 | 0 ms |

이 단음 테스트는 기본 pitch 비율과 길이 보존만 확인한다. 실제 곡의 음질과 폰 출력은 미측정이다.

추가로 `scripts/run_pitch_transient.py`가 만든 0.5초와 2.5초의 짧은 tone burst를 변환했다. 기준 신호 대비 -5반음 시작 차이는 각각 +7.5ms, +7.5ms였고 +5반음은 -9.4ms, -9.1ms였다. 출력 길이는 모두 3.000초였다. 검출은 5ms RMS와 상대 임계값을 사용하므로 실제 곡의 모든 transient를 보증하지 않는다.

실제 59초 MR을 -5/+5반음으로 렌더해 길이와 3개 시간창의 에너지 envelope를 비교했다. 두 결과 모두 길이는 59.0초(오차 0ms)였다. -5는 1/25/48초 창에서 기준 대비 최적 lag가 +10/+10/+10ms, +5는 -10/-10/-10ms였다. 48초 창의 envelope 상관은 각각 0.487/0.566으로 낮아 그 구간의 청감·동기화 확인이 남아 있다. 세부 수치는 `data/poc/bansanka/pitch_output/pitch_real_measurements.json`에 있다. 이 지표는 음질 평가를 대체하지 않는다.

## 실제 곡 PoC — 晩餐歌 구간 A

입력: `data/poc/bansanka/segment_A_0008.0-0067.0.wav` (원곡 8.0초부터 59.0초), 대응 일본어 가사 18줄. 원곡 MP3 MD5는 manifest와 일치한다. 참고 보컬 스템은 같은 전체 곡 길이(220.0555초)다.

- Demucs 4.1.0, `htdemucs`, `--two-stems vocals`로 구간 A 분리 성공. 출력: `data/poc/bansanka/demucs_output/htdemucs/segment_A_0008.0-0067.0/`. 실행 시 약 52초의 분리 진행 시간이 표시됐다. 보컬·반주 출력은 각각 59.0초다.
- 반주 peak 0.935, RMS 0.144; 보컬 peak 0.762, RMS 0.134 (float 정규화 진폭). 클리핑 수치 검사는 통과하나, 청감상 잔류 보컬·악기 손상은 아직 미검증이다.
- `faster-whisper` 1.2.1, `small`, CPU int8으로 분리 보컬 ASR 실행. 11개 거친 구간, 실행 시간 32.36초. 결과는 `data/poc/bansanka/asr_small_vocals.json`. 제공 가사와 대체로 순서가 맞지만 「一緒には居れないな」 등 오인식이 있으며 마지막 구간에는 입력 밖 다음 가사도 포함된다. ASR 시각을 줄 경계 정답으로 사용하지 않는다.
- 별도 `.venv-align`에 WhisperX 3.8.6·PyTorch 2.8.0·Transformers 4.57.1을 설치하고 일본어 정렬 모델 `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` 로드 성공. `scripts/run_align_poc.py`로 ASR 그룹 시간창 안에서 제공 가사 18줄을 각각 강제 정렬했다. 실행 시간 34.02초. 출력: `data/poc/bansanka/alignment_whisperx_preliminary.json`.
- 로컬 모델 캐시에서 일본어 모델의 config/기존 PyTorch 가중치는 `cf031e020336460d15a417eba710bbc5bb43be9a`, safetensors 가중치는 `2785e99ab97df77a32b5bd0ece5c9fa188a02f19` 스냅샷에 있다. Demucs 모델 캐시 스냅샷은 `cbc8a9b1a87023b7fd74e7b3412e6321c0eab003`이다. 현재 스크립트는 Hugging Face 기본 revision을 사용하므로 재현 실행 시 모델 revision 고정이 남아 있다.
- 이 결과는 자동으로 ready 처리하기 어렵다. 인접 5쌍(A04/A05, A06/A07, A09/A10, A11/A12, A13/A14)의 시간이 겹치고, A06/A07 및 A11/A12는 시작 순서가 뒤집혔다. A07과 A12는 탐색창 시작에 붙었다. 특히 A06/A07, A11/A12, A13/A14는 귀로 줄 경계를 확인해야 한다. 그룹 시간창과 줄 배정도 예비 수작업이므로 완전 자동 파이프라인의 성능으로 계산하지 않는다.
- `scripts/run_align_poc_sequential.py`에서는 같은 그룹의 가사를 이어 붙여 한 번에 정렬한 뒤 문자 위치로 줄을 나눴다. ASR 시간창 결과 18줄의 역전·겹침은 0건이고 실행 시간은 18.91초였다. 이 방법은 시간 순서 문제를 해결하지만 경계 정확도를 보증하지 않는다. MusicXML 자동 후보로 좁힌 창에서도 실행했고 `alignment_whisperx_sequential_musicxml.json`에 저장했다. 두 창의 경계가 0.5초 넘게 다른 줄은 A09, A11, A13, A14, A15, A16이다. 채보 후보를 사용한 결과를 독립적인 모델 정확도 평가로 세지 않는다.
- `scripts/build_alignment_review.py`가 생성한 `data/poc/bansanka/review_alignment.html`에서 원곡·분리 보컬·MR을 전환해 듣고 줄별 시작·끝을 수정할 수 있다. 검수 표시가 된 줄과 미검수 후보를 구별하여 CSV로 내보낸다. 페이지 렌더와 JavaScript 구문은 Chrome headless 및 Node 구문 검사로 확인했다. 실제 청취 검수는 아직 수행되지 않았다.
- 제공된 `segment_A_reference_manual_rough.csv`는 18줄이며 후반 7줄이 약 1.5~2초 빠르게 찍혔다는 사용자 메모가 있다. 정밀한 자동 정렬 게이트 기준으로 사용할 수 없다. `segment_A_reference_DRAFT.csv`의 값은 모두 자동 후보이며 사람 기준 칸은 비어 있다.

다음 단계는 남은 A03·A14·A15와 A00/A01의 7ms 겹침을 검수해 사람 기준 시각을 정리하는 것이다. 정확한 기준이 확보되기 전에는 자동 유효율·경계 오차·자동/혼합/수동 모드를 결정하지 않는다. 다른 곡 2개 구간과 총 20줄 이상의 최종 게이트도 미완료다.

### 사용자가 검수한 첫 CSV (2026-09-19)

`C:/Users/User/Downloads/segment_A_reference_reviewed.csv`를 `data/poc/bansanka/segment_A_reference_reviewed.csv`로 복사했다. 줄 전체의 첫 발음부터 마지막 발음까지를 구간 기준 초로 찍는 방식은 이 PoC의 줄 타이밍 정의와 맞는다. 18줄 중 15줄이 `manual_reviewed`; A03·A14·A15는 `candidate_unreviewed`다. 모든 경계는 0~59초 안에서 start < end다. A00 끝 2.600초와 A01 시작 2.593초는 7ms 겹친다. 최종 기준 사용 전 두 줄의 연결을 확인해야 한다.

검수 완료 15줄만 `scripts/evaluate_alignment.py --allow-partial`로 잠정 비교했다. ASR 시간창 순차 정렬은 시작 ±0.5초 11/15, 끝 ±0.7초 7/15였다. MusicXML 후보 시간창 순차 정렬은 시작 10/15, 끝 7/15였다. 이 15줄은 기존 후보를 보면서 검수한 값이므로 독립적인 블라인드 기준은 아니다. 세 줄이 미검수이고 다른 곡 두 개도 없으므로 이 숫자를 T01 최종 게이트 통과/실패로 사용하지 않는다. 끝 경계가 자주 길게 잡히는 문제가 있다는 진단 자료로만 사용한다.

### 구간 A 18줄 검수 완료 (2026-09-19)

`C:/Users/User/Downloads/segment_A_reference_reviewed (1).csv`를 최종 구간 A 기준 파일 `data/poc/bansanka/segment_A_reference_reviewed.csv`로 복사했다. 이전 15줄 부분 검수본은 `segment_A_reference_partial.csv`로 보존했다. 새 파일은 18/18줄이 `manual_reviewed`이고, 경계 범위 오류·역전·줄 간 겹침은 0건이다. 검수는 자동 후보가 표시된 페이지에서 이루어졌으므로 독립적인 블라인드 표기는 아니다.

| 구간 A 측정 (수정 전 모델 결과) | ASR 그룹 창 | MusicXML 후보 창 | 목표 |
|---|---:|---:|---:|
| 유효 줄 | 18/18 (100%) | 18/18 (100%) | 90% 이상 |
| 시작 ±0.5초 이내 | 13/18 (72.2%) | 14/18 (77.8%) | 80% 이상 |
| 끝 ±0.7초 이내 | 10/18 (55.6%) | 10/18 (55.6%) | 80% 이상 |
| 시작 절대오차 중앙값 / P90 | 0.024 / 0.876초 | 0.000 / 1.000초 | 별도 기록 |
| 끝 절대오차 중앙값 / P90 | 0.609 / 1.030초 | 0.601 / 1.239초 | 별도 기록 |

상세 결과는 `evaluation_asr_reviewed.json`과 `evaluation_musicxml_reviewed.json`에 있다. 이 곡에서는 두 방법 모두 시작·끝 목표를 통과하지 못했다. MusicXML 후보 창 방식은 기존 채보 자료를 사용했으므로 새 곡 업로드의 자동 성능으로 간주할 수 없다. 아직 다른 두 곡 구간과 합계 최소 20줄 평가가 없어 T01 최종 모드 결정은 보류한다. 현재 증거는 틀린 경계를 수정할 수 있는 혼합 모드가 필요함을 강하게 시사한다.

## T01 최종 판정 (2026-09-19)

세 곡(晩餐歌 18줄, 月面着陸計画 12줄, 星街の駅で 13줄, 합계 43줄) 모두 사람이 청취 검수한 기준(`segment_*_reference_reviewed.csv`, 전줄 `manual_reviewed`)이 갖춰졌다. 새로 업로드되는 곡에 사전 채보·MusicXML 같은 자료가 없다는 실제 제품 조건에 맞춰, 세 곡 모두 **동일한 완전 자동 파이프라인**(Demucs 보컬 분리 → faster-whisper 거친 ASR → ASR 구간에 가사를 글자 매칭으로 자동 배정 → WhisperX/wav2vec2 일본어 글자 단위 강제 정렬)으로 다시 후보를 만들어 채점했다. 晩餐歌의 기존 `alignment_whisperx_sequential*.json`(손으로 묶은 ASR 창, MusicXML 채보 창)은 week4 프로젝트의 기존 자료를 썼으므로 새 곡 업로드의 자동 성능으로 세지 않는다.

두 가지 창 방식으로 각각 채점했다. **ASR창**(자동 글자 매칭으로 가사를 ASR 구간에 배정, `evaluation_generic_asr.json`/`evaluation_final_asr.json`)과 **전체창**(가사 전체를 구간 전체에 한 번에 정렬, `evaluation_generic_whole.json`/`evaluation_final_whole.json`).

| 곡 | 줄 | 유효 | 시작 ±0.5s (ASR창/전체창) | 끝 ±0.7s (ASR창/전체창) | 끝 오차 중앙값/P90 (ASR창) |
|---|---:|---:|---:|---:|---:|
| 晩餐歌 A | 18 | 100% | 100% / 100% | **100%** / 88.9% | 0.091s / 0.313s |
| 月面着陸計画 B | 12 | 100% | 91.7% / 91.7% | **75.0%** / 91.7% | 0.131s / 1.272s |
| 星街の駅で A | 13 | 100% | 100% / 100% | **76.9%** / 76.9% | 0.200s / 0.818s |
| **합계 (43줄, pooled)** | 43 | **100%** | **97.7%** | **86.0%** | 0.117s / 0.818s |

두 창 방식 모두 합계는 시작 42/43, 끝 37/43로 완전히 같다(우연히 일치). 목표(유효 90%, 시작 80%, 끝 80%)는 **합계 기준으로는 셋 다 통과**한다.

다만 곡 단위로 보면 끝 경계 80% 목표를 **세 곡 중 두 곡(月面着陸計画, 星街の駅で)이 개별로는 통과하지 못한다.** 晩餐歌만 100%로 합계를 끌어올렸다. 晩餐歌는 이번 정렬 파이프라인이 처음 만들어진 곡이라 보컬 분리 품질이나 발음이 우연히 잘 맞았을 수 있고, 새로 추가한 두 곡(사전 정보 없이 순수 자동으로만 처리)이 오히려 실제 신규 업로드 조건에 더 가깝다. 끝 오차 P90이 0.8~1.3초로 큰 것도 두 신규 곡에서만 나타난다.

이 결과가 표시된 자동 후보(ASR창)를 검수 페이지 기본값으로 띄워 놓고 사람이 들으며 고친 값이라 완전한 블라인드 기준은 아니다(晩餐歌 노트에 이미 있는 주의사항과 동일). 다만 사람이 보지 않은 **전체창** 후보로 다시 채점해도 합계 통과 여부가 그대로였다(시작 42/43, 끝 37/43) — 앵커링만으로 통과한 결과는 아니다.

### 최종 판단 기록

```text
선택 모드: mixed (반자동)
선택 근거:
  - 시작 시각은 세 곡 모두, 개별로도 합계로도 목표(80%)를 넉넉히 넘는다(91.7~100%, 합계 97.7%).
    오차 중앙값이 0.00~0.01초로 사람이 손댈 필요가 거의 없다. → 시작 시각은 automatic로 채택.
  - 끝 시각은 합계로는 목표(80%)를 넘지만(86.0%), 사전 정보 없이 순수 자동으로 처리한 두 곡
    (月面着陸計画 75.0%, 星街の駅で 76.9%)은 개별로 목표를 못 넘긴다. 晩餐歌 한 곡의 100%가 합계를
    떠받치는 구조라 "끝 시각도 자동으로 충분하다"고 결론 내리기에는 근거가 약하다.
  - 끝 경계는 노래 끝 음을 길게 끌거나 숨소리·잔향이 섞이는 경우 wav2vec2 강제 정렬이 흔들리는
    패턴이 두 신규 곡에서 반복됐다(P90 0.8~1.3초).
게이트 미달 항목:
  - 끝 시각 ±0.7초 목표(80%)를 月面着陸計画(75.0%), 星街の駅で(76.9%)가 개별 곡 단위로 못 넘음.
  - 끝 오차 P90이 두 신규 곡에서 0.8~1.3초로, 노래방 화면에서 다음 줄 강조와 겹칠 수 있는 크기.
지원 가능한 입력 범위:
  - YouTube 128kbps 립, 보컬이 반주보다 상대적으로 크게 믹싱된 J-pop, 절/후렴 구조가 뚜렷한 곡.
  - 이 범위에서 시작 시각은 자동 생성 그대로 써도 된다.
  - 끝 시각은 자동 생성값을 기본으로 깔고, review_alignment.html 같은 가벼운 확인 화면에서
    사람이 한 번 듣고 필요하면 고치는 반자동 단계가 필요하다.
다음 단계에서 구현하지 않을 기능:
  - 끝 경계 완전 자동 신뢰(사람 검수 단계 생략)는 지금 구현하지 않는다.
  - 더 다양한 곡(느린 발라드, 랩·속사 구간, 다인 보컬)에 대한 자동 성능 보증도 지금 범위 밖이다.
  - 세 곡 모두 검수 자체가 자동 후보를 기본값으로 띄운 화면에서 이뤄졌으므로, 완전한 블라인드
    기준 재확보(검수자에게 후보를 안 보여주고 처음부터 듣게 하는 것)는 지금 하지 않는다.
```


## 공통 파이프라인 검증 — 一輪花 (2026-09-20)

Claude(Opus 5, "코덱스가 죽었고 이제 네가 다시 일을 이어받아야한다" 세션)가 코드를 전혀 고치지 않고, 유튜브 링크 하나와 사용자가 준 가사 텍스트만으로 기존 공통 파이프라인을 그대로 실행해 검증했다. 목적은 (1) 새 곡이 공통 파이프라인만으로 사람 개입 없이 끝까지 처리되는지, (2) 가사 텍스트가 실제로 부른 것보다 적을 때(반복·구간 생략) 파이프라인이 이를 감지하고 안전하게 처리하는지 확인하는 것이었다.

**실행:** `scripts/process_url_runpod.py --url "https://www.youtube.com/watch?v=DUAzYQzcVnU" --lyrics ... --out data/pipeline/ichirinka --host 213.173.104.69 --port 10226 --title "tuki. — 一輪花"`. RunPod RTX PRO 4000 Blackwell Pod, 기존 `/root/bypp-venv`. `--repeat-overrides`, `--skip-lines` 등 수동 보정 옵션은 쓰지 않았다.

**시간(총 96.3초, 225.3초짜리 곡):** 로컬 준비 6.3초, 업로드 29.1초, **GPU 처리 24.9초**(분리+정렬+검수), 결과 다운로드 36.0초. GPU 처리만 보면 CPU 대비(기존 3~5분) 대략 10배 이상 빠르다. 이번 구간에서는 업로드·다운로드가 전체의 2/3를 차지해 다음 병목이다.

**구조 QA:** 54/54줄 정렬, 역행 줄 0개, 무음 구간 한가운데서 시작하는 줄 0개.

**반복/누락 감지 — 실제 사례 발견:** 곡 끝부분 194.0~216.8초(22.8초)에 대응하는 가사 텍스트가 전혀 없었다. `quality_flags.json`에 `unmatched_vocal_activity`로 정확히 표시됐다(인접한 감탄사류 없음 → 억지로 이웃 줄에 붙이지 않고 그대로 둠). 후속 진단(파이프라인 코드 변경 없음, SSH로 직접 조사):
- 보컬 스템 에너지 비교: 194~217초 구간이 이미 검증된 가창 구간(20~190초)과 비슷하거나 더 큰 음량으로, 노래하는 패턴의 굴곡을 보임. 217초부터는 명확한 무음(-70dB 이하)으로 떨어짐 → 분리 잔여음이 아니라 실제 가창.
- 이미 아는 후렴구·2절 구간과의 스펙트럼 상호상관: 뚜렷한 일치 없음(최고 점수 0.17, 노이즈 수준).
- 5~12초 주기 자기상관 탐색: 5.2초 주기에 약한 신호(margin 0.12)뿐, 확신할 수준 아님.
- **결론:** 반복이 아니라 주어진 가사 텍스트 자체가 누락한 구간으로 보인다. 곡의 맨 끝이라 앞선 53줄의 타이밍은 전혀 밀리지 않았다(중간에 생겼다면 이후 모든 줄이 밀렸을 것).

**현재 상태 평가:** 감지·안전 격리는 됨(잘못 추측해 이웃 줄을 깨뜨리지 않음). 텍스트가 아예 없는 구간을 가사로 채우는 것은 안 됨 — 이건 정렬 알고리즘의 한계가 아니라 가사 출처 자체의 누락이라, 사람이 들어보고 텍스트를 보충해야 한다. `possible_omitted_repeat_or_hold`(짧은 줄이 비정상적으로 오래 끄는 경우) 감지기는 이번 곡에서 발동하지 않았고, 이는 이 곡에 그 패턴이 없어서였다(오탐·미탐 아님) — 별도로 발견된 "텍스트 자체가 없는 긴 구간"은 이 감지기의 대상 범위 밖이다.

## Korean engine v3 (opt-in) — drift (밀림/끌림) fix

Scope: Korean only. `align_full_song.py` (Japanese path and the deployed Korean engine, "v2") is untouched;
`scripts/korean_engine.py` wraps it and is used only with `process_song.py --ko-engine v3` (or `BYPP_KO_ENGINE=v3`).

Causes found on the 3 Korean demo songs (label-free, measured against the vocal stem):
1. Aligning on the original mix lights lines over stretches nobody sings when there are no stanza windows
   (`single`: 12 of 28 lines >30% silent).  No single audio choice is best, so v3 aligns on both mix and stem and keeps the
   one whose lit lines overlap the sung frames best (coverage F1).
2. Speech-trained CTC cuts held tails short / starts lines after the real onset.  v3 snaps line edges that border a clear
   vocal pause (>= 0.25 s) to the stem's onset/offset, and extends a line over singing that runs straight on from it
   (touching within 0.15 s, capped at 4 s).  Isolated sung fragments in gaps are left alone and reported in
   `unlitSinging` (the submitted text may omit sung repeats/ad-libs).

Results (coverage F1 lit-vs-sung; silent = lines >30% lit over silence; missed = sung seconds no line covers):

| song | F1 v2 → v3 | silent lines | missed s | median dStart |
|---|---|---|---|---|
| single | 0.730 → 0.865 | 12 → 3 | 54.9 → 18.9 | ~0 |
| minjok_aria | 0.904 → 0.912 | 0 → 0 | 19.4 → 17.8 | 0.15 → 0.00 |
| blueming | 0.948 → 0.948 | 2 → 2 | 107.0 → 107.0 | unchanged (already good) |

Limits: these are proxies computed from the same stem the engine uses (partly circular); there is no human reference for
Korean. Sparse ~1 s phrases spread over 12–29 s and 42–58 s of `single` stay unlit — the stem shows too little singing there
to place a line without knowing the words. Confirm by ear before making v3 the default. Not deployed to `/workspace/bypp`.
