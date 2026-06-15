pipeline {
  agent {
    kubernetes {
      defaultContainer 'tools'
      yaml """
apiVersion: v1
kind: Pod
spec:
  # IRSA: 노드 IMDS HopLimit=1 이라 노드 role을 못 씀 → 이 SA에 reranker-artifacts read role을 연결(IRSA)해야
  # Fetch Model from S3 단계가 동작한다. SA 생성·애너테이션은 infra(OnRamp-2026/infra#22) 적용 후.
  serviceAccountName: jenkins-reranker
  restartPolicy: Never
  containers:
    - name: tools
      image: python:3.11-slim
      command:
        - cat
      tty: true
    - name: kaniko
      image: gcr.io/kaniko-project/executor:debug
      command:
        - /busybox/cat
      tty: true
      # prebuilt(Dockerfile.prebuilt)는 양자화 없이 모델 COPY + 런타임 의존성 설치만 → 메모리 가볍다(노드 3.2Gi fit).
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: "2"
          memory: 2Gi
      volumeMounts:
        - name: kaniko-docker-config
          mountPath: /kaniko/.docker
  volumes:
    - name: kaniko-docker-config
      emptyDir: {}
"""
    }
  }

  options {
    disableConcurrentBuilds()
    skipDefaultCheckout(true)
  }

  environment {
    IMAGE_REPOSITORY = 'amdp-registry.skala-ai.com/skala26a-cloud/onramp-reranker'
    // #73 인클러스터 리랭커 폐지 — GitOps digest 자동 갱신 제거(ArgoCD 결합 해제). 리랭킹은 on-demand GPU(VESSL)로 이전.
    //     이 파이프라인은 빌드·테스트·Harbor push까지만 담당(배포 트리거 없음).
    // 사전 생성 모델(model_quantized.onnx + tokenizer)을 둔 S3 경로. 모델/arch 갱신 시 버전(v1) prefix만 올린다.
    RERANKER_MODEL_S3_URI = 's3://skala3-cloud1-finalproj-team3-reranker-artifacts-881490135253/onnx/bge-reranker-onnx-int8-avx2/v1'
    AWS_DEFAULT_REGION = 'ap-northeast-2'
  }

  stages {
    stage('Prepare Tools') {
      steps {
        sh '''
          set -eu
          apt-get update
          apt-get install -y --no-install-recommends git ca-certificates
          # awscli — S3에서 사전 생성 모델 받기 (creds는 Jenkins IRSA/node role에 reranker-artifacts read 정책 attach 전제)
          pip install --no-cache-dir awscli
          rm -rf /var/lib/apt/lists/*
        '''
      }
    }

    stage('Checkout') {
      steps {
        checkout scm
        sh '''
          set -eu
          git config --global --add safe.directory "${WORKSPACE}"
        '''
        script {
          env.IMAGE_TAG = sh(script: 'git rev-parse --short=12 HEAD', returnStdout: true).trim()
        }
      }
    }

    stage('Fetch Model from S3') {
      steps {
        sh '''
          set -eu
          mkdir -p "${WORKSPACE}/models/bge-reranker-onnx-int8"
          aws s3 sync "${RERANKER_MODEL_S3_URI}/" "${WORKSPACE}/models/bge-reranker-onnx-int8/"
          # 필수 산출물 확인 (없으면 빌드 실패 — S3 업로드/권한 점검)
          test -f "${WORKSPACE}/models/bge-reranker-onnx-int8/model_quantized.onnx"
          test -f "${WORKSPACE}/models/bge-reranker-onnx-int8/tokenizer.json"
          echo "model fetched: $(du -sh ${WORKSPACE}/models/bge-reranker-onnx-int8 | cut -f1)"
        '''
      }
    }

    stage('Lint and Test') {
      steps {
        sh '''
          set -eu
          python -m venv .venv
          . .venv/bin/activate
          pip install --upgrade pip
          pip install ".[dev]"
          ruff format --check app tests
          ruff check app tests
          PYTHONPATH="${WORKSPACE}" pytest tests -v
        '''
      }
    }

    stage('Build Image Check') {
      when { changeRequest() }
      steps {
        container('kaniko') {
          sh '''
            set -eu
            /kaniko/executor \
              --context "${WORKSPACE}" \
              --dockerfile "${WORKSPACE}/Dockerfile.prebuilt" \
              --custom-platform=linux/amd64 \
              --destination "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
              --no-push
          '''
        }
      }
    }

    stage('Build and Push Image') {
      when {
        allOf {
          branch 'main'
          not { changeRequest() }
        }
      }
      steps {
        container('kaniko') {
          withCredentials([usernamePassword(
            credentialsId: 'harbor-robot-credential',
            usernameVariable: 'HARBOR_USERNAME',
            passwordVariable: 'HARBOR_PASSWORD'
          )]) {
            sh '''
              set -eu
              REGISTRY_HOST="${IMAGE_REPOSITORY%%/*}"
              AUTH="$(printf '%s:%s' "${HARBOR_USERNAME}" "${HARBOR_PASSWORD}" | base64 | tr -d '\\n')"
              cat > /kaniko/.docker/config.json <<EOF
{"auths":{"${REGISTRY_HOST}":{"auth":"${AUTH}"}}}
EOF
              /kaniko/executor \
                --context "${WORKSPACE}" \
                --dockerfile "${WORKSPACE}/Dockerfile.prebuilt" \
                --custom-platform=linux/amd64 \
                --destination "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
                --digest-file "${WORKSPACE}/image-digest.txt"
            '''
          }
        }
        script {
          env.IMAGE_DIGEST = readFile('image-digest.txt').trim()
          echo "Built image: ${env.IMAGE_REPOSITORY}@${env.IMAGE_DIGEST}"
        }
      }
    }
    // #73 'Update GitOps Image Digest' 스테이지 제거 — 인클러스터 리랭커 폐지로 ArgoCD 자동배포 트리거 불필요.
    //     (GPU/VESSL 리랭커 URL은 Redis가 공급; onramp-api scripts/reranker/up.sh|down.sh 로 운영)
  }

  post {
    always {
      sh 'rm -rf .venv image-digest.txt models || true'
    }
  }
}
