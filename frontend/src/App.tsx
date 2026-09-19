import { useEffect, useRef, useState } from "react";
import { clock, lineAtTime, nextLine } from "./playback";
import type { KaraokeResult, LyricsMode, LyricLine } from "./types";

const RESULT_URL = "/api/jobs/demo-bansanka-a/result";

function LineText({ line, mode }: { line: LyricLine; mode: LyricsMode }) {
  if (mode === "jp") return <span>{line.jp}</span>;
  if (mode === "jp_ko") {
    return (
      <span className="dual-line">
        <span className="jp-line">{line.jp}</span>
        <span>{line.ko}</span>
      </span>
    );
  }
  return <span>{line.ko}</span>;
}

export default function App() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [result, setResult] = useState<KaraokeResult | null>(null);
  const [loadError, setLoadError] = useState("");
  const [playError, setPlayError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [mode, setMode] = useState<LyricsMode>("ko");

  useEffect(() => {
    const controller = new AbortController();
    fetch(RESULT_URL, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`결과를 가져오지 못했습니다 (${response.status})`);
        return (await response.json()) as KaraokeResult;
      })
      .then((data) => {
        setResult(data);
        setMode(data.playbackPreferences.lyricsMode);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "불러오기 실패");
      });
    return () => controller.abort();
  }, []);

  const current = result ? lineAtTime(result.lines, time, result.displayOffsetSec) : null;
  const upcoming = result ? nextLine(result.lines, time, result.displayOffsetSec) : null;
  const duration = result?.durationSec ?? 0;

  async function togglePlay() {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    try {
      await audio.play();
      setPlayError("");
    } catch (error) {
      setPlaying(false);
      setPlayError(error instanceof Error ? error.message : "브라우저가 재생을 허용하지 않았습니다.");
    }
  }

  function seek(seconds: number) {
    const audio = audioRef.current;
    if (!audio) return;
    const next = Math.max(0, Math.min(duration, seconds));
    audio.currentTime = next;
    setTime(next);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <span className="brand">BYPP <span>·</span> INSTANT KARAOKE</span>
        <a className="demo-badge" href="/new">+ 새 곡 추가</a>
      </header>

      {loadError ? (
        <section className="error-card" role="alert">
          <h1>결과를 열 수 없습니다</h1>
          <p>{loadError}</p>
          <p>로컬 API가 실행 중인지 확인하세요.</p>
        </section>
      ) : !result ? (
        <section className="loading" aria-live="polite">만찬가 결과를 불러오는 중…</section>
      ) : (
        <>
          <audio
            ref={audioRef}
            src={result.assets.instrumental}
            preload="metadata"
            onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
            onSeeked={(event) => setTime(event.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onError={() => setPlayError("반주 파일을 불러오지 못했습니다.")}
          />

          <div className="song-heading">
            <p className="eyebrow">tuki. / 59초 구간</p>
            <h1>{result.title}</h1>
            <p className="subcopy">보컬을 분리한 반주와 사람이 확인한 줄 시각을 사용합니다.</p>
          </div>

          <section className="stage" aria-label="동기화된 가사">
            <div className="stage-glow" />
            <div className="lyric-content" aria-live="off">
              {current ? (
                <div className="current-line" key={current.id}>
                  <LineText line={current} mode={mode} />
                </div>
              ) : (
                <div className="rest-line">{upcoming ? "♪" : "—"}</div>
              )}
              <div className="next-line">
                {upcoming ? <LineText line={upcoming} mode={mode} /> : ""}
              </div>
            </div>
          </section>

          <section className="controls" aria-label="재생 컨트롤">
            <div className="progress-row">
              <span>{clock(time)}</span>
              <input
                aria-label="재생 위치"
                type="range"
                min={0}
                max={duration}
                step={0.01}
                value={Math.min(time, duration)}
                onChange={(event) => seek(Number(event.target.value))}
              />
              <span>{clock(duration)}</span>
            </div>
            <div className="transport-row">
              <button onClick={() => seek(time - 10)} aria-label="10초 뒤로">−10초</button>
              <button className="play-button" onClick={togglePlay}>{playing ? "일시정지" : "재생"}</button>
              <button onClick={() => seek(time + 10)} aria-label="10초 앞으로">+10초</button>
            </div>
            {playError && <p className="play-error" role="alert">{playError}</p>}
          </section>

          <section className="mode-panel" aria-label="가사 표시 방식">
            <span>가사 보기</span>
            <div className="mode-options">
              {([
                ["ko", "한글 독음"],
                ["jp_ko", "일본어 + 한글"],
                ["jp", "일본어"],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  className={mode === value ? "selected" : ""}
                  aria-pressed={mode === value}
                  onClick={() => setMode(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
