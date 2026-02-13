from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

DATA_FILE = Path("data/records.json")
HOST = "0.0.0.0"
PORT = 8000


def ensure_data_file() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text("[]", encoding="utf-8")


def load_records() -> list[dict]:
    ensure_data_file()
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_records(records: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def next_id(records: list[dict]) -> int:
    return max((record["id"] for record in records), default=0) + 1


def parse_fee_items(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    items: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        try:
            price = max(0.0, float(item.get("price", 0) or 0))
        except (TypeError, ValueError):
            price = 0.0
        try:
            qty = max(1, int(item.get("quantity", 1) or 1))
        except (TypeError, ValueError):
            qty = 1
        subtotal = round(price * qty, 2)
        if name or subtotal:
            items.append({"name": name, "price": price, "quantity": qty, "subtotal": subtotal})
    return items


def compute_fee(record: dict) -> float:
    if isinstance(record.get("fee_items"), list) and record["fee_items"]:
        return round(sum(float(item.get("subtotal", 0) or 0) for item in record["fee_items"]), 2)
    try:
        return round(max(0.0, float(record.get("fee", 0) or 0)), 2)
    except (TypeError, ValueError):
        return 0.0


def stats(records: list[dict]) -> dict[str, float | int]:
    today = date.today().isoformat()
    month_prefix = date.today().strftime("%Y-%m")
    today_records = [r for r in records if r.get("visit_date", "") == today]
    month_records = [r for r in records if str(r.get("visit_date", "")).startswith(month_prefix)]
    return {
        "count_all": len(records),
        "fee_all": sum(compute_fee(r) for r in records),
        "count_today": len(today_records),
        "fee_today": sum(compute_fee(r) for r in today_records),
        "count_month": len(month_records),
        "fee_month": sum(compute_fee(r) for r in month_records),
    }


def render_index(records: list[dict], q_name: str, q_range: str) -> str:
    all_records = sorted(load_records(), key=lambda x: (x.get("visit_date", ""), x.get("id", 0)), reverse=True)
    patient_profiles: dict[str, dict[str, str]] = {}
    for item in all_records:
        name = str(item.get("patient_name", "")).strip()
        if not name or name in patient_profiles:
            continue
        patient_profiles[name] = {
            "gender": str(item.get("gender", "")).strip(),
            "age": str(item.get("age", "")).strip(),
            "phone": str(item.get("phone", "")).strip(),
            "case_no": str(item.get("case_no", "")).strip(),
        }

    patient_json = json.dumps(patient_profiles, ensure_ascii=False)
    patient_options = "".join(f"<option value='{escape(name)}'></option>" for name in patient_profiles)
    s = stats(all_records)
    today = date.today().isoformat()
    today_records = [r for r in all_records if r.get("visit_date", "") == today]

    row_html = ""
    for record in records:
        fee = compute_fee(record)
        row_html += f"""
        <tr>
          <td>{escape(record.get('visit_date', ''))}</td>
          <td>{escape(record.get('patient_name', ''))}</td>
          <td>{escape(record.get('phone', ''))}</td>
          <td>{escape(record.get('item', '') or summary_items(record))}</td>
          <td>{fee:.2f}</td>
          <td>{escape(record.get('payment_method', ''))}</td>
          <td class='note-cell' title='{escape(record.get('note', ''))}'>{escape(record.get('note', ''))}</td>
          <td>
            <form action='/delete' method='post' onsubmit="return confirm('确定删除这条记录吗？')">
              <input type='hidden' name='id' value='{record.get('id', 0)}' />
              <button class='btn btn-xs danger'>删除</button>
            </form>
          </td>
        </tr>
        """

    if not row_html:
        row_html = "<tr><td colspan='8' class='empty-state'>暂无记录</td></tr>"

    today_cards = ""
    if today_records:
        for item in today_records[:8]:
            today_cards += f"""
            <div class='today-card'>
              <div class='today-name'>{escape(item.get('patient_name', '未命名患者'))}</div>
              <div class='today-meta'>病历号：{escape(item.get('case_no', '-'))} · 金额：¥{compute_fee(item):.2f}</div>
              <div class='today-meta'>主诉：{escape(item.get('chief_complaint', '') or item.get('item', ''))}</div>
            </div>
            """
    else:
        today_cards = "<div class='today-empty'>今天还没有就诊记录。</div>"

    range_labels = {"day": "日", "week": "周", "month": "月", "all": "全部"}
    active_range = q_range if q_range in range_labels else "day"

    return f"""
<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>何江牙所 · 患者管理</title>
  <style>
    :root {{
      --bg: #d9edf1;
      --panel: #f8fbfc;
      --primary: #09a2c9;
      --primary-dark: #0488a8;
      --green: #0d8d4d;
      --text: #063b50;
      --line: #0f95b7;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "PingFang SC","Microsoft YaHei",sans-serif; background: var(--bg); color: var(--text); }}
    .container {{ max-width: 1180px; margin: 0 auto; padding: 18px 22px; }}
    .tab-switch {{ width: fit-content; margin: 0 auto 20px; display: flex; background: #e9f1f3; border-radius: 10px; padding: 4px; box-shadow: 0 2px 7px rgba(0,0,0,.15); }}
    .tab-btn {{ border: none; background: transparent; color: #007ea0; font-size: 28px; padding: 14px 36px; border-radius: 8px; cursor: pointer; }}
    .tab-btn.active {{ background: var(--primary); color: white; }}
    .panel {{ background: rgba(255,255,255,0.75); border-radius: 16px; padding: 22px; box-shadow: 0 2px 6px rgba(0,0,0,.08); }}
    h2 {{ margin: 0 0 18px; color: #048bb2; font-size: 44px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px 24px; }}
    .field label {{ display: block; font-size: 34px; margin-bottom: 8px; }}
    input, select, textarea {{ width: 100%; border: 3px solid var(--line); border-radius: 12px; font-size: 34px; padding: 12px 14px; background: #fff; color: #044962; }}
    textarea {{ min-height: 130px; resize: vertical; }}
    .inline {{ display: flex; gap: 10px; align-items: end; }}
    .btn {{ border: none; border-radius: 12px; padding: 12px 22px; font-size: 32px; cursor: pointer; }}
    .btn.compact {{ font-size: 24px; padding: 10px 14px; }}
    .btn.cyan {{ background: #25b8d6; color: white; }}
    .btn.green {{ background: #11a84f; color: white; }}
    .btn.secondary {{ background: #29b8dd; color: white; }}
    .btn-xs {{ font-size: 24px; padding: 8px 14px; border: none; border-radius: 8px; cursor: pointer; }}
    .btn-xs.danger {{ background: #25b8d6; color: white; }}
    .section-title {{ margin: 14px 0 10px; color: #048bb2; font-size: 40px; font-weight: 700; }}
    .fee-panel {{ background: #d8eef2; border-radius: 12px; padding: 12px; }}
    .fee-row {{ display: grid; grid-template-columns: 1.8fr .45fr .45fr .45fr .28fr; gap: 10px; align-items: end; margin-bottom: 10px; }}
    .fee-row .field label {{ margin-bottom: 6px; }}
    .money-total {{ display:flex; justify-content: space-between; align-items:center; margin-top: 12px; font-size: 50px; color: var(--green); font-weight: 700; }}
    .actions {{ display:flex; gap: 12px; }}
    .stats {{ display:grid; grid-template-columns: repeat(3,1fr); gap: 12px; margin-top: 20px; }}
    .stat {{ background: #edf9fc; border: 2px solid #bce7f0; border-radius: 10px; padding: 12px; }}
    .stat .label {{ font-size: 30px; }}
    .stat .value {{ font-size: 40px; font-weight: 700; margin-top: 6px; }}
    .today-list {{ display:grid; grid-template-columns: repeat(2,1fr); gap: 12px; }}
    .today-card {{ background: #f3fbfd; border: 2px solid #bde9f2; border-radius: 10px; padding: 10px 12px; }}
    .today-name {{ font-size: 34px; font-weight: 700; color: #0d6f8d; }}
    .today-meta {{ font-size: 28px; margin-top: 6px; }}
    .today-empty, .empty-state {{ text-align:center; padding: 20px; color: #4f7f90; font-size: 30px; }}
    .list-wrap {{ margin-top: 18px; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #d8e8ee; padding: 10px; font-size: 24px; text-align: left; }}
    th {{ background: #ebf7fa; }}
    .note-cell {{ max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .filter {{ margin-top: 16px; display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center; }}
    .quick-filters {{ margin-top: 10px; display:flex; gap: 8px; flex-wrap: wrap; }}
    .quick-link {{ text-decoration:none; background:#8cbeca; color:white; padding: 8px 12px; border-radius: 8px; font-size: 22px; }}
    .quick-link.active {{ background: var(--primary); }}
    .hidden {{ display: none; }}
    @media (max-width: 980px) {{
      .grid-2,.stats,.today-list,.fee-row,.filter {{ grid-template-columns: 1fr; }}
      .tab-btn {{ font-size: 22px; }}
      h2 {{ font-size: 30px; }}
      .field label, input,select,textarea,.btn,.section-title,.stat .label,.today-meta {{ font-size: 20px; }}
      .money-total, .today-name,.stat .value {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
<div class='container'>
  <div class='tab-switch'>
    <button class='tab-btn active' data-tab='new'>新增患者</button>
    <button class='tab-btn' data-tab='today'>患者记录</button>
  </div>

  <section class='panel' id='tab-new'>
    <h2>新增患者信息</h2>
    <form action='/add' method='post' id='patient-form'>
      <div class='grid-2'>
        <div class='field'><label>姓名 *</label><input type='text' name='patient_name' id='patient-name' list='patient-suggestions' required /></div>
        <div class='field'><label>性别 *</label><select name='gender' required><option value=''>请选择</option><option>男</option><option>女</option></select></div>
        <div class='field'><label>年龄 *</label><input type='number' min='0' name='age' required /></div>
        <div class='field'><label>电话</label><input type='text' name='phone' /></div>
        <div class='field'>
          <label>病历号</label>
          <div class='inline'>
            <input type='text' id='case-no' name='case_no' value='{generate_case_no()}' />
            <button type='button' class='btn cyan compact' id='regen-case'>生成</button>
            <button type='button' class='btn cyan compact' id='edit-case'>编辑</button>
          </div>
        </div>
        <div class='field'><label>就诊日期 *</label><input type='date' name='visit_date' value='{today}' required /></div>
      </div>

      <div class='field' style='margin-top:12px'><label>主诉</label><textarea name='chief_complaint' placeholder='请输入患者主诉...'></textarea></div>
      <div class='field' style='margin-top:12px'><label>诊断</label><textarea name='diagnosis' placeholder='请输入诊断结果...'></textarea></div>

      <div class='section-title'>费用项目</div>
      <div style='display:flex;justify-content:flex-end;margin-bottom:10px'>
        <button class='btn secondary' type='button' id='add-item'>添加项目</button>
      </div>
      <div class='fee-panel' id='fee-list'></div>
      <input type='hidden' name='fee_items' id='fee-items-json' />
      <input type='hidden' name='fee' id='fee-total-input' value='0' />

      <div class='money-total'>
        <span>总计: ¥<span id='grand-total'>0.00</span></span>
        <div class='actions'>
          <button class='btn secondary' type='reset' id='reset-form'>重置</button>
          <button class='btn green' type='submit'>保存患者</button>
        </div>
      </div>
    </form>

    <div class='stats'>
      <div class='stat'><div class='label'>总就诊人次</div><div class='value'>{s['count_all']}</div></div>
      <div class='stat'><div class='label'>今日人次</div><div class='value'>{s['count_today']}</div></div>
      <div class='stat'><div class='label'>今日费用(元)</div><div class='value'>{s['fee_today']:.2f}</div></div>
    </div>
  </section>

  <section class='panel hidden' id='tab-today'>
    <h2>患者记录</h2>
    <div class='today-list'>{today_cards}</div>

    <form method='get' class='filter'>
      <input type='hidden' name='range' value='{escape(active_range)}' />
      <input type='text' name='name' value='{escape(q_name)}' placeholder='按姓名筛选（将显示该患者全部记录）' list='patient-suggestions' />
      <button class='btn secondary' type='submit'>筛选</button>
      <a class='btn' style='text-decoration:none;text-align:center;background:#8cbeca;color:white' href='/?range={escape(active_range)}'>重置</a>
    </form>
    <div class='quick-filters'>
      <a class='quick-link {"active" if active_range == "day" else ""}' href='/?range=day'>日</a>
      <a class='quick-link {"active" if active_range == "week" else ""}' href='/?range=week'>周</a>
      <a class='quick-link {"active" if active_range == "month" else ""}' href='/?range=month'>月</a>
      <a class='quick-link {"active" if active_range == "all" else ""}' href='/?range=all'>全部</a>
      <span style='font-size:20px;color:#4f7f90;line-height:36px'>当前：按{range_labels[active_range]}查看</span>
    </div>
    <div class='list-wrap'>
      <table>
        <thead><tr><th>日期</th><th>姓名</th><th>电话</th><th>项目</th><th>费用</th><th>支付</th><th>备注</th><th>操作</th></tr></thead>
        <tbody>{row_html}</tbody>
      </table>
    </div>
  </section>
</div>
<script>
(function() {{
  const patientProfiles = {patient_json};
  const patientInput = document.getElementById('patient-name');
  const profileFields = {{
    gender: document.querySelector("select[name='gender']"),
    age: document.querySelector("input[name='age']"),
    phone: document.querySelector("input[name='phone']"),
    case_no: document.querySelector("input[name='case_no']"),
  }};

  function fillPatientInfo() {{
    const profile = patientProfiles[patientInput?.value.trim() || ''];
    if (!profile) return;
    Object.keys(profileFields).forEach(key => {{
      if (profileFields[key]) profileFields[key].value = profile[key] || '';
    }});
  }}
  patientInput?.addEventListener('change', fillPatientInfo);
  patientInput?.addEventListener('blur', fillPatientInfo);
  const tabs = document.querySelectorAll('.tab-btn');
  const tabNew = document.getElementById('tab-new');
  const tabToday = document.getElementById('tab-today');
  function setActiveTab(tabName) {{
    const isNew = tabName === 'new';
    tabs.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
    tabNew.classList.toggle('hidden', !isNew);
    tabToday.classList.toggle('hidden', isNew);
  }}

  tabs.forEach(btn => btn.addEventListener('click', () => {{
    setActiveTab(btn.dataset.tab);
  }}));

  const urlParams = new URLSearchParams(window.location.search);
  const hasRecordFilter = urlParams.has('range') || urlParams.has('name');
  if (hasRecordFilter) setActiveTab('today');

  const feeList = document.getElementById('fee-list');
  const addItemBtn = document.getElementById('add-item');
  const totalEl = document.getElementById('grand-total');
  const feeJson = document.getElementById('fee-items-json');
  const totalInput = document.getElementById('fee-total-input');

  function money(val) {{ return Number(val || 0).toFixed(2); }}

  function addRow(data = {{name:'', price:'0', quantity:'1'}}) {{
    const row = document.createElement('div');
    row.className = 'fee-row';
    row.innerHTML = `
      <div class='field'><label>项目名称</label><input class='item-name' type='text' placeholder='如：洗牙、补牙等' value='${{data.name}}'></div>
      <div class='field'><label>单价 (¥)</label><input class='item-price' type='number' step='0.01' min='0' value='${{data.price}}'></div>
      <div class='field'><label>数量</label><input class='item-qty' type='number' min='1' value='${{data.quantity}}'></div>
      <div class='field'><label>小计 (¥)</label><input class='item-subtotal' type='text' readonly value='0.00'></div>
      <button class='btn secondary remove-row' type='button'>删除</button>
    `;
    feeList.appendChild(row);
    row.querySelectorAll('input').forEach(input => input.addEventListener('input', recalc));
    row.querySelector('.remove-row').addEventListener('click', () => {{ row.remove(); recalc(); }});
    recalc();
  }}

  function recalc() {{
    let total = 0;
    const items = [];
    feeList.querySelectorAll('.fee-row').forEach(row => {{
      const name = row.querySelector('.item-name').value.trim();
      const price = Math.max(0, Number(row.querySelector('.item-price').value || 0));
      const qty = Math.max(1, parseInt(row.querySelector('.item-qty').value || '1', 10));
      const subtotal = price * qty;
      row.querySelector('.item-subtotal').value = money(subtotal);
      total += subtotal;
      if (name || subtotal) {{
        items.push({{ name, price: Number(money(price)), quantity: qty, subtotal: Number(money(subtotal)) }});
      }}
    }});
    totalEl.textContent = money(total);
    totalInput.value = money(total);
    feeJson.value = JSON.stringify(items);
  }}

  addItemBtn.addEventListener('click', () => addRow());
  document.getElementById('patient-form').addEventListener('submit', recalc);
  document.getElementById('reset-form').addEventListener('click', () => setTimeout(() => {{
    feeList.innerHTML = ''; addRow();
    document.getElementById('case-no').value = genCaseNo();
  }}, 0));

  function genCaseNo() {{
    const now = new Date();
    const yy = String(now.getFullYear()).slice(-2);
    const mm = String(now.getMonth()+1).padStart(2,'0');
    const dd = String(now.getDate()).padStart(2,'0');
    const rand = Math.floor(Math.random()*900+100);
    return `${{yy}}${{mm}}${{dd}}${{rand}}`;
  }}
  document.getElementById('regen-case').addEventListener('click', () => document.getElementById('case-no').value = genCaseNo());
  document.getElementById('edit-case').addEventListener('click', () => document.getElementById('case-no').focus());

  addRow();
}})();
</script>
<datalist id='patient-suggestions'>
  {patient_options}
</datalist>
</body>
</html>
"""


def summary_items(record: dict) -> str:
    items = record.get("fee_items")
    if not isinstance(items, list):
        return ""
    names = [str(item.get("name", "")).strip() for item in items if str(item.get("name", "")).strip()]
    return "、".join(names)


def generate_case_no() -> str:
    stamp = datetime.now().strftime("%y%m%d")
    return f"{stamp}{datetime.now().microsecond % 1000:03d}"


def escape(val: str) -> str:
    return html.escape(str(val or ""), quote=True)


class AppHandler(BaseHTTPRequestHandler):
    def _send_html(self, content: str, status: int = 200) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _redirect(self, location: str = "/") -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self._send_html("<h1>404 Not Found</h1>", 404)
            return

        params = parse_qs(parsed.query)
        q_name = (params.get("name") or [""])[0].strip()
        q_range = (params.get("range") or ["day"])[0].strip() or "day"

        records = sorted(load_records(), key=lambda x: (x.get("visit_date", ""), x.get("id", 0)), reverse=True)
        if q_name:
            records = [r for r in records if q_name in str(r.get("patient_name", ""))]
        else:
            today = date.today()
            if q_range == "day":
                records = [r for r in records if r.get("visit_date", "") == today.isoformat()]
            elif q_range == "week":
                week_start = today - timedelta(days=today.weekday())
                records = [r for r in records if str(r.get("visit_date", "")) >= week_start.isoformat()]
            elif q_range == "month":
                month_prefix = today.strftime("%Y-%m")
                records = [r for r in records if str(r.get("visit_date", "")).startswith(month_prefix)]

        self._send_html(render_index(records, q_name, q_range))

    def do_POST(self):
        if self.path not in {"/add", "/delete"}:
            self._send_html("<h1>404 Not Found</h1>", 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)

        if self.path == "/add":
            records = load_records()
            patient_name = (form.get("patient_name") or [""])[0].strip()
            gender = (form.get("gender") or [""])[0].strip()
            if patient_name and gender:
                fee_items = parse_fee_items((form.get("fee_items") or [""])[0])
                fee_total = sum(item["subtotal"] for item in fee_items)
                if not fee_total:
                    try:
                        fee_total = max(0.0, float((form.get("fee") or ["0"])[0]))
                    except ValueError:
                        fee_total = 0.0

                records.append(
                    {
                        "id": next_id(records),
                        "visit_date": (form.get("visit_date") or [date.today().isoformat()])[0],
                        "patient_name": patient_name,
                        "gender": gender,
                        "age": (form.get("age") or [""])[0].strip(),
                        "phone": (form.get("phone") or [""])[0].strip(),
                        "case_no": (form.get("case_no") or [generate_case_no()])[0].strip(),
                        "chief_complaint": (form.get("chief_complaint") or [""])[0].strip(),
                        "diagnosis": (form.get("diagnosis") or [""])[0].strip(),
                        "item": summary_items({"fee_items": fee_items}),
                        "fee_items": fee_items,
                        "fee": round(fee_total, 2),
                        "payment_method": (form.get("payment_method") or ["现场"])[0].strip() or "现场",
                        "note": (form.get("diagnosis") or [""])[0].strip(),
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                save_records(records)

        elif self.path == "/delete":
            record_id = int((form.get("id") or ["0"])[0])
            records = [r for r in load_records() if int(r.get("id", 0)) != record_id]
            save_records(records)

        filters = []
        for key in ["range", "name"]:
            value = (form.get(key) or [""])[0].strip()
            if value:
                filters.append(f"{key}={quote_plus(value)}")
        suffix = f"?{'&'.join(filters)}" if filters else ""
        self._redirect(f"/{suffix}")


def run() -> None:
    ensure_data_file()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"服务已启动：http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
