# BYPP 로컬 데모 실행

현재 실행되는 것은 **만찬가 59초 구간의 수동 검수 결과 플레이어**다. 새 곡 업로드·worker·자동 생성 API는 아직 연결되지 않았다. 아래 명령은 Windows PowerShell에서 프로젝트 루트 `C:\Users\User\sungjin\2026_dev\bypp` 기준으로 검증했다.

## 필요한 로컬 자료

`data/poc/bansanka/segment_A_reference_reviewed.csv`, `segment_A_lyrics_ko_reading.txt`, `segment_A_0008.0-0067.0.wav`, `demucs_output/htdemucs/segment_A_0008.0-0067.0/no_vocals.wav`가 있어야 한다. 이 자료는 `data/`에 있고 Git에는 포함하지 않는다.

## 첫 설치

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

## 실행

터미널 1, 프로젝트 루트에서:

```powershell
backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

터미널 2에서:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

브라우저에서 [로컬 플레이어](http://127.0.0.1:5173/)를 연다. 이 주소는 실행 중인 PC용이다. 폰 접속 경로와 실제 폰 스피커 청취는 아직 검증하지 않았다.

## 확인 명령

```powershell
cd frontend
npm run build
npm audit
```

API는 `GET /api/jobs/demo-bansanka-a/result`로 18줄 결과를, `GET /api/jobs/demo-bansanka-a/assets/instrumental`로 MR을 제공한다. 브라우저의 Range 요청에 206으로 응답한다. 결과의 `timingSource: manual`은 사용자가 직접 검수한 줄 경계를 의미한다.
