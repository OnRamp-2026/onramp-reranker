#!/bin/sh
# VESSL Workspace 시작 — sshd(22, VESSL 접속) + 리랭커 uvicorn(8080).
# VESSL Init script는 비워두고 이 CMD를 사용한다(둘 다 띄우면 중복 기동).
set -e

# SSH host key 생성(이미지에 굽지 않음 — 공개 이미지에 공유 키 노출 방지).
ssh-keygen -A

# sshd config 검증(-t) 후 정상일 때만 실행. 오류를 `|| true`로 숨기지 않는다.
if /usr/sbin/sshd -t; then
  /usr/sbin/sshd
else
  echo "WARN: sshd config 검증 실패 — sshd 미실행 (uvicorn은 계속)" >&2
fi

# 리랭커는 foreground(PID 1) — 종료 시 컨테이너도 종료.
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
