#!/bin/sh
# VESSL Workspace 시작 스크립트 — sshd(22, VESSL 접속/요구사항) + 리랭커 uvicorn(8080).
# 참고: VESSL이 CMD를 무시하고 자체 init을 쓰는 구성이면, 아래 uvicorn 한 줄을
#       VESSL Init/start 필드에 넣거나 SSH 접속 후 직접 실행하면 된다.
set -e

# SSH host key를 시작 시 생성(이미지에 굽지 않음 — 공개 이미지에 공유 키 노출 방지).
ssh-keygen -A 2>/dev/null || true

# sshd 실행(VESSL이 자체 sshd를 띄우는 환경이면 실패해도 무시).
/usr/sbin/sshd || true

# 리랭커는 foreground(PID 1 역할) — 종료 시 컨테이너도 종료.
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
