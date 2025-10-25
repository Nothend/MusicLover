FROM python:3.12-alpine3.21
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip3 install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/entrypoint.sh
ENV TZ=Asia/Shanghai
EXPOSE 5151
CMD ["/app/entrypoint.sh"]
