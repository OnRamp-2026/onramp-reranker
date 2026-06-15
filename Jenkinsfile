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
      # ⚠️ build-bake(Dockerfile)는 fp32 모델 로드+양자화로 메모리 多 — kaniko 컨테이너에 충분한 limit 필요.
      #    노드(~3.2Gi)에서 빠듯하면 ① Dockerfile.prebuilt + 사전생성 모델(S3/git-lfs) 또는 ② 큰 빌드 노드 고려.
      resources:
        requests:
          cpu: 500m
          memory: 2Gi
        limits:
          cpu: "2"
          memory: 5Gi
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
    // build-bake는 빌드 시 HF에서 base 모델 다운로드 필요(egress). avx2 양자화(노드 CPU = avx2·avx512f, vnni 미지원).
    RERANKER_ARCH = 'avx2'
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
              --dockerfile "${WORKSPACE}/Dockerfile" \
              --build-arg RERANKER_ARCH="${RERANKER_ARCH}" \
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
                --dockerfile "${WORKSPACE}/Dockerfile" \
                --build-arg RERANKER_ARCH="${RERANKER_ARCH}" \
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

            # ⚠️ onramp-api 파이프라인과 달리 **reranker.image 만** 스코프 업데이트(같은 파일 app.image 안 건드림).
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
      sh 'rm -rf .venv gitops image-digest.txt || true'
    }
  }
}
