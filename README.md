基于告警邮件的自动化根因分析与修复（需求说明）

版本：20250928-0153

1. 目标与范围

目标：实现“收到告警邮件 → 自动解析 → AI 根因分析 → 生成解决方案 → 自动/半自动执行”的闭环。
范围：覆盖你提供的 9 类典型告警（Jenkins 重启、vmalert 配置失败、Prometheus 远程写相关、日志泛滥、RecordingRulesError、vminsert 写入错误、etcd 延迟）。
成果：一套可部署的最小链路（Mail → Parse → JSON → Qwen → Tools），并提供 Runbook 与策略文件。
2. 架构与流程

见附件：aiops-email-rca-flowchart.png。关键组件：

邮件接入：IMAP 轮询（IDLE）或 Microsoft Graph 订阅（推荐对接 Outlook/Exchange）。
标准化：解析表格/文本，产出统一的事件 JSON（schema 见 §4）。
AI 引擎：Qwen-Plus（DashScope 兼容模式）执行 RCA 决策。
工具执行：Prometheus/VM/ES/K8s/网络探测。
审批与回写：Slack/钉钉 审批；事件归档到知识库。
3. 邮件服务器对接方案（强制给出两条路径）

3.1 IMAP 轮询（通用，部署最快）

依赖：可访问企业邮箱 IMAP（TLS），建议使用 OAuth2 或特定应用密码；开启 IDLE 减少轮询。
需要配置：
IMAP_HOST / IMAP_PORT（通常 993）
USERNAME / PASSWORD（或 XOAUTH2 令牌）
监控文件夹（如 INBOX/Alerts）与过滤条件（发件人/主题关键字）。
流程：
连接 IMAP，进入 IDLE；收到新邮件唤醒。
拉取最新邮件 → 解析 HTML/表格 → 结构化为 JSON（见 §4）。
投递到 RCA API（/events）。
3.2 Microsoft Graph 订阅 + Webhook（Outlook/Exchange Online 推荐）

依赖：Azure Entra 应用（client_id / secret）、邮箱的订阅权限（Mail.Read）。
流程：
Graph 订阅 messages，指向你的 /msgraph/webhook 回调；
验证回调（Graph 要求验证 token）；
收到通知后使用 Graph 拉取增量邮件内容；
解析并标准化为事件 JSON。
可选：若你的告警本源是 Alertmanager，也可绕过邮箱，直接将 Alertmanager Webhook 推送到 /webhook。
4. 事件 JSON Schema（标准化产物）

{
  "alert": "PrometheusRemoteWriteBehind",
  "severity": "P2|P3|P4",
  "labels": {
    "cluster": "HK-DCE5-PLATFORM",
    "namespace": "insight-system",
    "workload": "prometheus-insight-agent-kube-prometh-prometheus-0",
    "component": "prometheus"
  },
  "metrics": {
    "times": 2,
    "first_occur": "2025-09-23T00:00:00Z"
  },
  "raw": {
    "mail_subject": "...",
    "mail_id": "..."
  }
}
5. AI 引擎（Qwen）集成规范

模型：qwen-plus
Base URL：https://dashscope.aliyuncs.com/compatible-mode/v1
认证：HTTP Header Authorization: Bearer $QWEN_API_KEY（请通过环境变量注入）
接口：OpenAI-compatible /chat/completions
示例请求（curl）：
curl -s ${BASEURL}/chat/completions  -H "Authorization: Bearer $QWEN_API_KEY"  -H "Content-Type: application/json"  -d '{
  "model": "qwen-plus",
  "temperature": 0.1,
  "messages": [
    {"role":"system","content":"你是SRE助手，按JSON输出evidence_plan/diagnosis/actions"},
    {"role":"user","content":"<粘贴 §4 的事件 JSON>"}
  ]
}'
安全：不要在代码仓库明文写入密钥。使用 环境变量 QWEN_API_KEY，或密钥管理（Kubernetes Secret / Vault）。
6. 执行器与策略

执行器提供统一 REST：/tools/prom, /tools/k8s, /tools/es, /tools/netprobe。
策略文件：remediation_policies.yaml 把“告警 → 采证 → 行动/回滚”固化，支持阈值判断。
高风险动作（重启 etcd/Prometheus 主实例、规则大规模回滚）必须走审批。
7. 非功能性要求（NFR）

可靠性：邮件拉取与 Webhook 至少 1 小时断线重试；事件处理支持去重。
安全：密钥只存储在 Secret；所有出站请求走公司代理白名单；全链路审计日志。
性能：单实例可处理 ≥ 100 封告警邮件/分钟；端到端 MTTA ≤ 60s（Webhook），≤ 3min（IMAP）。
可观测：自身指标：处理耗时、失败率、动作采纳率；写入 Prometheus。
8. 交付件

流程图 aiops-email-rca-flowchart.png
参考实现：email_ingest.py、qwen_client.py、remediation_policies.yaml、n8n-flow.json
部署清单（Docker/K8s）
附：email_ingest.py（IMAP 轮询 + 解析示例）

import os, imaplib, email, time, re, json, requests
from bs4 import BeautifulSoup

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")
RCA_ENDPOINT = os.getenv("RCA_ENDPOINT", "http://ops-agent/events")

def parse_table(html):
    soup = BeautifulSoup(html, "html.parser")
    # TODO: 针对你模板做规则化解析（正则+列名匹配），返回事件JSON列表
    return []

def handle_message(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/html","text/plain"):
                body = part.get_payload(decode=True).decode(errors="ignore")
                events = parse_table(body)
                for e in events:
                    requests.post(RCA_ENDPOINT, json=e, timeout=10)
                break

def main():
    while True:
        M = imaplib.IMAP4_SSL(IMAP_HOST)
        M.login(IMAP_USER, IMAP_PASS)
        M.select("INBOX")
        typ, data = M.search(None, '(UNSEEN SUBJECT "Control Cluster Details")')
        for num in data[0].split():
            typ, d = M.fetch(num, '(RFC822)')
            msg = email.message_from_bytes(d[0][1])
            handle_message(msg)
        M.logout()
        time.sleep(30)

if __name__ == "__main__":
    main()
附：qwen_client.py（调用 Qwen-Plus 的 RCA 包装）

import os, requests, json

BASEURL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
APIKEY = os.getenv("QWEN_API_KEY")  # 在部署时注入环境变量
MODEL = "qwen-plus"

def rca(event_json):
    payload = {
        "model": MODEL,
        "temperature": 0.1,
        "messages": [
            {"role":"system","content":"你是SRE助手，严格输出JSON: evidence_plan, diagnosis, actions, rollback"},
            {"role":"user","content": json.dumps(event_json, ensure_ascii=False)}
        ]
    }
    r = requests.post(f"{BASEURL}/chat/completions",
                      headers={"Authorization": f"Bearer {APIKEY}", "Content-Type":"application/json"},
                      json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

if __name__ == "__main__":
    demo = {"alert":"PrometheusRemoteWriteBehind","labels":{"namespace":"insight-system"}}
    print(rca(demo))
附：n8n-flow.json（Webhook→标准化→Qwen→执行器）

{
  "name": "AIOps Email RCA",
  "nodes": [
    {"name":"Webhook","type":"n8n-nodes-base.webhook","parameters":{"path":"ops-agent/webhook","methods":["POST"]}},
    {"name":"Normalize","type":"n8n-nodes-base.function","parameters":{"functionCode":"return [{json:$json}];"}},
    {"name":"Qwen","type":"n8n-nodes-base.httpRequest","parameters":{"url":"https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions","method":"POST","options":{"bodyContentType":"json"},"jsonParameters":true,"authentication":"genericCredentialType","genericAuthType":"httpHeaderAuth","sendHeaders":true,"headerParametersUi":{"parameter":[{"name":"Authorization","value":"Bearer {{$env.QWEN_API_KEY}}"},{"name":"Content-Type","value":"application/json"}]},"jsonBodyParameters":{"model":"qwen-plus","messages":[{"role":"system","content":"你是SRE助手，按JSON输出evidence_plan/diagnosis/actions"},{"role":"user","content":"{{$json}}"]}}},
    {"name":"Act","type":"n8n-nodes-base.httpRequest","parameters":{"url":"http://ops-agent/tools/execute","method":"POST"}}
  ],
  "connections": {"Webhook":{"main":[["Normalize"]]}, "Normalize":{"main":[["Qwen"]]}, "Qwen":{"main":[["Act"]]}}
}
环境变量建议（.env）

IMAP_HOST=imap.example.com
IMAP_USER=alerts@example.com
IMAP_PASS=********
QWEN_API_KEY=***请在部署环境注入***
RCA_ENDPOINT=http://ops-agent/events
