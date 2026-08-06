#!/usr/bin/env bash
# DealMind 安全并发压测：只打轻量 /health，绝不触发 LLM / embedding / 写库。
# 目的：测单进程 uvicorn 在高并发连接下的请求处理能力与稳定性。
set -u

URL="http://127.0.0.1:8001/health"

run_level () {
  conc=$1; total=$2; tmp=$(mktemp)
  start=$(date +%s.%N)
  seq 1 "$total" | xargs -P "$conc" -I{} curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 "$URL" > "$tmp"
  end=$(date +%s.%N)
  ok=$(grep -c '^200 ' "$tmp")
  sort -n -k2 "$tmp" | awk -v conc="$conc" -v total="$total" -v ok="$ok" -v start="$start" -v end="$end" '
    {n++; s+=$2; t[n]=$2}
    END{
      wall=end-start; qps=(wall>0)?total/wall:0;
      idx=int(n*0.95); if(idx<1) idx=1;
      printf "  并发=%-3d 总请求=%-4d | 成功=%-4d 失败=%-3d | 用时=%.2fs QPS=%.1f | 平均=%.3fs P95=%.3fs 最大=%.3fs\n", \
             conc,total,ok,total-ok,wall,qps,s/n,t[idx],t[n]
    }'
  rm -f "$tmp"
}

echo "===== 压测前状态 ====="
free -h | grep -E 'Mem|Swap'; echo -n "负载: "; uptime | sed 's/.*load average/load average/'

echo "===== 逐级加压（目标 $URL）====="
run_level 10 200
run_level 30 600
run_level 50 1000
run_level 80 1600

echo "===== 压测后状态 ====="
free -h | grep -E 'Mem|Swap'; echo -n "负载: "; uptime | sed 's/.*load average/load average/'

echo "===== 后端存活检查 ====="
echo -n "dealmind-api: "; systemctl is-active dealmind-api
curl -s -o /dev/null -w "  /health = %{http_code}\n" http://127.0.0.1:8001/health
echo "DONE"
