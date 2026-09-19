# Runpod song pipeline

Tested on a Runpod RTX PRO 4000 Blackwell Pod with Python 3.12, PyTorch 2.8.0+cu128, and CUDA available.

## Setup

Use a PyTorch Pod template. From the Pod shell:

```bash
python -m venv --system-site-packages /root/bypp-venv
PIP_CACHE_DIR=/root/.cache/pip /root/bypp-venv/bin/python -m pip install -r scripts/requirements-pipeline.txt
```

Install the repository scripts on the Pod. Keep the project and downloaded audio on persistent storage when the Pod may be terminated. The current Runpod `/workspace` mount rejected Python package installation, so the tested virtual environment was created under `/root`.

If the template sets `HF_HUB_ENABLE_HF_TRANSFER=1` without `hf_transfer` installed, set `HF_HUB_ENABLE_HF_TRANSFER=0` before running WhisperX.

## One-song run

Provide a single video URL (or `--audio` for a local file) and a UTF-8 Japanese lyrics file. The lyrics file may include the Korean readings under each Japanese line.
Blog-style blocks of Japanese lyric / Korean reading / Korean translation are accepted directly. A duplicated title at the top is removed, `[3회]`-style Japanese verb repeats are expanded, and known English phrases are mapped to Japanese pronunciation for alignment. Lines without a supplied Korean reading get an automatic one; review its spelling before publishing.

The result is a timing candidate. Inspect `quality_flags.json` before using it: `english_pronunciation_unknown` means a Latin word was outside the current pronunciation map, and `possible_omitted_repeat_or_hold` means a short lyric occupied much longer than the song's typical syllable pace. For those lines, the pipeline checks periodicity in the vocal stem. `suggestedRepeatCount` is included only when the acoustic pattern is distinct; it is **not** an automatic lyric correction. A sustained note or instrumental bleed can also trigger a flag. On 月面着陸計画, both omitted ヨーソロー repetitions produced a four-time candidate; on 星街の駅で, the long ending was flagged without a count.

A confirmed omitted sung repeat can be specified with `--repeat-overrides repeat_overrides.json`, for example `{"18":4}` for source lyric line 18 (zero-based), sung four times. This expands the transcript before global alignment. Every override produces `repeat_override_requires_review` because the extra text can move neighboring boundaries. Listen to the repeated phrase and its adjacent lines before accepting that candidate.

Mixed-language pronunciation and missing sung words are the current accuracy limits. The Japanese CTC aligner requires a Japanese-script transcript; it cannot reliably infer unknown English pronunciation or verify omitted sung repeats from the provided lyrics. The pipeline flags these cases instead of treating a completed alignment as verification. A future reconciliation stage should locally realign only confirmed repeat changes within fixed neighboring boundaries.

For a Pod whose IP address is blocked by YouTube, run the Windows-side orchestrator. It downloads locally, transfers input and scripts over Direct TCP SSH, processes on the GPU, and retrieves the playable result:

```powershell
.\.venv-align\Scripts\python.exe scripts\process_url_runpod.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" `
  --lyrics data\poc\moon_landing_plan\lyrics_full_ja.txt `
  --readings data\poc\moon_landing_plan\lyrics_full_ko_reading.txt `
  --out data\pipeline\moon_landing_plan `
  --host POD_DIRECT_TCP_IP --port POD_DIRECT_TCP_PORT
```

The SSH key defaults to `~/.ssh/id_ed25519`. The Pod must have that public key in `/root/.ssh/authorized_keys`. Install local `yt-dlp[default]` in the selected Python environment. The remote environment must have the packages below.

For an existing local file, replace `--url ...` with `--audio path\to\original.mp3`. The same transfer, separation, alignment, QA, and retrieval stages run. `pipeline_timing.json` records the time of each stage. A source identity file prevents accidentally reusing an output directory for different audio.

## Current validation

The first common-pipeline run of 星街の駅で from its local MP3, without cached stems or alignment, took 85 seconds on the RTX PRO 4000 Pod including transfer and result retrieval (26.5 s upload, 24.4 s GPU process, 34.1 s download). It aligned all 44 lines. Against 13 previously listened reference lines, 13/13 starts were within 0.5 s and 8/13 ends were within 0.7 s. Thus this single run met the 1–2 minute speed target but did **not** meet a reliable line-end accuracy target. A cached rerun took 58.8 s; this is not a fresh-run speed measurement.

If YouTube access works directly on the Pod, the simpler command is:

```bash
HF_HUB_ENABLE_HF_TRANSFER=0 /root/bypp-venv/bin/python scripts/process_song.py \
  --url 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --lyrics lyrics.txt \
  --out /workspace/songs/song-id \
  --title 'Song title' \
  --device cuda
```

The output includes `original.wav`, Demucs stems, `alignment_raw.json`, `karaoke.json`, `mr.wav`, and `karaoke.html`. Repeating the same command in the same output directory reuses the downloaded audio and alignment. Use a distinct output directory for each source song.

`--device auto` uses CUDA when available and CPU otherwise. The YouTube step uses yt-dlp and FFmpeg. `--audio` can be used in place of `--url` for an existing local file.

The Pod SSH proxy supports an interactive terminal but did not accept SCP in this setup. Use Runpod's Direct TCP SSH option or another file transfer method for regular development sync.


## UX 추가 (2026-09-20) — 2줄 표시, 가이드 멜로디, 키 조절

Claude(Opus 5)가 추가. 기존 정렬·검수 파이프라인(위 내용)은 건드리지 않았고, `karaoke_template.html`과 `process_song.py`에 다음 세 가지를 더했다.

**2줄 롤링 표시.** 화면에 항상 두 줄이 같은 크기로 보이고, 지금 부르는 줄만 글자별로 칠해진다. 줄이 끝나면 다음 줄로 자연스럽게 올라간다(실제 노래방 화면과 같은 방식). 각 줄의 채움은 그 줄 자신의 글자 시각만으로 계산되므로, 아래 줄이 화면에 보이는 동안에도 실제 노래가 이미 그 줄로 넘어가 있으면 미리 채워지기 시작한다 — 줄 끝 시각이 ±0.7초 정도 틀려도 화면이 갑자기 끊기는 느낌이 줄어든다.

**가이드 멜로디(음정 안내음).** 가이드 보컬 음원을 넣는 게 아니라, 분리된 보컬 스템에서 음높이(F0) 곡선만 뽑아(`scripts/pitch_guide.py`, numpy/scipy 자기상관 방식 — librosa 의존성 추가 없음), 브라우저에서 그 곡선을 따라가는 사인파를 실시간 합성한다(Web Audio `OscillatorNode`). 켜고 끌 수 있고 음량 조절 가능. 4분짜리 곡 기준 추출 1.3초. 정밀한 피치 추정기는 아니라서(옥타브 오류 소수 존재) 정확한 음정 채점용이 아니라 "대략 이 음을 따라가면 된다"는 안내용이다.

**키 조절.** 기본 등록은 보컬에서 가이드 음정을 추출해 음역을 추정한 뒤 원키(0)와 반대 음역 키(-4 또는 +4)만 렌더한다. 웹 등록 폼에서 반음별 전체 키 조절을 선택하거나 CLI에 `--full-key-range`를 주면 -6~+6의 13단계를 렌더한다. **실시간 연속 조절이 아니라 반음 단위 사전 렌더 방식이다.** FFmpeg `rubberband` 필터를 사용하며 0은 원본 MR을 재사용한다. 음역 추정은 보컬 중앙값에 따른 휴리스틱이므로 표시된 성별 키는 청취로 확인할 수 있다.

**검증:** 月面着陸計画을 로컬 CPU로 처음부터 다시 돌려 8단계 전부(분리 재사용, 정렬, 검수, 키 렌더 12개, 피치 추출, 페이지)를 확인했고, 브라우저에서 2줄 표시의 줄 전환, 채움 진행, 남/여 키 버튼의 음원 전환, 가이드 멜로디 오실레이터의 주파수·음소거 동작을 구조적으로 테스트했다(직접 청취 검증은 아님). 一輪花도 RunPod에서 같은 방식으로 재처리해 반음 12개·피치 가이드가 정상 생성·다운로드됨을 확인했다.
