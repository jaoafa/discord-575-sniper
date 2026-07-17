FROM python:3.14-slim

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Tokyo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CI(reusable-docker.yml)が渡す build-arg を実行時の環境変数として引き継ぐ。
# ARG は素の状態ではビルド時にしか参照できないため、ENV に代入してコンテナ
# 実行時にも src/version.py から os.environ 経由で参照可能にする。
# バージョンはビルドのたびに変わるため、pip install の後に置いて
# 依存関係インストールのレイヤーキャッシュを無効化しないようにする。
ARG APPLICATION_VERSION
ENV APPLICATION_VERSION=${APPLICATION_VERSION}

COPY src/ ./src/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
