#!/bin/bash
# 自动构建多架构镜像并推送到私有仓库
sudo docker buildx build --platform linux/amd64,linux/arm64   -t 192.168.1.169:5000/threshold-service:v1   --push .

# 强制重启 K8s 中的 Pod（删除后由 Deployment 自动拉取最新镜像）
kubectl delete pod -l app=threshold-service
