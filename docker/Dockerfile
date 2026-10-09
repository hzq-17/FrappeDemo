# user_growth —— Frappe v15 开发/演示镜像
#
# 设计说明：
#   * 镜像只负责"环境"（系统依赖 + bench + frappe 框架），不包含业务代码；
#     业务代码（user_growth App）通过 docker-compose 以卷方式挂载进容器，
#     因此修改 Python/JS/CSS 后无需重新构建镜像。
#   * 默认使用国内可用的镜像源与包源（可通过 build args 覆盖），
#     以保证在网络受限（GitHub / npm 官方源不可达）的环境中也能构建成功。
#   * 默认安装 chromium（headless），用于对增长大屏做截图式视觉验证；
#     不需要时传 --build-arg INSTALL_BROWSER=0 可显著缩短构建时间。

ARG BASE_IMAGE=debian:bookworm-slim
FROM ${BASE_IMAGE}

ARG FRAPPE_BRANCH=version-15
ARG APT_MIRROR=deb.debian.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG INSTALL_BROWSER=1
# 构建期代理：仅用于 git clone GitHub 源码。
# 注意：故意不使用 HTTP_PROXY/HTTPS_PROXY 这两个名字——Docker/BuildKit 会把它们
# 视为预定义代理参数并注入到每一个 RUN 步骤，导致 apt / pip 也走代理而变慢。
ARG UG_HTTP_PROXY=
ARG UG_HTTPS_PROXY=

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BENCH_DIR=/home/frappe/frappe-bench

# ---------------------------------------------------------------------------
# 1. 系统依赖
# ---------------------------------------------------------------------------
RUN set -eux; \
    if [ "${APT_MIRROR}" != "deb.debian.org" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg \
        python3 python3-pip python3-dev python3-venv \
        build-essential pkg-config libffi-dev libssl-dev default-libmysqlclient-dev \
        mariadb-client redis-tools \
        nodejs npm \
        fonts-noto-cjk fontconfig \
        procps less vim jq unzip xz-utils sudo; \
    if [ "${INSTALL_BROWSER}" = "1" ]; then \
        apt-get install -y --no-install-recommends chromium; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Python / Node 工具链
# ---------------------------------------------------------------------------
RUN set -eux; \
    npm config set registry "${NPM_REGISTRY}"; \
    npm install -g yarn@1.22.22 --silent; \
    python3 -m pip install --no-cache-dir --break-system-packages \
        -i "${PIP_INDEX_URL}" frappe-bench; \
    if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then \
        python3 -m pip config --global set global.extra-index-url "${PIP_EXTRA_INDEX_URL}"; \
    fi

# ---------------------------------------------------------------------------
# 3. 运行用户（Frappe 官方镜像同样使用 uid=1000 的 frappe 用户）
# ---------------------------------------------------------------------------
RUN set -eux; \
    useradd -m -u 1000 -s /bin/bash frappe; \
    echo 'frappe ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/frappe; \
    chmod 0440 /etc/sudoers.d/frappe

USER frappe
WORKDIR /home/frappe

# ---------------------------------------------------------------------------
# 4. 初始化 bench + 拉取 frappe 框架
#    构建期代理只在此处生效：GitHub 不可达的环境需要传入 HTTP_PROXY/HTTPS_PROXY
# ---------------------------------------------------------------------------
RUN set -eux; \
    export http_proxy="${UG_HTTP_PROXY}" https_proxy="${UG_HTTPS_PROXY}"; \
    export no_proxy="localhost,127.0.0.1"; \
    export npm_config_registry="${NPM_REGISTRY}"; \
    export PIP_INDEX_URL="${PIP_INDEX_URL}"; \
    export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}"; \
    yarn config set registry "${NPM_REGISTRY}" >/dev/null; \
    bench init \
        --frappe-branch "${FRAPPE_BRANCH}" \
        --python python3 \
        --skip-redis-config-generation \
        --no-backups \
        --clone-without-update \
        /home/frappe/frappe-bench; \
    cp -a /home/frappe/frappe-bench/sites /home/frappe/sites-seed

WORKDIR /home/frappe/frappe-bench

# 页面与容器内工具都使用 UTF-8；此处仅为显式声明
ENV PYTHONIOENCODING=utf-8
