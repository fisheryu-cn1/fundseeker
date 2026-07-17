#!/usr/bin/env bash
#
# FundSeeker 持仓相似性分析定时脚本
# 与 fundseeker_cron.sh（信息采集）分离，专门负责聚类/归因跑批。
#
# 环境变量：
#   SIMILARITY_MODE         运行模式：full | auto | incremental（默认 auto）
#   SIMILARITY_REPORT_DATE  持仓报告期（YYYY-MM-DD），默认取数据库最新报告期
#   SIMILARITY_START_DATE   归因起始日，默认 report_date
#   SIMILARITY_END_DATE     归因截止日，默认 today
#   SIMILARITY_FEATURE_TYPE 特征空间：asset | industry（默认 asset）
#   SIMILARITY_K            聚类数或 auto（默认 auto）
#   SIMILARITY_BENCHMARK    归因基准：cluster_avg | index（默认 cluster_avg）
#   SIMILARITY_BENCHMARK_CODE 指数代码，benchmark=index 时必填
#   SKIP_INDEX_WEIGHTS      是否跳过指数权重刷新：1 跳过（默认 0）
#   SKIP_QUOTES             是否跳过行情补录：1 跳过（默认 0）
#
# 退出码：
#   0 = 执行成功或任务失败但已包进报告
#   >=2 = 脚本/参数错误

# shellcheck disable=SC2317
set -uo pipefail

cd /home/cc/projects/fundseeker
# shellcheck disable=SC1091
source .venv/bin/activate

TODAY=$(TZ=Asia/Shanghai date +%Y-%m-%d)
NOW=$(TZ=Asia/Shanghai date +%H:%M:%S)

MODE="${SIMILARITY_MODE:-auto}"
REPORT_DATE="${SIMILARITY_REPORT_DATE:-}"
# 默认 start_date = report_date；若 report_date 也未提供，则兜底为 today
START_DATE="${SIMILARITY_START_DATE:-${REPORT_DATE:-today}}"
END_DATE="${SIMILARITY_END_DATE:-today}"
FEATURE_TYPE="${SIMILARITY_FEATURE_TYPE:-asset}"
K="${SIMILARITY_K:-auto}"
BENCHMARK="${SIMILARITY_BENCHMARK:-cluster_avg}"
BENCHMARK_CODE="${SIMILARITY_BENCHMARK_CODE:-}"
SKIP_INDEX_WEIGHTS="${SKIP_INDEX_WEIGHTS:-0}"
SKIP_QUOTES="${SKIP_QUOTES:-0}"

# 构建 pipeline 参数数组
args=(
  python scripts/fundseeker_similarity.py pipeline
  --mode "${MODE}"
  --feature-type "${FEATURE_TYPE}"
  --k "${K}"
  --benchmark "${BENCHMARK}"
  --end-date "${END_DATE}"
)

[ -n "${REPORT_DATE}" ] && args+=(--report-date "${REPORT_DATE}")
[ -n "${START_DATE}" ] && args+=(--start-date "${START_DATE}")
[ -n "${BENCHMARK_CODE}" ] && args+=(--benchmark-code "${BENCHMARK_CODE}")
[ "${SKIP_INDEX_WEIGHTS}" = "1" ] && args+=(--skip-index-weights)
[ "${SKIP_QUOTES}" = "1" ] && args+=(--skip-quotes)

# 根据模式设置超时：
#   - full 模式可能重选 K，给 1h
#   - auto/incremental 给 1.5h 缓冲，避免内部 timeout 与 cron payload 同时到
# 注释：cron payload 已设为 3600s (1h)；脚本内部 timeout 必须 > cron 让 cron 来做最终清理
case "${MODE}" in
  full)     timeout_sec=5400 ;;
  *)        timeout_sec=5400 ;;
esac

output=$(PYTHONPATH=src timeout "${timeout_sec}" "${args[@]}" 2>&1)
ec=$?

if [ "$ec" -eq 124 ]; then
  output="${output}
⚠️ pipeline 超时（${timeout_sec}s）被 SIGTERM 终止"
fi

if [ "$ec" -eq 0 ]; then
  badge="✅"
elif [ "$ec" -eq 1 ]; then
  badge="⚠️"
else
  badge="❌"
fi

{
  echo "📊 FundSeeker 相似性分析日报 — ${TODAY} ${NOW}"
  echo "模式: ${MODE} | 特征: ${FEATURE_TYPE} | K: ${K}"
  echo "退出码: ${ec} ${badge}"
  echo ""
  echo "──────────── 完整报告 ────────────"
  echo "$output"
  echo "──────────── 报告结束 ────────────"
}

# ec 0/1 视为 cron ok（任务失败已在报告中高亮）
if [ "$ec" -ge 2 ]; then
  exit "$ec"
fi
exit 0
