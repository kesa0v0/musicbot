# Python 3.11-slim을 기반 이미지로 사용합니다.
FROM python:3.11.13-slim

# 시스템 패키지를 업데이트하고 ffmpeg를 설치합니다.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ffmpeg libffi-dev python3.11-dev ca-certificates

# 작업 디렉토리를 /app으로 설정합니다.
WORKDIR /app

# requirements.txt를 복사하고 의존성을 설치합니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 소스 코드를 컨테이너에 복사합니다.
COPY . .

# 봇을 실행하는 기본 명령어를 설정합니다.
CMD ["python", "main.py"]
