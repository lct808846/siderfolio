"""Durable encrypted outbox; SMTP submission is not proof of inbox delivery."""

import json
import smtplib
import ssl
import threading
from email.message import EmailMessage
from urllib.parse import parse_qs, urlsplit

from astroagent.auth_mail_quota import MailQuotaReached, reserve_mail_slot
from astroagent.auth_security import digest

NOTICE_SUBJECTS = {
    "security": "Siderfolio 安全通知",
    "feedback_received": "Siderfolio 收到新反馈",
    "feedback_reply": "Siderfolio 反馈已回复",
}


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
        message["From"], message["To"] = self.settings.smtp_from, payload["email"]
        domain = urlsplit(self.settings.origin).hostname
        message["Message-ID"] = f"<{row['id']}@{domain}>"
        if self.settings.smtp_host.lower() == "smtp.resend.com":
            message["Resend-Idempotency-Key"] = f"siderfolio/{row['id']}"
        message["Subject"] = (
            payload.get("subject")
            or NOTICE_SUBJECTS.get(purpose)
            or ("Siderfolio 邮箱验证" if purpose == "activate" else "Siderfolio 重置密码")
        )
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
