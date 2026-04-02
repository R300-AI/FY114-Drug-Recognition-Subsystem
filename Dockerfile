# Dockerfile - FY114 藥物辨識推論伺服器
# 
# 使用 AMD Ryzen AI PyTorch 官方映像
#
# 建立與執行:
#   docker build -t drug-detection-service .
#   docker run -d -p 5000:5000 --name drug-detection-service drug-detection-service

FROM amdih/ryzen-ai-pytorch:latest

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 複製所有檔案並安裝依賴
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "api:app"]
