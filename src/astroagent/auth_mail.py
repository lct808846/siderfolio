"""Durable encrypted outbox; SMTP submission is not proof of inbox delivery."""

import html
import json
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from astroagent.auth_mail_quota import MailQuotaReached, reserve_mail_slot
from astroagent.auth_security import digest

LOGO_PATH = Path(__file__).parent / "auth_data" / "siderfolio-logo.png"
LOGO_CID = "siderfolio-logo@siderfolio"

NOTICE_SUBJECTS = {
    "security": "Siderfolio 安全通知",
    "feedback_received": "Siderfolio 收到新反馈",
    "feedback_reply": "Siderfolio 反馈已回复",
}


@lru_cache(maxsize=1)
def _load_brand_logo() -> bytes | None:
    try:
        return LOGO_PATH.read_bytes()
    except OSError:
        return None


def _format_sender(raw_from: str) -> str:
    display, addr = parseaddr(raw_from)
    if addr and not display:
        return formataddr(("Siderfolio", addr))
    return raw_from


def _render_html_body(subject: str, purpose: str, payload: dict, *, has_logo: bool) -> str:
    esc_subject = html.escape(subject)
    logo_cell = (
        f'<td style="width:44px;padding-right:12px;vertical-align:middle;">'
        f'<img src="cid:{LOGO_CID}" alt="Siderfolio" width="40" height="40" '
        f'style="display:block;width:40px;height:40px;border-radius:10px;border:0;" />'
        f"</td>"
        if has_logo
        else ""
    )
    if purpose in NOTICE_SUBJECTS:
        paragraphs = [
            f'<p style="margin:0 0 12px;font-size:14px;line-height:1.7;color:#1f3530;">'
            f"{html.escape(block).replace(chr(10), '<br />')}</p>"
            for block in str(payload.get("message") or "").split("\n\n")
            if block.strip()
        ]
        content_html = "".join(paragraphs) or (
            '<p style="margin:0;font-size:14px;line-height:1.7;color:#1f3530;">'
            "您有一条新的 Siderfolio 通知。</p>"
        )
    else:
        action_label = "确认并激活邮箱" if purpose == "activate" else "前往重置密码"
        esc_url = html.escape(str(payload["url"]), quote=True)
        minutes = html.escape(str(payload["minutes"]))
        content_html = (
            f'<p style="margin:0 0 18px;font-size:14px;line-height:1.7;color:#1f3530;">'
            f"请点击下方按钮并在页面中主动确认。链接有效期 <strong>{minutes} 分钟</strong>。</p>"
            f'<table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 20px;">'
            f'<tr><td style="border-radius:10px;background:#2f6853;">'
            f'<a href="{esc_url}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;padding:11px 22px;font-size:14px;font-weight:600;'
            f'color:#ffffff;text-decoration:none;border-radius:10px;">{action_label}</a>'
            f"</td></tr></table>"
            f'<p style="margin:0 0 8px;font-size:12px;color:#5f736b;">'
            f"如果按钮无法打开，请复制以下链接到浏览器访问：</p>"
            f'<p style="margin:0 0 16px;padding:10px 12px;border-radius:8px;'
            f"background:#f4f8f6;border:1px solid #d8e3dc;font-size:12px;line-height:1.6;"
            f'color:#28503e;word-break:break-all;">'
            f'<a href="{esc_url}" style="color:#28503e;text-decoration:none;">{esc_url}</a></p>'
            f'<p style="margin:0;font-size:12px;line-height:1.6;color:#5f736b;">'
            f"如果不是您发起的操作，请直接忽略本邮件。</p>"
        )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8" />'
        f"<title>{esc_subject}</title></head>"
        '<body style="margin:0;padding:24px 12px;background:#f2f6f4;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC',"
        "'Microsoft YaHei',sans-serif;\">"
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0">'
        '<tr><td align="center">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:560px;background:#ffffff;border:1px solid #d8e3dc;'
        'border-radius:16px;overflow:hidden;">'
        '<tr><td style="padding:20px 24px;background:#132a36;">'
        '<table role="presentation" cellspacing="0" cellpadding="0"><tr>'
        f"{logo_cell}"
        '<td style="vertical-align:middle;">'
        '<div style="font-size:17px;font-weight:700;color:#f6fffb;letter-spacing:-0.01em;">'
        "Siderfolio</div>"
        '<div style="margin-top:2px;font-size:12px;color:#a8e8c8;">'
        "天文观测与文献工作台</div>"
        "</td></tr></table></td></tr>"
        '<tr><td style="padding:24px;">'
        f'<h1 style="margin:0 0 14px;font-size:18px;font-weight:600;color:#1f3530;">'
        f"{esc_subject}</h1>"
        f"{content_html}"
        "</td></tr>"
        '<tr><td style="padding:14px 24px;background:#f7faf8;border-top:1px solid #e4ece7;'
        'font-size:12px;color:#5f736b;">'
        "此邮件由 Siderfolio 系统自动发送，请勿直接回复。"
        "</td></tr></table></td></tr></table></body></html>"
    )


class MailWorker:
    def __init__(self, store, control_guard):
        self.store, self.settings = store, store.settings
        self.control_guard = control_guard
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="identity-mail", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=15)

    def take(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM public.auth_outbox WHERE ((state IN ('pending','failed') AND "
                "available_at<=now()) OR (state='sending' AND lease_until<now())) AND "
                "attempts<5 AND payload<>'' "
                "ORDER BY (purpose NOT IN ('activate','reset','security')), "
                "created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row:
                db.execute(
                    (
                        "UPDATE public.auth_outbox SET "
                        "state='sending',attempts=attempts+1,"
                        "lease_until=now()+interval '2 minutes' "
                        "WHERE id=%s"
                    ),
                    (row["id"],),
                )
            return row

    def deliver(self, row):
        payload = json.loads(self.store.crypto.decrypt(row["payload"].encode()).decode())
        purpose = payload["purpose"]
        with self.store.connect() as db:
            user = db.execute(
                "SELECT active,disabled FROM public.auth_users WHERE id=%s", (row["user_id"],)
            ).fetchone()
            valid = user and not user["disabled"]
            if purpose.startswith("feedback_"):
                valid = valid and user["active"] and self.settings.feedback_mail_ready
            elif purpose not in NOTICE_SUBJECTS:
                token = parse_qs(urlsplit(payload["url"]).fragment).get("token", [""])[0]
                valid = (
                    valid
                    and db.execute(
                        (
                            "SELECT 1 FROM public.auth_tokens WHERE hash=%s AND purpose=%s AND "
                            "consumed_at IS NULL AND expires_at>now()"
                        ),
                        (digest(token), purpose),
                    ).fetchone()
                )
            if not valid:
                db.execute(
                    (
                        "UPDATE public.auth_outbox SET "
                        "state='cancelled',payload='',error_class='expired_or_replaced' WHERE id=%s"
                    ),
                    (row["id"],),
                )
                return
        reserve_mail_slot(self.store)
        message = EmailMessage()
        message["From"], message["To"] = _format_sender(self.settings.smtp_from), payload["email"]
        domain = urlsplit(self.settings.origin).hostname
        message["Message-ID"] = f"<{row['id']}@{domain}>"
        if self.settings.smtp_host.lower() == "smtp.resend.com":
            message["Resend-Idempotency-Key"] = f"siderfolio/{row['id']}"
        subject = (
            payload.get("subject")
            or NOTICE_SUBJECTS.get(purpose)
            or ("Siderfolio 邮箱验证" if purpose == "activate" else "Siderfolio 重置密码")
        )
        message["Subject"] = subject
        message.set_content(
            "Siderfolio\n\n"
            + (
                payload["message"]
                if purpose in NOTICE_SUBJECTS
                else (
                    f"请打开以下链接并主动确认。有效期{payload['minutes']}分钟。\n\n"
                    f"{payload['url']}\n\n如果不是您发起的操作，请忽略。"
                )
            )
        )
        logo_bytes = _load_brand_logo()
        html_body = _render_html_body(subject, purpose, payload, has_logo=bool(logo_bytes))
        message.add_alternative(html_body, subtype="html")
        if logo_bytes:
            html_part = message.get_body(preferencelist=("html",))
            if html_part is not None:
                html_part.add_related(
                    logo_bytes,
                    maintype="image",
                    subtype="png",
                    cid=f"<{LOGO_CID}>",
                    filename="siderfolio-logo.png",
                    disposition="inline",
                )
        context = ssl.create_default_context()
        factory = smtplib.SMTP_SSL if self.settings.smtp_mode == "tls" else smtplib.SMTP
        kwargs = {"context": context} if self.settings.smtp_mode == "tls" else {}
        with factory(
            self.settings.smtp_host, self.settings.smtp_port, timeout=10, **kwargs
        ) as smtp:
            if self.settings.smtp_mode == "starttls":
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(self.settings.smtp_user, self.settings.smtp_password.get_secret_value())
            smtp.send_message(message)
        with self.store.connect() as db:
            db.execute(
                (
                    "UPDATE public.auth_outbox SET state='submitted',submitted_at=now(),payload='"
                    "',lease_until=NULL,error_class=NULL WHERE id=%s"
                ),
                (row["id"],),
            )

    def run(self):
        while not self.stop.is_set():
            row = None
            try:
                self.control_guard()
                if self.settings.mail_ready:
                    row = self.take()
                    if row:
                        self.deliver(row)
                with self.store.connect() as db:
                    db.execute(
                        "DELETE FROM public.auth_tokens WHERE expires_at<now()-interval '1 day'"
                    )
                    db.execute(
                        "DELETE FROM public.auth_sessions WHERE expires_at<now()-interval '1 day' "
                        "OR (revoked AND last_seen<now()-interval '1 day')"
                    )
                    db.execute(
                        "DELETE FROM public.auth_audit "
                        "WHERE created_at<now()-(%s*interval '1 day')",
                        (self.settings.audit_days,),
                    )
                    db.execute(
                        "UPDATE public.auth_outbox SET state='cancelled',payload='',"
                        "error_class='payload_expired',lease_until=NULL "
                        "WHERE payload<>'' AND created_at<now()-interval '1 day'"
                    )
                    db.execute(
                        "UPDATE public.auth_outbox SET "
                        "state='failed',error_class='retry_exhausted',lease_until=NULL WHERE "
                        "state='sending' AND lease_until<now() AND attempts>=5"
                    )
            except Exception as exc:
                # Never log SMTP responses, addresses, payloads, URLs or credentials.
                if row:
                    category = (
                        "smtp_authentication"
                        if isinstance(exc, smtplib.SMTPAuthenticationError)
                        else "smtp_rejected"
                        if isinstance(exc, smtplib.SMTPResponseException)
                        else "temporary_failure"
                    )
                    try:
                        with self.store.connect() as db:
                            if isinstance(exc, MailQuotaReached):
                                db.execute(
                                    "UPDATE public.auth_outbox SET state='pending',"
                                    "error_class='quota_deferred',lease_until=NULL,"
                                    "attempts=attempts-1,available_at=%s WHERE id=%s",
                                    (exc.resets_at, row["id"]),
                                )
                            else:
                                db.execute(
                                    "UPDATE public.auth_outbox SET "
                                    "state='failed',error_class=%s,lease_until=NULL,"
                                    "available_at=now()+interval '5 minutes' WHERE id=%s",
                                    (category, row["id"]),
                                )
                    except Exception:
                        pass
            self.stop.wait(5)
