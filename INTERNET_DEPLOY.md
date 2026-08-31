# 인터넷 공개 운영 안내

이 프로그램은 Docker를 지원하는 웹 호스팅 서버에 올릴 수 있습니다. 공개 후에는 교육생이 같은 Wi-Fi에 있지 않아도 HTTPS 주소와 강의방 QR코드로 접속할 수 있습니다.

## 반드시 필요한 서버 설정

다음 환경값을 호스팅 서비스의 설정 화면에 등록합니다.

- `QUIZ_PUBLIC_URL`: 발급받은 공개 주소(예: `https://검사주소.example`)
- `QUIZ_SECRET_KEY`: 길고 임의적인 비밀 문자열
- `ADMIN_PIN`: 기본값 `1234`가 아닌 총괄 관리자 번호
- `QUIZ_DATA_DIR`: 영구 디스크가 연결된 폴더(권장: `/app/data`)

서버 포트는 호스팅 서비스가 제공하는 `PORT` 값을 자동으로 사용합니다.

## 매우 중요한 데이터 보관 조건

검사 결과는 SQLite 파일에 저장됩니다. 호스팅 서비스에서 **영구 디스크**를 `/app/data`에 연결해야 재배포나 서버 재시작 뒤에도 결과가 남습니다. 영구 디스크 없이 운영하면 결과가 사라질 수 있습니다.

동시에 여러 서버 복제본을 실행하지 말고 인스턴스 수를 1개로 둡니다. 대규모 운영이 필요하면 SQLite 대신 관리형 PostgreSQL로 이전해야 합니다.

## 공개 후 주소

- 교육생: `https://공개주소/`
- 관리자: `https://공개주소/admin/login`
- 상태 확인: `https://공개주소/health`

관리자 화면은 반드시 HTTPS 주소로만 접속하고, 총괄 및 강의방 관리자 번호를 추측하기 어렵게 설정하십시오. 개인정보성 응답을 다루므로 이용 기관의 개인정보 보관·파기 기준도 함께 정해야 합니다.

## Render로 배포하기

프로젝트 폴더의 파일을 GitHub 저장소 최상위에 올립니다. 특히 `render.yaml`, `Dockerfile`, `app.py`, `templates`, `static`, `data/questions.json`이 포함되어야 합니다. `data/results.db`는 올리지 않습니다.

1. Render에 로그인하고 GitHub 계정을 연결합니다.
2. Render Dashboard에서 **New > Blueprint**를 선택합니다.
3. 위 GitHub 저장소를 연결합니다. Render가 저장소 최상위의 `render.yaml`을 읽습니다.
4. 생성 화면에서 `ADMIN_PIN`에 기본값 1234가 아닌 총괄 관리자 번호를 입력합니다.
5. 배포를 시작하고 상태가 **Live**가 될 때까지 기다립니다.
6. Render가 표시한 `https://...onrender.com` 주소로 접속합니다.

`render.yaml`은 유료 Starter 웹 서비스와 1GB 영구 디스크를 사용하도록 설정되어 있습니다. 검사 결과 보존을 위해 무료 서비스로 바꾸지 마십시오. Render가 제공하는 외부 주소는 앱이 자동 인식하므로 `QUIZ_PUBLIC_URL`을 따로 입력하지 않아도 QR코드가 올바른 HTTPS 주소로 생성됩니다.
