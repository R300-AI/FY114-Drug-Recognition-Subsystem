# Dockerfile - FY114 血液透析低血壓預警
# 
# 使用 TensorFlow 官方映像
# 包含：Ubuntu 22 + Python 3.8 + TensorFlow 2.3.0
#
# 建立與執行:
#   docker build -t hemo-detection-service .
#   docker run -d -p 5000:5000 --name hemo-detection-service hemo-detection-service

FROM tensorflow:2.3-py38

RUN apt-get update && apt-get install -y \
    python3.8 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install tensorflow==2.3.0

COPY . /home/ubuntu/hemo-detection-service

CMD ["python", "/home/ubuntu/hemo-detection-service/demo.py"]