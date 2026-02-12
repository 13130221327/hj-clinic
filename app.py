from __future__ import annotations

import html
import json
from datetime import date, datetime
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


def stats(records: list[dict]) -> dict[str, float | int]:
    today = date.today().isoformat()
    month_prefix = date.today().strftime("%Y-%m")
    today_records = [r for r in records if r["visit_date"] == today]
    month_records = [r for r in records if r["visit_date"].startswith(month_prefix)]
    return {
        "count_all": len(records),
        "fee_all": sum(float(r["fee"]) for r in records),
        "count_today": len(today_records),
        "fee_today": sum(float(r["fee"]) for r in today_records),
        "count_month": len(month_records),
        "fee_month": sum(float(r["fee"]) for r in month_records),
    }


def render_index(records: list[dict], q_date: str, q_name: str) -> str:
    all_records = sorted(load_records(), key=lambda x: (x["visit_date"], x["id"]), reverse=True)
    s = stats(all_records)

    stat_cards = "".join(
        [
            stat_card("总就诊人次", str(s["count_all"])),
            stat_card("总费用(元)", f"{s['fee_all']:.2f}"),
            stat_card("今日人次", str(s["count_today"])),
            stat_card("今日费用(元)", f"{s['fee_today']:.2f}"),
            stat_card("本月人次", str(s["count_month"])),
            stat_card("本月费用(元)", f"{s['fee_month']:.2f}"),
        ]
    )

    row_html = ""
    for record in records:
        row_html += f"""
        <tr>
          <td>{escape(record['visit_date'])}</td>
          <td>{escape(record['patient_name'])}</td>
          <td>{escape(record['phone'])}</td>
          <td>{escape(record['item'])}</td>
          <td>{float(record['fee']):.2f}</td>
          <td>{escape(record['payment_method'])}</td>
          <td class='note-cell' title='{escape(record['note'])}'>{escape(record['note'])}</td>
          <td>
            <form action='/delete' method='post' onsubmit="return confirm('确定删除这条记录吗？')">
              <input type='hidden' name='id' value='{record['id']}' />
              <button class='btn btn-sm btn-outline-danger'>删除</button>
            </form>
          </td>
        </tr>
        """

    if not row_html:
        row_html = "<tr><td colspan='8' class='text-center text-secondary py-4'>暂无记录</td></tr>"

    return f"""
<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>何江牙所 · 每日患者记录</title>
  <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet' />
  <style>
    body {{ background: #f6f8fb; }}
    .stat-card {{ border:none; box-shadow:0 2px 8px rgba(0,0,0,.04); }}
    .note-cell {{ max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  </style>
</head>
<body>
<div class='container py-4'>
  <header class='mb-4'>
    <h1 class='h3 mb-2'>何江牙所 · 每日患者与费用记录</h1>
    <p class='text-secondary mb-0'>无需安装数据库，数据保存在本地 JSON 文件，手机和电脑都可直接使用。</p>
  </header>

  <section class='row g-3 mb-4'>{stat_cards}</section>

  <section class='card shadow-sm mb-4'>
    <div class='card-header'>新增记录</div>
    <div class='card-body'>
      <form action='/add' method='post' class='row g-3'>
        <div class='col-6 col-md-3'><label class='form-label'>就诊日期</label><input type='date' name='visit_date' class='form-control' value='{date.today().isoformat()}' required /></div>
        <div class='col-6 col-md-3'><label class='form-label'>患者姓名</label><input type='text' name='patient_name' class='form-control' required /></div>
        <div class='col-6 col-md-3'><label class='form-label'>联系电话</label><input type='text' name='phone' class='form-control' /></div>
        <div class='col-6 col-md-3'><label class='form-label'>治疗项目</label><input type='text' name='item' class='form-control' required /></div>
        <div class='col-6 col-md-3'><label class='form-label'>费用(元)</label><input type='number' min='0' step='0.01' name='fee' class='form-control' required /></div>
        <div class='col-6 col-md-3'>
          <label class='form-label'>支付方式</label>
          <select name='payment_method' class='form-select'><option>现金</option><option>微信</option><option>支付宝</option><option>银行卡</option><option>其他</option></select>
        </div>
        <div class='col-12 col-md-6'><label class='form-label'>备注</label><input type='text' name='note' class='form-control' /></div>
        <div class='col-12'><button type='submit' class='btn btn-primary'>保存记录</button></div>
      </form>
    </div>
  </section>

  <section class='card shadow-sm'>
    <div class='card-header'>记录列表</div>
    <div class='card-body'>
      <form method='get' class='row g-2 mb-3'>
        <div class='col-12 col-md-4'><input type='date' name='date' value='{escape(q_date)}' class='form-control' /></div>
        <div class='col-12 col-md-4'><input type='text' name='name' value='{escape(q_name)}' class='form-control' placeholder='按姓名模糊筛选' /></div>
        <div class='col-6 col-md-2 d-grid'><button class='btn btn-outline-primary'>筛选</button></div>
        <div class='col-6 col-md-2 d-grid'><a href='/' class='btn btn-outline-secondary'>重置</a></div>
      </form>
      <div class='table-responsive'>
        <table class='table table-striped align-middle'>
          <thead><tr><th>日期</th><th>姓名</th><th>电话</th><th>项目</th><th>费用</th><th>支付方式</th><th>备注</th><th></th></tr></thead>
          <tbody>{row_html}</tbody>
        </table>
      </div>
    </div>
  </section>
</div>
</body>
</html>
"""


def stat_card(label: str, value: str) -> str:
    return f"""
      <div class='col-6 col-lg-2'>
        <div class='card stat-card'>
          <div class='card-body'>
            <div class='text-secondary small'>{escape(label)}</div>
            <div class='fs-4 fw-semibold'>{escape(value)}</div>
          </div>
        </div>
      </div>
    """


def escape(val: str) -> str:
    return html.escape(val or "", quote=True)


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
        q_date = (params.get("date") or [""])[0].strip()
        q_name = (params.get("name") or [""])[0].strip()

        records = sorted(load_records(), key=lambda x: (x["visit_date"], x["id"]), reverse=True)
        if q_date:
            records = [r for r in records if r["visit_date"] == q_date]
        if q_name:
            records = [r for r in records if q_name in r["patient_name"]]

        self._send_html(render_index(records, q_date, q_name))

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
            item = (form.get("item") or [""])[0].strip()
            if patient_name and item:
                fee_raw = (form.get("fee") or ["0"])[0].strip()
                try:
                    fee = max(0.0, float(fee_raw or 0))
                except ValueError:
                    fee = 0.0
                records.append(
                    {
                        "id": next_id(records),
                        "visit_date": (form.get("visit_date") or [date.today().isoformat()])[0],
                        "patient_name": patient_name,
                        "phone": (form.get("phone") or [""])[0].strip(),
                        "item": item,
                        "fee": fee,
                        "payment_method": (form.get("payment_method") or ["现金"])[0].strip(),
                        "note": (form.get("note") or [""])[0].strip(),
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                save_records(records)

        elif self.path == "/delete":
            record_id = int((form.get("id") or ["0"])[0])
            records = [r for r in load_records() if r["id"] != record_id]
            save_records(records)

        self._redirect("/")


def run() -> None:
    ensure_data_file()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"服务已启动：http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
