# Sử dụng image Python 3.9-slim làm base image
FROM python:3.9-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Sao chép file requirements.txt vào container
COPY requirements.txt .

# Cài đặt các thư viện cần thiết
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của dự án vào container
COPY . .

# Lệnh chạy ứng dụng
CMD ["python", "main.py"]