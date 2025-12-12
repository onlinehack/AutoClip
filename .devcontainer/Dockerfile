FROM python:3.11-slim

# Replace apt sources with Aliyun mirror for faster downloads in China
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list

# Install ffmpeg, imagemagick and fonts (critical)
RUN apt-get update && apt-get install -y \
    ffmpeg imagemagick fonts-noto-cjk git \
    && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick policy
RUN policy_file=""; \
    if [ -f /etc/ImageMagick-7/policy.xml ]; then policy_file="/etc/ImageMagick-7/policy.xml"; \
    elif [ -f /etc/ImageMagick-6/policy.xml ]; then policy_file="/etc/ImageMagick-6/policy.xml"; \
    elif [ -f /etc/ImageMagick/policy.xml ]; then policy_file="/etc/ImageMagick/policy.xml"; \
    fi; \
    if [ ! -z "$policy_file" ]; then \
    sed -i 's/none/read,write/g' "$policy_file"; \
    sed -i 's/rights="none" pattern="@\*"/rights="read|write" pattern="@*"/g' "$policy_file"; \
    fi

WORKDIR /workspace

COPY requirements.txt .
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir -r requirements.txt
