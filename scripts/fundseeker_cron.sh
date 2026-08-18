#!/usr/bin/env bash
#
# FundSeeker 每日基金产品信息采集脚本（command cron payload）
# 替代原来的 agent cron：纯 shell + python，0 次大模型调用。
#
# 流程：
#   1. 节假日判断（curl timor.tech）
#   2. 节假日 → 简单通知 + 退出
#   3. 工作日 → collect --all（25 分钟 timeout），包成飞书消息（stdout 即 announce payload）
#
# 退出码：
#   0 = OK（含任务失败但已包进 stdout 报告）
#   非 0 = 真正的脚本/系统错误，会触发 cron failureAlert
#
# 注意：保留最后输出的内容到 stderr 以便 cron delivery 使用

set -u

cd /home/cc/projects/fundseeker
# shellcheck disable=SC1091
source .venv/bin/activate

TODAY=$(TZ=Asia/Shanghai date +%Y-%m-%d)
NEXT=$(TZ=Asia/Shanghai date -d 'next workday' +%Y-%m-%d 2>/dev/null || date -d 'tomorrow' +%Y-%m-%d)

# Trap 任何异常退出，保证 stdout 总是有内容（cron 才会 announce）
trap 'ec=$?; if [ "$ec" -ne 0 ] && [ -z "${ALREADY_OUTPUT:-}" ]; then echo "[fundseeker_cron] 脚本异常退出 (exit=$ec, time=$(TZ=Asia/Shanghai date +%H:%M:%S))，请查看 gateway 日志或手动跑 collect 排查" >&2; fi' EXIT

# ---------------------------------------------------------------------------
# Step 1: 节假日判断（必须带 UA，否则 403）
# ---------------------------------------------------------------------------
holiday_json=$(curl -fsS -A "Mozilla/5.0" "https://timor.tech/api/holiday/info/${TODAY}" 2>/dev/null) || holiday_json=""

is_holiday="false"
holiday_name=""
if [ -n "$holiday_json" ]; then
  # holiday 字段是 dict 且 holiday.holiday == True 才是真节假日
  # 输出格式：<true|false>\t<name>，用 tab 分隔避免 read 被多行问题坑
  parse_out=$(echo "$holiday_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
h = d.get('holiday') or {}
ok = isinstance(h, dict) and h.get('holiday') is True
print(('true' if ok else 'false') + '\t' + (h.get('name', '') if isinstance(h, dict) else ''))
" 2>/dev/null) || parse_out=$'false\t'
  is_holiday=$(printf '%s' "$parse_out" | cut -f1)
  holiday_name=$(printf '%s' "$parse_out" | cut -f2-)
fi

# ---------------------------------------------------------------------------
# Step 2a: 节假日分支
# ---------------------------------------------------------------------------
if [ "$is_holiday" = "true" ]; then
  {
    echo "🌙 今日 (${TODAY}) 是 ${holiday_name:-节假日}，按用户要求跳过基金采集。"
    echo "下次采集: 下个工作日 18:00 (Asia/Shanghai)"
  }
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2b: 工作日分支 — 跑 collect
#   产品和净值每日采集（funds + bank-wm + market-quotes）。
#   持仓数据按季度披露，只在季度首月（1/4/7/10）22 日及以后跑 --all。
#   可通过 ENABLE_HOLDINGS=0 临时跳过持仓，ENABLE_HOLDINGS=1 强制跑持仓。
# ---------------------------------------------------------------------------
MONTH=$(TZ=Asia/Shanghai date +%m)
DAY=$(TZ=Asia/Shanghai date +%d)
case "$MONTH" in
  01|04|07|10) IS_HOLDING_MONTH=true ;;
  *) IS_HOLDING_MONTH=false ;;
esac
if [ "$IS_HOLDING_MONTH" = "true" ] && [ "$DAY" -ge 22 ]; then
  IN_HOLDING_WINDOW=true
else
  IN_HOLDING_WINDOW=false
fi

ALREADY_OUTPUT=1  # 标记脚本输出过内容，防止 trap 重复告警
if [ "${ENABLE_HOLDINGS:-}" = "1" ] || { [ "${ENABLE_HOLDINGS:-}" != "0" ] && [ "$IN_HOLDING_WINDOW" = "true" ]; }; then
  # 5400s = 90 min；持仓窗口期 642 只基金 × 90s per-product 最坏 ~16h，外层 timeout 设大让 collect 自然跑完
  # runner 内置 max_runtime_seconds=3600 + 内部 SIGTERM cleanup；cron payload 已设 7200s
  # --all 已包含 --market-quotes（见 fundseeker_cli.py:184）
  collect_output=$(PYTHONPATH=src timeout 5400 python scripts/fundseeker_cli.py collect --all 2>&1)
  collect_ec=$?
  if [ "$collect_ec" -eq 124 ]; then
    collect_output="${collect_output}
⚠️ collect --all 超时（5400s）被 SIGTERM，已写入部分结果"
  fi
else
  # 非持仓窗口：funds + bank-wm + market-quotes 三件套每日都跑。
  # market-quotes 实测 8~120s，加上 buffer；funds+bank-wm 实测 < 600s；总 timeout 780s。
  # market-quotes 失败 → collect exit 1（cron 仍 announce 报告，不算脚本错）。
  collect_output=$(PYTHONPATH=src timeout 780 python scripts/fundseeker_cli.py collect --funds --bank-wm --market-quotes 2>&1)
  collect_ec=$?
  if [ "$collect_ec" -eq 124 ]; then
    collect_output="${collect_output}
⚠️ collect 超时（780s）被 SIGTERM，已写入部分结果"
  fi
  if [ "$collect_ec" -eq 0 ]; then
    collect_output="${collect_output}

ℹ️ 本次未进入持仓采集窗口（季度首月 22 日及以后才采集持仓；ENABLE_HOLDINGS 未强制开启）"
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: 包成飞书消息（stdout 即 announce payload）
# ---------------------------------------------------------------------------
if [ "$collect_ec" -eq 0 ]; then
  badge="✅"
elif [ "$collect_ec" -eq 1 ]; then
  badge="⚠️"
else
  badge="❌"
fi

{
  echo "📊 FundSeeker 基金产品信息日报 — ${TODAY}"
  echo "退出码: ${collect_ec} ${badge}"
  echo ""
  echo "──────────── 完整报告 ────────────"
  echo "$collect_output"
  echo "──────────── 报告结束 ────────────"
  echo ""
  echo "下次计划: ${NEXT} 18:00 (Asia/Shanghai)"
}

# ec == 0/1 都视为 cron ok（任务失败已在报告里高亮）；ec >= 2 才是脚本错
if [ "$collect_ec" -ge 2 ]; then
  exit "$collect_ec"
fi
exit 0