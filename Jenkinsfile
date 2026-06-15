pipeline {
  agent {
    kubernetes {
      defaultContainer 'tools'
      yaml """
apiVersion: v1
kind: Pod
spec:
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
    GITOPS_REPOSITORY = 'https://github.com/OnRamp-2026/gitops.git'
    GITOPS_VALUES_FILE = 'apps/onramp-api/values-dev.yaml'
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
          apt-get install -y --no-install-recommends git ca-certificates curl
          # yq(mikefarah) — values-dev.yaml의 reranker.image 만 스코프 업데이트(주석 보존)
          curl -sSL -o /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
          chmod +x /usr/local/bin/yq
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

    stage('Update GitOps Image Digest') {
      when {
        allOf {
          branch 'main'
          not { changeRequest() }
        }
      }
      steps {
        withCredentials([usernamePassword(
          credentialsId: 'github-gitops-write-token',
          usernameVariable: 'GITOPS_USERNAME',
          passwordVariable: 'GITOPS_TOKEN'
        )]) {
          sh '''
            set -eu
            rm -rf gitops
            ENCODED_GITOPS_USERNAME="$(python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["GITOPS_USERNAME"], safe=""))')"
            ENCODED_GITOPS_TOKEN="$(python -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["GITOPS_TOKEN"], safe=""))')"
            AUTHED_REPO="$(printf '%s' "${GITOPS_REPOSITORY}" | sed "s#https://#https://${ENCODED_GITOPS_USERNAME}:${ENCODED_GITOPS_TOKEN}@#")"
            git clone "${AUTHED_REPO}" gitops
            cd gitops
            git config user.name "onramp-jenkins"
            git config user.email "onramp-jenkins@users.noreply.github.com"

            # reranker.image 만 스코프 업데이트(같은 파일 app.image 보존). enabled 토글은 사람이 수동(활성화 순서).
            REPO="${IMAGE_REPOSITORY}" TAG="${IMAGE_TAG}" DIG="${IMAGE_DIGEST}" \
              yq -i '.reranker.image.repository = strenv(REPO) | .reranker.image.tag = strenv(TAG) | .reranker.image.digest = strenv(DIG)' "${GITOPS_VALUES_FILE}"

            git diff -- "${GITOPS_VALUES_FILE}"
            if git diff --quiet -- "${GITOPS_VALUES_FILE}"; then
              echo "No GitOps image digest change."
              exit 0
            fi
            git add "${GITOPS_VALUES_FILE}"
            git commit -m "chore: update onramp-reranker image ${IMAGE_TAG} [skip ci]"
            git push origin main
          '''
        }
      }
    }
  }

  post {
    always {
      sh 'rm -rf .venv gitops image-digest.txt models || true'
    }
  }
}
