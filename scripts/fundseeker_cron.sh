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
# Step 2b: 工作日分支 — 跑 collect（fast path：只跑 funds + bank-wm）
#   当前东方财富 holdings API 不可用，今天 4 次跑都卡死，跳过 holdings。
#   如果 ENABLE_HOLDINGS=1，则跑 --all（30 分钟超时，含 holdings）。
# ---------------------------------------------------------------------------
ALREADY_OUTPUT=1  # 标记脚本输出过内容，防止 trap 重复告警
if [ "${ENABLE_HOLDINGS:-0}" = "1" ]; then
  collect_output=$(PYTHONPATH=src timeout 1800 python scripts/fundseeker_cli.py collect --all 2>&1)
  collect_ec=$?
  if [ "$collect_ec" -eq 124 ]; then
    collect_output="${collect_output}
⚠️ collect --all 超时（1800s）被 SIGTERM，已写入部分结果"
  fi
else
  collect_output=$(PYTHONPATH=src timeout 600 python scripts/fundseeker_cli.py collect --funds --bank-wm 2>&1)
  collect_ec=$?
  if [ "$collect_ec" -eq 124 ]; then
    collect_output="${collect_output}
⚠️ collect 超时（600s）被 SIGTERM，已写入部分结果"
  fi
  if [ "$collect_ec" -eq 0 ]; then
    collect_output="${collect_output}

ℹ️ 本次 fast path 跳过了 holdings（东方财富 API 当前不可用）"
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